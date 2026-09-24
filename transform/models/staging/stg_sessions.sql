with latest as (
    {{ latest_version(source('raw', 'sessions')) }}
),

cleaned as (
    select
        id                                                          as session_id,
        payload ->> 'customer_id'                                   as customer_id,
        timezone('UTC', (payload ->> 'landing_ts')::timestamptz)    as landed_at_utc,
        payload ->> 'utm_source'                                    as utm_source_raw,
        {{ clean_text("payload ->> 'utm_source'") }}                as utm_source,
        replace(replace({{ clean_text("payload ->> 'utm_medium'") }}, '-', '_'), ' ', '_') as utm_medium,
        {{ clean_text("payload ->> 'utm_campaign'") }}              as utm_campaign,
        nullif(trim(payload ->> 'utm_id'), '')                      as campaign_id
    from latest
)

select
    '{{ var("brand") }}'                                            as brand_id,
    cleaned.*,
    case
        when cleaned.utm_source is null then 'direct'
        else coalesce(aliases.platform, 'unmapped')
    end                                                             as source_platform
from cleaned
left join {{ ref('utm_source_aliases') }} as aliases
    on cleaned.utm_source = aliases.utm_source
