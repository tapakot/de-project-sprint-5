import logging
import pendulum

from airflow.decorators import dag, task
from airflow.operators.empty import EmptyOperator

from dds.loaders.dm_users_loader import UserLoader
from dds.loaders.dm_restaurants_loader import RestaurantLoader
from dds.loaders.dm_timestamps_loader import TimestampLoader
from dds.loaders.dm_products_loader import ProductLoader
from dds.loaders.dm_orders_loader import OrderLoader
from dds.loaders.fct_product_sales_loader import SalesLoader
from lib import ConnectionBuilder

log = logging.getLogger(__name__)

@dag(
    schedule_interval='0/15 * * * *',  # Задаем расписание выполнения дага - каждый 15 минут.
    start_date=pendulum.datetime(2022, 5, 5, tz="UTC"),  # Дата начала выполнения дага. Можно поставить сегодня.
    catchup=False,  # Нужно ли запускать даг за предыдущие периоды (с start_date до сегодня) - False (не нужно).
    tags=['sprint5', 'dds', 'my'],  # Теги, используются для фильтрации в интерфейсе Airflow.
    is_paused_upon_creation=True,  # Остановлен/запущен при появлении. Сразу запущен.
    template_searchpath="dds/scripts"
)
def dds_dag():
    # Создаем подключение к базе dwh.
    dwh_pg_connect = ConnectionBuilder.pg_conn("PG_WAREHOUSE_CONNECTION")

    empty_task = EmptyOperator(task_id = "connect1")

    @task(task_id="dm_users_load")
    def load_users():
        loader = UserLoader(dwh_pg_connect, log)
        loader.load_users()

    @task(task_id="dm_restaurants_load")
    def load_restaurants():
        loader = RestaurantLoader(dwh_pg_connect, log)
        loader.load_restaurants()

    @task(task_id="dm_timestamps_load")
    def load_timestamps():
        loader = TimestampLoader(dwh_pg_connect, log)
        loader.load_timestamps()

    @task(task_id="dm_products_load")
    def load_products():
        loader = ProductLoader(dwh_pg_connect, log)
        loader.load_products()

    @task(task_id="dm_orders_load")
    def load_orders():
        loader = OrderLoader(dwh_pg_connect, log)
        loader.load_orders()

    @task(task_id="fct_sales_load")
    def load_sales():
        loader = SalesLoader(dwh_pg_connect, log)
        loader.load_sales()
    


    # Инициализируем объявленные таски.
    users_task = load_users()
    restaurants_task = load_restaurants()
    timestamps_task = load_timestamps()
    products_task = load_products()
    orders_task = load_orders()
    sales_task = load_sales()

    # Далее задаем последовательность выполнения тасков.
    # Т.к. таск один, просто обозначим его здесь.
    [users_task, restaurants_task, timestamps_task] >> empty_task >> [products_task, orders_task] >> sales_task # type: ignore


dds_dag = dds_dag()
