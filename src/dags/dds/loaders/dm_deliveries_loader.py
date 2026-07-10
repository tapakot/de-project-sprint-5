from logging import Logger
from typing import List
from datetime import datetime

from dds.dds_settings_repository import EtlSetting, StgEtlSettingsRepository
from lib import PgConnect
from lib.dict_util import json2str
from psycopg import Connection
from psycopg.rows import class_row
from pydantic import BaseModel


class DeliveryObj(BaseModel):
    origin_id: str
    order_id: int
    timestamp_id: int
    courier_id: int
    tip_sum: float
    rate: int
    last_updated: datetime

class DeliveriesOriginRepository:
    def __init__(self, pg: PgConnect) -> None:
        self._db = pg

    def list_deliveries(self, load_threshold: datetime) -> List[DeliveryObj]:
        with self._db.client().cursor(row_factory=class_row(DeliveryObj)) as cur:
            cur.execute(
                """
                    select 
                        t.origin_id as origin_id,
                        dor.id as order_id,
                        dt.id as timestamp_id,
                        dc.id as courier_id,
                        t.tip_sum as tip_sum,
                        t.rate as rate,
                        t.last_updated as last_updated
                    from (
                        select
                            d.object_value::json ->> 'delivery_id' as origin_id,
                            d.object_value::json ->> 'order_id' as order_id_str,
                            date_trunc('second', (d.object_value::json ->> 'order_ts')::timestamp) as order_ts,
                            d.object_value::json ->> 'courier_id' as courier_id_str,
                            d.object_value::json ->> 'tip_sum' as tip_sum,
                            d.object_value::json ->> 'rate' as rate,
                            d.updated_at as last_updated
                        from stg.deliverysystem_deliveries d
                        where d.updated_at > %(threshold)s --Пропускаем те объекты, которые уже загрузили.
                    ) t
                    join 
                        (select id, origin_id from dds.dm_couriers) as dc
                        on t.courier_id_str = dc.origin_id
                    join 
                        (select id, order_key from dds.dm_orders) as dor
                        on t.order_id_str = dor.order_key
                    join 
                        (select id, ts from dds.dm_timestamps) as dt
                        on t.order_ts = dt.ts
                """, {
                    "threshold": load_threshold
                }
            )
            objs = cur.fetchall()
        return objs


class DeliveryDestRepository:

    def insert_delivery(self, conn: Connection, delivery: DeliveryObj) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                    insert into dds.dm_deliveries (origin_id, order_id, timestamp_id, courier_id, tip_sum, rate)
                    VALUES (%(origin_id)s, %(order_id)s, %(timestamp_id)s, %(courier_id)s, %(tip_sum)s, %(rate)s)
                    on conflict (origin_id) DO UPDATE 
                    set
                        order_id = EXCLUDED.order_id,
                        timestamp_id = EXCLUDED.timestamp_id,
                        courier_id = EXCLUDED.courier_id,
                        tip_sum = EXCLUDED.tip_sum,
                        rate = EXCLUDED.rate;
                """,
                {
                    "origin_id": delivery.origin_id,
                    "order_id": delivery.order_id,
                    "timestamp_id": delivery.timestamp_id,
                    "courier_id": delivery.courier_id,
                    "tip_sum": delivery.tip_sum,
                    "rate": delivery.rate
                },
            )

class DeliveryLoader:
    _LOG_THRESHOLD = 10

    WF_KEY = "dds_dm_deliveries_workflow"
    LAST_LOADED_TS_KEY = "last_loaded_ts"

    def __init__(self, pg_dwh: PgConnect, logger: Logger) -> None:
        self.pg_dwh = pg_dwh
        self.origin = DeliveriesOriginRepository(pg_dwh)
        self.dest = DeliveryDestRepository()
        self.settings_repository = StgEtlSettingsRepository()
        self.logger = logger

    def load_deliveries(self):
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

            load_queue = self.origin.list_deliveries(last_loaded_ts)
            self.logger.info(f"Found {len(load_queue)} deliveries to load.")
            if not load_queue:
                self.logger.info("Quitting.")
                return

            # Сохраняем объекты в базу dwh.
            for sale in load_queue:
                self.dest.insert_delivery(conn, sale)

            wf_setting.workflow_settings[self.LAST_LOADED_TS_KEY] = max([t.last_updated for t in load_queue])
            wf_setting_json = json2str(wf_setting.workflow_settings)
            self.settings_repository.save_setting(conn, wf_setting.workflow_key, wf_setting_json)

            self.logger.info(f"Finishing work. Last checkpoint: {wf_setting_json}")