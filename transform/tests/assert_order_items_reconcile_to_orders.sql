-- An order's line items must add up to the subtotal the order itself reports, and every order
-- must have lines at all. If this drifts, every per-SKU number downstream is quietly wrong.
with lines as (
    select
        order_id,
        round(sum(line_subtotal), 2) as line_total
    from {{ ref('stg_order_items') }}
    group by order_id
)

select
    orders.order_id,
    orders.subtotal,
    lines.line_total
from {{ ref('stg_orders') }} as orders
left join lines
    on orders.order_id = lines.order_id
where lines.line_total is null
   or abs(orders.subtotal - lines.line_total) > 0.01
