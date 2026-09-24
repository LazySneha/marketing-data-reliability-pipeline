with latest as (
    {{ latest_version(source('raw', 'orders')) }}
)

select
    '{{ var("brand") }}'                                            as brand_id,
    id                                                              as order_id,
    payload ->> 'customer_id'                                       as customer_id,
    payload ->> 'session_id'                                        as session_id,
    timezone('UTC', (payload ->> 'created_at')::timestamptz)        as created_at_utc,
    -- bucket orders into the brand's reporting day, not the UTC day
    cast(timezone('{{ var("reporting_tz") }}', (payload ->> 'created_at')::timestamptz) as date) as order_date,
    payload ->> 'currency'                                          as currency,
    (payload ->> 'subtotal_price')::decimal(12, 2)                  as subtotal,
    (payload ->> 'total_discounts')::decimal(12, 2)                 as discounts,
    (payload ->> 'subtotal_price')::decimal(12, 2)
        - (payload ->> 'total_discounts')::decimal(12, 2)           as gross_revenue,
    (payload ->> 'total_tax')::decimal(12, 2)                       as tax,
    (payload ->> 'total_shipping')::decimal(12, 2)                  as shipping,
    payload ->> 'financial_status'                                  as financial_status,
    payload ->> 'fulfillment_status'                                as fulfillment_status,
    timezone('UTC', updated_at::timestamptz)                        as updated_at_utc
from latest
