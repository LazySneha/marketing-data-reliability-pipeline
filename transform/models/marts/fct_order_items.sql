-- One row per order line. The order-level discount is spread across the lines in proportion
-- to their subtotal, so line revenue always adds back up to the order's gross revenue.
with items as (
    select * from {{ ref('stg_order_items') }}
),

orders as (
    select
        fct.order_id,
        fct.order_date,
        fct.attributed_platform,
        fct.attributed_campaign_id,
        fct.is_new_customer,
        fct.gross_revenue,
        stg.subtotal,
        stg.fulfillment_status
    from {{ ref('fct_orders') }} as fct
    join {{ ref('stg_orders') }} as stg
        on fct.order_id = stg.order_id
),

-- A backorder the customer gave up on: refunded in full, with the reason recorded.
out_of_stock_cancellations as (
    select distinct order_id
    from {{ ref('stg_refunds') }}
    where refund_reason = 'out_of_stock'
)

select
    '{{ var("brand") }}'                                            as brand_id,
    items.order_item_id,
    items.order_id,
    items.sku,
    orders.order_date,
    orders.attributed_platform,
    orders.attributed_campaign_id,
    orders.is_new_customer,
    items.quantity,
    items.unit_price,
    items.line_subtotal,
    round(items.line_subtotal * orders.gross_revenue
          / nullif(orders.subtotal, 0), 2)                          as line_gross_revenue,
    orders.fulfillment_status = 'on_backorder'                      as is_backorder,
    cancellations.order_id is not null                              as is_out_of_stock_cancellation
from items
join orders
    on items.order_id = orders.order_id
left join out_of_stock_cancellations as cancellations
    on items.order_id = cancellations.order_id
