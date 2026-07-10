from logging import Logger
from typing import List, Dict
import requests
from datetime import datetime



from stg.stg_settings_repository import EtlSetting, StgEtlSettingsRepository
from lib import PgConnect
from stg.pg_saver import PgSaver
from lib.dict_util import json2str

class CouriersOriginRepository:
    def list_couriers(self, offset: int, log: Logger, limit) -> List[Dict]:
        nickname = 'tapakot'
        cohort = '49'
        api_key = '25c27781-8fde-4b30-a22e-524044a7580f'

        headers = {
            'X-Nickname': nickname,
            'X-Cohort': cohort,
            'X-API-KEY': api_key
        }

        base_url = "https://d5d04q7d963eapoepsqr.apigw.yandexcloud.net"

        couriers = []

        for _ in range(limit):
            params = { # "restaurant_id" : restaurant_id, # без указания - все доступные
                    "sort_field" : "date", # "_id" по order_id, "date" по order_ts
                    "sort_direction" : "asc", # "asc", "desc"
                    #"limit" : limit,
                    "offset" : offset 
                    }
            
            log.info(f"Offset is: {offset}")
            response = requests.get(f'{base_url}/couriers', params=params, headers=headers)
            log.info(response.status_code)
            response.raise_for_status()

            new_couriers = response.json()

            if len(new_couriers) == 0:
                break

            couriers.extend(new_couriers)
            offset += len(new_couriers)

        return couriers
        

class CouriersLoader:
    WF_KEY = "couriers_origin_to_stg_workflow"
    LAST_LOADED_ID_KEY = "last_loaded_offset"
    _LOG_THRESHOLD = 10
    _SESSION_LIMIT = 5

    def __init__(self, pg_dest: PgConnect, pg_saver: PgSaver, log: Logger) -> None:
        self.pg_dest = pg_dest
        self.origin = CouriersOriginRepository()
        self.pg_saver = pg_saver
        self.settings_repository = StgEtlSettingsRepository()
        self.log = log

    def load_couriers(self):
        # открываем транзакцию.
        # Транзакция будет закоммичена, если код в блоке with пройдет успешно (т.е. без ошибок).
        # Если возникнет ошибка, произойдет откат изменений (rollback транзакции).
        with self.pg_dest.connection() as conn:

            # Прочитываем состояние загрузки
            # Если настройки еще нет, заводим ее.
            wf_setting = self.settings_repository.get_setting(conn, self.WF_KEY)
            if not wf_setting:
                wf_setting = EtlSetting(id=0, workflow_key=self.WF_KEY, workflow_settings={self.LAST_LOADED_ID_KEY: -1})

            # Вычитываем очередную пачку объектов.
            last_loaded_offset = wf_setting.workflow_settings[self.LAST_LOADED_ID_KEY]
            load_queue = self.origin.list_couriers(last_loaded_offset + 1, self.log, self._SESSION_LIMIT)
            self.log.info(f"Found {len(load_queue)} couriers to load.")

            if not load_queue:
                self.log.info("Quitting.")
                return

            i = 0
            for d in load_queue:
                self.pg_saver.save_courier(conn, str(d["_id"]), d)

                i += 1
                if i % self._LOG_THRESHOLD == 0:
                    self.log.info(f"processed {i} documents of {len(load_queue)} while syncing couriers.")

            # Сохраняем прогресс.
            # Мы пользуемся тем же connection, поэтому настройка сохранится вместе с объектами,
            # либо откатятся все изменения целиком.
            wf_setting.workflow_settings[self.LAST_LOADED_ID_KEY] = last_loaded_offset + len(load_queue)
            wf_setting_json = json2str(wf_setting.workflow_settings)  # Преобразуем к строке, чтобы положить в БД.
            self.settings_repository.save_setting(conn, wf_setting.workflow_key, wf_setting_json)

            self.log.info(f"Load finished on {wf_setting.workflow_settings[self.LAST_LOADED_ID_KEY]}")
