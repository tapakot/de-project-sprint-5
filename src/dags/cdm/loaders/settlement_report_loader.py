from logging import Logger

from lib import PgConnect
from psycopg import Connection

class DestRepository:

    def load_settlement_report(self, conn: Connection) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                delete from cdm.dm_settlement_report;
                """
            )
            cur.execute(
                """
                    insert into cdm.dm_settlement_report (restaurant_id, restaurant_name, settlement_date, orders_count,orders_total_sum, orders_bonus_payment_sum, orders_bonus_granted_sum, order_processing_fee, restaurant_reward_sum)
                    select 
                        restaurant_id,
                        restaurant_name,
                        settlement_date,
                        count(distinct order_key) as orders_count,
                        sum(t.total_sum) as orders_total_sum,
                        sum(t.bonus_payment) as orders_bonus_payment_sum,
                        sum(t.bonus_grant) as orders_bonus_granted_sum,
                        sum(t.total_sum) * 0.25 as order_processing_fee,
                        sum(t.total_sum)-sum(t.bonus_payment)-sum(t.total_sum) * 0.25 as restaurant_reward_sum
                    from (
                        select
                            dr.restaurant_id  as restaurant_id,
                            dr.restaurant_name as restaurant_name,
                            t."date" as settlement_date,
                            pr.total_sum as total_sum,
                            pr.bonus_grant as bonus_grant,
                            pr.bonus_payment as bonus_payment,
                            o.order_key as order_key
                        FROM dds.fct_product_sales AS pr
                            INNER JOIN dds.dm_orders AS o
                                ON pr.order_id = o.id
                            INNER JOIN dds.dm_timestamps AS t
                                ON o.timestamp_id = t.id
                            INNER JOIN dds.dm_products AS dp 
                                ON pr.product_id = dp.id
                            inner join (select * from dds.dm_restaurants where active_to::Date = '2099-12-31') dr 
                                on o.restaurant_id = dr.id --and dr.active_to::Date = '2099-12-31'
                        WHERE o.order_status = 'CLOSED' 
                    ) as t
                    group by settlement_date, restaurant_id, restaurant_name
                    ;
                """
            )

class SettlementReportLoader:
    def __init__(self, pg_dwh: PgConnect, logger: Logger) -> None:
        self.pg_dwh = pg_dwh
        self.dest = DestRepository()
        self.logger = logger

    def load_settlement_report(self):
        # открываем транзакцию.
        # Транзакция будет закоммичена, если код в блоке with пройдет успешно (т.е. без ошибок).
        # Если возникнет ошибка, произойдет откат изменений (rollback транзакции).
        with self.pg_dwh.connection() as conn:
            self.dest.load_settlement_report(conn)
            self.logger.info(f"Finishing work.")