select
    table_name,
    column_name,
    data_type,
    character_maximum_length,
    column_default,
    is_nullable
from
    information_schema."columns" 
where table_name in (SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public');