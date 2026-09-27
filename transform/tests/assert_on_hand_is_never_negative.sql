-- You cannot hold minus four units. A negative on-hand means the snapshot logic drifted, or
-- backordered units were deducted from stock that was never there.
select
    sku,
    snapshot_date,
    on_hand
from {{ ref('fct_inventory_daily') }}
where on_hand < 0
