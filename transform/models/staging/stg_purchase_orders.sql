with latest as (
    {{ latest_version(source('raw', 'purchase_orders')) }}
)

select
    '{{ var("brand") }}'                                            as brand_id,
    id                                                              as purchase_order_id,
    payload ->> 'sku'                                               as sku,
    (payload ->> 'quantity')::integer                               as ordered_quantity,
    timezone('UTC', (payload ->> 'ordered_at')::timestamptz)        as ordered_at_utc,
    -- the date the supplier promised, which is not always the date it lands
    (payload ->> 'expected_arrival_date')::date                     as expected_arrival_date,
    timezone('UTC', (payload ->> 'received_at')::timestamptz)       as received_at_utc,
    cast(timezone('{{ var("reporting_tz") }}', (payload ->> 'received_at')::timestamptz) as date) as received_date,
    (payload ->> 'received_at') is not null                         as is_received,
    timezone('UTC', updated_at::timestamptz)                        as updated_at_utc
from latest
