drop table if EXISTS dds.dm_deliveries;
create table dds.dm_deliveries (
	id int not null primary key generated always as identity,
	origin_id text not null,
	timestamp_id int not null,
	order_id int not null,
	courier_id int not null,
	tip_sum numeric(14,2) default 0 not null,
	rate smallint not null,
	constraint dm_deliveries_origin_id_uindex unique (origin_id),
	CONSTRAINT dm_deliveries_tip_sum_check CHECK (tip_sum >= 0),
	CONSTRAINT dm_deliveries_rate_check CHECK (rate >= 0 and rate <= 5),
	CONSTRAINT dm_deliveries_timestamp_id_fkey FOREIGN KEY (timestamp_id) REFERENCES dds.dm_timestamps(id),
	CONSTRAINT dm_deliveries_order_id_fkey FOREIGN KEY (order_id) REFERENCES dds.dm_orders(id),
	CONSTRAINT dm_deliveries_courier_id_fkey FOREIGN KEY (courier_id) REFERENCES dds.dm_couriers(id)
);
