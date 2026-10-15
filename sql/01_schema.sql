/* ============================================================
   uptime-sla-monitor — Azure SQL schema (Phase 2)
   Run once, as the server admin, in database uptime_sla.
   ============================================================ */

-- Site reference list (synced from sites.csv by the daily loader)
CREATE TABLE dbo.sites (
    site_id     VARCHAR(10)   NOT NULL CONSTRAINT PK_sites PRIMARY KEY,
    site_name   NVARCHAR(100) NOT NULL,
    sector      NVARCHAR(50)  NOT NULL,
    url         NVARCHAR(300) NOT NULL,
    is_active   BIT           NOT NULL CONSTRAINT DF_sites_is_active DEFAULT (1)
);

-- One row per site per hourly probe run (loaded daily from data/checks.csv)
CREATE TABLE dbo.checks (
    checked_at_utc  DATETIME2(0)  NOT NULL,
    site_id         VARCHAR(10)   NOT NULL,
    run_id          VARCHAR(30)   NOT NULL,
    url             NVARCHAR(300) NOT NULL,
    outcome         VARCHAR(10)   NOT NULL,
    status_code     SMALLINT      NULL,
    response_ms     INT           NULL,
    attempts        TINYINT       NOT NULL,
    final_url       NVARCHAR(500) NULL,
    error           VARCHAR(100)  NULL,
    probe_location  VARCHAR(50)   NOT NULL,
    loaded_at_utc   DATETIME2(0)  NOT NULL CONSTRAINT DF_checks_loaded_at DEFAULT (SYSUTCDATETIME()),
    -- Clustered on time first: incremental refresh filters by checked_at_utc
    CONSTRAINT PK_checks PRIMARY KEY CLUSTERED (checked_at_utc, site_id, run_id),
    CONSTRAINT CK_checks_outcome CHECK (outcome IN ('UP', 'BLOCKED', 'DOWN'))
);

-- Mapping table for dynamic row-level security in Power BI
CREATE TABLE dbo.user_sector_access (
    user_email  NVARCHAR(256) NOT NULL,
    sector      NVARCHAR(50)  NOT NULL,
    CONSTRAINT PK_user_sector_access PRIMARY KEY (user_email, sector)
);
