{{ config(severity='warn') }}

-- A campaign with spend but no SKU mapping cannot be checked against stock, so its spend is
-- invisible to the alerts. That is a gap in the mapping rather than broken data, so it warns:
-- brand campaigns and always-on PMax legitimately promote the whole catalogue.
select
    campaign_id,
    round(sum(spend), 2) as spend
from {{ ref('fct_ad_spend_daily') }}
where campaign_id not in (
    select campaign_id
    from {{ ref('campaign_products') }}
    where brand_id = '{{ var("brand") }}'
)
group by campaign_id
