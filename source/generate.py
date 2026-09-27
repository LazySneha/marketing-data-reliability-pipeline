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

v2 adds the inventory side, because ad spend and stock are the same problem:
  - orders are built from line items, so an order's subtotal is the sum of its items
  - each brand sells ~12 SKUs, and each campaign promotes a few of them
  - a campaign's spend drives demand for the SKUs it promotes
  - stock is snapshotted daily: it falls with sales and rises when a PO is received
  - an order for an SKU with no stock is a backorder, and some backorders get
    cancelled a week or two later as full refunds with reason = out_of_stock
  - one scenario per brand is built on purpose: the hero SKU of the best-spending
    campaign sells out mid-period while the campaign keeps spending, and its
    replacement PO arrives 12 days after the date the supplier promised

Each entity file is a list of record versions. The fake API decides which version is
visible at a given point in time.

Output: data/source/<brand>/<entity>.json
Run:    python -m source.generate
"""
import json
import random
from collections import defaultdict
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

REFUND_REASONS = ["damaged", "changed_mind", "wrong_size", "late_delivery"]
OUT_OF_STOCK = "out_of_stock"

# sku, title, price, unit_cost, supplier_lead_time_days
CATALOG = {
    "acme_apparel": [
        ("TEE-BLK-M", "Essential Tee - Black - M", 38.00, 11.50, 21),
        ("TEE-BLK-L", "Essential Tee - Black - L", 38.00, 11.50, 21),
        ("TEE-WHT-M", "Essential Tee - White - M", 38.00, 11.50, 21),
        ("HOOD-GRY-L", "Heavyweight Hoodie - Grey - L", 89.00, 28.00, 35),
        ("JEAN-IND-32", "Slim Jean - Indigo - 32", 118.00, 34.00, 45),
        ("JEAN-IND-34", "Slim Jean - Indigo - 34", 118.00, 34.00, 45),
        ("SHORT-KHA-32", "Chino Short - Khaki - 32", 58.00, 17.00, 30),
        ("DRESS-RED-S", "Wrap Dress - Red - S", 128.00, 38.00, 42),
        ("JKT-OLV-M", "Field Jacket - Olive - M", 168.00, 52.00, 60),
        ("CAP-NVY", "Logo Cap - Navy", 32.00, 8.00, 28),
        ("BELT-BRN", "Leather Belt - Brown", 48.00, 14.00, 25),
        ("SOCK-3PK", "Crew Socks 3-Pack", 22.00, 5.50, 14),
    ],
    "bloom_skin": [
        ("SERUM-VITC-30", "Vitamin C Serum 30ml", 68.00, 14.00, 30),
        ("SERUM-RET-30", "Retinol Serum 30ml", 78.00, 17.00, 30),
        ("CLEANSE-GEL-150", "Gel Cleanser 150ml", 32.00, 7.00, 21),
        ("MOIST-DAY-50", "Day Moisturiser 50ml", 54.00, 12.00, 25),
        ("MOIST-NGT-50", "Night Cream 50ml", 62.00, 14.00, 25),
        ("SPF-50-50", "Mineral SPF 50 - 50ml", 42.00, 9.50, 35),
        ("MASK-CLAY-100", "Clay Mask 100ml", 38.00, 8.00, 21),
        ("TONER-ROSE-200", "Rose Toner 200ml", 34.00, 7.50, 21),
        ("EYE-CRM-15", "Eye Cream 15ml", 58.00, 13.00, 28),
        ("OIL-ARG-30", "Argan Oil 30ml", 46.00, 10.00, 40),
        ("SCRUB-SUG-200", "Sugar Scrub 200ml", 28.00, 6.00, 21),
        ("LIP-BLM-10", "Lip Balm 10ml", 16.00, 3.50, 14),
    ],
}

# Which SKUs each campaign promotes. Written out to seeds/campaign_products.csv as well,
# because the warehouse needs the same mapping to join spend to stock.
CAMPAIGN_PRODUCTS = {
    "acme_apparel": {
        "m_1001": ["TEE-BLK-M", "SHORT-KHA-32", "SOCK-3PK"],
        "m_1002": ["HOOD-GRY-L", "JEAN-IND-32"],
        "m_1003": ["TEE-WHT-M", "CAP-NVY", "DRESS-RED-S"],
        "g_2001": ["JEAN-IND-34", "BELT-BRN"],
        "g_2002": ["JKT-OLV-M", "TEE-BLK-L"],
    },
    "bloom_skin": {
        "m_1001": ["SERUM-VITC-30", "CLEANSE-GEL-150", "LIP-BLM-10"],
        "m_1002": ["MOIST-DAY-50", "MOIST-NGT-50"],
        "m_1003": ["SPF-50-50", "MASK-CLAY-100", "SCRUB-SUG-200"],
        "g_2001": ["SERUM-RET-30", "TONER-ROSE-200"],
        "g_2002": ["EYE-CRM-15", "OIL-ARG-30"],
    },
}

# The designed scenario. The hero SKU is the bestseller of the highest-spending campaign;
# it starts with about a month of cover and its replacement PO is promised for day 38 but
# lands on day 50. HERO_CAMPAIGN keeps spending at a high, steady rate the whole time.
HERO_CAMPAIGN = "m_1001"
HERO_SKU = {"acme_apparel": "TEE-BLK-M", "bloom_skin": "SERUM-VITC-30"}
HERO_INITIAL_STOCK = {"acme_apparel": 300, "bloom_skin": 290}
HERO_PO_QUANTITY = 500
HERO_PO_EXPECTED_DAY = 54
HERO_PO_RECEIVED_DAY = 58
HERO_SPEND_RANGE = (280.0, 340.0)

STOCKED_INITIAL = 400        # every other SKU starts with enough not to run out
RESTOCK_ORDER_DAY = 10       # routine POs for the other SKUs
RESTOCK_QUANTITY = 200


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
                   refund_is_full: bool, rng: random.Random,
                   is_backorder: bool = False) -> list[dict]:
    versions = [dict(order, updated_at=iso(created))]
    # A backordered order is never fulfilled: it either ships after the restock or is cancelled.
    if not is_backorder and rng.random() < 0.7:
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


def pick_line_items(rng: random.Random, skus: list[str], promoted: list[str] | None,
                    hero: str) -> list[tuple[str, int]]:
    """Choose 1-3 line items. A campaign's promoted SKUs are what its clicks mostly buy."""
    quantities: dict[str, int] = defaultdict(int)

    if promoted and rng.random() < 0.75:
        first = hero if hero in promoted and rng.random() < 0.7 else rng.choice(promoted)
    else:
        # the hero SKU is the brand's bestseller, so it shows up in untracked orders too
        weights = [3 if sku == hero else 1 for sku in skus]
        first = rng.choices(skus, weights=weights)[0]
    quantities[first] += rng.choices([1, 2, 3], weights=[6, 3, 1])[0]

    for _ in range(rng.choices([0, 1, 2], weights=[5, 4, 1])[0]):
        quantities[rng.choice(skus)] += 1

    return list(quantities.items())


def purchase_order_plan(brand: str, rng: random.Random,
                        lead_times: dict[str, int]) -> list[dict]:
    """One routine PO per SKU, plus the hero SKU's late one. Day numbers are offsets from START."""
    hero = HERO_SKU[brand]
    plan = [{
        "sku": hero,
        "quantity": HERO_PO_QUANTITY,
        "ordered_day": HERO_PO_EXPECTED_DAY - lead_times[hero],
        "expected_day": HERO_PO_EXPECTED_DAY,
        "received_day": HERO_PO_RECEIVED_DAY,
    }]

    for sku, lead_time in lead_times.items():
        if sku == hero:
            continue
        expected_day = RESTOCK_ORDER_DAY + lead_time
        plan.append({
            "sku": sku,
            "quantity": RESTOCK_QUANTITY,
            "ordered_day": RESTOCK_ORDER_DAY,
            "expected_day": expected_day,
            # a PO whose expected arrival is past the end of the window stays open
            "received_day": expected_day + rng.randint(0, 2) if expected_day < DAYS else None,
        })
    return plan


def generate_brand(brand: str, brand_index: int) -> dict[str, list[dict]]:
    rng = random.Random(SEED + brand_index)
    tz = ZoneInfo(config.BRANDS[brand]["reporting_tz"])
    prefix = brand.split("_")[0][:3]

    catalog = CATALOG[brand]
    skus = [row[0] for row in catalog]
    price = {row[0]: row[2] for row in catalog}
    lead_times = {row[0]: row[4] for row in catalog}
    hero = HERO_SKU[brand]
    promoted_by_campaign = CAMPAIGN_PRODUCTS[brand]

    customers, sessions, orders, order_items = [], [], [], []
    refunds, ad_spend, products, inventory_snapshots, purchase_orders = [], [], [], [], []
    attributed_revenue: dict[tuple[date, str], float] = {}

    # --- products: one version each, plus a mid-period price rise on the hero SKU ---
    catalogued_at = datetime.combine(START - timedelta(days=30), time(9), tz)
    for index, (sku, title, unit_price, unit_cost, lead_time) in enumerate(catalog, start=1):
        products.append({
            "id": f"{prefix}_prod_{index:03d}",
            "sku": sku,
            "title": title,
            "price": money(unit_price),
            "unit_cost": money(unit_cost),
            "supplier_lead_time_days": lead_time,
            "updated_at": iso(catalogued_at),
        })
        if sku == hero:
            repriced_at = datetime.combine(START + timedelta(days=35), time(11), tz)
            products.append({
                **products[-1],
                "price": money(round(unit_price * 1.05, 2)),
                "updated_at": iso(repriced_at),
            })

    # --- purchase orders: a created version, then a received version once it lands ---
    arrivals_by_day: dict[date, list[dict]] = defaultdict(list)
    for index, planned in enumerate(purchase_order_plan(brand, rng, lead_times), start=1):
        ordered_at = datetime.combine(START + timedelta(days=planned["ordered_day"]), time(10), tz)
        expected_date = START + timedelta(days=planned["expected_day"])
        created = {
            "id": f"{prefix}_po_{index:04d}",
            "sku": planned["sku"],
            "quantity": planned["quantity"],
            "ordered_at": iso(ordered_at),
            "expected_arrival_date": expected_date.isoformat(),
            "received_at": None,
            "updated_at": iso(ordered_at),
        }
        purchase_orders.append(created)

        if planned["received_day"] is not None:
            received_day = START + timedelta(days=planned["received_day"])
            received_at = datetime.combine(received_day, time(14), tz)
            purchase_orders.append(arrive_late({
                **created,
                "received_at": iso(received_at),
                "updated_at": iso(received_at),
            }, rng, probability=0.2, max_days=3))   # receipts get keyed in a few days late
            arrivals_by_day[received_day].append(planned)

    # --- the day loop: stock moves with sales and PO receipts ---
    stock = {sku: STOCKED_INITIAL for sku in skus}
    stock[hero] = HERO_INITIAL_STOCK[brand]

    for day_number in range(DAYS):
        day = START + timedelta(days=day_number)

        for arrival in arrivals_by_day[day]:
            stock[arrival["sku"]] += arrival["quantity"]

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

            order_id = f"{prefix}_ord_{len(orders) + 1:06d}"
            items = pick_line_items(rng, skus, promoted_by_campaign.get(campaign_id), hero)

            # Sell what is on hand; anything short of that puts the order on backorder.
            subtotal = 0.0
            is_backorder = False
            new_items = []
            for sku, quantity in items:
                if stock[sku] >= quantity:
                    stock[sku] -= quantity
                else:
                    is_backorder = True
                    stock[sku] = 0
                subtotal += price[sku] * quantity
                new_items.append({
                    "id": f"{prefix}_oi_{len(order_items) + len(new_items) + 1:06d}",
                    "order_id": order_id,
                    "sku": sku,
                    "quantity": quantity,
                    "unit_price": money(price[sku]),
                    "updated_at": iso(created),
                })

            subtotal = round(subtotal, 2)
            discount = round(subtotal * rng.choice([0.1, 0.15, 0.2]), 2) if rng.random() < 0.3 else 0.0
            net = round(subtotal - discount, 2)
            order = {
                "id": order_id,
                "customer_id": customer["id"],
                "session_id": session["id"],
                "created_at": iso(created),
                "currency": "USD",
                "subtotal_price": money(subtotal),
                "total_discounts": money(discount),
                "total_tax": money(net * 0.08),
                "total_shipping": rng.choice(["0.00", "6.95"]),
                "financial_status": "paid",
                "fulfillment_status": "on_backorder" if is_backorder else None,
            }

            # A backorder that runs out of patience is cancelled outright; everything else
            # refunds at the ordinary rate for ordinary reasons.
            refund_at, refund_is_full, reason = None, False, None
            if is_backorder and rng.random() < 0.30:
                refund_at = created + timedelta(days=rng.randint(7, 14), hours=rng.randint(0, 23))
                refund_is_full, reason = True, OUT_OF_STOCK
                amount = net
            elif not is_backorder and rng.random() < 0.08:
                refund_at = created + timedelta(days=rng.randint(1, 20), hours=rng.randint(0, 23))
                refund_is_full = rng.random() < 0.6
                reason = rng.choice(REFUND_REASONS)
                amount = net if refund_is_full else round(net * rng.uniform(0.2, 0.7), 2)

            if refund_at:
                refunds.append(arrive_late({
                    "id": f"{prefix}_ref_{len(refunds) + 1:05d}",
                    "order_id": order["id"],
                    "created_at": iso(refund_at),
                    "updated_at": iso(refund_at),
                    "amount": money(amount),
                    "reason": reason,
                }, rng, probability=0.05, max_days=2))

            versions = [
                arrive_late(version, rng, probability=0.03, max_days=2)
                for version in order_versions(order, created, refund_at, refund_is_full, rng,
                                              is_backorder=is_backorder)
            ]
            orders.extend(versions)

            # Line items become visible with the order they belong to, never before it.
            for item in new_items:
                if "_available_at" in versions[0]:
                    item["_available_at"] = versions[0]["_available_at"]
            order_items.extend(new_items)

            if campaign_id:
                key = (day, campaign_id)
                attributed_revenue[key] = attributed_revenue.get(key, 0.0) + net

        # The warehouse counts stock at close of business, brand-local time.
        counted_at = datetime.combine(day, time(23, 45), tz)
        for sku in skus:
            inventory_snapshots.append(arrive_late({
                "id": f"{sku}-{day.isoformat()}",
                "sku": sku,
                "date": day.isoformat(),
                "on_hand": stock[sku],
                "updated_at": iso(counted_at),
            }, rng, probability=0.03, max_days=2))

        # Ad platforms report each day's spend the next morning (brand-local date).
        for platform, campaigns in CAMPAIGNS.items():
            for campaign_id, campaign_name in campaigns:
                if campaign_id == HERO_CAMPAIGN:
                    spend = round(rng.uniform(*HERO_SPEND_RANGE), 2)
                else:
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
            "order_items": order_items, "refunds": refunds, "ad_spend": ad_spend,
            "products": products, "inventory_snapshots": inventory_snapshots,
            "purchase_orders": purchase_orders}


def write_campaign_products_seed() -> None:
    """The warehouse needs the campaign -> SKU mapping too, so it ships as a dbt seed."""
    path = config.DBT_PROJECT_DIR / "seeds" / "campaign_products.csv"
    lines = ["brand_id,campaign_id,sku"]
    for brand, mapping in CAMPAIGN_PRODUCTS.items():
        for campaign_id, skus in mapping.items():
            lines.extend(f"{brand},{campaign_id},{sku}" for sku in skus)
    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    for index, brand in enumerate(config.BRANDS):
        out_dir = config.SOURCE_DIR / brand
        out_dir.mkdir(parents=True, exist_ok=True)
        data = generate_brand(brand, index)
        for entity, rows in data.items():
            (out_dir / f"{entity}.json").write_text(json.dumps(rows, indent=1))
        print(f"{brand}: " + ", ".join(f"{len({r['id'] for r in rows})} {name}" for name, rows in data.items()))
    write_campaign_products_seed()


if __name__ == "__main__":
    main()
