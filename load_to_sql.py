#!/usr/bin/env python3
"""Daily batch load: data/checks.csv and sites.csv -> Azure SQL (uptime_sla).

- sites:  upserted from sites.csv; sites no longer in the file are kept but
          marked is_active = 0, so their history stays intact.
- checks: rows newer than (latest loaded timestamp - 1 day) are inserted;
          rows already in the table are skipped, so re-running is safe.

Connection settings come from environment variables (GitHub secrets):
SQL_SERVER, SQL_DATABASE, SQL_USER, SQL_PASSWORD.
"""
from __future__ import annotations

import csv
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pymssql

CHECKS_CSV = Path("data/checks.csv")
SITES_CSV = Path("sites.csv")
OVERLAP = timedelta(days=1)  # re-check the last day in case of late rows
CONNECT_ATTEMPTS = 5
CONNECT_WAIT_S = 30          # a paused serverless database needs time to resume

CHECK_COLUMNS = [
    "checked_at_utc", "site_id", "run_id", "url", "outcome", "status_code",
    "response_ms", "attempts", "final_url", "error", "probe_location",
]

INSERT_CHECK_SQL = f"""
INSERT INTO dbo.checks ({", ".join(CHECK_COLUMNS)})
SELECT %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
WHERE NOT EXISTS (
    SELECT 1 FROM dbo.checks
    WHERE checked_at_utc = %s AND site_id = %s AND run_id = %s
)
"""

UPSERT_SITE_SQL = """
MERGE dbo.sites AS t
USING (SELECT %s AS site_id, %s AS site_name, %s AS sector, %s AS url) AS s
ON t.site_id = s.site_id
WHEN MATCHED THEN
    UPDATE SET site_name = s.site_name, sector = s.sector, url = s.url, is_active = 1
WHEN NOT MATCHED THEN
    INSERT (site_id, site_name, sector, url, is_active)
    VALUES (s.site_id, s.site_name, s.sector, s.url, 1);
"""


def blank_to_none(value: str):
    return value if value not in ("", None) else None


def parse_ts(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def read_sites(path: Path) -> list[tuple]:
    with path.open(newline="", encoding="utf-8") as f:
        return [
            (r["site_id"], r["site_name"], r["sector"], r["url"])
            for r in csv.DictReader(f) if r.get("site_id")
        ]


def read_checks(path: Path, since: datetime | None) -> list[tuple]:
    """Rows from checks.csv, optionally only those at or after `since`."""
    rows = []
    with path.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            ts = parse_ts(r["checked_at_utc"])
            if since is not None and ts < since:
                continue
            values = (
                ts,
                r["site_id"],
                r["run_id"],
                r["url"],
                r["outcome"],
                int(r["status_code"]) if r["status_code"] else None,
                int(r["response_ms"]) if r["response_ms"] else None,
                int(r["attempts"]),
                blank_to_none(r["final_url"]),
                blank_to_none(r["error"]),
                r["probe_location"],
            )
            # last three params feed the NOT EXISTS duplicate check
            rows.append(values + (ts, r["site_id"], r["run_id"]))
    return rows


def connect():
    settings = dict(
        server=os.environ["SQL_SERVER"],
        database=os.environ["SQL_DATABASE"],
        user=os.environ["SQL_USER"],
        password=os.environ["SQL_PASSWORD"],
        port=1433,
        login_timeout=60,
        timeout=300,
    )
    for attempt in range(1, CONNECT_ATTEMPTS + 1):
        try:
            return pymssql.connect(**settings)
        except pymssql.Error as exc:
            if attempt == CONNECT_ATTEMPTS:
                raise
            print(f"Connect attempt {attempt} failed ({type(exc).__name__}); "
                  f"database may be resuming, retrying in {CONNECT_WAIT_S}s")
            time.sleep(CONNECT_WAIT_S)


def main() -> int:
    conn = connect()
    cur = conn.cursor()

    # 1. Sites: upsert current list, deactivate sites that were removed
    sites = read_sites(SITES_CSV)
    for site in sites:
        cur.execute(UPSERT_SITE_SQL, site)
    ids = tuple(s[0] for s in sites)
    cur.execute(
        "UPDATE dbo.sites SET is_active = 0 WHERE is_active = 1 AND site_id NOT IN %s",
        (ids,),
    )
    deactivated = cur.rowcount

    # 2. Checks: incremental load with one day of overlap
    cur.execute("SELECT MAX(checked_at_utc) FROM dbo.checks")
    latest = cur.fetchone()[0]
    since = latest - OVERLAP if latest else None
    rows = read_checks(CHECKS_CSV, since)

    before = count_checks(cur)
    if rows:
        cur.executemany(INSERT_CHECK_SQL, rows)
    conn.commit()
    after = count_checks(cur)
    conn.close()

    print(f"sites upserted: {len(sites)} | deactivated: {deactivated}")
    print(f"latest before load: {latest} | candidate rows: {len(rows)} | "
          f"inserted: {after - before} | total rows: {after}")
    return 0


def count_checks(cur) -> int:
    cur.execute("SELECT COUNT(*) FROM dbo.checks")
    return cur.fetchone()[0]


if __name__ == "__main__":
    sys.exit(main())
