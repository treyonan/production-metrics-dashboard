-- Fetch every production-report row, joined against the production-run
-- history (shift, weather) and comments (notes) tables. Service layer
-- re-applies any site / date filters client-side so the query is
-- parameterless and one-round-trip per /range.
--
-- CANONICAL JOIN REFERENCE (Phase 8):
--   [UNS].[GET_PRODUCTION_RUN_REPORTS]  -- an existing stored procedure
--   that joins the same three tables. We replicate its joins here
--   rather than EXEC-ing the SP because:
--     (a) the SP requires a single @WORKCENTER param, which would force
--         N-round-trips per /range (one per department), and
--     (b) the Phase 3 pattern in this project hits base tables directly
--         via query files under this folder.
--   If the SP's join logic evolves (new table, new column), this file
--   needs to be updated in lockstep. See tasks/decisions/
--   003-enrichment-joins.md for the full rationale.
--
-- DIVERGENCE FROM THE SP:
--   The SP uses INNER JOIN against SITE_PRODUCTION_RUN_HISTORY, which
--   silently drops any report that doesn't yet have a history row.
--   This query uses LEFT JOIN so every report still comes back --
--   matches the historical "fetch every row" behaviour of the original
--   select_all.sql. Reports without a history row get NULL for shift
--   and weather fields; the dashboard surfaces those as em-dash via
--   the standard placeholderize path.
--
-- Phase 12 (2026-04-28): added LEFT JOIN to
-- [DailyProductionEntry].[dbo].[Departments] for human-readable
-- department names. Cross-database query; the API's read-only
-- account must hold SELECT on [DailyProductionEntry].[dbo].[Departments].
-- LEFT JOIN (not INNER) so a missing lookup row doesn't drop the
-- production report -- name comes back NULL and the frontend falls
-- back to the numeric department_id.
--
-- DEPT_NAME normalization (D8): underscores in [Name] are replaced
-- with spaces at the SQL layer. Single source of truth -- every
-- downstream surface (panel headers, Trends legends, modal,
-- XLSX export) inherits the normalization for free. If a caller
-- ever needs the raw underscored form, add a separate
-- DEPT_NAME_RAW column rather than re-doing the transformation
-- in multiple places.
--
-- Column order matches SqlProductionReportSource._row_to_dataclass.
-- DEPT_NAME appended at position 13 to avoid shifting any existing
-- positional indices in _row_to_dataclass.
SELECT
    rr.ID,
    rr.PRODDATE,
    rr.PROD_ID,
    rr.SITE_ID,
    rr.DEPARTMENT_ID,
    rr.PAYLOAD,
    rr.DTM,
    rh.SHIFT,
    rh.WEATHER_CONDITIONS,
    rh.AVG_TEMP,
    rh.AVG_HUMIDITY,
    rh.MAX_WIND_SPEED,
    rc.NOTES,
    REPLACE(d.[Name], '_', ' ') AS DEPT_NAME
FROM [UNS].[SITE_PRODUCTION_RUN_REPORTS] rr
LEFT JOIN [UNS].[SITE_PRODUCTION_RUN_HISTORY] rh
    ON rh.PROD_ID = rr.PROD_ID
LEFT JOIN [UNS].[SITE_PRODUCTION_RUN_COMMENTS] rc
    ON rc.PROD_ID = rr.PROD_ID
LEFT JOIN [DailyProductionEntry].[dbo].[Departments] d
    ON d.[Id] = rr.DEPARTMENT_ID;
