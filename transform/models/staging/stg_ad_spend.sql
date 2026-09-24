with latest as (
    {{ latest_version(source('raw', 'ad_spend')) }}
)

select
    '{{ var("brand") }}'                                            as brand_id,
    id                                                              as ad_spend_id,
    -- ad platforms report in the ad account's timezone, which matches the brand's
    (payload ->> 'date')::date                                      as report_date,
    lower(payload ->> 'platform')                                   as platform,
    payload ->> 'campaign_id'                                       as campaign_id,
    nullif(trim(payload ->> 'campaign_name'), '')                   as campaign_name,
    (payload ->> 'spend')::decimal(12, 2)                           as spend,
    (payload ->> 'impressions')::integer                            as impressions,
    (payload ->> 'clicks')::integer                                 as clicks,
    (payload ->> 'platform_conversions')::integer                   as platform_conversions,
    (payload ->> 'platform_conversion_value')::decimal(12, 2)       as platform_conversion_value,
    timezone('UTC', updated_at::timestamptz)                        as updated_at_utc
from latest
