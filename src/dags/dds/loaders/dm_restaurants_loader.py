from logging import Logger
from typing import List
from datetime import datetime

from dds.dds_settings_repository import EtlSetting, StgEtlSettingsRepository
from lib import PgConnect
from lib.dict_util import json2str
from psycopg import Connection
from psycopg.rows import class_row
from pydantic import BaseModel


class RestaurantObj(BaseModel):
    restaurant_id: str
    restaurant_name: str
    active_from: datetime

class RestaurantsOriginRepository:
    def __init__(self, pg: PgConnect) -> None:
        self._db = pg

    def list_restaurants(self, load_threshold: datetime) -> List[RestaurantObj]:
        with self._db.client().cursor(row_factory=class_row(RestaurantObj)) as cur:
            cur.execute(
                """
                    select
                        u.object_value::json ->> '_id' as restaurant_id,
                        u.object_value::json ->> 'name' as restaurant_name,
                        u.update_ts as active_from
                    from
                        stg.ordersystem_restaurants u
                    WHERE u.update_ts > %(threshold)s --Пропускаем те объекты, которые уже загрузили.
                    ORDER BY u.update_ts ASC;
                """, {
                    "threshold": load_threshold
                }
            )
            objs = cur.fetchall()
        return objs


class RestaurantDestRepository:

    def insert_restaurant(self, conn: Connection, restaurant: RestaurantObj) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                    update dds.dm_restaurants
                    set
                        active_to = %(active_from)s
                    where restaurant_id = %(restaurant_id)s and active_to::Date = '2099-12-31' and restaurant_name <> %(restaurant_name)s;
                """,
                {
                    "restaurant_id": restaurant.restaurant_id,
                    "restaurant_name": restaurant.restaurant_name,
                    "active_from": restaurant.active_from
                },
            )
            cur.execute(
                """
                    insert into dds.dm_restaurants (restaurant_id, restaurant_name, active_from, active_to)
                    VALUES (%(restaurant_id)s, %(restaurant_name)s, %(active_from)s, '2099-12-31');
                """,
                {
                    "restaurant_id": restaurant.restaurant_id,
                    "restaurant_name": restaurant.restaurant_name,
                    "active_from": restaurant.active_from
                },
            )

class RestaurantLoader:
    _LOG_THRESHOLD = 2

    WF_KEY = "dds_dm_restaurants_workflow"
    LAST_LOADED_TS_KEY = "last_loaded_ts"

    def __init__(self, pg_dwh: PgConnect, logger: Logger) -> None:
        self.pg_dwh = pg_dwh
        self.origin = RestaurantsOriginRepository(pg_dwh)
        self.dest = RestaurantDestRepository()
        self.settings_repository = StgEtlSettingsRepository()
        self.logger = logger

    def load_restaurants(self):
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

            load_queue = self.origin.list_restaurants(last_loaded_ts)
            self.logger.info(f"Found {len(load_queue)} restaurants to load.")
            if not load_queue:
                self.logger.info("Quitting.")
                return

            # Сохраняем объекты в базу dwh.
            for user in load_queue:
                self.dest.insert_restaurant(conn, user)

            wf_setting.workflow_settings[self.LAST_LOADED_TS_KEY] = max([t.active_from for t in load_queue])
            wf_setting_json = json2str(wf_setting.workflow_settings)
            self.settings_repository.save_setting(conn, wf_setting.workflow_key, wf_setting_json)

            self.logger.info(f"Finishing work. Last checkpoint: {wf_setting_json}")