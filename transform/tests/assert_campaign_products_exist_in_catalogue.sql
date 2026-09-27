-- The campaign -> SKU seed is maintained by hand, so it drifts when a SKU is renamed or dropped.
-- A mapping to a SKU that does not exist silently removes that campaign's spend from the
-- spend-at-risk mart, which is the worst kind of failure: a report that looks fine.
select
    seed.campaign_id,
    seed.sku
from {{ ref('campaign_products') }} as seed
left join {{ ref('stg_products') }} as products
    on seed.sku = products.sku
where seed.brand_id = '{{ var("brand") }}'
  and products.sku is null
