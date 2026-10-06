-- One row per order cancelled because something in it was out of stock: what the stockout
-- cost in sales, and roughly what it cost in ads.
--
-- Two things mart_spend_at_risk can't show, because its grain is campaign x SKU x day:
--   * Basket loss. The whole order is refunded, so in-stock items in the same cart are lost too.
--     An item counts as out of stock if on-hand was 0 at close of business on the order date.
--   * The ad cost of winning an order that then produced nothing. Spend is only reported per
--     campaign per day, so this is an estimate: the campaign's cost per attributed order over the
--     order's calendar month. It overlaps mart_spend_at_risk.spend_at_risk; never add the two.
with lines as (
    select
        items.order_id,
        items.order_date,
        items.attributed_platform,
        items.attributed_campaign_id,
        items.sku,
        items.line_gross_revenue,
        inventory.on_hand = 0                                       as is_out_of_stock_item
    from {{ ref('fct_order_items') }} as items
    left join {{ ref('fct_inventory_daily') }} as inventory
        on items.sku = inventory.sku
       and items.order_date = inventory.snapshot_date
    where items.is_out_of_stock_cancellation
),

campaign_cost_per_order as (
    select
        campaign_id,
        date_trunc('month', report_date)                           as report_month,
        sum(spend) / nullif(sum(attributed_orders), 0)              as cost_per_order
    from {{ ref('mart_campaign_daily') }}
    group by campaign_id, date_trunc('month', report_date)
),

orders as (
    select
        order_id,
        any_value(order_date)                                       as order_date,
        any_value(attributed_platform)                              as attributed_platform,
        any_value(attributed_campaign_id)                           as attributed_campaign_id,
        string_agg(sku, ', ' order by sku) filter (where is_out_of_stock_item)
                                                                    as out_of_stock_skus,
        round(sum(line_gross_revenue), 2)                           as lost_revenue,
        round(coalesce(sum(line_gross_revenue) filter (where is_out_of_stock_item), 0), 2)
                                                                    as lost_revenue_out_of_stock_items,
        round(coalesce(sum(line_gross_revenue) filter (where not is_out_of_stock_item), 0), 2)
                                                                    as lost_revenue_in_stock_items
    from lines
    group by order_id
)

select
    '{{ var("brand") }}'                                            as brand_id,
    orders.order_id,
    orders.order_date,
    orders.attributed_platform,
    orders.attributed_campaign_id,
    orders.out_of_stock_skus,
    orders.lost_revenue,
    orders.lost_revenue_out_of_stock_items,
    orders.lost_revenue_in_stock_items,
    -- No campaign on the landing session means no paid click to account for.
    case
        when orders.attributed_campaign_id is null then 0
        else round(cost.cost_per_order, 2)
    end                                                             as estimated_ad_cost
from orders
left join campaign_cost_per_order as cost
    on orders.attributed_campaign_id = cost.campaign_id
   and date_trunc('month', orders.order_date) = cost.report_month
