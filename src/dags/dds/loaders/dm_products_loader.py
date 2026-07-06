from logging import Logger
from typing import List
from datetime import datetime

from dds.dds_settings_repository import EtlSetting, StgEtlSettingsRepository
from lib import PgConnect
from lib.dict_util import json2str
from psycopg import Connection
from psycopg.rows import class_row
from pydantic import BaseModel


class ProductObj(BaseModel):
    product_id: str
    product_name: str
    product_price: float
    restaurant_id: int
    active_from: datetime

class ProductsOriginRepository:
    def __init__(self, pg: PgConnect) -> None:
        self._db = pg

    def list_products(self, load_threshold: datetime) -> List[ProductObj]:
        with self._db.client().cursor(row_factory=class_row(ProductObj)) as cur:
            cur.execute(
                """
                    select
                        t.d::json ->> '_id' as product_id,
                        t.d::json ->> 'name' as product_name,
                        t.d::json ->> 'price' as product_price,
                        dr.id as restaurant_id,
                        t.last_updated as active_from
                    from
                        (select
                            json_array_elements( r.object_value::json -> 'menu' ) as d,
                            r.update_ts as last_updated,
                            r.object_value::json ->> '_id' as restaurant_id_str
                        from stg.ordersystem_restaurants r
                        WHERE r.update_ts > %(threshold)s --Пропускаем те объекты, которые уже загрузили.
                        ORDER BY r.update_ts ASC) as t
                    join 
                        (select id, restaurant_id from dds.dm_restaurants where active_to::date = '2099-12-31') as dr 
                    on t.restaurant_id_str = dr.restaurant_id;
                """, {
                    "threshold": load_threshold
                }
            )
            objs = cur.fetchall()
        return objs


class ProductDestRepository:

    def insert_product(self, conn: Connection, product: ProductObj) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                    update dds.dm_products
                    set
                        active_to = %(active_from)s
                    where product_id = %(product_id)s and active_to::Date = '2099-12-31';
                """,
                {
                    "product_id": product.product_id,
                    "active_from": product.active_from
                },
            )
            cur.execute(
                """
                    insert into dds.dm_products (product_id, product_name, product_price, restaurant_id, active_from, active_to)
                    VALUES (%(product_id)s, %(product_name)s, %(product_price)s, %(restaurant_id)s, %(active_from)s, '2099-12-31');
                """,
                {
                    "product_id": product.product_id,
                    "product_name": product.product_name,
                    "product_price": product.product_price,
                    "restaurant_id": product.restaurant_id,
                    "active_from": product.active_from
                },
            )

class ProductLoader:
    _LOG_THRESHOLD = 2

    WF_KEY = "dds_dm_products_workflow"
    LAST_LOADED_TS_KEY = "last_loaded_ts"

    def __init__(self, pg_dwh: PgConnect, logger: Logger) -> None:
        self.pg_dwh = pg_dwh
        self.origin = ProductsOriginRepository(pg_dwh)
        self.dest = ProductDestRepository()
        self.settings_repository = StgEtlSettingsRepository()
        self.logger = logger

    def load_products(self):
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

            load_queue = self.origin.list_products(last_loaded_ts)
            self.logger.info(f"Found {len(load_queue)} products to load.")
            if not load_queue:
                self.logger.info("Quitting.")
                return

            # Сохраняем объекты в базу dwh.
            for product in load_queue:
                self.dest.insert_product(conn, product)

            wf_setting.workflow_settings[self.LAST_LOADED_TS_KEY] = max([t.active_from for t in load_queue])
            wf_setting_json = json2str(wf_setting.workflow_settings)
            self.settings_repository.save_setting(conn, wf_setting.workflow_key, wf_setting_json)

            self.logger.info(f"Finishing work. Last checkpoint: {wf_setting_json}")