select order_id, gross_revenue, refunded_amount
from {{ ref('fct_orders') }}
where refunded_amount > gross_revenue
