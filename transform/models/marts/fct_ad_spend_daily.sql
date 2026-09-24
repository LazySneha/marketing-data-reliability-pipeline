{{
    config(
        materialized='incremental',
        unique_key='ad_spend_id',
        incremental_strategy='delete+insert'
    )
}}

-- Platforms restate recent days, so each incremental run rebuilds a trailing window
-- instead of only appending new dates.
select
    brand_id,
    ad_spend_id,
    report_date,
    platform,
    campaign_id,
    spend,
    impressions,
    clicks,
    platform_conversions,
    platform_conversion_value,
    updated_at_utc
from {{ ref('stg_ad_spend') }}

{% if is_incremental() %}
where report_date >= (
    select max(report_date) - interval {{ var('ad_spend_lookback_days') }} day from {{ this }}
)
{% endif %}
