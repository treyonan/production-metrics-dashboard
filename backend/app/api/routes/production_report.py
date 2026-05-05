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
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from app.api.dependencies import get_production_report_source
from app.integrations.production_report.base import (
    ProductionReportRow,
    ProductionReportSource,
)
from app.schemas.production_report import (
    CircuitBucketEntry as PydCircuitBucketEntry,
    CircuitRollup as PydCircuitRollup,
    CircuitRollupResponse,
    ConveyorTotals,
    DepartmentCircuitRollup as PydDepartmentCircuitRollup,
    LatestDateResponse,
    LineRollup as PydLineRollup,
    ProductionReportEntry,
    ProductionReportLatestResponse,
    ProductionReportRangeResponse,
    RollupEntry,
    RollupResponse,
)
from app.services.production_report import (
    CircuitBucketEntry as SvcCircuitBucketEntry,
    CircuitRollup as SvcCircuitRollup,
    ConveyorAggregate,
    DepartmentCircuitRollup as SvcDepartmentCircuitRollup,
    LineRollup as SvcLineRollup,
    Rollup,
    compute_conveyor_totals,
    get_circuit_rollup,
    get_latest_date,
    get_latest_per_workcenter,
    get_range,
    get_rollup,
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



# ---- /rollup/{bucket} (Phase 18) ------------------------------------

def _to_rollup_entry(r: Rollup) -> RollupEntry:
    return RollupEntry(
        department_id=r.department_id,
        department_name=r.department_name,  # Phase 12; non-null per Phase 13 contract.
        bucket_label=r.bucket_label,
        total_tons=r.total_tons,
        total_runtime_hours=r.total_runtime_hours,
        report_count=r.report_count,
        avg_tph_fed=r.avg_tph_fed,                     # Phase 14a
        avg_runtime_pct=r.avg_runtime_pct,             # Phase 14a
        avg_performance_pct=r.avg_performance_pct,     # Phase 14a
        calcs=r.calcs,                                  # Phase 22
    )


BucketLiteral = Literal["monthly", "yearly"]

# Per-bucket caps on the number of buckets a single response can contain.
# Keeps a malformed client from accidentally requesting a 500-year scan.
_MAX_BUCKETS = {"monthly": 37, "yearly": 50}


def _bucket_count(bucket: str, from_d: date, to_d: date) -> int:
    if bucket == "yearly":
        return to_d.year - from_d.year + 1
    return (to_d.year - from_d.year) * 12 + (to_d.month - from_d.month) + 1


@router.get(
    "/rollup/{bucket}",
    response_model=RollupResponse,
    summary="Per-bucket, per-workcenter rollup of production-report data",
    description=(
        "Computes one row per (department_id, bucket) within "
        "[from_date, to_date]. ``bucket`` is 'monthly' or 'yearly'; "
        "the response shape is identical across both -- only the "
        "bucket_label differs (YYYY-MM vs YYYY). Aggregates: total_tons "
        "(sum of belt-scaled CX conveyor totals), total_runtime_hours "
        "(sum of Workcenter.Runtime in decimal hours), tph (null when "
        "runtime is 0), report_count, and the Phase 14a simple-average "
        "fields. Used by the dashboard's Trends tab. Future versions "
        "may swap the underlying data path to Flow-sourced rolled-up "
        "metrics; the wire shape stays stable. Caps: 37 monthly buckets, "
        "50 yearly buckets per response."
    ),
)
async def rollup(
    production_report: ProductionReportSourceDep,
    bucket: Annotated[
        BucketLiteral,
        Path(description="Bucket regime: 'monthly' or 'yearly'."),
    ],
    site_id: Annotated[str, Query(description="Site to roll up (required).")],
    from_date: Annotated[
        date,
        Query(description=(
            "Inclusive window start, YYYY-MM-DD. For monthly bucket, "
            "use the first of the month (YYYY-MM-01). For yearly "
            "bucket, use Jan 1 (YYYY-01-01)."
        )),
    ],
    to_date: Annotated[
        date,
        Query(description=(
            "Inclusive window end, YYYY-MM-DD. For monthly bucket, "
            "use the last day of the month. For yearly bucket, use "
            "Dec 31 (YYYY-12-31)."
        )),
    ],
    department_id: Annotated[
        str | None,
        Query(description="Optional filter: roll up only this department_id."),
    ] = None,
) -> RollupResponse:
    if from_date > to_date:
        raise HTTPException(
            status_code=422,
            detail=(
                f"from_date ({from_date.isoformat()}) must be <= "
                f"to_date ({to_date.isoformat()})."
            ),
        )
    count = _bucket_count(bucket, from_date, to_date)
    cap = _MAX_BUCKETS[bucket]
    if count > cap:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Window too large: {count} {bucket} buckets exceeds "
                f"the {cap}-bucket cap. Narrow the window."
            ),
        )

    try:
        rollups = await get_rollup(
            production_report,
            site_id=site_id,
            bucket=bucket,
            from_date=from_date,
            to_date=to_date,
            department_id=department_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return RollupResponse(
        site_id=site_id,
        bucket=bucket,
        from_date=from_date,
        to_date=to_date,
        department_id=department_id,
        generated_at=datetime.now(UTC),
        rollups=[_to_rollup_entry(r) for r in rollups],
    )


# --- /circuit-rollup/{bucket} (Phase 14b + Phase 18) ----------------------


def _to_pyd_circuit_entry(e: SvcCircuitBucketEntry) -> PydCircuitBucketEntry:
    return PydCircuitBucketEntry(
        bucket_label=e.bucket_label,
        total_tons=e.total_tons,
        runtime_hours=e.runtime_hours,
        avg_tph=e.avg_tph,
        avg_yield=e.avg_yield,
        report_count=e.report_count,
        calcs=e.calcs,                                  # Phase 22
    )


def _to_pyd_line(line: SvcLineRollup) -> PydLineRollup:
    return PydLineRollup(
        line_id=line.line_id,
        description=line.description,
        buckets=[_to_pyd_circuit_entry(b) for b in line.buckets],
    )


def _to_pyd_circuit(c: SvcCircuitRollup) -> PydCircuitRollup:
    return PydCircuitRollup(
        circuit_id=c.circuit_id,
        description=c.description,
        buckets=[_to_pyd_circuit_entry(b) for b in c.buckets],
        lines=[_to_pyd_line(l) for l in c.lines],
    )


def _to_pyd_department(d: SvcDepartmentCircuitRollup) -> PydDepartmentCircuitRollup:
    return PydDepartmentCircuitRollup(
        department_id=d.department_id,
        department_name=d.department_name,
        circuits=[_to_pyd_circuit(c) for c in d.circuits],
    )


@router.get(
    "/circuit-rollup/{bucket}",
    response_model=CircuitRollupResponse,
    summary="Per-circuit and per-line bucket rollups (monthly or yearly)",
    description=(
        "Walks payload.Metrics.Circuit on every production-report row "
        "in [from_date, to_date] and returns a hierarchical "
        "(department -> circuits -> [optional] lines -> buckets) view "
        "of TPH, total tons, and yield per node. ``bucket`` is "
        "'monthly' or 'yearly'; same shape, different bucket_label "
        "format. Site-specific topology is encoded in node "
        "`description` fields; consumers render them as labels with "
        "no hard-coded knowledge of '57-1' / 'Main Circuit'. "
        "Aggregations are simple averages across reports in each "
        "(node, bucket) pair. Caps: 37 monthly buckets, 50 yearly."
    ),
)
async def circuit_rollup(
    production_report: ProductionReportSourceDep,
    bucket: Annotated[
        BucketLiteral,
        Path(description="Bucket regime: 'monthly' or 'yearly'."),
    ],
    site_id: Annotated[str, Query(description="Site to roll up (required).")],
    from_date: Annotated[date, Query(description="Inclusive window start, YYYY-MM-DD.")],
    to_date: Annotated[date, Query(description="Inclusive window end, YYYY-MM-DD.")],
    department_id: Annotated[
        str | None,
        Query(description="Optional filter: roll up only this department_id."),
    ] = None,
) -> CircuitRollupResponse:
    if from_date > to_date:
        raise HTTPException(
            status_code=422,
            detail=f"from_date ({from_date.isoformat()}) must be <= to_date ({to_date.isoformat()}).",
        )
    count = _bucket_count(bucket, from_date, to_date)
    cap = _MAX_BUCKETS[bucket]
    if count > cap:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Window too large: {count} {bucket} buckets exceeds the "
                f"{cap}-bucket cap. Narrow the window."
            ),
        )
    try:
        depts = await get_circuit_rollup(
            production_report,
            site_id=site_id,
            bucket=bucket,
            from_date=from_date,
            to_date=to_date,
            department_id=department_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return CircuitRollupResponse(
        site_id=site_id,
        bucket=bucket,
        from_date=from_date,
        to_date=to_date,
        department_id=department_id,
        generated_at=datetime.now(UTC),
        departments=[_to_pyd_department(d) for d in depts],
    )

