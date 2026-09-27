with latest as (
    {{ latest_version(source('raw', 'products')) }}
)

select
    '{{ var("brand") }}'                                            as brand_id,
    id                                                              as product_id,
    payload ->> 'sku'                                               as sku,
    payload ->> 'title'                                             as title,
    (payload ->> 'price')::decimal(12, 2)                           as price,
    (payload ->> 'unit_cost')::decimal(12, 2)                       as unit_cost,
    -- how long the supplier takes to deliver a replenishment order, in days
    (payload ->> 'supplier_lead_time_days')::integer                as supplier_lead_time_days,
    timezone('UTC', updated_at::timestamptz)                        as updated_at_utc
from latest
