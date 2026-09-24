import pytest

from conftest import record
from ingestion.ingest import (
    checkpoint_path, ensure_raw_table, load_raw, read_checkpoint, write_checkpoint,
)


def row_count(con, table):
    return con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def test_loading_the_same_records_twice_is_a_no_op(con):
    table = ensure_raw_table(con, "b", "orders")
    records = [record("o1", "2026-07-01T00:00:00Z"), record("o2", "2026-07-01T00:00:01Z")]

    first = load_raw(con, table, records, "batch-1")
    second = load_raw(con, table, records, "batch-2")

    assert first == (2, 2, "2026-07-01T00:00:01Z")
    assert second == (2, 0, "2026-07-01T00:00:01Z")
    assert row_count(con, table) == 2


def test_a_corrected_record_is_kept_as_a_new_version(con):
    table = ensure_raw_table(con, "b", "ad_spend")
    load_raw(con, table, [record("s1", "2026-07-02T06:00:00Z", spend="100.00")], "batch-1")

    _, inserted, _ = load_raw(con, table, [record("s1", "2026-07-04T06:00:00Z", spend="112.50")], "batch-2")

    assert inserted == 1
    assert con.execute(f"SELECT count(*), count(DISTINCT id) FROM {table}").fetchone() == (2, 1)


def test_duplicates_inside_one_batch_land_once(con):
    table = ensure_raw_table(con, "b", "orders")
    duplicate = record("o1", "2026-07-01T00:00:00Z")

    seen, inserted, _ = load_raw(con, table, [duplicate, dict(duplicate)], "batch-1")

    assert (seen, inserted) == (2, 1)


def test_a_bad_record_rolls_back_the_whole_load(con):
    table = ensure_raw_table(con, "b", "orders")
    records = [record("o1", "2026-07-01T00:00:00Z"), {"id": "o2"}]  # second one has no updated_at

    with pytest.raises(ValueError):
        load_raw(con, table, records, "batch-1", chunk_size=1)

    assert row_count(con, table) == 0


def test_checkpoint_round_trip(tmp_paths):
    assert read_checkpoint("b", "orders") is None

    write_checkpoint("b", "orders", "2026-07-01T00:00:00Z")
    write_checkpoint("b", "orders", "2026-07-02T00:00:00Z")

    assert read_checkpoint("b", "orders") == "2026-07-02T00:00:00Z"
    assert not checkpoint_path("b", "orders").with_suffix(".tmp").exists()
