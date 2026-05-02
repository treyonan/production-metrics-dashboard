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



class RollupEntry(BaseModel):
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
    bucket_label: str = Field(
        description=(
            "Bucket identifier. YYYY-MM for monthly buckets (e.g. "
            "'2026-04'); YYYY for yearly buckets (e.g. '2026'). Sortable "
            "lexicographically; consumers can plot directly as a category axis."
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
    avg_tph_fed: float | None = Field(
        default=None,
        description=(
            "Phase 14a. Simple arithmetic mean of per-report "
            "Workcenter.Rate (with fallback to Total / Runtime when "
            "Rate is null but both denominators are present and "
            "Runtime > 0) across every report in this (department, "
            "month) bucket. Drives the manager-style 'Total TPH "
            "Fed' bar chart on the Trends tab. Null when no report "
            "in the bucket has a usable value."
        ),
    )
    avg_runtime_pct: float | None = Field(
        default=None,
        description=(
            "Phase 14a. Simple arithmetic mean of per-report "
            "Workcenter.Availability (Runtime / Scheduled_Runtime "
            "as a percent, capped at 100). Falls back to Runtime / "
            "Scheduled_Runtime * 100 when Availability is null but "
            "both denominators are present and Scheduled_Runtime "
            "> 0. Drives the manager-style 'Runtime %' bar chart. "
            "Null when no report in the bucket has a usable value."
        ),
    )
    avg_performance_pct: float | None = Field(
        default=None,
        description=(
            "Phase 14a. Simple arithmetic mean of per-report "
            "Workcenter.Performance, which in the current payload "
            "schema equals Rate / Ideal_Rate * 100 (the OEE "
            "Performance Efficiency component / throughput "
            "utilization against nameplate capacity). Drives the "
            "'Performance %' bar chart. Null when no report in "
            "the bucket has a non-null Performance value."
        ),
    )


class RollupResponse(BaseModel):
    """Envelope for /api/production-report/monthly-rollup."""

    site_id: str = Field(description="Echo of the site_id filter.")
    bucket: str = Field(description="Echo of the bucket path parameter (monthly or yearly).")
    from_date: date = Field(description="Echo of the inclusive window start (YYYY-MM-DD).")
    to_date: date = Field(description="Echo of the inclusive window end (YYYY-MM-DD).")
    department_id: str | None = Field(
        default=None,
        description="Echo of the optional department_id filter.",
    )
    generated_at: datetime = Field(description="UTC timestamp the response was assembled.")
    rollups: list[RollupEntry] = Field(
        description=(
            "Flat list of (department_id, month) aggregates, sorted "
            "by department_id then month ascending. Empty when no "
            "production-report rows exist in the window for the site."
        )
    )


# --- Phase 14b: per-circuit / per-line monthly rollup wire shape ----------


class CircuitBucketEntry(BaseModel):
    """One per-(circuit-or-line, month) aggregate on the wire."""

    bucket_label: str = Field(description="Bucket identifier (YYYY-MM for monthly, YYYY for yearly).")
    total_tons: float = Field(description="Sum of node.Total across reports in this month bucket.")
    runtime_hours: float = Field(description="Sum of node.Runtime (decimal hours) across reports.")
    avg_tph: float | None = Field(
        default=None,
        description=(
            "Simple mean of per-report (Total/Runtime) where Runtime > 0. "
            "Null when no report in the bucket has positive Runtime."
        ),
    )
    avg_yield: float | None = Field(
        default=None,
        description=(
            "Simple mean of per-report Yield (the mass-conversion ratio "
            "pre-computed upstream as Line.Total / Workcenter.Total or the "
            "circuit-level equivalent). Null when no report has a usable "
            "Yield value."
        ),
    )
    report_count: int = Field(description="Number of reports contributing to this bucket.")


class LineRollup(BaseModel):
    """A sub-circuit ('line') under a top-level circuit. Empty for
    circuits without a Line sub-structure (e.g., a CR-only circuit)."""

    line_id: str = Field(description="Payload slot key (e.g. 'A', 'B'). Positional.")
    description: str = Field(description="Operator-facing label from payload (e.g. '57-1').")
    buckets: list[CircuitBucketEntry] = Field(description="Per-bucket aggregates (monthly or yearly per bucket arg) for this line.")


class CircuitRollup(BaseModel):
    """One top-level circuit, with optional nested lines."""

    circuit_id: str = Field(description="Payload slot key (e.g. 'A', 'B'). Positional.")
    description: str = Field(description="Operator-facing label from payload (e.g. 'Main Circuit').")
    buckets: list[CircuitBucketEntry] = Field(description="Per-bucket aggregates (monthly or yearly per bucket arg) for this circuit.")
    lines: list[LineRollup] = Field(
        default_factory=list,
        description="Sub-lines under this circuit. Empty when the circuit has no Line sub-structure.",
    )


class DepartmentCircuitRollup(BaseModel):
    """All circuits / lines for one department in the response."""

    department_id: str = Field(description="Workcenter / department identifier.")
    department_name: str = Field(description="Human-readable department name.")
    circuits: list[CircuitRollup] = Field(
        default_factory=list,
        description="Top-level circuits discovered in this department's reports. Empty when no Circuit block was present.",
    )


class CircuitRollupResponse(BaseModel):
    """Envelope for /api/production-report/circuit-monthly-rollup."""

    site_id: str = Field(description="Echo of the site_id filter.")
    bucket: str = Field(description="Echo of the bucket path parameter (monthly or yearly).")
    from_date: date = Field(description="Echo of the inclusive window start (YYYY-MM-DD).")
    to_date: date = Field(description="Echo of the inclusive window end (YYYY-MM-DD).")
    department_id: str | None = Field(
        default=None,
        description="Echo of optional department_id filter.",
    )
    generated_at: datetime = Field(description="UTC timestamp the response was assembled.")
    departments: list[DepartmentCircuitRollup] = Field(
        description="Per-department rollup. Empty when no rows match the filter."
    )

