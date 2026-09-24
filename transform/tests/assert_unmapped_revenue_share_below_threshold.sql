-- Fails when too much revenue comes from utm_sources nobody has mapped.
-- Usually means a new source went live without being added to seeds/utm_source_aliases.csv.
select
    sum(gross_revenue) filter (where attributed_platform = 'unmapped') / sum(gross_revenue) as unmapped_share
from {{ ref('fct_orders') }}
having unmapped_share > {{ var('max_unmapped_revenue_share') }}
