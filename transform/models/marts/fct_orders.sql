-- One row per order. Internal orders are the source of truth for revenue.
with refunds as (
    select
        order_id,
        sum(refund_amount)   as refunded_amount,
        max(refunded_at_utc) as last_refunded_at_utc
    from {{ ref('stg_refunds') }}
    group by order_id
),

orders as (
    select
        *,
        row_number() over (partition by customer_id order by created_at_utc, order_id) = 1 as is_new_customer
    from {{ ref('stg_orders') }}
)

select
    orders.brand_id,
    orders.order_id,
    orders.customer_id,
    orders.session_id,
    orders.created_at_utc,
    orders.order_date,
    -- the campaign id is authoritative; utm_source is only used when there is no campaign
    coalesce(campaigns.platform, sessions.source_platform, 'direct')    as attributed_platform,
    campaigns.campaign_id                                               as attributed_campaign_id,
    orders.is_new_customer,
    orders.gross_revenue,
    coalesce(refunds.refunded_amount, 0)                                as refunded_amount,
    orders.gross_revenue - coalesce(refunds.refunded_amount, 0)         as net_revenue,
    refunds.last_refunded_at_utc,
    orders.financial_status,
    orders.fulfillment_status
from orders
left join refunds
    on orders.order_id = refunds.order_id
left join {{ ref('stg_sessions') }} as sessions
    on orders.session_id = sessions.session_id
left join {{ ref('dim_campaigns') }} as campaigns
    on sessions.campaign_id = campaigns.campaign_id
