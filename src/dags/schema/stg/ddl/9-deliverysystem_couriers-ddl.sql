drop table if exists stg.deliverysystem_couriers;
CREATE TABLE stg.deliverysystem_couriers (
	id serial4 NOT null,
	object_id varchar NOT NULL,
	object_value text NOT NULL,
	updated_at timestamp(0) not null default CURRENT_TIMESTAMP,
	CONSTRAINT deliverysystem_couriers_object_id_uindex UNIQUE (object_id),
	CONSTRAINT deliverysystem_couriers_pkey PRIMARY KEY (id)
);