/* ============================================================
   Least-privilege user for the daily GitHub Actions loader.
   Run once, as the server admin, in database uptime_sla.
   Replace the placeholder password before running and store the
   real password only as a GitHub secret — never commit it.
   ============================================================ */

CREATE USER loader_app WITH PASSWORD = '<REPLACE_WITH_STRONG_PASSWORD>';

-- The loader only reads and writes these two tables
GRANT SELECT, INSERT, UPDATE ON dbo.sites  TO loader_app;
GRANT SELECT, INSERT         ON dbo.checks TO loader_app;
