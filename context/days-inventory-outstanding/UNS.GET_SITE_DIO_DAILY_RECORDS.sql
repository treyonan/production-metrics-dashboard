USE [IA_ENTERPRISE]
GO
/****** Object:  StoredProcedure [UNS].[GET_SITE_DIO_DAILY_RECORDS]    Script Date: 7/23/2026 4:58:31 PM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
ALTER PROCEDURE [UNS].[GET_SITE_DIO_DAILY_RECORDS]
    @SiteID     INT,
    @StartDate  DATETIME,
    @EndDate    DATETIME,
    @OutageRange INT = 67
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @DayCount INT = DATEDIFF(DAY, @StartDate, @EndDate) + 1;

    WITH RankedInventory AS (
        SELECT
            ITEM_ID,
            DAY_END_INVENTORY,
            ROW_NUMBER() OVER (PARTITION BY ITEM_ID ORDER BY PRODDATE DESC) AS rn
        FROM [UNS].[SITE_DIO_DAILY_RECORDS]
        WHERE SITE_ID  = @SiteID
          AND PRODDATE BETWEEN @StartDate AND @EndDate
    ),
    Sales AS (
        SELECT
            ITEM_ID,
            SUM(TOTAL_SALES) AS TOTAL_SALES
        FROM [UNS].[SITE_DIO_DAILY_RECORDS]
        WHERE SITE_ID  = @SiteID
          AND PRODDATE BETWEEN @StartDate AND @EndDate
        GROUP BY ITEM_ID
    )
    SELECT
        mid.ITEMID                                                              AS 'Item Code',
        mid.ITEM_DESC                                                           AS 'Item Description',
        s.TOTAL_SALES                                                           AS 'Total Sales',
        s.TOTAL_SALES / @DayCount                                               AS 'TPD of sales',
        ri.DAY_END_INVENTORY                                                    AS 'Current Inventory',
        CASE 
            WHEN s.TOTAL_SALES = 0 THEN NULL
            ELSE ri.DAY_END_INVENTORY / (s.TOTAL_SALES / @DayCount)
        END                                                                     AS 'Days Of Inventory On Hand',
        CASE
            WHEN s.TOTAL_SALES = 0 THEN NULL
            ELSE (ri.DAY_END_INVENTORY / (s.TOTAL_SALES / @DayCount)) - @OutageRange
        END                                                                     AS 'Days Of Inventory After Shutdown'
    FROM RankedInventory ri
    JOIN Sales s ON s.ITEM_ID = ri.ITEM_ID
    JOIN [MES].[MASTER_ITEMS_DEFINITIONS] mid ON mid.ID = ri.ITEM_ID
    WHERE ri.rn = 1;
END
