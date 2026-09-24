-- One row per campaign. campaign_id is the stable key; names change and get mistyped.
select
    brand_id,
    platform,
    campaign_id,
    arg_max(campaign_name, report_date) filter (where campaign_name is not null) as campaign_name,
    min(report_date)                                                            as first_spend_date,
    max(report_date)                                                            as last_spend_date
from {{ ref('stg_ad_spend') }}
group by all
