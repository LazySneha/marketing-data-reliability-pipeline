{{ config(severity='warn') }}

-- Warns when a day's share of unattributed (no UTM) revenue jumps well above its trailing
-- average. A sudden jump usually means tracking broke on the storefront, not that customers
-- stopped clicking ads.
with daily as (
    select
        report_date,
        orders,
        unattributed_gross_revenue / nullif(gross_revenue, 0) as unattributed_share
    from {{ ref('mart_marketing_daily') }}
),

with_baseline as (
    select
        *,
        avg(unattributed_share) over (
            order by report_date rows between 14 preceding and 1 preceding
        ) as baseline_share
    from daily
)

select *
from with_baseline
where orders >= 10
  and baseline_share is not null
  and unattributed_share > baseline_share + 0.40
