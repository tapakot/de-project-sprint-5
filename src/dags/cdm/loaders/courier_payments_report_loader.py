from logging import Logger

from lib import PgConnect
from psycopg import Connection

class DestRepository:

    def load_courier_payments_report(self, conn: Connection) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                delete from cdm.dm_courier_payments_report;
                """
            )
            cur.execute(
                """
                    with t1 as (
                    select 
                        dc.id as courier_id,
                        dc.name as courier_name,
                        dt.year as settlement_year,
                        dt.month as settlement_month, 
                        count(distinct dd.order_id) as orders_count,
                        sum(fps.total_sum) as orders_total_sum,
                        avg(dd.rate) as rate_avg,
                        sum(dd.tip_sum) as courier_tips_sum
                    from dds.dm_couriers dc
                        left join dds.dm_deliveries dd on dc.id = dd.courier_id 
                        left join dds.dm_timestamps dt on dt.id = dd.timestamp_id 
                        left join (select order_id, sum(total_sum) as total_sum from  dds.fct_product_sales group by order_id) fps on fps.order_id = dd.order_id 
                    group by dc.id, dc.name, dt.year, dt.month
                    ),
                    t2 as (
                    select
                        courier_id,
                        courier_name,
                        settlement_year,
                        settlement_month,
                        orders_count,
                        orders_total_sum,
                        rate_avg,
                        (orders_total_sum*0.25) as order_processing_fee,
                        case 
                            when rate_avg < 4 then greatest(0.05*orders_total_sum, 100::numeric)
                            when rate_avg < 4.5 and rate_avg >= 4 then greatest(0.07*orders_total_sum, 150::numeric)
                            when rate_avg < 4.9 and rate_avg >= 4.5 then greatest(0.08*orders_total_sum, 175::numeric)
                            else greatest(0.1*orders_total_sum, 200::numeric)
                        end as courier_order_sum,
                        courier_tips_sum
                    from t1)
                    insert into cdm.dm_courier_payments_report (courier_id, courier_name, settlement_year, settlement_month, orders_count, orders_total_sum, rate_avg, order_processing_fee, courier_order_sum, courier_tips_sum, courier_reward_sum)
                    select
                        t2.*,
                        (courier_order_sum + courier_tips_sum*0.95) as courier_reward_sum
                    from t2;
                """
            )

class CourierReportLoader:
    def __init__(self, pg_dwh: PgConnect, logger: Logger) -> None:
        self.pg_dwh = pg_dwh
        self.dest = DestRepository()
        self.logger = logger

    def load_courier_payments_report(self):
        # открываем транзакцию.
        # Транзакция будет закоммичена, если код в блоке with пройдет успешно (т.е. без ошибок).
        # Если возникнет ошибка, произойдет откат изменений (rollback транзакции).
        with self.pg_dwh.connection() as conn:
            self.dest.load_courier_payments_report(conn)
            self.logger.info(f"Finishing work.")