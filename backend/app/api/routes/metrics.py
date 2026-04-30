"""/api/metrics/* routes -- interval metrics from Flow.

URL namespace (parametric subject_type per Phase 15 -- 2026-04-30):

  GET /api/metrics/{subject_type}/{interval}
  GET /api/metrics/{subject_type}/subjects

subject_type is validated by a Literal: 'conveyor', 'workcenter',
'circuit', 'line', 'equipment', 'site'. The service layer + SQL
source are subject-type-agnostic; only the route knows the path
shape and the validation set. A typo or unsupported value (e.g.
/api/metrics/foo/shiftly) returns 422 from FastAPI's path validator
before any DB or HTTP work.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated, Literal

import httpx
import structlog

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request

from app.api.dependencies import get_interval_metric_source
from app.core.config import get_settings
from app.core.snapshot import SnapshotStore
from app.integrations.metrics.base import (
    IntervalMetricPoint,
    IntervalMetricSource,
    IntervalMetricSubject,
)
from app.schemas.metrics import (
    IntervalMetricEntry,
    IntervalMetricsResponse,
    IntervalMetricSubject as IntervalMetricSubjectSchema,
    IntervalMetricSubjectsResponse,
)
from app.services.metrics import get_interval_metrics, list_metric_subjects

router = APIRouter()
log = structlog.get_logger("api.routes.metrics")

IntervalMetricSourceDep = Annotated[
    IntervalMetricSource, Depends(get_interval_metric_source)
]

SubjectTypeLiteral = Literal[
    "conveyor", "workcenter", "circuit", "line", "equipment", "site"
]


def _entry_from_point(p: IntervalMetricPoint) -> IntervalMetricEntry:
    return IntervalMetricEntry(
        subject_type=p.subject_type,
        subject_id=p.subject_id,
        metric=p.metric,
        interval=p.interval,
        bucket_start=p.bucket_start,
        bucket_end=p.bucket_end,
        value=p.value,
        unit=p.unit,
        quality_code=p.quality_code,
    )


def _schema_subject(s: IntervalMetricSubject) -> IntervalMetricSubjectSchema:
    return IntervalMetricSubjectSchema(
        subject_id=s.subject_id,
        department_id=s.department_id,
        metric_names=list(s.metric_names),
        intervals=list(s.intervals),
        last_seen=s.last_seen,
    )


def _snapshot_store(request: Request) -> SnapshotStore:
    """Pull the lifespan-created SnapshotStore off app.state."""
    store = getattr(request.app.state, "snapshot_store", None)
    if store is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Snapshot store not initialised. Check uvicorn startup log."
            ),
        )
    return store


# Note: register the more-specific `/subjects` route BEFORE the
# parametric `/{interval}` route. Starlette / FastAPI match in
# declaration order, and `subjects` would otherwise be tried as
# an `interval` value and rejected by the Literal validator.
@router.get(
    "/{subject_type}/subjects",
    response_model=IntervalMetricSubjectsResponse,
    summary="List interval-metric tags available for a site + subject type",
    description=(
        "Cheap discovery -- a single SELECT against "
        "[FLOW].[INTERVAL_METRIC_TAGS] with no upstream HTTP fan-out. "
        "Useful for Ignition dropdowns, dashboard inventory pages, and "
        "freshness checks (last_seen tells you when the tag last "
        "published)."
    ),
)
async def metrics_subjects(
    source: IntervalMetricSourceDep,
    subject_type: Annotated[
        SubjectTypeLiteral,
        Path(
            description=(
                "Subject type. One of: 'conveyor', 'workcenter', "
                "'circuit', 'line', 'equipment', 'site'."
            )
        ),
    ],
    site_id: Annotated[str, Query(description="Site to enumerate (required).")],
    department_id: Annotated[
        str | None,
        Query(description="Optional filter to one workcenter / department."),
    ] = None,
) -> IntervalMetricSubjectsResponse:
    subjects = await list_metric_subjects(
        source=source,
        site_id=site_id,
        subject_type=subject_type,
        department_id=department_id,
    )
    return IntervalMetricSubjectsResponse(
        count=len(subjects),
        subject_type=subject_type,
        site_id=site_id,
        department_id=department_id,
        generated_at=datetime.now(UTC),
        subjects=[_schema_subject(s) for s in subjects],
    )


@router.get(
    "/{subject_type}/{interval}",
    response_model=IntervalMetricsResponse,
    summary="Fetch interval-metric history",
    description=(
        "Look up matching tags in [FLOW].[INTERVAL_METRIC_TAGS], fan "
        "out per-tag history fetches to Flow's REST API, return one "
        "envelope. Filters compose: site_id + dates required, others "
        "optional. ``truncated`` on the response is True when at "
        "least one upstream fetch hit Flow's per-tag cap (limit=1000); "
        "narrow the window or add a tag filter and re-request."
    ),
)
async def metrics_history(
    request: Request,
    source: IntervalMetricSourceDep,
    subject_type: Annotated[
        SubjectTypeLiteral,
        Path(
            description=(
                "Subject type. One of: 'conveyor', 'workcenter', "
                "'circuit', 'line', 'equipment', 'site'."
            )
        ),
    ],
    interval: Annotated[
        Literal["hourly", "shiftly"],
        Path(description="Bucket regime: 'hourly' or 'shiftly'."),
    ],
    site_id: Annotated[str, Query(description="Site to fetch.")],
    from_date: Annotated[
        date, Query(description="Inclusive window start, YYYY-MM-DD.")
    ],
    to_date: Annotated[
        date, Query(description="Inclusive window end, YYYY-MM-DD.")
    ],
    department_id: Annotated[
        str | None, Query(description="Optional workcenter filter.")
    ] = None,
    subject_id: Annotated[
        str | None, Query(description="Optional asset filter (e.g. 'C4').")
    ] = None,
    metric: Annotated[
        str | None,
        Query(description="Optional metric-name filter (e.g. 'Total')."),
    ] = None,
) -> IntervalMetricsResponse:
    settings = get_settings()
    store = _snapshot_store(request)

    if interval == "hourly":
        ttl = settings.metrics_cache_ttl_hourly_s
        max_window = settings.metrics_max_window_days_hourly
    else:
        ttl = settings.metrics_cache_ttl_shiftly_s
        max_window = settings.metrics_max_window_days_shiftly

    try:
        result = await get_interval_metrics(
            source=source,
            snapshot_store=store,
            site_id=site_id,
            subject_type=subject_type,
            interval=interval,
            from_date=from_date,
            to_date=to_date,
            department_id=department_id,
            subject_id=subject_id,
            metric=metric,
            cache_ttl_seconds=ttl,
            max_points=settings.metrics_max_points,
            max_window_days=max_window,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        # Flow returned a non-2xx. Forward the upstream status and a
        # truncated body so the client knows what Flow said.
        body_excerpt = exc.response.text[:500] if exc.response is not None else ""
        log.error(
            "flow_api.http_error",
            status=exc.response.status_code if exc.response is not None else None,
            url=str(exc.request.url) if exc.request is not None else None,
            body=body_excerpt,
        )
        raise HTTPException(
            status_code=502,
            detail=(
                f"Flow API returned {exc.response.status_code if exc.response is not None else '?'}: "
                f"{body_excerpt}"
            ),
        ) from exc
    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
        log.error(
            "flow_api.connect_error",
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        raise HTTPException(
            status_code=504,
            detail=(
                f"Cannot reach Flow API: {type(exc).__name__}: {exc}. "
                "Check that the container can resolve the historian "
                "hostname and reach the port."
            ),
        ) from exc
    except httpx.TimeoutException as exc:
        log.error(
            "flow_api.timeout",
            error_message=str(exc),
        )
        raise HTTPException(
            status_code=504,
            detail=f"Flow API request timed out: {exc}",
        ) from exc
    except httpx.HTTPError as exc:
        # Catch-all for other httpx-level errors (DNS, SSL, etc.)
        log.error(
            "flow_api.http_error_generic",
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        raise HTTPException(
            status_code=502,
            detail=f"Flow API call failed: {type(exc).__name__}: {exc}",
        ) from exc

    return IntervalMetricsResponse(
        count=len(result.points),
        subject_type=subject_type,
        interval=interval,
        site_id=site_id,
        department_id=department_id,
        subject_id=subject_id,
        metric=metric,
        from_date=from_date,
        to_date=to_date,
        generated_at=datetime.now(UTC),
        truncated=result.truncated,
        entries=[_entry_from_point(p) for p in result.points],
    )
