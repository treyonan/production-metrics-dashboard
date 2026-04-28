"""/api/production-report/* -- current and historical workcenter metrics.

Phase 7 (2026-04-24): the rolling ``/history?days=N`` endpoint was
replaced by an absolute-window ``/range?from_date&to_date`` endpoint,
plus a small ``/latest-date?site_id=X`` bootstrap endpoint that tells
the dashboard which day to preselect in the day picker. See
``tasks/decisions/002-absolute-time-filter.md`` for the semantic
rationale.
"""

from __future__ import annotations

import re

from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.dependencies import get_production_report_source
from app.integrations.production_report.base import (
    ProductionReportRow,
    ProductionReportSource,
)
from app.schemas.production_report import (
    ConveyorTotals,
    LatestDateResponse,
    MonthlyRollupEntry,
    MonthlyRollupResponse,
    ProductionReportEntry,
    ProductionReportLatestResponse,
    ProductionReportRangeResponse,
)
from app.services.production_report import (
    ConveyorAggregate,
    MonthlyRollup,
    compute_conveyor_totals,
    get_latest_date,
    get_latest_per_workcenter,
    get_monthly_rollup,
    get_range,
)

router = APIRouter()

ProductionReportSourceDep = Annotated[ProductionReportSource, Depends(get_production_report_source)]

# Maximum span of /range in days (inclusive-inclusive). A defensive
# upper bound so a malformed client can't accidentally scan years of
# rows. 400 covers "a full year plus some calendar slack" -- anything
# wider is almost certainly a bug.
_MAX_RANGE_DAYS = 400


def _to_entry(r: ProductionReportRow) -> ProductionReportEntry:
    return ProductionReportEntry(
        id=r.id,
        prod_date=r.prod_date,
        prod_id=r.prod_id,
        site_id=r.site_id,
        department_id=r.department_id,
        department_name=r.department_name,  # Phase 12; non-null per Phase 13 contract.
        payload=r.payload,
        dtm=r.dtm,
        # Phase 8 enrichment (all optional; default to None if absent).
        shift=r.shift,
        weather_conditions=r.weather_conditions,
        avg_temp=r.avg_temp,
        avg_humidity=r.avg_humidity,
        max_wind_speed=r.max_wind_speed,
        notes=r.notes,
    )


def _totals_map(
    aggregates: dict[tuple[str, str], ConveyorAggregate],
) -> dict[str, ConveyorTotals]:
    """Convert the service-layer aggregate dict to the Pydantic wire shape.

    Keys are flattened from ``(site_id, department_id)`` tuples to
    ``"<site_id>:<department_id>"`` strings so the response is valid JSON
    (tuples aren't JSON-serializable object keys).
    """
    return {
        f"{sid}:{did}": ConveyorTotals(
            per_conveyor=agg.per_conveyor,
            product_mode=agg.product_mode,
            grand_total=agg.grand_total,
            conveyors_counted=agg.conveyors_counted,
            reports_counted=agg.reports_counted,
        )
        for (sid, did), agg in aggregates.items()
    }


@router.get(
    "/latest",
    response_model=ProductionReportLatestResponse,
    summary="Latest production report per workcenter",
    description=(
        "Returns the most recent production-report row for each "
        "(site_id, department_id), ordered by production date descending. "
        "Pass ``site_id`` to restrict the response to a single site. "
        "The ``payload`` field is a passthrough of the upstream PAYLOAD JSON; "
        "its internal shape is still stabilizing and is not strictly typed yet. "
        "The envelope also carries ``conveyor_totals`` -- per-workcenter "
        "belt-scaled conveyor tonnage summed from the returned entries, "
        "keyed by '<site_id>:<department_id>'."
    ),
)
async def latest(
    production_report: ProductionReportSourceDep,
    site_id: Annotated[
        str | None, Query(description="Optional filter: return only rows for this site_id.")
    ] = None,
) -> ProductionReportLatestResponse:
    rows = await get_latest_per_workcenter(production_report, site_id=site_id)
    totals = compute_conveyor_totals(rows)
    return ProductionReportLatestResponse(
        count=len(rows),
        generated_at=datetime.now(UTC),
        entries=[_to_entry(r) for r in rows],
        conveyor_totals=_totals_map(totals),
    )


@router.get(
    "/range",
    response_model=ProductionReportRangeResponse,
    summary="Production reports within an absolute date window",
    description=(
        "Returns all production-report rows where ``from_date <= "
        "prod_date.date() <= to_date``. Bounds are inclusive on both "
        "ends. Dates are ISO-8601 (YYYY-MM-DD); comparison is against "
        "the prod_date calendar day in UTC. Multiple entries per "
        "(site_id, department_id) are expected -- one per production "
        "report in the window. Ordered by (prod_date, dtm) descending. "
        "The frontend typically groups entries by department_id to "
        "render per-workcenter history tables. The envelope also "
        "carries ``conveyor_totals`` -- per-workcenter belt-scaled "
        "conveyor tonnage summed across all entries in the window, "
        "keyed by '<site_id>:<department_id>'. "
        "Maximum window is 400 days; larger requests are rejected "
        "with 422 to guard against accidental full-table scans."
    ),
)
async def range_(
    production_report: ProductionReportSourceDep,
    from_date: Annotated[
        date,
        Query(
            description=(
                "Inclusive start of the window (YYYY-MM-DD). "
                "Compared against prod_date.date()."
            )
        ),
    ],
    to_date: Annotated[
        date,
        Query(
            description=(
                "Inclusive end of the window (YYYY-MM-DD). "
                "Compared against prod_date.date()."
            )
        ),
    ],
    site_id: Annotated[
        str | None,
        Query(description="Optional filter: return only rows for this site_id."),
    ] = None,
) -> ProductionReportRangeResponse:
    if from_date > to_date:
        raise HTTPException(
            status_code=422,
            detail=(
                f"from_date ({from_date.isoformat()}) must be <= "
                f"to_date ({to_date.isoformat()})."
            ),
        )
    window_days = (to_date - from_date).days + 1
    if window_days > _MAX_RANGE_DAYS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Window too large: {window_days} days. "
                f"Max is {_MAX_RANGE_DAYS}."
            ),
        )

    try:
        rows = await get_range(
            production_report,
            from_date=from_date,
            to_date=to_date,
            site_id=site_id,
        )
    except ValueError as exc:
        # Defensive: the route-level guard above already catches the
        # from > to case, but the service also enforces it so the
        # function is safe to call from non-HTTP contexts.
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    totals = compute_conveyor_totals(rows)
    return ProductionReportRangeResponse(
        count=len(rows),
        from_date=from_date,
        to_date=to_date,
        site_id=site_id,
        generated_at=datetime.now(UTC),
        entries=[_to_entry(r) for r in rows],
        conveyor_totals=_totals_map(totals),
    )


@router.get(
    "/latest-date",
    response_model=LatestDateResponse,
    summary="Most recent production date for a site",
    description=(
        "Returns the newest prod_date.date() (UTC calendar day) for "
        "the given site. Used by the dashboard on load to default "
        "the day picker to the most-recent day with data -- sidesteps "
        "the empty-state that occurs when 'today' has not yet reported. "
        "Returns ``latest_date: null`` when the site has no reports."
    ),
)
async def latest_date_endpoint(
    production_report: ProductionReportSourceDep,
    site_id: Annotated[str, Query(description="Site to look up (required).")],
) -> LatestDateResponse:
    result = await get_latest_date(production_report, site_id=site_id)
    return LatestDateResponse(site_id=site_id, latest_date=result)



# ---- /monthly-rollup (Phase 10a) ------------------------------------

# Cap on the from->to span. ~37 months gives a comfortable window for
# rolling 3-year trends; beyond that, consumers should chunk client-side.
_MAX_ROLLUP_MONTHS = 37

_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")


def _parse_month_string(s: str, *, field_name: str) -> date:
    """Parse a YYYY-MM string into the first-day-of-month date."""
    match = _MONTH_RE.match(s or "")
    if not match:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Invalid {field_name} format: {s!r}; expected YYYY-MM "
                "(e.g. '2026-04')."
            ),
        )
    year = int(match.group(1))
    month = int(match.group(2))
    if month < 1 or month > 12:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid {field_name} month: {month}; must be 1-12.",
        )
    try:
        return date(year, month, 1)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid {field_name}: {exc}",
        ) from exc


def _last_day_of_month(d: date) -> date:
    """Return the last day of d's month."""
    from datetime import timedelta as _td
    if d.month == 12:
        nxt = date(d.year + 1, 1, 1)
    else:
        nxt = date(d.year, d.month + 1, 1)
    return nxt - _td(days=1)


def _months_between(a: date, b: date) -> int:
    """Inclusive month count between two first-of-month dates."""
    return (b.year - a.year) * 12 + (b.month - a.month) + 1


def _to_rollup_entry(r: MonthlyRollup) -> MonthlyRollupEntry:
    return MonthlyRollupEntry(
        department_id=r.department_id,
        department_name=r.department_name,  # Phase 12; non-null per Phase 13 contract.
        month=r.month,
        total_tons=r.total_tons,
        total_runtime_minutes=r.total_runtime_minutes,
        tph=r.tph,
        report_count=r.report_count,
    )


@router.get(
    "/monthly-rollup",
    response_model=MonthlyRollupResponse,
    summary="Per-month, per-workcenter rollup of production-report data",
    description=(
        "Computes one row per (department_id, year-month) within "
        "[from_month, to_month]. Aggregates: total_tons (sum of "
        "belt-scaled CX conveyor totals), total_runtime_minutes "
        "(Workcenter.Runtime, with Actual_Runtime_Hours*60 fallback), "
        "tph (tons-per-hour, null when runtime is 0), and "
        "report_count. Used by the dashboard's Trends tab. "
        "Future versions may swap the underlying data path to "
        "Flow-sourced monthly interval metrics; the wire shape is "
        "stable across that migration. Maximum window: 37 months."
    ),
)
async def monthly_rollup(
    production_report: ProductionReportSourceDep,
    site_id: Annotated[str, Query(description="Site to roll up (required).")],
    from_month: Annotated[
        str,
        Query(
            description=(
                "Earliest month to include, YYYY-MM (inclusive). "
                "Example: '2026-01' includes the entire January 2026."
            )
        ),
    ],
    to_month: Annotated[
        str,
        Query(
            description=(
                "Latest month to include, YYYY-MM (inclusive). Example: "
                "'2026-04' includes the entire April 2026."
            )
        ),
    ],
    department_id: Annotated[
        str | None,
        Query(description="Optional filter: roll up only this department_id."),
    ] = None,
) -> MonthlyRollupResponse:
    from_first = _parse_month_string(from_month, field_name="from_month")
    to_first = _parse_month_string(to_month, field_name="to_month")
    if from_first > to_first:
        raise HTTPException(
            status_code=422,
            detail=(
                f"from_month ({from_month}) must be <= to_month ({to_month})."
            ),
        )
    span = _months_between(from_first, to_first)
    if span > _MAX_ROLLUP_MONTHS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Window too large: {span} months exceeds the "
                f"{_MAX_ROLLUP_MONTHS}-month cap. Narrow the window."
            ),
        )

    to_last = _last_day_of_month(to_first)
    try:
        rollups = await get_monthly_rollup(
            production_report,
            site_id=site_id,
            from_month=from_first,
            to_month=to_last,
            department_id=department_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return MonthlyRollupResponse(
        site_id=site_id,
        from_month=from_month,
        to_month=to_month,
        department_id=department_id,
        generated_at=datetime.now(UTC),
        rollups=[_to_rollup_entry(r) for r in rollups],
    )
