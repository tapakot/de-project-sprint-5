drop table if EXISTS dds.dm_couriers;
create table dds.dm_couriers (
	id int not null primary key generated always as identity,
	origin_id text not null,
	name text not null,
	constraint dm_couriers_origin_id_uindex unique (origin_id)
);