-- Chart label lookup. Returns one row per active config entry from the
-- existing MES.RUN_REPORTS_CONFIG label tables. The CHART_LABEL column
-- is dashboard-specific (added separately so chart titles can diverge
-- from DISPLAY_NAME, which the legacy [UNS].[GET_CONFIGURED_RUN_REPORT]
-- SP relies on for unique tabular column headers).
--
-- Database / schema:
--   [IA_ENTERPRISE].[MES].[RUN_REPORTS_CONFIG]   -- the per-(site, dept)
--                                                   label rows
--   [IA_ENTERPRISE].[MES].[REPORT_COLUMN_CONFIG] -- metric-key dictionary
--                                                   (Total / Rate / Yield / ...)
--   [IA_ENTERPRISE].[MES].[REPORT_ASSET_CLASSES] -- scope enum
--                                                   (Workcenter / Circuit /
--                                                    Circuit_Line_A / ...)
--
-- The API's read-only login must hold SELECT on the three tables above.
--
-- Parameterless on purpose: the chart consumer loads every active row
-- once at startup, caches the result keyed by
--   (site_id, dept_id, class, asset, column_name) -> display_name
-- and resolves in-process with a two-tier fallback:
--   (site_id, dept_id) -> (0, 0) -> raw metric key.
--
-- ACTIVE / RETIRED flags are applied server-side so soft-deleted rows
-- don't leak through to the cache. DISPLAY_ORDER is included for
-- future use (e.g. preferred chart ordering driven from config);
-- the label resolver itself doesn't consume it.
SELECT
    cfg.[ID]            AS config_id,
    cfg.[SITE_ID]       AS site_id,
    cfg.[DEPARTMENT_ID] AS department_id,
    ac.[CLASS]          AS class,
    cfg.[ASSET]         AS asset,
    rc.[COLUMN_NAME]    AS column_name,
    cfg.[CHART_LABEL]   AS display_name    
FROM       [IA_ENTERPRISE].[MES].[RUN_REPORTS_CONFIG]   cfg
INNER JOIN [IA_ENTERPRISE].[MES].[REPORT_COLUMN_CONFIG] rc
        ON rc.[ID] = cfg.[COLUMN_CONFIG_ID]
INNER JOIN [IA_ENTERPRISE].[MES].[REPORT_ASSET_CLASSES] ac
        ON ac.[ID] = cfg.[CLASS_ID]
WHERE cfg.[ACTIVE]  = 1
  AND cfg.[RETIRED] = 0
ORDER BY cfg.[SITE_ID], cfg.[DEPARTMENT_ID], cfg.[DISPLAY_ORDER];
