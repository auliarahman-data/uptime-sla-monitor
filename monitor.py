#!/usr/bin/env python3
"""Uptime & latency probe for a list of public homepages.

Each run checks every site in sites.csv once (with one retry on failure)
and appends one row per site to data/checks.csv.

Outcome rules
-------------
UP       final HTTP status 2xx/3xx
BLOCKED  401 / 403 / 429 - server answered but refused an automated request
         (bot protection, geo-blocking, rate limit). Reachable, not "down".
DOWN     any other 4xx/5xx, timeout, DNS, TLS or connection error
"""
from __future__ import annotations

import argparse
import csv
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import requests

FIELDS = [
    "run_id",
    "checked_at_utc",
    "site_id",
    "url",
    "outcome",
    "status_code",
    "response_ms",
    "attempts",
    "final_url",
    "error",
    "probe_location",
]

BLOCKED_CODES = {401, 403, 429}
USER_AGENT = (
    "uptime-sla-monitor/1.0 (portfolio project; homepage check once per hour)"
)


def classify(status_code: int) -> str:
    if 200 <= status_code < 400:
        return "UP"
    if status_code in BLOCKED_CODES:
        return "BLOCKED"
    return "DOWN"


def probe_once(url: str, connect_timeout: float, read_timeout: float) -> dict:
    """One GET request. response_ms = time until the final response headers
    arrive, including DNS, TCP/TLS handshake and any redirects."""
    start = time.perf_counter()
    try:
        with requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=(connect_timeout, read_timeout),
            allow_redirects=True,
            stream=True,  # do not download the full page body
        ) as resp:
            elapsed_ms = round((time.perf_counter() - start) * 1000)
            return {
                "outcome": classify(resp.status_code),
                "status_code": resp.status_code,
                "response_ms": elapsed_ms,
                "final_url": resp.url,
                "error": "",
            }
    except requests.RequestException as exc:
        return {
            "outcome": "DOWN",
            "status_code": "",
            "response_ms": "",
            "final_url": "",
            "error": type(exc).__name__,
        }


def check_site(site: dict, args) -> dict:
    result = probe_once(site["url"], args.connect_timeout, args.read_timeout)
    attempts = 1
    if result["outcome"] == "DOWN":
        # Retry once so a single dropped packet is not counted as an incident.
        time.sleep(args.retry_delay)
        result = probe_once(site["url"], args.connect_timeout, args.read_timeout)
        attempts = 2
    return {"site_id": site["site_id"], "url": site["url"], "attempts": attempts, **result}


def load_sites(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return [row for row in csv.DictReader(f) if row.get("url")]


def append_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sites", default="sites.csv", type=Path)
    parser.add_argument("--out", default="data/checks.csv", type=Path)
    parser.add_argument("--connect-timeout", default=10.0, type=float)
    parser.add_argument("--read-timeout", default=20.0, type=float)
    parser.add_argument("--retry-delay", default=10.0, type=float)
    parser.add_argument("--workers", default=10, type=int)
    args = parser.parse_args()

    sites = load_sites(args.sites)
    run_id = os.environ.get("GITHUB_RUN_ID") or uuid.uuid4().hex[:10]
    checked_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    probe_location = os.environ.get("PROBE_LOCATION", "local")

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(lambda s: check_site(s, args), sites))

    rows = [
        {"run_id": run_id, "checked_at_utc": checked_at,
         "probe_location": probe_location, **r}
        for r in sorted(results, key=lambda r: r["site_id"])
    ]
    append_rows(args.out, rows)

    counts = {k: sum(r["outcome"] == k for r in rows) for k in ("UP", "BLOCKED", "DOWN")}
    print(f"{checked_at} UTC | {len(rows)} sites | " +
          " ".join(f"{k}={v}" for k, v in counts.items()))
    for r in rows:
        if r["outcome"] != "UP":
            print(f"  {r['site_id']:6} {r['outcome']:8} {r['status_code'] or r['error']}")


if __name__ == "__main__":
    main()
