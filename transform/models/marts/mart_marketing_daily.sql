-- Brand x day. Spend comes from the ad platforms; revenue comes only from internal orders.
with spend as (
    select
        report_date,
        sum(spend)                     as spend,
        sum(platform_conversion_value) as platform_reported_revenue
    from {{ ref('fct_ad_spend_daily') }}
    group by report_date
),

orders as (
    select
        order_date                                                      as report_date,
        count(*)                                                        as orders,
        count(*) filter (where is_new_customer)                         as new_customers,
        sum(gross_revenue)                                              as gross_revenue,
        sum(refunded_amount)                                            as refunded_amount,
        sum(net_revenue)                                                as net_revenue,
        sum(gross_revenue) filter (where attributed_platform = 'direct')   as unattributed_gross_revenue,
        sum(gross_revenue) filter (where attributed_platform = 'unmapped') as unmapped_gross_revenue
    from {{ ref('fct_orders') }}
    group by order_date
)

select
    '{{ var("brand") }}'                                            as brand_id,
    report_date,
    coalesce(spend.spend, 0)                                        as spend,
    coalesce(orders.orders, 0)                                      as orders,
    coalesce(orders.new_customers, 0)                               as new_customers,
    coalesce(orders.gross_revenue, 0)                               as gross_revenue,
    coalesce(orders.refunded_amount, 0)                             as refunded_amount,
    coalesce(orders.net_revenue, 0)                                 as net_revenue,
    round(orders.gross_revenue / nullif(orders.orders, 0), 2)       as aov,
    round(orders.net_revenue / nullif(spend.spend, 0), 2)           as mer,
    round(spend.spend / nullif(orders.new_customers, 0), 2)         as new_customer_cac,
    -- kept for comparison only; platforms double-count, so never add this to revenue
    coalesce(spend.platform_reported_revenue, 0)                    as platform_reported_revenue,
    coalesce(orders.unattributed_gross_revenue, 0)                  as unattributed_gross_revenue,
    coalesce(orders.unmapped_gross_revenue, 0)                      as unmapped_gross_revenue
from spend
full outer join orders using (report_date)
