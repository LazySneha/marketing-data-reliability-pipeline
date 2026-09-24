{{ config(severity='warn') }}

-- Platforms routinely restate recent spend by a few percent. A large swing is worth a human look.
with versions as (
    select
        id,
        (payload ->> 'spend')::decimal(12, 2) as spend,
        row_number() over (partition by id order by updated_at asc)  as first_rank,
        row_number() over (partition by id order by updated_at desc) as last_rank
    from {{ source('raw', 'ad_spend') }}
)

select
    first_version.id,
    first_version.spend as first_reported_spend,
    last_version.spend  as current_spend
from versions as first_version
inner join versions as last_version
    on first_version.id = last_version.id
where first_version.first_rank = 1
  and last_version.last_rank = 1
  and first_version.spend > 0
  and abs(last_version.spend - first_version.spend) / first_version.spend > 0.25
