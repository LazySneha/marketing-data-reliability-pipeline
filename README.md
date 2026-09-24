# Marketing Data Reliability Pipeline

> DRAFT: rewrite this in your own words before it goes public. The README is the writing sample.

Ingests daily ad spend (Meta, Google) and e-commerce orders for multiple brands, standardizes messy campaign metadata, reconciles spend against actual revenue (net of refunds), and produces trusted MER, CAC and AOV.

All data is synthetic. No real brand or customer data.

## Architecture (v1)

```
fake paginated API (per brand)
  -> Python ingestion   pagination · retries/backoff · checkpoints · idempotent load
  -> DuckDB raw_<brand>  append-only, one row per record version
  -> dbt staging         dedup (latest version wins) · type casting · UTM normalization · timezone
  -> dbt marts           fct_orders · fct_refunds · dim_customers · dim_campaigns · fct_ad_spend_daily
  -> mart_marketing_daily (brand x day)
```

## Design decisions

### Tenancy
Each brand is a tenant with its own raw schema (`raw_<brand>`) and its own mart schema, and dbt runs once per brand. Every table also carries `brand_id`, as a second safeguard. The trade-off is that cross-brand benchmarking is harder, which is the right trade when brands' data must never mix.

### Raw layer: append-only, keyed on version
Raw stores the untouched payload with primary key `(id, updated_at)`. Loading the same version twice is a no-op (`INSERT OR IGNORE`), and a newer version of the same record lands as a new row. Nothing in raw is ever updated or deleted, so any downstream model can be rebuilt from it.

### Incremental ingestion
Each brand × entity has a checkpoint: the max `updated_at` fully loaded. The next run asks the API for `updated_at >= checkpoint`. The boundary is **inclusive** on purpose: records that share the checkpoint's timestamp get re-fetched rather than missed, and the idempotent load absorbs the overlap. The checkpoint advances only **after** the load succeeds, so a crash causes a harmless re-pull, never a gap.

### Failure handling
429s wait for `Retry-After`. 503s back off exponentially with jitter. 400s fail immediately, because retrying a bad request only hides a bug. Running out of retries raises; the pipeline never silently skips a page.

### Grain

| Model | One row per | Notes |
|---|---|---|
| `fct_orders` | brand × order | gross revenue = subtotal − discounts (excl. tax & shipping) |
| `fct_refunds` | brand × refund | rolled up onto the order for net revenue |
| `dim_customers` | brand × customer | `first_order_date` drives new-customer CAC |
| `dim_campaigns` | brand × platform × campaign_id | joined on id, never on name |
| `fct_ad_spend_daily` | brand × platform × campaign_id × date | |
| `mart_marketing_daily` | brand × date | spend, orders, gross/net revenue, AOV, MER, CAC |

### Metric definitions
- **Revenue** excludes tax and shipping: tax isn't the brand's money, and shipping is mostly pass-through.
- **Refunds are dated to the original order**, not to the refund date. A day's net revenue therefore reflects that day's orders, and it keeps changing as refunds arrive, which means past days are not final. Refunds arrive up to ~20 days late, so the refund look-back window must be longer than the ad-spend restatement window.
- **AOV is gross** (gross revenue ÷ orders), following industry convention.
- **MER = net revenue ÷ total spend** is the headline number. Platform-reported conversions double-count (Meta and Google both claim the same sale), so they're kept side by side for comparison but never summed.
- **Divide-by-zero returns NULL, not 0.** A day with no spend has no MER. It doesn't have an MER of 0.

### Timezones
Orders arrive in UTC; ad platforms report in the account's local date. Staging converts orders to the brand's `reporting_tz` before bucketing by day. Skipping this is a classic silent ROAS bug: late-evening orders land on the wrong day.

### Messy UTMs
A seed maps every `utm_source` / `utm_medium` alias to a canonical platform. Unknown values go to an explicit `unmapped` bucket, and missing UTMs go to `direct / unattributed`. Revenue is never dropped and the source is never guessed.

## How to run

```bash
python -m source.generate                                   # synthetic data
python -m ingestion.ingest --as-of 2026-08-15T00:00:00Z     # first load
python -m ingestion.ingest                                  # incremental catch-up
```

## Future considerations (deliberately out of scope)
Click-ID / identity stitching · view-through and multi-touch attribution · MMM · cross-device identity · multi-currency · iOS privacy delays · subscriptions and chargebacks.
