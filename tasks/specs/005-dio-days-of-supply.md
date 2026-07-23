# Spec 005 — Operational DIO / Days of Supply view

Status: FINAL (ready to build on go-ahead)
Source material: context/days-inventory-outstanding/
  - Operational_DIO_Days_of_Supply_Design_Summary.docx (business design)
  - UNS.GET_SITE_DIO_DAILY_RECORDS.sql (the SP)
  - UNS.SITE_DIO_DAILY_RECORDS.csv (source table sample)
  - dio-table.png (UI mockup), UNS.GET_SITE_DIO_DAILY_RECORDS_results.png (real SP output)

## 1. What it is
Operational **Days of Supply** per product/SKU at a site: how many days the
current on-hand inventory lasts at the recent sales rate.
  Days of Supply = Current Inventory / Average Daily Sales
Inventory is a point-in-time SNAPSHOT (never summed); sales are SUMMED over the
selected window (design doc s6). Operational DIO, not financial DIO.

## 2. Data source (SP-backed, like the Configured Run Report)
Source table `UNS.SITE_DIO_DAILY_RECORDS`: one row per (SITE_ID, PRODDATE,
ITEM_ID) with DAY_END_INVENTORY + TOTAL_SALES.

SP: `UNS.GET_SITE_DIO_DAILY_RECORDS(@SiteID INT, @StartDate DATETIME,
@EndDate DATETIME, @OutageRange INT = 67)` -> ONE row per item over the window:
  - Current Inventory = latest DAY_END_INVENTORY in range (ROW_NUMBER by PRODDATE DESC)
  - Total Sales = SUM(TOTAL_SALES) in range
  - TPD of sales = Total Sales / DayCount   (DayCount = DATEDIFF(day)+1, calendar days)
  - Days Of Inventory On Hand = Current Inventory / TPD   (NULL when sales = 0)
  - Days Of Inventory After Shutdown = Days On Hand - @OutageRange (67)  (NULL when sales = 0)

## 3. SP return columns (rendered verbatim in v1)
| SP alias | notes |
|---|---|
| Item Code | ST5450 etc. (MES.MASTER_ITEMS_DEFINITIONS.ITEMID) |
| Item Description | "1 1/2\" CRUSHER RUN" etc. |
| Total Sales | tons, SUM over window |
| TPD of sales | tons/day avg |
| Current Inventory | tons, latest snapshot in range |
| Days Of Inventory On Hand | nullable (NULL when Total Sales = 0) |
| Days Of Inventory After Shutdown | nullable; negative = short during the outage |
Values return with many decimals -> round on display; NULL -> "—".

## 4. Decisions locked (Trey, 2026-07-24)
- **67 / shutdown**: render the SP output VERBATIM for v1 (no client recompute).
  Denominator-adjustment method (doc s3) is DEFERRED pending clarification on
  what 67 represents. v1 shows what the SP returns.
- **Date range**: Week / Month / Quarter preset buttons + a manual From/To
  picker. Presets = rolling last **7 / 30 / 90** days, ending today (the SP's
  latest-in-range inventory covers a missing "today"). Default preset on load =
  **Month (30d)**.
- **Placement**: dedicated top-level in-app view "Days of Supply" (new vtab
  after "Production Charts").
- **Item Code**: its OWN column (not a sub-line). Can revisit later.
- **Route**: `GET /api/dio/daily`.
- **Excel export**: IN v1 — an export button on the view (SheetJS).

## 5. Backend design
Mirror the Configured Run Report SP pattern (integrations/production_report/
configured_run_report.py is the template).
- Integration source: EXEC the SP via the aioodbc pool, positional params
  (siteID, start, end) -- @OutageRange left at the SP default (67) for v1.
  JSON-safe coercion (Decimal->float, None passthrough).
- Service: validate window (from<=to), call source, map to typed rows.
- Schemas: `DioRow { item_code, item_description, total_sales, tpd_sales,
  current_inventory, days_on_hand: float|None, days_after_shutdown: float|None }`
  and `DioResponse { site_id, from_date, to_date, day_count, generated_at, rows[] }`.
- Route: `GET /api/dio/daily?site_id=&from_date=&to_date=`
  - 422 on from_date > to_date / bad dates.
  - 503 on SP failure (graceful degradation convention).
  - short-TTL cache (DIO is daily data; per-minute polling not needed).

## 6. Frontend design
- New in-app view: vtab `data-view="dio"` labelled "Days of Supply", after
  Production Charts. Uses the global site selector.
- Controls bar (own to this view):
  - Preset buttons [Week][Month][Quarter] -> set From/To (7/30/90d rolling,
    default Month on first load).
  - From/To date inputs (manual override).
  - **Export to Excel** button (right side, like the Run Report button).
- Auto-fetch on: site change, preset click, From/To change. (Not tied to the
  30s dashboard poll.)
- Table (per mockup) with header + formula-subtitle rows, reusing existing
  table styling + light/dark theme:
  Item Code | Item Description | Total Sales (SUM in range) |
  Avg Daily Sales (Total / days) | Current Inventory (latest on-hand) |
  Days of Supply (Inventory / avg daily) | DIO After Shutdown (Days - 67).
  - Totals row: SUM(sales), SUM(inventory), SUM(avg-daily); Days of Supply for
    the total = total inventory / total avg-daily (WEIGHTED, not a row average);
    After Shutdown = total Days - 67.
  - Formatting: tons with thousands sep; Days of Supply 1 decimal; NULL -> "—";
    negative "After Shutdown" in red.
  - Loading / empty / error states.
- Range/shutdown summary line above the table (mockup):
  "Date range: <from> to <to> · <N> days in range · Shutdown: 67 days".

## 7. Excel export (v1)
- Button on the DIO controls bar. Uses the vendored SheetJS (XLSX), same
  helpers as the other exports (_appendSheet / applyColumnFormats).
- One sheet: the displayed table (all product rows + the totals row, so the
  export MIRRORS the display per the "export mirrors displayed data" rule).
- Number formats: tons "#,##0"; TPD / Days of Supply "0.0"; NULL -> blank.
- Filename: `dio_<site-slug>_<from>_<to>_<timestamp>.xlsx`.

## 8. Deferred / out of scope for v1
- Clarify what 67 (outage range) means; possibly switch to the doc's
  denominator method or expose a configurable outage-days control.
- Daily DIO **trend** view (exec/ops trend, doc s6/s7) -- feasible later from
  the daily source table.
- Stockout / excess threshold color-coding (needs threshold definitions).
