-- One row per refund, carrying the original order's date so revenue can be netted on order date.
select
    refunds.brand_id,
    refunds.refund_id,
    refunds.order_id,
    orders.order_date,
    refunds.refund_date,
    refunds.refund_date - orders.order_date as days_after_order,
    refunds.refund_amount
from {{ ref('stg_refunds') }} as refunds
inner join {{ ref('stg_orders') }} as orders
    on refunds.order_id = orders.order_id
