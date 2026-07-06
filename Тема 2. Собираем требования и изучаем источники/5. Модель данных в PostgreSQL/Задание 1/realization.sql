select distinct el::JSON->>'product_name'
from(
	select json_array_elements((event_value::JSON->>'product_payments')::JSON) as el
	from public.outbox
) els;