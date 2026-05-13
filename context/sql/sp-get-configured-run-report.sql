USE [IA_ENTERPRISE]
GO
/****** Object:  StoredProcedure [UNS].[GET_CONFIGURED_RUN_REPORT]    Script Date: 5/13/2026 10:58:12 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
ALTER PROCEDURE [UNS].[GET_CONFIGURED_RUN_REPORT]
    @siteID       INT,
    @departmentID INT,
    @startDate    DATETIME,
    @endDate      DATETIME
AS
BEGIN
    SET NOCOUNT ON;

    -- =============================================================================
    -- Build dynamic column list from config
    -- =============================================================================
    DECLARE @jsonSelects NVARCHAR(MAX) = '';
    DECLARE @sql         NVARCHAR(MAX) = '';

    SELECT @jsonSelects +=
        'JSON_VALUE(r.[PAYLOAD], ''$.Metrics.' +
        CASE ac.[CLASS]
            WHEN 'Site'           THEN 'Site.'             + rc.[COLUMN_NAME]
            WHEN 'Workcenter'     THEN 'Workcenter.'       + rc.[COLUMN_NAME]
            WHEN 'Conveyor'       THEN cfg.[ASSET] + '.'   + rc.[COLUMN_NAME]
            WHEN 'Crusher'        THEN cfg.[ASSET] + '.'   + rc.[COLUMN_NAME]
            WHEN 'Circuit'        THEN 'Circuit.'          + cfg.[ASSET] + '.' + rc.[COLUMN_NAME]
            WHEN 'Circuit_Line_A' THEN 'Circuit.' + cfg.[ASSET] + '.Line.A.' + rc.[COLUMN_NAME]
            WHEN 'Circuit_Line_B' THEN 'Circuit.' + cfg.[ASSET] + '.Line.B.' + rc.[COLUMN_NAME]
            WHEN 'Circuit_Line_C' THEN 'Circuit.' + cfg.[ASSET] + '.Line.C.' + rc.[COLUMN_NAME]
        END +
        ''') AS ' + QUOTENAME(cfg.[DISPLAY_NAME]) + ', '
    FROM      [MES].[RUN_REPORTS_CONFIG]  cfg
    INNER JOIN [MES].[REPORT_COLUMN_CONFIG]       rc  ON rc.[ID]  = cfg.[COLUMN_CONFIG_ID]
    INNER JOIN [MES].[REPORT_ASSET_CLASSES]       ac  ON ac.[ID]  = cfg.[CLASS_ID]
    WHERE cfg.[SITE_ID]       = @siteID
    AND   cfg.[DEPARTMENT_ID] = @departmentID
    AND   cfg.[ACTIVE]        = 1
    AND   cfg.[RETIRED]       = 0
    ORDER BY cfg.[DISPLAY_ORDER];

    -- Strip trailing comma and space
    SET @jsonSelects = LEFT(@jsonSelects, LEN(@jsonSelects) - 1);

    -- =============================================================================
    -- Build and execute dynamic SQL
    -- =============================================================================
    SET @sql = '
    SELECT
        -- Pre-payload fixed columns
        CONVERT(NVARCHAR(10), r.[PRODDATE], 101)                            AS [Date],
        YEAR(r.[PRODDATE])                                                  AS [Year],
        DATENAME(MONTH, r.[PRODDATE])                                       AS [Month],
        r.[PROD_ID],
        h.[SHIFT],
        FORMAT(h.[STARTTIME], ''hh:mm tt'') AS [Start Time],
        FORMAT(h.[ENDTIME],   ''hh:mm tt'') AS [End Time],

        -- Dynamic payload columns
        ' + @jsonSelects + ',

        -- Post-payload fixed columns
        h.[WEATHER_CONDITIONS]                  AS [Weather],
        h.[AVG_TEMP]                            AS [Avg Temp],
        h.[AVG_HUMIDITY]                        AS [Avg Humidity],
        h.[MAX_WIND_SPEED]                      AS [Max Wind Speed],
        h.[MODIFIEDBY]                          AS [Modified By],
        c.[NOTES]                               AS [Notes]

    FROM      [IA_ENTERPRISE].[UNS].[SITE_PRODUCTION_RUN_REPORTS]  r
    LEFT JOIN [IA_ENTERPRISE].[UNS].[SITE_PRODUCTION_RUN_HISTORY]  h ON h.[PROD_ID] = r.[PROD_ID]
    LEFT JOIN [IA_ENTERPRISE].[UNS].[SITE_PRODUCTION_RUN_COMMENTS] c ON c.[PROD_ID] = r.[PROD_ID]

    WHERE r.[SITE_ID]       = ' + CAST(@siteID       AS NVARCHAR(10)) + '
    AND   r.[DEPARTMENT_ID] = ' + CAST(@departmentID AS NVARCHAR(10)) + '
    AND   r.[PRODDATE] BETWEEN ''' + CONVERT(NVARCHAR(20), @startDate, 120) + '''
                           AND ''' + CONVERT(NVARCHAR(20), @endDate,   120) + '''

    ORDER BY r.[PRODDATE] DESC, h.[SHIFT] ASC;
    ';

    EXEC sp_executesql @sql;

END;