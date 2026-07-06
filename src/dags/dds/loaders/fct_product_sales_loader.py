from logging import Logger
from typing import List
from datetime import datetime

from dds.dds_settings_repository import EtlSetting, StgEtlSettingsRepository
from lib import PgConnect
from lib.dict_util import json2str
from psycopg import Connection
from psycopg.rows import class_row
from pydantic import BaseModel


class SaleObj(BaseModel):
    product_id: int
    order_id: int
    count: int
    price: float
    total_sum: float
    bonus_payment: float
    bonus_grant: float
    last_updated: datetime

class SalesOriginRepository:
    def __init__(self, pg: PgConnect) -> None:
        self._db = pg

    def list_sales(self, load_threshold: datetime) -> List[SaleObj]:
        with self._db.client().cursor(row_factory=class_row(SaleObj)) as cur:
            cur.execute(
                """
                    select 
                        dp.id as product_id,
                        dor.id as order_id,
                        "count",
                        price,
                        "count" * price as total_sum,
                        bonus_payment,
                        bonus_grant,
                        event_ts as last_updated
                    from (
                        select
                            (be.event_value::json ->> 'order_id') as order_str,
                            (item ->> 'product_id') as product_str,
                            (item ->> 'quantity')::int as "count",
                            (item ->> 'price')::float as price,
                            (item ->> 'bonus_payment')::float as bonus_payment,
                            (item ->> 'bonus_grant')::float as bonus_grant,
                            be.event_ts as event_ts
                        from stg.bonussystem_events be  
                        cross join lateral json_array_elements(be.event_value::json -> 'product_payments') as item
                        where be.event_type = 'bonus_transaction'
                            and be.event_ts > %(threshold)s --Пропускаем те объекты, которые уже загрузили.
                    ) t
                    join 
                        (select id, product_id from dds.dm_products where active_to::date = '2099-12-31') as dp
                        on t.product_str = dp.product_id 
                    join 
                        (select id, order_key from dds.dm_orders) as dor
                        on t.order_str = dor.order_key 
                """, {
                    "threshold": load_threshold
                }
            )
            objs = cur.fetchall()
        return objs


class SaleDestRepository:

    def insert_sale(self, conn: Connection, sale: SaleObj) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                    insert into dds.fct_product_sales (product_id, order_id, "count", price, total_sum, bonus_payment, bonus_grant)
                    VALUES (%(product_id)s, %(order_id)s, %(count)s, %(price)s, %(total_sum)s, %(bonus_payment)s, %(bonus_grant)s);
                """,
                {
                    "product_id": sale.product_id,
                    "order_id": sale.order_id,
                    "count": sale.count,
                    "price": sale.price,
                    "total_sum": sale.total_sum,
                    "bonus_payment": sale.bonus_payment,
                    "bonus_grant": sale.bonus_grant
                },
            )

class SalesLoader:
    _LOG_THRESHOLD = 2

    WF_KEY = "dds_dm_sales_workflow"
    LAST_LOADED_TS_KEY = "last_loaded_ts"

    def __init__(self, pg_dwh: PgConnect, logger: Logger) -> None:
        self.pg_dwh = pg_dwh
        self.origin = SalesOriginRepository(pg_dwh)
        self.dest = SaleDestRepository()
        self.settings_repository = StgEtlSettingsRepository()
        self.logger = logger

    def load_sales(self):
        # открываем транзакцию.
        # Транзакция будет закоммичена, если код в блоке with пройдет успешно (т.е. без ошибок).
        # Если возникнет ошибка, произойдет откат изменений (rollback транзакции).
        with self.pg_dwh.connection() as conn:

            # Прочитываем состояние загрузки
            # Если настройки еще нет, заводим ее.
            wf_setting = self.settings_repository.get_setting(conn, self.WF_KEY)
            if not wf_setting:
                wf_setting = EtlSetting(
                    id=0,
                    workflow_key=self.WF_KEY,
                    workflow_settings={
                        # JSON ничего не знает про даты. Поэтому записываем строку, которую будем кастить при использовании.
                        # А в БД мы сохраним именно JSON.
                        self.LAST_LOADED_TS_KEY: datetime(2022, 1, 1).isoformat()
                    }
                )

            last_loaded_ts_str = wf_setting.workflow_settings[self.LAST_LOADED_TS_KEY]
            last_loaded_ts = datetime.fromisoformat(last_loaded_ts_str)
            self.logger.info(f"starting to load from last checkpoint: {last_loaded_ts}")

            load_queue = self.origin.list_sales(last_loaded_ts)
            self.logger.info(f"Found {len(load_queue)} sales to load.")
            if not load_queue:
                self.logger.info("Quitting.")
                return

            # Сохраняем объекты в базу dwh.
            for sale in load_queue:
                self.dest.insert_sale(conn, sale)

            wf_setting.workflow_settings[self.LAST_LOADED_TS_KEY] = max([t.last_updated for t in load_queue])
            wf_setting_json = json2str(wf_setting.workflow_settings)
            self.settings_repository.save_setting(conn, wf_setting.workflow_key, wf_setting_json)

            self.logger.info(f"Finishing work. Last checkpoint: {wf_setting_json}")