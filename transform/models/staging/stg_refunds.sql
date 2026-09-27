with latest as (
    {{ latest_version(source('raw', 'refunds')) }}
)

select
    '{{ var("brand") }}'                                            as brand_id,
    id                                                              as refund_id,
    payload ->> 'order_id'                                          as order_id,
    timezone('UTC', (payload ->> 'created_at')::timestamptz)        as refunded_at_utc,
    cast(timezone('{{ var("reporting_tz") }}', (payload ->> 'created_at')::timestamptz) as date) as refund_date,
    (payload ->> 'amount')::decimal(12, 2)                          as refund_amount,
    -- out_of_stock means the customer gave up on a backorder, which is a spend problem
    {{ clean_text("payload ->> 'reason'") }}                        as refund_reason
from latest
