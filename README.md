# uptime-sla-monitor

Hourly uptime & latency monitoring of 20 Indonesian digital services (public services, e-commerce, banking, telco), with a Power BI SLA dashboard.

The data is self-collected: a Python probe runs every hour on GitHub Actions (started by an external cron trigger) and checks each homepage once. Results are staged in this repo and loaded once a day into Azure SQL Database, which feeds a Power BI dashboard.

## Architecture

```
cron-job.org (minute :05, every hour)
  │  POST workflow_dispatch
  ▼
GitHub Actions — hourly           GitHub Actions — daily (22:31 UTC)
  monitor.py                        load_to_sql.py
     │                                 │  incremental, idempotent
     ▼                                 ▼
  data/checks.csv  ───────────►  Azure SQL Database (serverless, free offer)
  sites.csv                            │  tables: checks, sites, user_sector_access
                                       ▼
                         Power BI Service — scheduled refresh,
                         SLA dashboard, mobile layout
```

- **External trigger:** [cron-job.org](https://cron-job.org) calls the GitHub API (`workflow_dispatch`) at minute 5 of every hour. GitHub's own `schedule` trigger was tried first but ran only about 4 to 6 of 24 slots per day, so it was removed.
- **Hourly probe** (`monitor.py`) appends results to `data/checks.csv` in this repo, which acts as the staging layer.
- **Daily load** (`load_to_sql.py`) upserts `sites.csv` and inserts new check rows into Azure SQL. It re-reads the last day on every run and skips rows that already exist, so a re-run never creates duplicates.
- **Least privilege:** the loader signs in as `loader_app`, a database user that can only read and insert check rows and maintain the site list. Credentials are stored as GitHub secrets.
- **Why daily, not hourly:** the serverless database bills compute while it is awake and stays awake for about an hour after each connection. One load per day keeps usage well inside the monthly free allowance; loading every hour would keep it awake around the clock.

Schema: [`sql/01_schema.sql`](sql/01_schema.sql) · loader user: [`sql/02_loader_user.sql`](sql/02_loader_user.sql)

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
- **Scheduling jitter:** the external trigger is hourly, but a run can still start late or be missed (one hourly slot is missing since 18 Oct 2026), so checks are not exactly 60 min apart.
- **Homepage only:** a working homepage does not mean login, payment or API services are working.
- **Not an official SLA:** these figures are an independent outside-in measurement and do not represent any provider's own SLA reporting.
- **Daily freshness:** the dashboard can be up to one day behind the hourly probe, by design (see Architecture).

## Roadmap

- Power BI incremental refresh with `RangeStart`/`RangeEnd` on `checked_at_utc`, folded to Azure SQL.
- Dynamic row-level security by sector, driven by the `user_sector_access` table.

## Run locally

```bash
pip install -r requirements.txt
python monitor.py                      # appends to data/checks.csv
python monitor.py --out test.csv       # write somewhere else
```
