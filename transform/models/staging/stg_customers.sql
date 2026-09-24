with latest as (
    {{ latest_version(source('raw', 'customers')) }}
)

select
    '{{ var("brand") }}'                                            as brand_id,
    id                                                              as customer_id,
    timezone('UTC', (payload ->> 'created_at')::timestamptz)        as created_at_utc
from latest
