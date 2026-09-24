"""
Ingestion: fake API -> DuckDB raw layer.

YOU WRITE every function marked TODO. Everything else is boilerplate.

Flow for one (brand, entity):
    1. read the checkpoint        -> the last updated_at we fully loaded (None = full pull)
    2. paginate the API from there, retrying each page call when the error is retryable
    3. load records into raw_<brand>.<entity> idempotently (a rerun must not duplicate)
    4. ONLY THEN advance the checkpoint to the max updated_at we loaded

Run:
    python -m ingestion.ingest --task1                      # Task 1 smoke test
    python -m ingestion.ingest --as-of 2026-08-15T00:00:00Z  # full run, data up to Aug 15
    python -m ingestion.ingest                              # full run, all data
"""
import argparse
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Callable, Iterable, Iterator

import duckdb

import config
from source.fake_api import APIError, FakeAPI, RateLimitError


# ---------------------------------------------------------------------------
# TASK 1: pagination
# ---------------------------------------------------------------------------
def paginate(api: FakeAPI, entity: str, updated_since: str | None = None) -> Iterator[dict]:
    """Yield every record for `entity`, one at a time, following next_cursor until it is None.

    - This is a GENERATOR: use `yield`, don't build and return a list.
    - Task 1: call api.get_page(...) directly.
    - Task 2: swap that call for fetch_page_with_retry(...).
    """
    raise NotImplementedError("Task 1")


# ---------------------------------------------------------------------------
# TASK 2: retries
# ---------------------------------------------------------------------------
def fetch_page_with_retry(
    api: FakeAPI,
    entity: str,
    cursor: str | None,
    updated_since: str | None,
    max_attempts: int = 5,
    base_delay: float = 0.1,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """Call api.get_page once, retrying ONLY errors that are retryable.

    - RateLimitError (429): wait e.retry_after, then retry.
    - Other retryable errors (503): wait base_delay * 2**attempt (+ a little random jitter).
    - Non-retryable errors (400): re-raise immediately. Fail loudly.
    - Out of attempts: re-raise the last error. Never return None, never swallow it.
    - Use the `sleep` argument, not time.sleep directly (lets tests run without waiting).
    """
    raise NotImplementedError("Task 2")


# ---------------------------------------------------------------------------
# TASK 3: idempotent load
# ---------------------------------------------------------------------------
def ensure_raw_table(con: duckdb.DuckDBPyConnection, brand: str, entity: str) -> str:
    """Boilerplate. Creates raw_<brand>.<entity> and returns its full name.

    Raw is append-only: one row per VERSION of a record. The primary key (id, updated_at)
    means the same version can't land twice, but a newer version of the same id can.
    """
    table = f"raw_{brand}.{entity}"
    con.execute(f"CREATE SCHEMA IF NOT EXISTS raw_{brand}")
    con.execute(f"""
        CREATE TABLE IF NOT EXISTS {table} (
            id            VARCHAR   NOT NULL,
            updated_at    VARCHAR   NOT NULL,   -- ISO string exactly as the API sent it
            payload       JSON      NOT NULL,   -- the whole record, untouched
            _batch_id     VARCHAR   NOT NULL,   -- which run loaded it
            _ingested_at  TIMESTAMP NOT NULL,
            PRIMARY KEY (id, updated_at)
        )
    """)
    return table


def load_raw(
    con: duckdb.DuckDBPyConnection,
    table: str,
    records: Iterable[dict],
    batch_id: str,
    chunk_size: int = 500,
) -> tuple[int, str | None]:
    """Insert records into `table` in chunks, idempotently.

    - Consume `records` lazily (it's a generator). Insert every `chunk_size` rows,
      plus whatever is left over at the end.
    - Idempotent: re-inserting a row with the same (id, updated_at) must be a no-op.
    - Returns (rows_seen, max_updated_at_seen). max is None if there were no records.
    """
    raise NotImplementedError("Task 3")


# ---------------------------------------------------------------------------
# TASK 4: checkpoints + the glue
# ---------------------------------------------------------------------------
def checkpoint_path(brand: str, entity: str):
    return config.CHECKPOINT_DIR / f"{brand}__{entity}.json"


def read_checkpoint(brand: str, entity: str) -> str | None:
    """Return the stored updated_at watermark, or None if there's no checkpoint yet."""
    raise NotImplementedError("Task 4")


def write_checkpoint(brand: str, entity: str, updated_at: str) -> None:
    """Persist the watermark. Write atomically: temp file, then rename over the real one."""
    raise NotImplementedError("Task 4")


def ingest_entity(con: duckdb.DuckDBPyConnection, api: FakeAPI, brand: str, entity: str,
                  batch_id: str) -> int:
    """checkpoint -> paginate -> load -> advance checkpoint. Returns rows seen.

    The ORDER is the whole point. Be ready to explain what happens if the process
    dies between loading and writing the checkpoint, and vice versa.
    """
    raise NotImplementedError("Task 4")


# ---------------------------------------------------------------------------
# Runner (boilerplate)
# ---------------------------------------------------------------------------
def run(as_of: str | None = None) -> None:
    config.DATA_DIR.mkdir(exist_ok=True)
    config.CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    batch_id = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"
    con = duckdb.connect(str(config.WAREHOUSE_PATH))
    try:
        for brand in config.BRANDS:
            api = FakeAPI(brand, as_of=as_of)
            for entity in config.ENTITIES:
                n = ingest_entity(con, api, brand, entity, batch_id)
                print(f"[{batch_id}] {brand}.{entity}: {n} rows seen")
            print(f"[{batch_id}] {brand}: {api.calls} API calls")
    finally:
        con.close()


def task1_smoke() -> None:
    """Pagination only, against a perfectly reliable API (no 429s, no 503s)."""
    brand = next(iter(config.BRANDS))
    api = FakeAPI(brand, rate_limit_prob=0, server_error_prob=0)
    expected = len(json.loads((config.SOURCE_DIR / brand / "orders.json").read_text()))
    ids = [r["id"] for r in paginate(api, "orders")]
    print(f"records: {len(ids)}  expected: {expected}  unique: {len(set(ids))}  api calls: {api.calls}")
    assert len(ids) == expected == len(set(ids)), "pagination missed or repeated records"
    print("Task 1 passed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", default=None, help='e.g. "2026-08-15T00:00:00Z"')
    parser.add_argument("--task1", action="store_true", help="run the Task 1 smoke test")
    args = parser.parse_args()
    task1_smoke() if args.task1 else run(args.as_of)
