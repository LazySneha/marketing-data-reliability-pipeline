-- One row per alert. This is the push layer: the pipeline says what changed instead of waiting
-- for someone to open a dashboard. alerts/digest.py turns these rows into a daily Markdown note.
--
-- Every rule has a volume guard. On a quiet day a handful of orders can halve MER on their own,
-- and an alerting layer that fires on noise gets muted within a week.
with risk as (
    select * from {{ ref('mart_spend_at_risk') }}
),

campaign_names as (
    select
        campaign_id,
        coalesce(campaign_name, campaign_id) as campaign_name
    from {{ ref('dim_campaigns') }}
),

-- 1. The SKU has stock today, but the campaign will burn through it before the next delivery.
stockout_risk as (
    select
        risk.report_date                                            as alert_date,
        risk.brand_id,
        'stockout_risk_with_active_spend'                           as alert_type,
        case when risk.days_of_cover < 3 then 'high' else 'medium' end as severity,
        risk.campaign_id || '|' || risk.sku                         as entity_id,
        risk.days_of_cover                                          as observed_value,
        cast(risk.days_to_restock as double)                        as baseline_value,
        printf(
            'Campaign %s (%s) is spending ~$%.2f/day on SKU %s. On-hand stock covers %.1f days; %s. Estimated spend at risk: $%.2f.',
            names.campaign_name,
            risk.platform,
            risk.spend_at_risk,
            risk.sku,
            risk.days_of_cover,
            case
                when risk.days_to_restock is not null
                    then printf('the next PO lands in %d days', risk.days_to_restock)
                else 'no PO is due'
            end,
            -- the days between running out and being restocked are the days the spend is wasted
            risk.spend_at_risk * greatest(
                coalesce(risk.days_to_restock, {{ var('stockout_alert_days') }}) - risk.days_of_cover, 0
            )
        )                                                           as message
    from risk
    join campaign_names as names
        on risk.campaign_id = names.campaign_id
    where risk.risk_reason in ('stockout_before_restock', 'stockout_with_no_restock_due')
      and risk.spend_at_risk > 0
      and risk.on_hand > 0
),

-- 2. Already out of stock and still paying for clicks on it.
spend_on_out_of_stock as (
    select
        risk.report_date                                            as alert_date,
        risk.brand_id,
        'spend_on_out_of_stock_sku'                                 as alert_type,
        'high'                                                      as severity,
        risk.campaign_id || '|' || risk.sku                         as entity_id,
        cast(risk.spend_at_risk as double)                          as observed_value,
        0.0                                                         as baseline_value,
        printf(
            'SKU %s is out of stock and campaign %s (%s) still spent $%.2f on it. Revenue lost to out-of-stock cancellations that day: $%.2f.',
            risk.sku,
            names.campaign_name,
            risk.platform,
            risk.spend_at_risk,
            risk.lost_revenue_out_of_stock
        )                                                           as message
    from risk
    join campaign_names as names
        on risk.campaign_id = names.campaign_id
    where risk.risk_reason = 'spend_on_out_of_stock_sku'
      and risk.spend_at_risk > 0
),

-- 3. and 4. Blended efficiency against its own trailing baseline, not against a target someone
-- picked in a planning meeting.
daily as (
    select
        brand_id,
        report_date,
        orders,
        new_customers,
        cast(mer as double)              as mer,
        cast(new_customer_cac as double) as new_customer_cac
    from {{ ref('mart_marketing_daily') }}
),

-- A single day's MER on twenty orders swings by a third on its own, so the observed side is a
-- 3-day average and only the baseline is the long window. Comparing one noisy day against a
-- smooth baseline is what makes an alerting layer fire constantly and then get ignored.
with_baselines as (
    select
        *,
        avg(mer) over three_days                   as mer_3d,
        avg(new_customer_cac) over three_days      as cac_3d,
        avg(mer) over trailing_window              as mer_baseline,
        avg(new_customer_cac) over trailing_window as cac_baseline
    from daily
    window
        three_days as (order by report_date rows between 2 preceding and current row),
        trailing_window as (
            order by report_date
            rows between {{ var('alert_baseline_days') }} preceding and 1 preceding
        )
),

mer_drop as (
    select
        report_date                                                 as alert_date,
        brand_id,
        'mer_drop'                                                  as alert_type,
        case
            when mer_3d < mer_baseline * (1 - 2 * {{ var('mer_drop_threshold') }}) then 'high'
            else 'medium'
        end                                                         as severity,
        brand_id                                                    as entity_id,
        mer_3d                                                      as observed_value,
        mer_baseline                                                as baseline_value,
        printf(
            'Blended MER is %.2f over the last 3 days against a %d-day baseline of %.2f, on %d orders today.',
            mer_3d, {{ var('alert_baseline_days') }}, mer_baseline, orders
        )                                                           as message
    from with_baselines
    where orders >= {{ var('alert_min_orders') }}
      and mer_3d is not null
      and mer_baseline is not null
      and mer_3d < mer_baseline * (1 - {{ var('mer_drop_threshold') }})
),

cac_spike as (
    select
        report_date                                                 as alert_date,
        brand_id,
        'cac_spike'                                                 as alert_type,
        case
            when cac_3d > cac_baseline * (1 + 2 * {{ var('cac_spike_threshold') }}) then 'high'
            else 'medium'
        end                                                         as severity,
        brand_id                                                    as entity_id,
        cac_3d                                                      as observed_value,
        cac_baseline                                                as baseline_value,
        printf(
            'New-customer CAC is $%.2f over the last 3 days against a %d-day baseline of $%.2f, on %d new customers today.',
            cac_3d, {{ var('alert_baseline_days') }}, cac_baseline, new_customers
        )                                                           as message
    from with_baselines
    where new_customers >= {{ var('alert_min_new_customers') }}
      and cac_3d is not null
      and cac_baseline is not null
      and cac_3d > cac_baseline * (1 + {{ var('cac_spike_threshold') }})
)

select * from stockout_risk
union all
select * from spend_on_out_of_stock
union all
select * from mer_drop
union all
select * from cac_spike
