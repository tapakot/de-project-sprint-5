select CURRENT_TIMESTAMP, 'test_01', 
    case (
        select count(*)
        from public_test.dm_settlement_report_actual a
        full outer join 
        public_test.dm_settlement_report_expected e
        on a.restaurant_id = e.restaurant_id) 
    when 0 then True
    else False
    end