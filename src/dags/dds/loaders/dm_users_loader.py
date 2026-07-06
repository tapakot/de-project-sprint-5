from logging import Logger
from typing import List
from datetime import datetime

from dds.dds_settings_repository import EtlSetting, StgEtlSettingsRepository
from lib import PgConnect
from lib.dict_util import json2str
from psycopg import Connection
from psycopg.rows import class_row
from pydantic import BaseModel


class UserObj(BaseModel):
    order_user_id: str
    name: str
    login: str
    last_updated: datetime

class UsersOriginRepository:
    def __init__(self, pg: PgConnect) -> None:
        self._db = pg

    def list_users(self, load_threshold: datetime) -> List[UserObj]:
        with self._db.client().cursor(row_factory=class_row(UserObj)) as cur:
            cur.execute(
                """
                    select
                        u.object_value::json ->> '_id' as order_user_id,
                        u.object_value::json ->> 'name' as name,
                        u.object_value::json ->> 'login' as login,
                        u.update_ts as last_updated
                    from
                        stg.ordersystem_users u
                    WHERE u.update_ts > %(threshold)s; --Пропускаем те объекты, которые уже загрузили.
                """, {
                    "threshold": load_threshold
                }
            )
            objs = cur.fetchall()
        return objs


class UserDestRepository:

    def insert_user(self, conn: Connection, user: UserObj) -> None:
        with conn.cursor() as cur:
            # cur.execute(
            #     """
            #         delete from dds.dm_users
            #         where user_id = %(order_user_id)s;
            #     """,
            #     {
            #         "order_user_id": user.order_user_id,
            #     },
            # )
            cur.execute(
                """
                    insert into dds.dm_users (user_id, user_name, user_login)
                    VALUES (%(order_user_id)s, %(user_name)s, %(user_login)s);
                """,
                {
                    "order_user_id": user.order_user_id,
                    "user_name": user.name,
                    "user_login": user.login
                },
            )

class UserLoader:
    _LOG_THRESHOLD = 2

    WF_KEY = "dds_dm_users_workflow"
    LAST_LOADED_TS_KEY = "last_loaded_ts"

    def __init__(self, pg_dwh: PgConnect, logger: Logger) -> None:
        self.pg_dwh = pg_dwh
        self.origin = UsersOriginRepository(pg_dwh)
        self.dest = UserDestRepository()
        self.settings_repository = StgEtlSettingsRepository()
        self.logger = logger

    def load_users(self):
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

            load_queue = self.origin.list_users(last_loaded_ts)
            self.logger.info(f"Found {len(load_queue)} users to load.")
            if not load_queue:
                self.logger.info("Quitting.")
                return

            # Сохраняем объекты в базу dwh.
            for user in load_queue:
                self.dest.insert_user(conn, user)

            wf_setting.workflow_settings[self.LAST_LOADED_TS_KEY] = max([t.last_updated for t in load_queue])
            wf_setting_json = json2str(wf_setting.workflow_settings)
            self.settings_repository.save_setting(conn, wf_setting.workflow_key, wf_setting_json)

            self.logger.info(f"Finishing work. Last checkpoint: {wf_setting_json}")