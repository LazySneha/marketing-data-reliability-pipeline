-- One row per SKU x date: the inventory state that spend-at-risk and the alerts read.
--
-- The daily stock counts are the spine, not the orders: a SKU that sold nothing on a date still
-- needs a row, otherwise the trailing windows below would silently skip days.
with snapshots as (
    select
        brand_id,
        sku,
        snapshot_date,
        on_hand
    from {{ ref('stg_inventory_snapshots') }}
),

daily_sales as (
    select
        sku,
        order_date,
        sum(quantity) as units_sold
    from {{ ref('fct_order_items') }}
    group by sku, order_date
),

-- Units ordered, including units that went on backorder. During a stockout this deliberately
-- exceeds the fall in on_hand: demand and physical stock are different measurements.
spine as (
    select
        snapshots.brand_id,
        snapshots.sku,
        snapshots.snapshot_date,
        snapshots.on_hand,
        coalesce(daily_sales.units_sold, 0) as units_sold
    from snapshots
    left join daily_sales
        on snapshots.sku = daily_sales.sku
       and snapshots.snapshot_date = daily_sales.order_date
),

-- A PO counts as open on a date if it had been placed by then and had not yet been received.
-- is_received alone would answer "is it open now", which is the wrong question for a past day.
open_purchase_orders as (
    select
        spine.sku,
        spine.snapshot_date,
        sum(purchase_orders.ordered_quantity)        as open_po_units,
        min(purchase_orders.expected_arrival_date)   as next_restock_date
    from spine
    join {{ ref('stg_purchase_orders') }} as purchase_orders
        on purchase_orders.sku = spine.sku
       and cast(purchase_orders.ordered_at_utc as date) <= spine.snapshot_date
       and (purchase_orders.received_date is null
            or purchase_orders.received_date > spine.snapshot_date)
    group by spine.sku, spine.snapshot_date
),

measured as (
    select
        spine.brand_id,
        spine.sku,
        spine.snapshot_date,
        spine.on_hand,
        spine.units_sold,
        -- Trailing average ending YESTERDAY: today's sales are not evidence about the cover you
        -- had this morning. ROWS works as "days" only because the spine has no gaps. Partial
        -- windows early in the series divide by the days available, so a new SKU reports the rate
        -- actually observed rather than an artificially low one.
        avg(spine.units_sold) over (
            partition by spine.sku
            order by spine.snapshot_date
            rows between {{ var('velocity_window_days') }} preceding and 1 preceding
        )                                                           as velocity_14d,
        coalesce(open_purchase_orders.open_po_units, 0)             as open_po_units,
        -- Can be in the past. A supplier who missed the promised date leaves the PO open, and
        -- mart_spend_at_risk treats an overdue promise as no promise at all.
        open_purchase_orders.next_restock_date,
        products.supplier_lead_time_days
    from spine
    left join open_purchase_orders
        on spine.sku = open_purchase_orders.sku
       and spine.snapshot_date = open_purchase_orders.snapshot_date
    left join {{ ref('stg_products') }} as products
        on spine.sku = products.sku
),

-- NULL rather than zero or infinity when nothing has sold: "no cover" and "no basis to say"
-- are different answers, and an alert built on the first would be wrong.
with_cover as (
    select
        *,
        on_hand / nullif(velocity_14d, 0)                           as days_of_cover,
        velocity_14d * (supplier_lead_time_days + {{ var('safety_days') }}) as reorder_point
    from measured
)

select
    brand_id,
    sku,
    snapshot_date,
    on_hand,
    units_sold,
    velocity_14d,
    days_of_cover,
    -- floor, not round: the day you run out, not the day you might
    snapshot_date + cast(floor(days_of_cover) as integer)           as projected_stockout_date,
    open_po_units,
    next_restock_date,
    reorder_point,
    -- stock already on its way to you counts towards covering the lead time
    on_hand + open_po_units < reorder_point                         as needs_reorder
from with_cover
