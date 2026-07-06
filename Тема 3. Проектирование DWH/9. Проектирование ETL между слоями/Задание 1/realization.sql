INSERT INTO cdm.dm_settlement_report(
	restaurant_id,
	restaurant_name,
	settlement_date,
	orders_count,
	orders_total_sum,
	orders_bonus_payment_sum,
	orders_bonus_granted_sum,
	order_processing_fee,
	restaurant_reward_sum
)
(
select 
	dr.restaurant_id, 
	dr.restaurant_name,
	dt.date,
	count(distinct dor.id) as orders_count,
	sum(fps.total_sum),
	sum(fps.bonus_payment ),
	sum(fps.bonus_grant ),
	sum(fps.total_sum) * 0.25,
	sum(fps.total_sum) * 0.75 - sum(fps.bonus_payment )
	
from dds.fct_product_sales fps 
left join dds.dm_orders dor on fps.order_id = dor.id
left join dds.dm_restaurants dr on dor.restaurant_id = dr.id
left join dds.dm_timestamps dt on dor.timestamp_id = dt.id
group by
	dr.restaurant_id, dr.restaurant_name, dt.date

)