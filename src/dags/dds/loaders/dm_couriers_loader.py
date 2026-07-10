from logging import Logger
from typing import List
from datetime import datetime

from dds.dds_settings_repository import EtlSetting, StgEtlSettingsRepository
from lib import PgConnect
from lib.dict_util import json2str
from psycopg import Connection
from psycopg.rows import class_row
from pydantic import BaseModel


class CourierObj(BaseModel):
    origin_id: str
    name: str
    last_updated: datetime

class CouriersOriginRepository:
    def __init__(self, pg: PgConnect) -> None:
        self._db = pg

    def list_couriers(self, load_threshold: datetime) -> List[CourierObj]:
        with self._db.client().cursor(row_factory=class_row(CourierObj)) as cur:
            cur.execute(
                """
                    select
                        date_trunc('second', c.updated_at) as last_updated,
                        c.object_value::json ->> '_id' as origin_id,
                        c.object_value::json ->> 'name' as name
                    from stg.deliverysystem_couriers c
                    WHERE c.updated_at > %(threshold)s --Пропускаем те объекты, которые уже загрузили.
                """, {
                    "threshold": load_threshold
                }
            )
            objs = cur.fetchall()
        return objs


class CourierDestRepository:

    def insert_courier(self, conn: Connection, courier: CourierObj) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                    insert into dds.dm_couriers (origin_id, name)
                    VALUES (%(origin_id)s, %(name)s);
                """,
                {    
                    "origin_id": courier.origin_id,
                    "name": courier.name
                },
            )

class CourierLoader:
    _LOG_THRESHOLD = 10

    WF_KEY = "dds_dm_couriers_workflow"
    LAST_LOADED_TS_KEY = "last_loaded_ts"

    def __init__(self, pg_dwh: PgConnect, logger: Logger) -> None:
        self.pg_dwh = pg_dwh
        self.origin = CouriersOriginRepository(pg_dwh)
        self.dest = CourierDestRepository()
        self.settings_repository = StgEtlSettingsRepository()
        self.logger = logger

    def load_couriers(self):
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

            load_queue = self.origin.list_couriers(last_loaded_ts)
            self.logger.info(f"Found {len(load_queue)} orders to load.")
            if not load_queue:
                self.logger.info("Quitting.")
                return

            # Сохраняем объекты в базу dwh.
            for order in load_queue:
                self.dest.insert_courier(conn, order)

            wf_setting.workflow_settings[self.LAST_LOADED_TS_KEY] = max([t.last_updated for t in load_queue])
            wf_setting_json = json2str(wf_setting.workflow_settings)
            self.settings_repository.save_setting(conn, wf_setting.workflow_key, wf_setting_json)

            self.logger.info(f"Finishing work. Last checkpoint: {wf_setting_json}")