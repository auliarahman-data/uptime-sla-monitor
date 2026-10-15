# uptime-sla-monitor

Hourly uptime & latency monitoring of 20 Indonesian digital services (public services, e-commerce, banking, telco), with a Power BI SLA dashboard.

The data is self-collected: a Python probe runs every hour on GitHub Actions, checks each homepage once, and appends the result to `data/checks.csv`. Power BI reads that file directly from GitHub and refreshes on a schedule.

## Architecture (Phase 1)

```
GitHub Actions (hourly cron)
   └─ monitor.py  ──►  data/checks.csv (committed to this repo)
                              │
                              ▼
          Power BI (Web connector → raw CSV URL)
          scheduled refresh · SLA dashboard · mobile layout
```

## What the dashboard measures

| Metric | Definition |
|---|---|
| Availability % | UP checks ÷ (UP + DOWN) checks. BLOCKED checks are excluded (see below). |
| Incident | One or more consecutive DOWN checks for the same site |
| Incident duration | Number of consecutive DOWN checks × 60 min (estimate, see limitations) |
| MTTR | Average incident duration |
| Latency | `response_ms`: time to the final response headers, including DNS, TLS and redirects |

## Data dictionary — `data/checks.csv`

| Column | Description |
|---|---|
| `run_id` | GitHub Actions run ID (one per hourly run) |
| `checked_at_utc` | Run timestamp, UTC (`yyyy-MM-dd HH:mm:ss`). Add 7 h for WIB. |
| `site_id` | Joins to `sites.csv` (site name, sector) |
| `url` | URL requested |
| `outcome` | `UP` (2xx/3xx) · `BLOCKED` (401/403/406/429) · `DOWN` (other 4xx/5xx, timeout, DNS/TLS/connection error) |
| `status_code` | Final HTTP status code (empty when no response) |
| `response_ms` | Latency in milliseconds (empty when no response) |
| `attempts` | 1, or 2 when the first attempt failed and was retried after 10 s |
| `final_url` | URL after redirects |
| `error` | Exception type when no response was received (e.g. `ReadTimeout`) |
| `probe_location` | Where the check ran (`github-hosted`) |

## Design decisions

- **Retry once before marking DOWN** — a single dropped connection should not count as an incident.
- **BLOCKED is not DOWN** — a 401/403/406/429 means the server is up but refused an automated request (bot protection, WAF, geo-blocking, rate limiting). Counting it as downtime would make availability figures wrong.
- **Persistent timeouts are reviewed, not reported** — some sites silently drop automated or foreign traffic, which looks like a timeout. A site that is DOWN in almost every run is treated as unreachable from the probe location and replaced, because a real outage is intermittent.
- **Headers only** — the probe stops after receiving response headers and does not download page content.
- **Light load** — one request per site per hour, homepage only, with a User-Agent that identifies the project.

## Limitations

- **Probe location:** GitHub-hosted runners are outside Indonesia. Latency reflects the path from the runner, not from Indonesian users, and some sites may block foreign or data-center traffic.
- **Hourly resolution:** outages shorter than the check interval can be missed, and incident duration is an estimate rounded to whole hours.
- **Scheduling jitter:** GitHub may delay scheduled runs during high load, so checks are not exactly 60 min apart.
- **Homepage only:** a working homepage does not mean login, payment or API services are working.
- **Not an official SLA:** these figures are an independent outside-in measurement and do not represent any provider's own SLA reporting.
- **Phase 1 refresh:** a CSV source does not support query folding, so Power BI incremental refresh gives little benefit until the data moves to SQL (Phase 2).

## Roadmap — Phase 2

- Load the hourly CSV into Azure SQL Database once a day (auto-pause to stay within the free offer).
- Power BI incremental refresh with `RangeStart`/`RangeEnd` and query folding.

## Run locally

```bash
pip install -r requirements.txt
python monitor.py                      # appends to data/checks.csv
python monitor.py --out test.csv       # write somewhere else
```
