import logging

import pendulum
from airflow.decorators import dag, task
from stg.loaders.deliveries_loader import DeliveryLoader
from stg.loaders.couriers_loader import CouriersLoader
from stg.pg_saver import PgSaver
from lib import ConnectionBuilder

log = logging.getLogger(__name__)


@dag(
    schedule_interval='0/15 * * * *',  # Задаем расписание выполнения дага - каждый 15 минут.
    start_date=pendulum.datetime(2022, 5, 5, tz="UTC"),  # Дата начала выполнения дага. Можно поставить сегодня.
    catchup=False,  # Нужно ли запускать даг за предыдущие периоды (с start_date до сегодня) - False (не нужно).
    tags=['sprint5', 'stg', 'origin', 'my'],  # Теги, используются для фильтрации в интерфейсе Airflow.
    is_paused_upon_creation=True  # Остановлен/запущен при появлении. Сразу запущен.
)
def stg_delivery_system_dag():
    # Создаем подключение к базе dwh.
    dwh_pg_connect = ConnectionBuilder.pg_conn("PG_WAREHOUSE_CONNECTION")

    # Объявляем таск, который загружает данные.
    @task(task_id="deliveries_load")
    def load_deliveries():
        pg_saver = PgSaver()
        loader = DeliveryLoader(dwh_pg_connect, pg_saver, log)
        loader.load_deliveries()

    @task(task_id="couriers_load")
    def load_couriers():
        pg_saver = PgSaver()
        loader = CouriersLoader(dwh_pg_connect, pg_saver, log)
        loader.load_couriers()

    # Инициализируем объявленные таски.
    deliveries_task = load_deliveries()
    couriers_task = load_couriers()


    # Далее задаем последовательность выполнения тасков.
    # Т.к. таск один, просто обозначим его здесь.
    [deliveries_task, couriers_task] # type: ignore


stg_delivery_system_dag = stg_delivery_system_dag()
