-- Platform x campaign x day. ROAS here is last-click on internal orders and is directional:
-- it can't see view-through or cross-device conversions. MER is the headline number.
with spend as (
    select
        report_date,
        platform,
        campaign_id,
        sum(spend)                     as spend,
        sum(clicks)                    as clicks,
        sum(platform_conversions)      as platform_conversions,
        sum(platform_conversion_value) as platform_conversion_value
    from {{ ref('fct_ad_spend_daily') }}
    group by all
),

attributed as (
    select
        order_date                  as report_date,
        attributed_platform         as platform,
        attributed_campaign_id      as campaign_id,
        count(*)                    as attributed_orders,
        sum(gross_revenue)          as attributed_gross_revenue,
        sum(net_revenue)            as attributed_net_revenue
    from {{ ref('fct_orders') }}
    where attributed_campaign_id is not null
    group by all
)

select
    '{{ var("brand") }}'                                                as brand_id,
    report_date,
    platform,
    campaign_id,
    campaigns.campaign_name,
    coalesce(spend.spend, 0)                                            as spend,
    coalesce(spend.clicks, 0)                                           as clicks,
    coalesce(attributed.attributed_orders, 0)                           as attributed_orders,
    coalesce(attributed.attributed_gross_revenue, 0)                    as attributed_gross_revenue,
    coalesce(attributed.attributed_net_revenue, 0)                      as attributed_net_revenue,
    round(attributed.attributed_net_revenue / nullif(spend.spend, 0), 2) as roas,
    round(spend.spend / nullif(attributed.attributed_orders, 0), 2)     as cpa,
    round(attributed.attributed_orders / nullif(spend.clicks, 0), 4)    as conversion_rate,
    coalesce(spend.platform_conversions, 0)                             as platform_reported_conversions,
    coalesce(spend.platform_conversion_value, 0)                        as platform_reported_revenue,
    round(spend.platform_conversion_value / nullif(spend.spend, 0), 2)  as platform_reported_roas
from spend
full outer join attributed using (report_date, platform, campaign_id)
left join {{ ref('dim_campaigns') }} as campaigns using (platform, campaign_id)
