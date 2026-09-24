"""
Generate synthetic Shopify-shaped source data for each brand.

BOILERPLATE: written for you. You don't need to be able to write this in an interview,
but you DO need to know what mess it bakes in, because your pipeline has to handle it:

  - money fields are strings ("49.00"), like the real Shopify Admin API
  - order timestamps are UTC; ad_spend dates are in the brand's local timezone
  - utm_source has many spellings of one platform (facebook / FB / meta / IG ...)
  - a few sessions carry sources nobody has mapped yet (newsletter_sept, partner-xyz)
  - ~15% of sessions have no UTMs at all
  - ~30% of orders are updated days after creation, so updated_at != created_at
  - ~8% of orders get a refund 1-20 days later (full or partial)
  - platform-reported conversion_value is inflated vs real revenue (platforms over-claim)

Output: data/source/<brand>/<entity>.json   (one JSON list per entity)
Run:    python -m source.generate
"""
import json
import random
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import config

SEED = 42
START = date(2026, 7, 1)
DAYS = 60

CAMPAIGNS = {  # platform -> [(campaign_id, campaign_name)]
    "meta": [("m_1001", "Summer_Sale"), ("m_1002", "Retargeting_ATC"), ("m_1003", "Prospecting_Broad")],
    "google": [("g_2001", "Brand Search"), ("g_2002", "PMax - All Products")],
}
UTM_SOURCE_ALIASES = {
    "meta": ["facebook", "Facebook", "FB", "fb", "meta", "instagram", "IG"],
    "google": ["google", "Google", "adwords", "google_ads"],
}
UTM_MEDIUM_ALIASES = {
    "meta": ["paid_social", "paid-social", "Paid Social", "cpc"],
    "google": ["cpc", "CPC", "ppc"],
}
UNMAPPED_SOURCES = ["newsletter_sept", "partner-xyz"]


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def money(x: float) -> str:
    return f"{x:.2f}"


def messy_campaign_name(name: str, rng: random.Random) -> str:
    return rng.choice([name, name.lower(), name.replace("_", " "), name.lower().replace(" ", "_") + "_2026"])


def generate_brand(brand: str, brand_index: int) -> dict[str, list[dict]]:
    rng = random.Random(SEED + brand_index)
    tz = ZoneInfo(config.BRANDS[brand]["reporting_tz"])
    prefix = brand.split("_")[0][:3]

    customers, sessions, orders, refunds, ad_spend = [], [], [], [], []
    # real revenue per (local date, campaign_id), used to build inflated platform numbers
    real_rev: dict[tuple[date, str], float] = {}

    for d in range(DAYS):
        day = START + timedelta(days=d)
        for _ in range(rng.randint(15, 30)):
            local_ts = datetime.combine(day, time(0), tz) + timedelta(seconds=rng.randint(0, 86399))
            created = local_ts.astimezone(timezone.utc)

            # customer: ~35% returning, otherwise new
            if customers and rng.random() < 0.35:
                cust = rng.choice(customers)
            else:
                cust = {
                    "id": f"{prefix}_cust_{len(customers) + 1:05d}",
                    "email": f"customer{len(customers) + 1}@example.com",
                    "created_at": iso(created),
                    "updated_at": iso(created),
                }
                customers.append(cust)

            # session with (messy) UTMs
            session = {
                "id": f"{prefix}_sess_{len(sessions) + 1:06d}",
                "customer_id": cust["id"],
                "landing_ts": iso(created - timedelta(minutes=rng.randint(1, 90))),
                "utm_source": None, "utm_medium": None, "utm_campaign": None, "utm_id": None,
            }
            campaign_id = None
            r = rng.random()
            if r < 0.15:
                pass  # no UTMs at all -> must land in direct / unattributed
            elif r < 0.18:
                session.update(utm_source=rng.choice(UNMAPPED_SOURCES), utm_medium="email")
            else:
                platform = "meta" if rng.random() < 0.6 else "google"
                campaign_id, campaign_name = rng.choice(CAMPAIGNS[platform])
                session.update(
                    utm_source=rng.choice(UTM_SOURCE_ALIASES[platform]),
                    utm_medium=rng.choice(UTM_MEDIUM_ALIASES[platform]),
                    utm_campaign=messy_campaign_name(campaign_name, rng),
                    utm_id=campaign_id,
                )
            session["updated_at"] = session["landing_ts"]
            sessions.append(session)

            # order
            subtotal = round(rng.uniform(25, 180), 2)
            discount = round(subtotal * rng.choice([0.1, 0.15, 0.2]), 2) if rng.random() < 0.3 else 0.0
            updated = created + timedelta(days=rng.randint(1, 5)) if rng.random() < 0.3 else created
            order = {
                "id": f"{prefix}_ord_{len(orders) + 1:06d}",
                "customer_id": cust["id"],
                "session_id": session["id"],
                "created_at": iso(created),
                "updated_at": iso(updated),
                "currency": "USD",
                "subtotal_price": money(subtotal),
                "total_discounts": money(discount),
                "total_tax": money((subtotal - discount) * 0.08),
                "total_shipping": rng.choice(["0.00", "6.95"]),
                "financial_status": "paid",
            }

            # refund ~8%
            if rng.random() < 0.08:
                refund_ts = created + timedelta(days=rng.randint(1, 20), hours=rng.randint(0, 23))
                net = subtotal - discount
                amount = net if rng.random() < 0.6 else round(net * rng.uniform(0.2, 0.7), 2)
                refunds.append({
                    "id": f"{prefix}_ref_{len(refunds) + 1:05d}",
                    "order_id": order["id"],
                    "created_at": iso(refund_ts),
                    "updated_at": iso(refund_ts),
                    "amount": money(amount),
                })
                order["financial_status"] = "refunded" if amount == net else "partially_refunded"
                order["updated_at"] = iso(max(updated, refund_ts))
            orders.append(order)

            if campaign_id:
                key = (day, campaign_id)
                real_rev[key] = real_rev.get(key, 0.0) + (subtotal - discount)

        # ad spend: one row per platform x campaign x local date, reported the next morning
        for platform, camps in CAMPAIGNS.items():
            for campaign_id, campaign_name in camps:
                spend = round(rng.uniform(80, 400), 2)
                clicks = int(spend / rng.uniform(0.8, 2.5))
                rev = real_rev.get((day, campaign_id), 0.0)
                reported_at = datetime.combine(day + timedelta(days=1), time(6), tz) + timedelta(minutes=rng.randint(0, 120))
                ad_spend.append({
                    "id": f"{platform}-{campaign_id}-{day.isoformat()}",
                    "date": day.isoformat(),               # brand-local date, NOT UTC
                    "platform": platform,
                    "campaign_id": campaign_id,
                    "campaign_name": campaign_name,
                    "spend": money(spend),
                    "impressions": clicks * rng.randint(40, 90),
                    "clicks": clicks,
                    "platform_conversions": int(rev / 60 * rng.uniform(1.1, 1.6)) if rev else rng.randint(0, 2),
                    "platform_conversion_value": money(rev * rng.uniform(1.1, 1.6)),
                    "updated_at": iso(reported_at),
                })

    return {"customers": customers, "sessions": sessions, "orders": orders,
            "refunds": refunds, "ad_spend": ad_spend}


def main() -> None:
    for i, brand in enumerate(config.BRANDS):
        out_dir = config.SOURCE_DIR / brand
        out_dir.mkdir(parents=True, exist_ok=True)
        data = generate_brand(brand, i)
        for entity, rows in data.items():
            (out_dir / f"{entity}.json").write_text(json.dumps(rows, indent=1))
        print(f"{brand}: " + ", ".join(f"{len(v)} {k}" for k, v in data.items()))


if __name__ == "__main__":
    main()
