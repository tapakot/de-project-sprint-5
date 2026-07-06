from logging import Logger
from typing import List
from datetime import datetime

from dds.dds_settings_repository import EtlSetting, StgEtlSettingsRepository
from lib import PgConnect
from lib.dict_util import json2str
from psycopg import Connection
from psycopg.rows import class_row
from pydantic import BaseModel


class OrderObj(BaseModel):
    user_id: int
    restaurant_id: int
    timestamp_id: int
    order_key: str
    order_status: str
    last_updated: datetime

class OrdersOriginRepository:
    def __init__(self, pg: PgConnect) -> None:
        self._db = pg

    def list_orders(self, load_threshold: datetime) -> List[OrderObj]:
        with self._db.client().cursor(row_factory=class_row(OrderObj)) as cur:
            cur.execute(
                """
                    select
                        du.id as user_id,
                        dr.id as restaurant_id,
                        dt.id as timestamp_id,
                        t.order_key as order_key,
                        t.order_status as order_status,
                        t.last_updated as last_updated
                    from
                        (select
                            r.update_ts as last_updated,
                            r.object_value::json ->> '_id' as order_key,
                            r.object_value::json ->> 'final_status' as order_status,
                            (r.object_value::json ->> 'date')::timestamp as timestamp_str,
                            r.object_value::json -> 'restaurant' ->> 'id' as restaurant_str,
                            r.object_value::json -> 'user' ->> 'id' as user_str
                        from stg.ordersystem_orders r
                        WHERE r.update_ts > %(threshold)s --Пропускаем те объекты, которые уже загрузили.
                        ORDER BY r.update_ts ASC) as t
                    join 
                        (select id, restaurant_id from dds.dm_restaurants where active_to::date = '2099-12-31') as dr 
                        on t.restaurant_str = dr.restaurant_id
                    join 
                        (select id, user_id from dds.dm_users) as du
                        on t.user_str = du.user_id
                    join 
                        (select id, ts from dds.dm_timestamps) as dt
                        on t.timestamp_str = dt.ts
                """, {
                    "threshold": load_threshold
                }
            )
            objs = cur.fetchall()
        return objs


class OrderDestRepository:

    def insert_order(self, conn: Connection, order: OrderObj) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                    insert into dds.dm_orders (user_id, restaurant_id, timestamp_id, order_key, order_status)
                    VALUES (%(user_id)s, %(restaurant_id)s, %(timestamp_id)s, %(order_key)s, %(order_status)s);
                """,
                {
                    "user_id": order.user_id,
                    "restaurant_id": order.restaurant_id,
                    "timestamp_id": order.timestamp_id,
                    "order_key": order.order_key,
                    "order_status": order.order_status
                },
            )

class OrderLoader:
    _LOG_THRESHOLD = 2

    WF_KEY = "dds_dm_orders_workflow"
    LAST_LOADED_TS_KEY = "last_loaded_ts"

    def __init__(self, pg_dwh: PgConnect, logger: Logger) -> None:
        self.pg_dwh = pg_dwh
        self.origin = OrdersOriginRepository(pg_dwh)
        self.dest = OrderDestRepository()
        self.settings_repository = StgEtlSettingsRepository()
        self.logger = logger

    def load_orders(self):
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

            load_queue = self.origin.list_orders(last_loaded_ts)
            self.logger.info(f"Found {len(load_queue)} orders to load.")
            if not load_queue:
                self.logger.info("Quitting.")
                return

            # Сохраняем объекты в базу dwh.
            for order in load_queue:
                self.dest.insert_order(conn, order)

            wf_setting.workflow_settings[self.LAST_LOADED_TS_KEY] = max([t.last_updated for t in load_queue])
            wf_setting_json = json2str(wf_setting.workflow_settings)
            self.settings_repository.save_setting(conn, wf_setting.workflow_key, wf_setting_json)

            self.logger.info(f"Finishing work. Last checkpoint: {wf_setting_json}")