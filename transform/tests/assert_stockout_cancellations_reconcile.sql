-- Every out-of-stock cancellation in fct_order_items must land in fct_stockout_cancellations,
-- each order must split cleanly into out-of-stock and in-stock items, and each must contain at
-- least one item that really was out of stock. If the last check fails, the snapshot timing and
-- the cancellation reason disagree, and the split between the two kinds of loss can't be trusted.
with source_total as (
    select round(coalesce(sum(line_gross_revenue), 0), 2) as total
    from {{ ref('fct_order_items') }}
    where is_out_of_stock_cancellation
),

model_total as (
    select round(coalesce(sum(lost_revenue), 0), 2) as total
    from {{ ref('fct_stockout_cancellations') }}
)

select 'total does not reconcile' as problem, null as order_id
from source_total, model_total
where abs(source_total.total - model_total.total) > 0.01

union all

select 'split does not add up', order_id
from {{ ref('fct_stockout_cancellations') }}
where abs(lost_revenue - lost_revenue_out_of_stock_items - lost_revenue_in_stock_items) > 0.01

union all

select 'no out-of-stock item in the order', order_id
from {{ ref('fct_stockout_cancellations') }}
where out_of_stock_skus is null
