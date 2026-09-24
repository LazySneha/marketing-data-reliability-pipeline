-- The daily mart must add up to the facts it summarizes, and the incremental spend table
-- must match current (restated) spend. A mismatch means a restatement fell outside the
-- incremental lookback window or a join fanned out.
with checks as (
    select 'spend' as metric,
           (select sum(spend) from {{ ref('mart_marketing_daily') }}) as mart_total,
           (select sum(spend) from {{ ref('stg_ad_spend') }})         as source_total
    union all
    select 'gross_revenue',
           (select sum(gross_revenue) from {{ ref('mart_marketing_daily') }}),
           (select sum(gross_revenue) from {{ ref('stg_orders') }})
    union all
    select 'net_revenue',
           (select sum(net_revenue) from {{ ref('mart_marketing_daily') }}),
           (select sum(gross_revenue) from {{ ref('stg_orders') }})
             - (select coalesce(sum(refund_amount), 0) from {{ ref('stg_refunds') }})
    union all
    select 'campaign_spend',
           (select sum(spend) from {{ ref('mart_campaign_daily') }}),
           (select sum(spend) from {{ ref('stg_ad_spend') }})
)

select *
from checks
where abs(coalesce(mart_total, 0) - coalesce(source_total, 0)) > 0.01
