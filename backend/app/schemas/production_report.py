"""Pydantic schemas for /api/production-report/*."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


class ProductionReportEntry(BaseModel):
    """One production-report row as surfaced by the API.

    The inner ``payload`` is intentionally untyped at this stage -- the
    upstream JSON shape is still stabilizing and current rows mix a
    legacy and a current variant. Treat it as data, not a contract.
    """

    id: int = Field(description="Source row ID.")
    prod_date: datetime = Field(description="Production day (midnight on the production date).")
    prod_id: str = Field(description="Upstream production-report identifier.")
    site_id: str = Field(description="Plant site identifier.")
    department_id: str = Field(description="Workcenter / department identifier.")
    department_name: str = Field(
        description=(
            "Human-readable department name from "
            "[DailyProductionEntry].[dbo].[Departments].[Name]. "
            "Underscores in the upstream value are normalized to "
            "spaces at the SQL layer (Phase 12, D8). Always populated "
            "in production responses -- the SQL source synthesizes a "
            "'Dept <id>' fallback (and logs a warning) on the rare "
            "LEFT JOIN miss so consumers never see null."
        ),
    )
    payload: dict[str, Any] = Field(
        description=(
            "Raw parsed PAYLOAD JSON. Shape evolving; see "
            "context/sample-data/production-report/payload-schema.md."
        )
    )
    dtm: datetime | None = Field(
        description=(
            "Upstream row write timestamp. Nullable -- the SQL DTM column "
            "allows NULL; legacy rows may omit it."
        )
    )
    # Phase 8 enrichment fields. All optional on the wire because the
    # SQL LEFT JOINs can miss if a report doesn't yet have a history
    # row.
    shift: str | None = Field(
        default=None,
        description=(
            "Shift identifier for this production report. Comes from "
            "SITE_PRODUCTION_RUN_HISTORY via a LEFT JOIN; null when "
            "the history row is absent."
        ),
    )
    weather_conditions: str | None = Field(
        default=None,
        description="Free-form weather description (e.g. 'Sunny', 'Overcast').",
    )
    avg_temp: float | None = Field(
        default=None,
        description="Average temperature over the shift, units per upstream.",
    )
    avg_humidity: float | None = Field(
        default=None,
        description="Average relative humidity over the shift (percent).",
    )
    max_wind_speed: float | None = Field(
        default=None,
        description="Peak wind speed over the shift, units per upstream.",
    )
    notes: str | None = Field(
        default=None,
        description=(
            "Free-form notes for this production run. Comes from "
            "SITE_PRODUCTION_RUN_COMMENTS via a LEFT JOIN; null when "
            "no comment exists for this PROD_ID."
        ),
    )


class ConveyorTotals(BaseModel):
    """Belt-scaled conveyor tonnage aggregated over the current window.

    Computed per ``(site_id, department_id)`` from the workcenter's
    production-report entries in the window. Only keys matching the
    strict regex ``/^C\\d+$/`` contribute -- other equipment (crushers,
    screens) has no belt scale and therefore no meaningful ``Total``.

    See ``PAYLOAD-CONTRACT.md`` for the rationale behind the strict-CX
    selection versus the shape-based discovery used for the asset
    table rows.
    """

    per_conveyor: dict[str, float] = Field(
        description=(
            "Per-conveyor summed tonnage. Keys are conveyor names in "
            "numeric order (C1, C3, C4, ...). Values are the sum of "
            "``Total`` across every production report in the window; "
            "nulls / missing values contribute 0."
        )
    )
    product_mode: dict[str, str | None] = Field(
        default_factory=dict,
        description=(
            "Per-conveyor *mode* of ``Produced_Item_Description`` across "
            "the window -- the value that appears most often for that "
            "conveyor. Keys match ``per_conveyor``. Placeholder values "
            "(``_``, ``None``, empty string) are excluded from the count "
            "so a conveyor that ran \"#57\" a few times but sat idle for "
            "the rest of the window still reports ``\"#57\"``. Ties are "
            "broken toward the newest report. Null when every observation "
            "is a placeholder, absent, or non-string."
        ),
    )
    grand_total: float = Field(
        description="Sum of all ``per_conveyor`` values for this workcenter's window."
    )
    conveyors_counted: int = Field(
        description="Number of distinct conveyors contributing to this aggregate."
    )
    reports_counted: int = Field(
        description="Number of production reports that contributed to this aggregate."
    )


class ProductionReportLatestResponse(BaseModel):
    """Envelope for the 'latest row per workcenter' endpoint."""

    count: int = Field(description="Number of entries returned.")
    generated_at: datetime = Field(description="UTC timestamp the response was assembled.")
    entries: list[ProductionReportEntry] = Field(
        description=(
            "Latest row per (site_id, department_id), ordered by production date descending."
        )
    )
    conveyor_totals: dict[str, ConveyorTotals] = Field(
        default_factory=dict,
        description=(
            "Per-workcenter belt-scaled conveyor totals for the current window. "
            "Keys are '<site_id>:<department_id>' strings. Workcenters without "
            "any conveyor data in the window are omitted entirely. Only keys "
            "matching /^C\\d+$/ are summed (belt-scaled assets) -- crushers, "
            "screens, and other equipment are excluded by design."
        ),
    )


class ProductionReportRangeResponse(BaseModel):
    """Envelope for the absolute-date-window endpoint.

    Returns every production-report row within ``[from_date, to_date]``
    inclusive, optionally filtered by ``site_id``. Bounds are compared
    against ``prod_date.date()`` so time-of-day doesn't affect inclusion.
    Unlike ``/latest``, multiple entries per ``(site_id, department_id)``
    are expected -- one per production report within the window.

    Replaces the rolling-window ``ProductionReportHistoryResponse``
    shape from Phase 2.1. Callers wanting "last N days" build
    ``from_date = today - (N-1)``, ``to_date = today`` client-side;
    the backend stays focused on absolute windows.
    """

    count: int = Field(description="Number of entries returned.")
    from_date: date = Field(description="Inclusive start of the window (UTC calendar date).")
    to_date: date = Field(description="Inclusive end of the window (UTC calendar date).")
    site_id: str | None = Field(
        default=None,
        description="Echo of the site_id filter (if any).",
    )
    generated_at: datetime = Field(description="UTC timestamp the response was assembled.")
    entries: list[ProductionReportEntry] = Field(
        description=(
            "All rows within the window, ordered by (prod_date, dtm) descending. "
            "The frontend is expected to group these by department_id for display."
        )
    )
    conveyor_totals: dict[str, ConveyorTotals] = Field(
        default_factory=dict,
        description=(
            "Per-workcenter belt-scaled conveyor totals summed across the entire "
            "window. Keys are '<site_id>:<department_id>' strings. See "
            "``ConveyorTotals`` for selection semantics."
        ),
    )


class LatestDateResponse(BaseModel):
    """Envelope for the /latest-date bootstrap endpoint.

    Returns the newest ``prod_date.date()`` for the given site, or
    ``null`` if the site has no reports. Used by the dashboard on load
    to seed the day picker with the most-recent day that actually has
    data -- sidesteps the "Today is often empty" problem that drove
    the Phase 7 time-filter redesign.
    """

    site_id: str = Field(description="Echo of the site_id input.")
    latest_date: date | None = Field(
        default=None,
        description=(
            "Newest UTC calendar date on which a production report exists "
            "for this site. Null when the site has no reports at all."
        ),
    )



class MonthlyRollupEntry(BaseModel):
    """One per-(department, month) production-report aggregate.

    Aggregates are computed server-side from per-shift production-
    report rows (see ``services.production_report.get_monthly_rollup``).
    Today the math runs against rows from
    ``[UNS].[SITE_PRODUCTION_RUN_REPORTS]``; future versions may swap
    to Flow-sourced monthly interval metrics with no change to this
    response shape.
    """

    department_id: str = Field(description="Workcenter / department identifier.")
    department_name: str = Field(
        description=(
            "Human-readable department name from Departments LEFT JOIN "
            "(Phase 12). All rows in a (dept_id, month) bucket share "
            "the same dept_id and therefore the same name. Always "
            "populated -- the SQL source synthesizes a fallback on a "
            "JOIN miss (see ProductionReportEntry.department_name)."
        ),
    )
    month: str = Field(
        description=(
            "Year-month identifier in YYYY-MM form (e.g. '2026-04'). "
            "Sortable lexicographically; consumers can plot directly "
            "as a category axis or parse to date(year, month, 1)."
        )
    )
    total_tons: float = Field(
        description=(
            "Sum of belt-scaled conveyor tonnage across every "
            "production-report row in this (department, month) "
            "combination. Computed via the same strict `/^C\d+$/` "
            "selection as Phase 5's bar-chart aggregation."
        )
    )
    total_runtime_hours: float = Field(
        description=(
            "Sum of Workcenter.Runtime (decimal hours) across every "
            "report in this month. Zero is a valid value (workcenter "
            "not scheduled or fully down). All payload runtime values "
            "are decimal hours as of 2026-04-28; the legacy "
            "minutes/hours unit-mismatch quirk is gone."
        )
    )
    tph: float | None = Field(
        default=None,
        description=(
            "Tons-per-hour: total_tons / total_runtime_hours. Null "
            "when total_runtime_hours is 0 (would be a divide-by-"
            "zero). Consumers render null as em-dash or skip the "
            "data point."
        ),
    )
    report_count: int = Field(
        description=(
            "Number of production-report rows that contributed to "
            "this rollup. Useful for confidence weighting -- a month "
            "with 2 reports is less reliable than one with 28."
        )
    )


class MonthlyRollupResponse(BaseModel):
    """Envelope for /api/production-report/monthly-rollup."""

    site_id: str = Field(description="Echo of the site_id filter.")
    from_month: str = Field(description="Echo of the from_month query (YYYY-MM).")
    to_month: str = Field(description="Echo of the to_month query (YYYY-MM).")
    department_id: str | None = Field(
        default=None,
        description="Echo of the optional department_id filter.",
    )
    generated_at: datetime = Field(description="UTC timestamp the response was assembled.")
    rollups: list[MonthlyRollupEntry] = Field(
        description=(
            "Flat list of (department_id, month) aggregates, sorted "
            "by department_id then month ascending. Empty when no "
            "production-report rows exist in the window for the site."
        )
    )
