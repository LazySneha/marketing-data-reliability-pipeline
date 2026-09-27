-- One row per campaign x SKU x date where ad spend is exposed to an inventory problem:
-- either the SKU is already out of stock, or it will run out before the next delivery lands.
--
-- Assumption: a campaign's spend is split evenly across the SKUs it promotes. A real ad account
-- would give spend per ad or per product; the mapping seed only says which SKUs a campaign pushes,
-- so an even split is the honest approximation. It is stated in the README for the same reason.
with campaign_skus as (
    select campaign_id, sku
    from {{ ref('campaign_products') }}
    where brand_id = '{{ var("brand") }}'
),

promoted_counts as (
    select campaign_id, count(*) as promoted_skus
    from campaign_skus
    group by campaign_id
),

daily_spend as (
    select report_date, platform, campaign_id, sum(spend) as campaign_spend
    from {{ ref('fct_ad_spend_daily') }}
    group by report_date, platform, campaign_id
),

allocated as (
    select
        daily_spend.report_date,
        daily_spend.platform,
        daily_spend.campaign_id,
        campaign_skus.sku,
        daily_spend.campaign_spend,
        round(daily_spend.campaign_spend / promoted_counts.promoted_skus, 2) as sku_spend
    from daily_spend
    join campaign_skus
        on daily_spend.campaign_id = campaign_skus.campaign_id
    join promoted_counts
        on daily_spend.campaign_id = promoted_counts.campaign_id
),

lost_to_cancellations as (
    select sku, order_date, sum(line_gross_revenue) as lost_revenue
    from {{ ref('fct_order_items') }}
    where is_out_of_stock_cancellation
    group by sku, order_date
),

classified as (
    select
        allocated.report_date,
        allocated.platform,
        allocated.campaign_id,
        allocated.sku,
        allocated.campaign_spend,
        allocated.sku_spend,
        inventory.on_hand,
        inventory.days_of_cover,
        inventory.projected_stockout_date,
        inventory.next_restock_date,
        -- A promised date that has already passed is not a delivery you can plan around, so the
        -- late PO in the demo data stops counting as a restock the day it goes overdue.
        case
            when inventory.next_restock_date > allocated.report_date then inventory.next_restock_date
        end                                                         as reliable_restock_date,
        coalesce(lost.lost_revenue, 0)                              as lost_revenue_out_of_stock
    from allocated
    left join {{ ref('fct_inventory_daily') }} as inventory
        on allocated.sku = inventory.sku
       and allocated.report_date = inventory.snapshot_date
    left join lost_to_cancellations as lost
        on allocated.sku = lost.sku
       and allocated.report_date = lost.order_date
),

risky as (
    select
        *,
        date_diff('day', report_date, reliable_restock_date)        as days_to_restock,
        case
            when on_hand = 0
                then 'spend_on_out_of_stock_sku'
            when reliable_restock_date is not null
                 and projected_stockout_date < reliable_restock_date
                then 'stockout_before_restock'
            when reliable_restock_date is null
                 and days_of_cover <= {{ var('stockout_alert_days') }}
                then 'stockout_with_no_restock_due'
        end                                                         as risk_reason
    from classified
)

select
    '{{ var("brand") }}'                                            as brand_id,
    report_date,
    platform,
    campaign_id,
    sku,
    campaign_spend,
    sku_spend                                                       as spend_at_risk,
    on_hand,
    days_of_cover,
    projected_stockout_date,
    next_restock_date,
    days_to_restock,
    risk_reason,
    lost_revenue_out_of_stock
from risky
where risk_reason is not null
