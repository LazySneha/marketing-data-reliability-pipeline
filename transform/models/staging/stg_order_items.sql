with latest as (
    {{ latest_version(source('raw', 'order_items')) }}
)

select
    '{{ var("brand") }}'                                            as brand_id,
    id                                                              as order_item_id,
    payload ->> 'order_id'                                          as order_id,
    payload ->> 'sku'                                               as sku,
    (payload ->> 'quantity')::integer                               as quantity,
    (payload ->> 'unit_price')::decimal(12, 2)                      as unit_price,
    -- before the order-level discount; fct_order_items spreads that across the lines
    (payload ->> 'quantity')::integer
        * (payload ->> 'unit_price')::decimal(12, 2)                as line_subtotal,
    timezone('UTC', updated_at::timestamptz)                        as updated_at_utc
from latest
