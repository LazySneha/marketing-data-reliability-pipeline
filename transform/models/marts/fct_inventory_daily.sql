-- One row per SKU x date: the inventory state that spend-at-risk and the alerts read.
--
-- ============================== THIS MODEL IS YOURS TO WRITE ==============================
-- Everything below the placeholder line is scaffolding so the rest of the pipeline compiles
-- and runs. Replace it. The failing test to work against is
--   tests/test_alerts.py::test_stockout_alert_fires_before_the_stockout
-- and `dbt build --select fct_inventory_daily+ --vars '{brand: acme_apparel, reporting_tz: America/New_York}'`
-- rebuilds this model and everything downstream of it.
--
-- Grain: one row for every (sku, snapshot_date) in stg_inventory_snapshots. The snapshots are
-- the spine, not the orders: a SKU that sold nothing on a date still needs its row.
--
-- Columns and their contracts:
--
--   brand_id                 '{{ var("brand") }}'
--   sku                      from stg_inventory_snapshots
--   snapshot_date            the brand's local day, already local in staging
--   on_hand                  units in the warehouse at close of business
--
--   units_sold               units ordered that day, from fct_order_items (sum of quantity by
--                            sku and order_date). Counts units that went on backorder, so during
--                            a stockout units_sold can exceed the fall in on_hand. A date with no
--                            orders is 0, not NULL.
--
--   velocity_14d             trailing average units_sold per day over var('velocity_window_days')
--                            days, ending the day BEFORE snapshot_date (today's sales are not
--                            evidence about today's cover). Use a window function, not a self-join.
--                            Early dates have a partial window: decide whether you divide by the
--                            window length or by the days actually available, and say which in a
--                            comment. An interviewer will ask.
--
--   days_of_cover            on_hand / velocity_14d. NULL when velocity_14d is 0 -- never divide by
--                            zero, and "nothing sold recently" is not "infinite cover".
--
--   projected_stockout_date  snapshot_date + days_of_cover days, NULL when days_of_cover is NULL.
--                            In DuckDB, a date plus a variable number of days is
--                            snapshot_date + (cast(days_of_cover as integer) * interval 1 day).
--
--   open_po_units            units on POs for this SKU placed on or before snapshot_date and not
--                            received as at snapshot_date. This is a point-in-time question, so
--                            is_received alone is not enough: compare ordered_at_utc and
--                            received_date against snapshot_date.
--
--   next_restock_date        earliest expected_arrival_date among those open POs. It can be in the
--                            PAST: a supplier who has missed the promised date leaves the PO open.
--                            That is the late-PO case, and mart_spend_at_risk deliberately treats
--                            an overdue promise as no promise at all.
--
--   reorder_point            velocity_14d * (supplier_lead_time_days + var('safety_days')), with
--                            the lead time from stg_products.
--
--   needs_reorder            on_hand + open_po_units < reorder_point.
--
-- ============================ PLACEHOLDER -- DELETE FROM HERE ============================
select
    snapshots.brand_id,
    snapshots.sku,
    snapshots.snapshot_date,
    snapshots.on_hand,
    cast(null as integer)  as units_sold,
    cast(null as double)   as velocity_14d,
    cast(null as double)   as days_of_cover,
    cast(null as date)     as projected_stockout_date,
    cast(null as integer)  as open_po_units,
    cast(null as date)     as next_restock_date,
    cast(null as double)   as reorder_point,
    cast(null as boolean)  as needs_reorder
from {{ ref('stg_inventory_snapshots') }} as snapshots
