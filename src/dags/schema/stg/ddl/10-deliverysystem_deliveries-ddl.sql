drop table if exists stg.deliverysystem_deliveries;
CREATE TABLE stg.deliverysystem_deliveries (
	id serial4 NOT null,
	object_id varchar NOT NULL,
	object_value text NOT NULL,
	object_ts timestamp NOT NULL,
	updated_at timestamp(0) not null default CURRENT_TIMESTAMP,
	CONSTRAINT deliverysystem_deliveries_object_id_uindex UNIQUE (object_id),
	CONSTRAINT deliverysystem_deliveries_pkey PRIMARY KEY (id)
);