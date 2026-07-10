drop table if exists cdm.dm_courier_payments_report;
create table cdm.dm_courier_payments_report(
	id int NOT null primary key generated always as identity,
	courier_id int not null,
	courier_name text not null,
	settlement_year smallint not null CHECK (settlement_year >= 2022 and settlement_year <= 2050),
	settlement_month smallint not null CHECK (settlement_month >= 1 and settlement_month <= 12),
	orders_count int not null CHECK (orders_count >= 0),
	orders_total_sum numeric(14,2) not null CHECK (orders_total_sum >= (0)::numeric),
	rate_avg numeric(3,2) not null,
	order_processing_fee numeric(14,2) not null CHECK ((order_processing_fee >= (0)::numeric)),
	courier_order_sum numeric(14,2) not null CHECK ((courier_order_sum >= (0)::numeric)),
	courier_tips_sum numeric(14,2) not null CHECK ((courier_tips_sum >= (0)::numeric)),
	courier_reward_sum numeric(14,2) not null CHECK ((courier_reward_sum >= (0)::numeric)),
	CONSTRAINT dm_courier_payments_report_unique_check UNIQUE (settlement_year, settlement_month, courier_id)
);