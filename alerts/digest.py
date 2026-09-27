"""
Turn mart_alerts rows into a readable daily note per brand.

    python -m alerts.digest            # write a digest for every brand

This is the push step: the pipeline says what changed instead of waiting for someone to open a
table. Delivery to Slack or email is deliberately out of scope, so the digest is a Markdown file
plus a short summary on stdout, and no external dependency is involved.

"Today" means the most recent date mart_alerts covers, not the wall clock. The synthetic sources
stop at the end of August, and an alerting layer that reported on the real today would have
nothing to say about them.

Output: data/alerts/<brand>_<date>.md
"""
import logging
from datetime import date

import duckdb

import config

log = logging.getLogger("alerts")

SEVERITY_ORDER = ["high", "medium"]
TRAILING_DAYS = 7


def latest_alert_date(con: duckdb.DuckDBPyConnection, brand: str) -> date | None:
    row = con.execute(f"SELECT max(alert_date) FROM {brand}_marts.mart_alerts").fetchone()
    return row[0] if row else None


def read_alerts(con: duckdb.DuckDBPyConnection, brand: str, alert_date: date) -> list[dict]:
    rows = con.execute(f"""
        SELECT alert_type, severity, entity_id, observed_value, baseline_value, message
        FROM {brand}_marts.mart_alerts
        WHERE alert_date = ?
        ORDER BY array_position(?::varchar[], severity), alert_type, entity_id
    """, [alert_date, SEVERITY_ORDER]).fetchall()
    columns = ["alert_type", "severity", "entity_id", "observed_value", "baseline_value", "message"]
    return [dict(zip(columns, row)) for row in rows]


def trailing_count(con: duckdb.DuckDBPyConnection, brand: str, alert_date: date) -> int:
    return con.execute(f"""
        SELECT count(*)
        FROM {brand}_marts.mart_alerts
        WHERE alert_date > ? - INTERVAL {TRAILING_DAYS} DAY AND alert_date <= ?
    """, [alert_date, alert_date]).fetchone()[0]


def render(brand: str, alert_date: date, alerts: list[dict], trailing: int) -> str:
    lines = [f"# {brand} — alerts for {alert_date}", ""]

    if not alerts:
        lines += ["Nothing fired today.", "",
                  f"{trailing} alerts in the {TRAILING_DAYS} days to {alert_date}.", ""]
        return "\n".join(lines)

    counts = ", ".join(
        f"{sum(1 for a in alerts if a['severity'] == severity)} {severity}"
        for severity in SEVERITY_ORDER
        if any(a["severity"] == severity for a in alerts)
    )
    noun = "alert" if len(alerts) == 1 else "alerts"
    lines += [f"{len(alerts)} {noun} ({counts}). "
              f"{trailing} in the {TRAILING_DAYS} days to {alert_date}.", ""]

    for severity in SEVERITY_ORDER:
        in_bucket = [a for a in alerts if a["severity"] == severity]
        if not in_bucket:
            continue
        lines += [f"## {severity.title()}", ""]
        for alert in in_bucket:
            lines.append(f"- **{alert['alert_type']}** · `{alert['entity_id']}`")
            lines.append(f"  {alert['message']}")
            if alert["observed_value"] is not None and alert["baseline_value"] is not None:
                lines.append(f"  <sub>observed {alert['observed_value']:.2f} · "
                             f"baseline {alert['baseline_value']:.2f}</sub>")
            lines.append("")

    return "\n".join(lines)


def write_digest(con: duckdb.DuckDBPyConnection, brand: str, top: int = 3) -> dict:
    """Write one brand's digest and print its most severe alerts. Returns a small summary."""
    alert_date = latest_alert_date(con, brand)
    if alert_date is None:
        log.info("%s: mart_alerts is empty, no digest written", brand)
        return {"brand": brand, "alert_date": None, "alerts": 0, "path": None}

    alerts = read_alerts(con, brand, alert_date)
    config.ALERTS_DIR.mkdir(parents=True, exist_ok=True)
    path = config.ALERTS_DIR / f"{brand}_{alert_date}.md"
    path.write_text(render(brand, alert_date, alerts, trailing_count(con, brand, alert_date)))

    log.info("%s: %d alerts for %s -> %s", brand, len(alerts), alert_date, path)
    for alert in alerts[:top]:
        print(f"  [{alert['severity']}] {alert['message']}")

    return {"brand": brand, "alert_date": alert_date, "alerts": len(alerts), "path": path}


def run(brands=None, top: int = 3) -> list[dict]:
    con = duckdb.connect(str(config.WAREHOUSE_PATH), read_only=True)
    try:
        summaries = []
        for brand in brands or config.BRANDS:
            print(f"\nalerts · {brand}")
            summaries.append(write_digest(con, brand, top=top))
        return summaries
    finally:
        con.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    run()


if __name__ == "__main__":
    main()
