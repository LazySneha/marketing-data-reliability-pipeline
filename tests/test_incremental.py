import pytest

from conftest import BRAND, record
from ingestion.ingest import ingest_entity, read_checkpoint
from source.fake_api import BadRequestError


def raw_count(con, entity="orders"):
    return con.execute(f"SELECT count(*) FROM raw_{BRAND}.{entity}").fetchone()[0]


def test_first_run_loads_everything_and_sets_the_watermark(make_api, con):
    api = make_api(orders=[record("o1", "2026-07-01T10:00:00Z"), record("o2", "2026-07-02T10:00:00Z")])

    result = ingest_entity(con, api, BRAND, "orders", "batch-1")

    assert result == {"seen": 2, "inserted": 2}
    assert read_checkpoint(BRAND, "orders") == "2026-07-02T10:00:00Z"


def test_rerun_does_not_duplicate(make_api, con):
    api = make_api(orders=[record(f"o{i}", f"2026-07-0{i}T10:00:00Z") for i in range(1, 6)])

    ingest_entity(con, api, BRAND, "orders", "batch-1")
    rerun = ingest_entity(con, api, BRAND, "orders", "batch-2")

    assert rerun["inserted"] == 0
    assert raw_count(con) == 5


def test_watermark_does_not_move_when_the_load_fails(make_api, con):
    api = make_api(orders=[record(f"o{i:03d}", "2026-07-01T10:00:00Z") for i in range(80)])
    real_get_page = api.get_page

    def fail_on_second_page(entity, cursor=None, updated_since=None, **kwargs):
        if cursor is not None:
            raise BadRequestError("400 on page 2")
        return real_get_page(entity, cursor=cursor, updated_since=updated_since, **kwargs)

    api.get_page = fail_on_second_page

    with pytest.raises(BadRequestError):
        ingest_entity(con, api, BRAND, "orders", "batch-1")

    assert read_checkpoint(BRAND, "orders") is None
    assert raw_count(con) == 0  # page 1 was rolled back, so the retry starts clean


@pytest.mark.parametrize("lookback_days, expect_late_record", [(3, True), (0, False)])
def test_lookback_window_picks_up_late_arriving_records(make_api, con, lookback_days, expect_late_record):
    on_time = record("s1", "2026-08-10T06:00:00Z")
    late = record("s2", "2026-08-09T06:00:00Z", _available_at="2026-08-12T00:00:00Z")

    first_api = make_api(as_of="2026-08-11T00:00:00Z", ad_spend=[on_time, late])
    ingest_entity(con, first_api, BRAND, "ad_spend", "batch-1", lookback_days=lookback_days)

    second_api = make_api(as_of="2026-08-13T00:00:00Z", ad_spend=[on_time, late])
    ingest_entity(con, second_api, BRAND, "ad_spend", "batch-2", lookback_days=lookback_days)

    ids = {row[0] for row in con.execute(f"SELECT id FROM raw_{BRAND}.ad_spend").fetchall()}
    assert ("s2" in ids) is expect_late_record
