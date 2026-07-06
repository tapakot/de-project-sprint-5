import logging

import pendulum
from airflow.decorators import dag, task
from airflow.models.variable import Variable
from schema.schema_init import SchemaDdl
from lib import ConnectionBuilder

log = logging.getLogger(__name__)


@dag(
    schedule_interval=None,  # Задаем расписание выполнения дага - ручной запуск
    start_date=pendulum.datetime(2022, 5, 5, tz="UTC"),  # Дата начала выполнения дага. Можно поставить сегодня.
    catchup=False,  # Нужно ли запускать даг за предыдущие периоды (с start_date до сегодня) - False (не нужно).
    tags=['sprint5', 'schema', 'ddl', 'initialization'],  # Теги, используются для фильтрации в интерфейсе Airflow.
    is_paused_upon_creation=True  # Остановлен/запущен при появлении. Сразу запущен.
)
def init_schema_dag():
    # Создаем подключение к базе dwh.
    dwh_pg_connect = ConnectionBuilder.pg_conn("PG_WAREHOUSE_CONNECTION")

    # Объявляем таск, который создает структуру таблиц.
    @task(task_id="init_schema_stg")
    def init_schema_stg():
        rest_loader = SchemaDdl(dwh_pg_connect, log)
        rest_loader.init_schema(Variable.get("init_schema_stg"))

    @task(task_id="init_schema_dds")
    def init_schema_dds():
        rest_loader = SchemaDdl(dwh_pg_connect, log)
        rest_loader.init_schema(Variable.get("init_schema_dds"))

    @task(task_id="init_schema_cdm")
    def init_schema_cdm():
        rest_loader = SchemaDdl(dwh_pg_connect, log)
        rest_loader.init_schema(Variable.get("init_schema_cdm"))

    # Инициализируем объявленные таски.
    stg_task = init_schema_stg()
    dds_task = init_schema_dds()
    cdm_task = init_schema_cdm()

    # Задаем последовательность выполнения тасков. У нас только инициализация схемы.
    stg_task >> dds_task >> cdm_task # type: ignore


# Вызываем функцию, описывающую даг.
init_schema_dag = init_schema_dag() 
