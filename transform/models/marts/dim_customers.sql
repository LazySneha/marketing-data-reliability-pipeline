select
    customers.brand_id,
    customers.customer_id,
    customers.created_at_utc,
    min(orders.created_at_utc)  as first_order_at_utc,
    min(orders.order_date)      as first_order_date,
    count(orders.order_id)      as order_count
from {{ ref('stg_customers') }} as customers
left join {{ ref('stg_orders') }} as orders
    on customers.customer_id = orders.customer_id
group by all
