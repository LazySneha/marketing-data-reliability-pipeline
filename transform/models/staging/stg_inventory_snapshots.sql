with latest as (
    {{ latest_version(source('raw', 'inventory_snapshots')) }}
)

select
    '{{ var("brand") }}'                                            as brand_id,
    id                                                              as snapshot_id,
    payload ->> 'sku'                                               as sku,
    -- the warehouse counts at close of business, so the date is already the brand's local day
    (payload ->> 'date')::date                                      as snapshot_date,
    (payload ->> 'on_hand')::integer                                as on_hand,
    timezone('UTC', updated_at::timestamptz)                        as updated_at_utc
from latest
