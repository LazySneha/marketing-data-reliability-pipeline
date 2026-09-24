"""
Incremental ingestion: fake API -> DuckDB raw layer.

For each brand and entity:
    1. read the watermark (max updated_at already loaded) and step back by the lookback window
    2. page through the API from there, retrying transient failures
    3. insert every record version into raw_<brand>.<entity>; re-inserting a version is a no-op
    4. advance the watermark, only after the load has committed

Usage:
    python -m ingestion.ingest                               # everything the API has
    python -m ingestion.ingest --as-of 2026-08-15T00:00:00Z  # pretend it's Aug 15
"""
import argparse
import json
import logging
import os
import random
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, Iterator

import duckdb

import config
from source.fake_api import APIError, FakeAPI, RateLimitError

log = logging.getLogger("ingest")

TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


# --- API client -----------------------------------------------------------------------

def fetch_page_with_retry(
    api: FakeAPI,
    entity: str,
    cursor: str | None,
    updated_since: str | None,
    max_attempts: int = config.MAX_ATTEMPTS,
    base_delay: float = config.BASE_BACKOFF_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """Fetch one page, retrying only errors the API marks as retryable."""
    for attempt in range(1, max_attempts + 1):
        try:
            return api.get_page(entity, cursor=cursor, updated_since=updated_since)
        except APIError as error:
            if not error.retryable or attempt == max_attempts:
                raise
            if isinstance(error, RateLimitError):
                delay = error.retry_after
            else:
                # exponential backoff with jitter so parallel workers don't retry in lockstep
                delay = base_delay * 2 ** (attempt - 1) + random.uniform(0, base_delay)
            log.warning("%s: %s (attempt %d/%d), retrying in %.2fs",
                        entity, error, attempt, max_attempts, delay)
            sleep(delay)
    raise AssertionError("unreachable")


def paginate(api: FakeAPI, entity: str, updated_since: str | None = None,
             fetch: Callable[..., dict] = fetch_page_with_retry) -> Iterator[dict]:
    """Yield records one at a time, following next_cursor until the API says there are no more."""
    cursor = None
    while True:
        page = fetch(api, entity, cursor, updated_since)
        yield from page["data"]
        cursor = page["next_cursor"]
        if cursor is None:
            return


# --- Raw layer ------------------------------------------------------------------------

def ensure_raw_table(con: duckdb.DuckDBPyConnection, brand: str, entity: str) -> str:
    """Raw keeps one row per record version. (id, updated_at) identifies a version."""
    table = f"raw_{brand}.{entity}"
    con.execute(f"CREATE SCHEMA IF NOT EXISTS raw_{brand}")
    con.execute(f"""
        CREATE TABLE IF NOT EXISTS {table} (
            id            VARCHAR   NOT NULL,
            updated_at    VARCHAR   NOT NULL,
            payload       JSON      NOT NULL,
            _batch_id     VARCHAR   NOT NULL,
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
    chunk_size: int = config.LOAD_CHUNK_SIZE,
) -> tuple[int, int, str | None]:
    """Insert records in chunks inside one transaction.

    Returns (rows_seen, rows_inserted, max_updated_at). Versions that are already
    loaded are skipped by the primary key, so re-running a load changes nothing.
    """
    seen = 0
    max_updated_at = None
    chunk: list[tuple] = []
    before = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]

    def flush() -> None:
        if chunk:
            con.executemany(
                f"INSERT OR IGNORE INTO {table} VALUES (?, ?, ?, ?, now())", chunk
            )
            chunk.clear()

    con.execute("BEGIN TRANSACTION")
    try:
        for record in records:
            if not record.get("id") or not record.get("updated_at"):
                raise ValueError(f"{table}: record without id/updated_at: {record!r}")
            chunk.append((record["id"], record["updated_at"], json.dumps(record), batch_id))
            seen += 1
            if max_updated_at is None or record["updated_at"] > max_updated_at:
                max_updated_at = record["updated_at"]
            if len(chunk) >= chunk_size:
                flush()
        flush()
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise

    inserted = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0] - before
    return seen, inserted, max_updated_at


# --- Checkpoints ----------------------------------------------------------------------

def checkpoint_path(brand: str, entity: str) -> Path:
    return config.CHECKPOINT_DIR / f"{brand}__{entity}.json"


def read_checkpoint(brand: str, entity: str) -> str | None:
    path = checkpoint_path(brand, entity)
    if not path.exists():
        return None
    return json.loads(path.read_text())["updated_at"]


def write_checkpoint(brand: str, entity: str, updated_at: str) -> None:
    """Write to a temp file and rename, so a crash never leaves a half-written checkpoint."""
    path = checkpoint_path(brand, entity)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"updated_at": updated_at}))
    os.replace(tmp, path)


def start_from(watermark: str | None, lookback_days: int) -> str | None:
    if watermark is None:
        return None
    moment = datetime.strptime(watermark, TS_FORMAT) - timedelta(days=lookback_days)
    return moment.strftime(TS_FORMAT)


# --- Orchestration --------------------------------------------------------------------

def ingest_entity(con: duckdb.DuckDBPyConnection, api: FakeAPI, brand: str, entity: str,
                  batch_id: str, lookback_days: int | None = None) -> dict:
    if lookback_days is None:
        lookback_days = config.LOOKBACK_DAYS.get(entity, 0)

    table = ensure_raw_table(con, brand, entity)
    watermark = read_checkpoint(brand, entity)
    since = start_from(watermark, lookback_days)

    seen, inserted, max_updated_at = load_raw(con, table, paginate(api, entity, since), batch_id)

    # Only after the load has committed. A crash before this line means the next run
    # re-reads the same window, which the idempotent load absorbs.
    if max_updated_at and (watermark is None or max_updated_at > watermark):
        write_checkpoint(brand, entity, max_updated_at)

    log.info("%s.%s: since=%s seen=%d inserted=%d watermark=%s",
             brand, entity, since or "beginning", seen, inserted, max_updated_at or watermark)
    return {"seen": seen, "inserted": inserted}


def run(as_of: str | None = None, brands: Iterable[str] | None = None) -> dict:
    config.CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    batch_id = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"
    log.info("batch %s starting (as_of=%s)", batch_id, as_of or "now")

    totals = {"seen": 0, "inserted": 0}
    con = duckdb.connect(str(config.WAREHOUSE_PATH))
    try:
        for brand in brands or config.BRANDS:
            api = FakeAPI(brand, as_of=as_of)
            for entity in config.ENTITIES:
                result = ingest_entity(con, api, brand, entity, batch_id)
                totals["seen"] += result["seen"]
                totals["inserted"] += result["inserted"]
            log.info("%s: %d API calls", brand, api.calls)
    finally:
        con.close()

    log.info("batch %s done: %d records seen, %d new versions inserted",
             batch_id, totals["seen"], totals["inserted"])
    return totals


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--as-of", help='simulate running at this time, e.g. "2026-08-15T00:00:00Z"')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    run(args.as_of)


if __name__ == "__main__":
    main()
