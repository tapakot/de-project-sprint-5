alter table cdm.dm_settlement_report
add constraint dm_settlement_report_settlement_date_check 
CHECK (((date_part('year'::text, settlement_date) >= (2022)::double precision) AND (date_part('year'::text, settlement_date) < (2500)::double precision)))