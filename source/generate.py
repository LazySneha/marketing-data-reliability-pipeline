"""
Generate synthetic Shopify-style order data and Meta/Google ad spend for each brand.

The data is deliberately messy in the ways real marketing data is:
  - money fields are strings ("49.00"), as in the Shopify Admin API
  - order timestamps are UTC; ad spend dates are in the brand's local timezone
  - utm_source has many spellings of one platform (facebook, FB, " Facebook ", fb.com ...)
  - some sessions use sources nobody has mapped yet, some have blank or missing UTMs
  - some ad spend rows have a missing or padded campaign_name
  - records change after creation: orders get fulfilled and refunded, ad platforms
    restate spend a few days later. Each change is a new version with a newer updated_at.
  - some records arrive late: they become visible to the API days after their updated_at
  - platform-reported conversion value over-claims compared with real revenue
  - bloom_skin has a two-day tracking outage (Aug 20-21) where no session carries UTMs

Each entity file is a list of record versions. The fake API decides which version is
visible at a given point in time.

Output: data/source/<brand>/<entity>.json
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

CAMPAIGNS = {
    "meta": [("m_1001", "Summer_Sale"), ("m_1002", "Retargeting_ATC"), ("m_1003", "Prospecting_Broad")],
    "google": [("g_2001", "Brand Search"), ("g_2002", "PMax - All Products")],
}
UTM_SOURCE_SPELLINGS = {
    "meta": ["facebook", "Facebook", "FB", "fb", "meta", "instagram", "IG", " Facebook ", "fb.com"],
    "google": ["google", "Google", "GOOGLE", "adwords", "google_ads"],
}
UTM_MEDIUM_SPELLINGS = {
    "meta": ["paid_social", "paid-social", "Paid Social", "cpc"],
    "google": ["cpc", "CPC", "ppc"],
}
UNMAPPED_SOURCES = ["newsletter_sept", "partner-xyz"]
TRACKING_OUTAGES = {"bloom_skin": {date(2026, 8, 20), date(2026, 8, 21)}}


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def money(amount: float) -> str:
    return f"{amount:.2f}"


def messy_campaign_name(name: str, rng: random.Random) -> str:
    return rng.choice([name, name.lower(), name.replace("_", " "), name.lower().replace(" ", "_") + "_2026"])


def make_session(session_id: str, customer_id: str, landing: datetime, rng: random.Random,
                 tracking_broken: bool = False) -> tuple[dict, str | None]:
    session = {
        "id": session_id,
        "customer_id": customer_id,
        "landing_ts": iso(landing),
        "updated_at": iso(landing),
        "utm_source": None,
        "utm_medium": None,
        "utm_campaign": None,
        "utm_id": None,
    }
    roll = rng.random()
    if tracking_broken or roll < 0.13:
        return session, None                      # no UTMs at all
    if roll < 0.15:
        session.update(utm_source="", utm_medium="")  # blank, not null
        return session, None
    if roll < 0.165:
        session.update(utm_source=rng.choice(UNMAPPED_SOURCES), utm_medium="email")
        return session, None

    platform = "meta" if rng.random() < 0.6 else "google"
    campaign_id, campaign_name = rng.choice(CAMPAIGNS[platform])
    session.update(
        utm_source=rng.choice(UTM_SOURCE_SPELLINGS[platform]),
        utm_medium=rng.choice(UTM_MEDIUM_SPELLINGS[platform]),
        utm_campaign=messy_campaign_name(campaign_name, rng),
        utm_id=campaign_id,
    )
    return session, campaign_id


def order_versions(order: dict, created: datetime, refund_at: datetime | None,
                   refund_is_full: bool, rng: random.Random) -> list[dict]:
    versions = [dict(order, updated_at=iso(created))]
    if rng.random() < 0.7:
        fulfilled = created + timedelta(days=rng.randint(1, 4), hours=rng.randint(0, 12))
        versions.append(dict(versions[-1], fulfillment_status="fulfilled", updated_at=iso(fulfilled)))
    if refund_at:
        status = "refunded" if refund_is_full else "partially_refunded"
        versions.append(dict(versions[-1], financial_status=status, updated_at=iso(refund_at)))
    return versions


def arrive_late(record: dict, rng: random.Random, probability: float, max_days: int) -> dict:
    """Mark a record as reaching the API some days after its updated_at."""
    if rng.random() < probability:
        updated = datetime.strptime(record["updated_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        record["_available_at"] = iso(updated + timedelta(days=rng.randint(1, max_days)))
    return record


def generate_brand(brand: str, brand_index: int) -> dict[str, list[dict]]:
    rng = random.Random(SEED + brand_index)
    tz = ZoneInfo(config.BRANDS[brand]["reporting_tz"])
    prefix = brand.split("_")[0][:3]

    customers, sessions, orders, refunds, ad_spend = [], [], [], [], []
    attributed_revenue: dict[tuple[date, str], float] = {}

    for day_number in range(DAYS):
        day = START + timedelta(days=day_number)

        for _ in range(rng.randint(15, 30)):
            local_ts = datetime.combine(day, time(0), tz) + timedelta(seconds=rng.randint(0, 86399))
            created = local_ts.astimezone(timezone.utc)

            if customers and rng.random() < 0.35:
                customer = rng.choice(customers)
            else:
                n = len(customers) + 1
                customer = {
                    "id": f"{prefix}_cust_{n:05d}",
                    "email": f"customer{n}@example.com",
                    "created_at": iso(created),
                    "updated_at": iso(created),
                }
                customers.append(customer)

            landing = created - timedelta(minutes=rng.randint(1, 90))
            session, campaign_id = make_session(
                f"{prefix}_sess_{len(sessions) + 1:06d}", customer["id"], landing, rng,
                tracking_broken=day in TRACKING_OUTAGES.get(brand, set()),
            )
            sessions.append(session)

            subtotal = round(rng.uniform(25, 180), 2)
            discount = round(subtotal * rng.choice([0.1, 0.15, 0.2]), 2) if rng.random() < 0.3 else 0.0
            net = round(subtotal - discount, 2)
            order = {
                "id": f"{prefix}_ord_{len(orders) + 1:06d}",
                "customer_id": customer["id"],
                "session_id": session["id"],
                "created_at": iso(created),
                "currency": "USD",
                "subtotal_price": money(subtotal),
                "total_discounts": money(discount),
                "total_tax": money(net * 0.08),
                "total_shipping": rng.choice(["0.00", "6.95"]),
                "financial_status": "paid",
                "fulfillment_status": None,
            }

            refund_at, refund_is_full = None, False
            if rng.random() < 0.08:
                refund_at = created + timedelta(days=rng.randint(1, 20), hours=rng.randint(0, 23))
                refund_is_full = rng.random() < 0.6
                amount = net if refund_is_full else round(net * rng.uniform(0.2, 0.7), 2)
                refunds.append(arrive_late({
                    "id": f"{prefix}_ref_{len(refunds) + 1:05d}",
                    "order_id": order["id"],
                    "created_at": iso(refund_at),
                    "updated_at": iso(refund_at),
                    "amount": money(amount),
                }, rng, probability=0.05, max_days=2))

            for version in order_versions(order, created, refund_at, refund_is_full, rng):
                orders.append(arrive_late(version, rng, probability=0.03, max_days=2))

            if campaign_id:
                key = (day, campaign_id)
                attributed_revenue[key] = attributed_revenue.get(key, 0.0) + net

        # Ad platforms report each day's spend the next morning (brand-local date).
        for platform, campaigns in CAMPAIGNS.items():
            for campaign_id, campaign_name in campaigns:
                spend = round(rng.uniform(80, 400), 2)
                clicks = int(spend / rng.uniform(0.8, 2.5))
                revenue = attributed_revenue.get((day, campaign_id), 0.0)
                reported_at = datetime.combine(day + timedelta(days=1), time(6), tz) + timedelta(minutes=rng.randint(0, 120))

                name_roll = rng.random()
                if name_roll < 0.03:
                    shown_name = None
                elif name_roll < 0.06:
                    shown_name = f"  {campaign_name} "
                else:
                    shown_name = campaign_name

                row = {
                    "id": f"{platform}-{campaign_id}-{day.isoformat()}",
                    "date": day.isoformat(),
                    "platform": platform,
                    "campaign_id": campaign_id,
                    "campaign_name": shown_name,
                    "spend": money(spend),
                    "impressions": clicks * rng.randint(40, 90),
                    "clicks": clicks,
                    "platform_conversions": int(revenue / 60 * rng.uniform(1.1, 1.6)) if revenue else rng.randint(0, 2),
                    "platform_conversion_value": money(revenue * rng.uniform(1.1, 1.6)),
                    "updated_at": iso(reported_at),
                }
                ad_spend.append(arrive_late(row, rng, probability=0.05, max_days=4))

                if rng.random() < 0.12:  # platform restates spend 1-3 days later
                    restated_at = reported_at + timedelta(days=rng.randint(1, 3))
                    ad_spend.append({
                        **{k: v for k, v in row.items() if not k.startswith("_")},
                        "spend": money(spend * rng.uniform(0.9, 1.15)),
                        "updated_at": iso(restated_at),
                    })

    return {"customers": customers, "sessions": sessions, "orders": orders,
            "refunds": refunds, "ad_spend": ad_spend}


def main() -> None:
    for index, brand in enumerate(config.BRANDS):
        out_dir = config.SOURCE_DIR / brand
        out_dir.mkdir(parents=True, exist_ok=True)
        data = generate_brand(brand, index)
        for entity, rows in data.items():
            (out_dir / f"{entity}.json").write_text(json.dumps(rows, indent=1))
        print(f"{brand}: " + ", ".join(f"{len({r['id'] for r in rows})} {name}" for name, rows in data.items()))


if __name__ == "__main__":
    main()
