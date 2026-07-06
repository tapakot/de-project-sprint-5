from logging import Logger
from typing import List
from datetime import datetime

from dds.dds_settings_repository import EtlSetting, StgEtlSettingsRepository
from lib import PgConnect
from lib.dict_util import json2str
from psycopg import Connection
from psycopg.rows import class_row
from pydantic import BaseModel


class TimestampObj(BaseModel):
    ts: datetime
    last_updated: datetime

class TimestampsOriginRepository:
    def __init__(self, pg: PgConnect) -> None:
        self._db = pg

    def list_timestamps(self, load_threshold: datetime) -> List[TimestampObj]:
        with self._db.client().cursor(row_factory=class_row(TimestampObj)) as cur:
            cur.execute(
                """
                    select 
                        t.d::json ->> 'dttm' as ts,
                        t.last_updated as last_updated
                    from 
                        (select
                            json_array_elements( oo.object_value::json -> 'statuses' ) as d,
                            oo.update_ts as last_updated
                        from stg.ordersystem_orders oo 
                        WHERE oo.update_ts > %(threshold)s
                        ) as t
                    where t.d::json ->> 'status' in ('CANCELLED', 'CLOSED');
                """, {
                    "threshold": load_threshold
                }
            )
            objs = cur.fetchall()
        return objs


class TimestampDestRepository:

    def insert_timestamp(self, conn: Connection, timestamp: TimestampObj) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                    insert into dds.dm_timestamps (ts, "year", "month", "day", "time", "date")
                    VALUES  (%(ts)s, 
                            extract(year from %(ts)s),
                            extract(month from %(ts)s),
                            extract(day from %(ts)s),
                            %(ts)s::time,
                            %(ts)s::date);
                """,
                {
                    "ts": timestamp.ts,
                },
            )

class TimestampLoader:
    _LOG_THRESHOLD = 2

    WF_KEY = "dds_dm_timestamps_workflow"
    LAST_LOADED_TS_KEY = "last_loaded_ts"

    def __init__(self, pg_dwh: PgConnect, logger: Logger) -> None:
        self.pg_dwh = pg_dwh
        self.origin = TimestampsOriginRepository(pg_dwh)
        self.dest = TimestampDestRepository()
        self.settings_repository = StgEtlSettingsRepository()
        self.logger = logger

    def load_timestamps(self):
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

            load_queue = self.origin.list_timestamps(last_loaded_ts)
            self.logger.info(f"Found {len(load_queue)} timestamps to load.")
            if not load_queue:
                self.logger.info("Quitting.")
                return

            # Сохраняем объекты в базу dwh.
            for ts in load_queue:
                self.dest.insert_timestamp(conn, ts)

            wf_setting.workflow_settings[self.LAST_LOADED_TS_KEY] = max([t.last_updated for t in load_queue])
            wf_setting_json = json2str(wf_setting.workflow_settings)
            self.settings_repository.save_setting(conn, wf_setting.workflow_key, wf_setting_json)

            self.logger.info(f"Finishing work. Last checkpoint: {wf_setting_json}")