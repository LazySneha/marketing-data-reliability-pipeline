"""The v2 entities go through the same ingestion path, so they get the same guarantees."""
from conftest import BRAND, record

from ingestion import ingest

NEW_ENTITIES = ["order_items", "products", "inventory_snapshots", "purchase_orders"]


def sample_entities() -> dict:
    return {
        "order_items": [
            record("acm_oi_000001", "2026-07-01T10:00:00Z",
                   order_id="acm_ord_000001", sku="TEE-BLK-M", quantity=2, unit_price="38.00"),
            record("acm_oi_000002", "2026-07-01T10:00:00Z",
                   order_id="acm_ord_000001", sku="SOCK-3PK", quantity=1, unit_price="22.00"),
        ],
        "products": [
            record("acm_prod_001", "2026-06-01T09:00:00Z", sku="TEE-BLK-M",
                   price="38.00", unit_cost="11.50", supplier_lead_time_days=21),
        ],
        "inventory_snapshots": [
            record("TEE-BLK-M-2026-07-01", "2026-07-01T23:45:00Z",
                   sku="TEE-BLK-M", date="2026-07-01", on_hand=42),
        ],
        "purchase_orders": [
            # the same PO twice: placed, then received. Only the newer version is current.
            record("acm_po_0001", "2026-07-05T10:00:00Z", sku="TEE-BLK-M",
                   quantity=500, expected_arrival_date="2026-07-26", received_at=None),
            record("acm_po_0001", "2026-08-07T14:00:00Z", sku="TEE-BLK-M",
                   quantity=500, expected_arrival_date="2026-07-26",
                   received_at="2026-08-07T14:00:00Z"),
        ],
    }


def test_new_entities_reload_without_duplicating(con, make_api):
    api = make_api(**sample_entities())

    for entity in NEW_ENTITIES:
        first = ingest.ingest_entity(con, api, BRAND, entity, "batch-1")
        assert first["inserted"] > 0, f"{entity} loaded nothing"

        second = ingest.ingest_entity(con, api, BRAND, entity, "batch-2")
        assert second["inserted"] == 0, f"{entity} duplicated on reload"


def test_corrected_snapshot_for_a_past_day_is_picked_up(con, make_api):
    """A warehouse recount for a day already loaded arrives as a new version, inside the lookback."""
    entities = sample_entities()
    api = make_api(**entities)
    ingest.ingest_entity(con, api, BRAND, "inventory_snapshots", "batch-1")

    corrected = record("TEE-BLK-M-2026-07-01", "2026-07-02T08:00:00Z",
                       sku="TEE-BLK-M", date="2026-07-01", on_hand=37)
    entities["inventory_snapshots"] = entities["inventory_snapshots"] + [corrected]
    api = make_api(**entities)

    result = ingest.ingest_entity(con, api, BRAND, "inventory_snapshots", "batch-2",
                                  lookback_days=3)
    assert result["inserted"] == 1

    versions = con.execute(
        f"SELECT count(*) FROM raw_{BRAND}.inventory_snapshots WHERE id = ?",
        ["TEE-BLK-M-2026-07-01"],
    ).fetchone()[0]
    assert versions == 2, "both the original count and the correction should be kept"
