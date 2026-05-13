-- Chart Labels -- joined view of the three MES config tables for ad-hoc
-- inspection. Same join the API uses, but with a human-friendly column
-- order and descriptive aliases.
--
-- Tables:
--   IA_ENTERPRISE.MES.RUN_REPORTS_CONFIG   cfg  -- per-(site, dept) label rows
--   IA_ENTERPRISE.MES.REPORT_COLUMN_CONFIG rc   -- metric-key dictionary
--   IA_ENTERPRISE.MES.REPORT_ASSET_CLASSES ac   -- scope dictionary
--
-- Two label columns are surfaced side by side:
--   CHART_LABEL  -- the dashboard reads this for chart titles (free
--                   to duplicate; only the row-key tuple must be
--                   unique). Source of truth for our consumer.
--   DISPLAY_NAME -- the legacy [UNS].[GET_CONFIGURED_RUN_REPORT] SP
--                   reads this for tabular column headers (unique per
--                   site/dept). Shown here for cross-reference.
--
-- Default: returns every row (active + retired, all sites, all depts)
-- sorted globals-first, then by (site, dept, scope, asset, order).
-- Common filter predicates are listed under "Filters" below -- uncomment
-- the ones you want.

SELECT
    cfg.[SITE_ID]            AS Site_Id,         -- 0 = global fallback row
    cfg.[DEPARTMENT_ID]      AS Department_Id,   -- 0 = global fallback row
    ac.[CLASS]               AS Scope,           -- 'Site' | 'Workcenter' | 'Conveyor' |
                                                 -- 'Crusher' | 'Circuit' |
                                                 -- 'Circuit_Line_A' | '_B' | '_C'
    cfg.[ASSET]              AS Asset,           -- e.g. 'Workcenter', 'A', 'B', 'C4', 'Crusher1'
    rc.[COLUMN_NAME]         AS Metric_Key,      -- e.g. 'Total', 'Rate', 'Yield',
                                                 --      'Performance', 'Availability'
    cfg.[CHART_LABEL]        AS Chart_Label,     -- dashboard chart title (our consumer)
    cfg.[DISPLAY_NAME]       AS Display_Name,    -- legacy tabular column header
    cfg.[DISPLAY_ORDER]      AS Display_Order,
    cfg.[ACTIVE]             AS Active,
    cfg.[RETIRED]            AS Retired,
    cfg.[DTM]                AS Modified_At,
    cfg.[ID]                 AS Config_Id,       -- surfacing IDs for debugging
    cfg.[CLASS_ID]           AS Class_Id,        -- (FK -> REPORT_ASSET_CLASSES.ID)
    cfg.[COLUMN_CONFIG_ID]   AS Column_Config_Id -- (FK -> REPORT_COLUMN_CONFIG.ID)
FROM       [IA_ENTERPRISE].[MES].[RUN_REPORTS_CONFIG]   cfg
INNER JOIN [IA_ENTERPRISE].[MES].[REPORT_COLUMN_CONFIG] rc
        ON rc.[ID] = cfg.[COLUMN_CONFIG_ID]
INNER JOIN [IA_ENTERPRISE].[MES].[REPORT_ASSET_CLASSES] ac
        ON ac.[ID] = cfg.[CLASS_ID]
-- =============================================================
-- Filters (uncomment as needed)
-- =============================================================
-- WHERE cfg.[ACTIVE] = 1 AND cfg.[RETIRED] = 0                 -- only currently-rendered labels
-- WHERE cfg.[SITE_ID] = 101                                    -- one site
-- WHERE cfg.[SITE_ID] = 101 AND cfg.[DEPARTMENT_ID] = 127      -- one workcenter
-- WHERE cfg.[SITE_ID] = 0   AND cfg.[DEPARTMENT_ID] = 0        -- only global fallback rows
-- WHERE ac.[CLASS] = 'Workcenter'                              -- workcenter-scope only
-- WHERE ac.[CLASS] LIKE 'Circuit%'                             -- circuits + lines only
-- WHERE rc.[COLUMN_NAME] = 'Total'                             -- one metric across all scopes/sites
ORDER BY
    cfg.[SITE_ID],          -- globals (0) first, then sites ascending
    cfg.[DEPARTMENT_ID],
    ac.[CLASS],
    cfg.[ASSET],
    cfg.[DISPLAY_ORDER];

-- ===================================================================
-- Optional: materialize as a view for repeated browsing.
-- Run once as a DBA; thereafter just `SELECT * FROM [MES].[v_ChartLabels]`.
-- ===================================================================
-- CREATE VIEW [IA_ENTERPRISE].[MES].[v_ChartLabels] AS
-- SELECT
--     cfg.[SITE_ID]            AS Site_Id,
--     cfg.[DEPARTMENT_ID]      AS Department_Id,
--     ac.[CLASS]               AS Scope,
--     cfg.[ASSET]              AS Asset,
--     rc.[COLUMN_NAME]         AS Metric_Key,
--     cfg.[CHART_LABEL]        AS Chart_Label,
--     cfg.[DISPLAY_NAME]       AS Display_Name,
--     cfg.[DISPLAY_ORDER]      AS Display_Order,
--     cfg.[ACTIVE]             AS Active,
--     cfg.[RETIRED]            AS Retired,
--     cfg.[DTM]                AS Modified_At,
--     cfg.[ID]                 AS Config_Id,
--     cfg.[CLASS_ID]           AS Class_Id,
--     cfg.[COLUMN_CONFIG_ID]   AS Column_Config_Id
-- FROM       [IA_ENTERPRISE].[MES].[RUN_REPORTS_CONFIG]   cfg
-- INNER JOIN [IA_ENTERPRISE].[MES].[REPORT_COLUMN_CONFIG] rc
--         ON rc.[ID] = cfg.[COLUMN_CONFIG_ID]
-- INNER JOIN [IA_ENTERPRISE].[MES].[REPORT_ASSET_CLASSES] ac
--         ON ac.[ID] = cfg.[CLASS_ID];
