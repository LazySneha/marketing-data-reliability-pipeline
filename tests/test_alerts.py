"""
The designed scenario, checked end to end against the built warehouse.

Each brand's synthetic data contains one deliberate failure: the hero SKU of the
highest-spending campaign runs out mid-period while that campaign keeps spending, and its
replacement PO lands days after the date the supplier promised. The point of the alerting layer
is to say so *before* the stockout, while there is still time to move the budget.

These tests read the warehouse, so they need a build first:

    python run_pipeline.py --demo

test_stockout_alert_fires_before_the_stockout is expected to fail until fct_inventory_daily
computes velocity, days of cover and the next restock date.
"""
import duckdb
import pytest

import config
from source.generate import HERO_CAMPAIGN, HERO_SKU

pytestmark = pytest.mark.skipif(
    not config.WAREHOUSE_PATH.exists(),
    reason=f"no warehouse at {config.WAREHOUSE_PATH}; run: python run_pipeline.py --demo",
)

MINIMUM_WARNING_DAYS = 3


@pytest.fixture(scope="module")
def warehouse():
    connection = duckdb.connect(str(config.WAREHOUSE_PATH), read_only=True)
    yield connection
    connection.close()


def stockout_start(warehouse, brand: str, sku: str):
    return warehouse.execute(f"""
        SELECT min(snapshot_date)
        FROM {brand}_marts.fct_inventory_daily
        WHERE sku = ? AND on_hand = 0
    """, [sku]).fetchone()[0]


@pytest.mark.parametrize("brand", list(config.BRANDS))
def test_the_scenario_is_still_in_the_data(warehouse, brand):
    """If this fails, the generator changed and the other tests are testing nothing."""
    hero = HERO_SKU[brand]
    stockout = stockout_start(warehouse, brand, hero)
    assert stockout is not None, f"{hero} never runs out of stock any more"

    spend_during = warehouse.execute(f"""
        SELECT round(sum(spend), 2)
        FROM {brand}_marts.fct_ad_spend_daily
        WHERE campaign_id = ? AND report_date >= ?
    """, [HERO_CAMPAIGN, stockout]).fetchone()[0]
    assert spend_during > 0, "the campaign stopped spending, so there is nothing to warn about"


@pytest.mark.parametrize("brand", list(config.BRANDS))
def test_spend_on_an_out_of_stock_sku_is_flagged(warehouse, brand):
    hero = HERO_SKU[brand]
    stockout = stockout_start(warehouse, brand, hero)

    first_alert = warehouse.execute(f"""
        SELECT min(alert_date)
        FROM {brand}_marts.mart_alerts
        WHERE alert_type = 'spend_on_out_of_stock_sku' AND entity_id = ?
    """, [f"{HERO_CAMPAIGN}|{hero}"]).fetchone()[0]

    assert first_alert is not None, f"no out-of-stock spend alert for {hero}"
    assert first_alert >= stockout, "flagged before the SKU was actually out of stock"


@pytest.mark.parametrize("brand", list(config.BRANDS))
def test_stockout_alert_fires_before_the_stockout(warehouse, brand):
    hero = HERO_SKU[brand]
    stockout = stockout_start(warehouse, brand, hero)

    first_alert = warehouse.execute(f"""
        SELECT min(alert_date)
        FROM {brand}_marts.mart_alerts
        WHERE alert_type = 'stockout_risk_with_active_spend' AND entity_id = ?
    """, [f"{HERO_CAMPAIGN}|{hero}"]).fetchone()[0]

    assert first_alert is not None, (
        f"no stockout_risk_with_active_spend alert for {hero}. fct_inventory_daily still needs "
        "velocity_14d, days_of_cover, projected_stockout_date and next_restock_date."
    )
    warning_days = (stockout - first_alert).days
    assert warning_days >= MINIMUM_WARNING_DAYS, (
        f"only {warning_days} days of warning: alert on {first_alert}, stockout on {stockout}"
    )
