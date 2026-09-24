"""
Run the pipeline end to end.

    python run_pipeline.py            # ingest whatever is new, then dbt build for every brand
    python run_pipeline.py --demo     # start from scratch and replay three daily-style runs

The demo wipes data/, regenerates the synthetic sources, and runs ingestion + dbt at three
points in time so that incremental loads, late-arriving records and spend restatements all
get exercised. It finishes by re-running ingestion to show that nothing gets duplicated.
"""
import argparse
import logging
import os
import shutil
import subprocess
import sys

import duckdb

import config
from ingestion import ingest
from source import generate

log = logging.getLogger("pipeline")

DEMO_SNAPSHOTS = ["2026-08-01T00:00:00Z", "2026-08-15T00:00:00Z", None]  # None = everything


def dbt_build(brand: str) -> None:
    variables = f"{{brand: {brand}, reporting_tz: {config.BRANDS[brand]['reporting_tz']}}}"
    command = [
        "dbt", "build",
        "--project-dir", str(config.DBT_PROJECT_DIR),
        "--profiles-dir", str(config.DBT_PROJECT_DIR),
        "--vars", variables,
        "--quiet",
    ]
    env = {**os.environ, "WAREHOUSE_PATH": str(config.WAREHOUSE_PATH)}
    log.info("dbt build for %s", brand)
    result = subprocess.run(command, env=env)
    if result.returncode != 0:
        sys.exit(f"dbt build failed for {brand}")


def run_once(as_of: str | None = None) -> None:
    ingest.run(as_of)
    for brand in config.BRANDS:
        dbt_build(brand)


def raw_row_counts() -> dict[str, tuple[int, int]]:
    con = duckdb.connect(str(config.WAREHOUSE_PATH), read_only=True)
    try:
        return {
            f"{brand}.{entity}": con.execute(
                f"SELECT count(*), count(DISTINCT id) FROM raw_{brand}.{entity}"
            ).fetchone()
            for brand in config.BRANDS
            for entity in config.ENTITIES
        }
    finally:
        con.close()


def print_summary() -> None:
    con = duckdb.connect(str(config.WAREHOUSE_PATH), read_only=True)
    try:
        for brand in config.BRANDS:
            row = con.execute(f"""
                SELECT
                    sum(spend), sum(orders), sum(gross_revenue), sum(refunded_amount), sum(net_revenue),
                    round(sum(net_revenue) / sum(spend), 2),
                    round(sum(gross_revenue) / sum(orders), 2),
                    round(sum(spend) / sum(new_customers), 2),
                    sum(platform_reported_revenue)
                FROM {brand}_marts.mart_marketing_daily
            """).fetchone()
            spend, orders, gross, refunds, net, mer, aov, cac, platform_revenue = row
            print(f"\n{brand}")
            print(f"  spend ${spend:,.2f} | orders {orders:,} | gross ${gross:,.2f} | "
                  f"refunds ${refunds:,.2f} | net ${net:,.2f}")
            print(f"  MER {mer} | AOV ${aov} | new-customer CAC ${cac} | "
                  f"platform-reported revenue ${platform_revenue:,.2f} (not used for revenue)")
    finally:
        con.close()


def demo() -> None:
    if config.DATA_DIR.exists():
        shutil.rmtree(config.DATA_DIR)
    generate.main()

    for as_of in DEMO_SNAPSHOTS:
        log.info("=== run as of %s ===", as_of or "now")
        run_once(as_of)

    before = raw_row_counts()
    log.info("=== re-running ingestion to check idempotency ===")
    totals = ingest.run()
    after = raw_row_counts()
    if before != after or totals["inserted"] != 0:
        sys.exit("idempotency check failed: a rerun changed the raw tables")
    log.info("rerun inserted 0 rows; raw tables unchanged")

    print_summary()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--demo", action="store_true", help="reset data/ and replay three runs")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.demo:
        demo()
    else:
        run_once()
        print_summary()


if __name__ == "__main__":
    main()
