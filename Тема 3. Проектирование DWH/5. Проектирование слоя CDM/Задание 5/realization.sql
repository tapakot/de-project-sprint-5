ALTER TABLE cdm.dm_settlement_report  
drop constraint if exists dm_settlement_report_unique_check;
ALTER TABLE cdm.dm_settlement_report  
ADD CONSTRAINT dm_settlement_report_unique_check UNIQUE (settlement_date, restaurant_id);