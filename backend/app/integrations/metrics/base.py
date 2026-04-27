"""Interval-metric source Protocol and shared types.

Mirrors the Phase 3 ``ProductionReportSource`` pattern. One Protocol,
one dataclass row type, one ``SourceStatus`` shared with the
production-report integration. Concrete sources implement the
Protocol; routes and services depend only on the Protocol.

Today there's exactly one implementation -- ``SqlIntervalMetricSource``,
which reads tag rows from ``[FLOW].[INTERVAL_METRIC_TAGS]`` on the
enterprise SQL server and fans out per-tag history fetches to Flow's
REST API via ``FlowClient``. Future implementations (e.g. a CSV
fixture for offline tests, or a different vendor's REST API) plug
into the same Protocol.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol, runtime_checkable

# Re-use the production-report integration's SourceStatus -- one shape
# for /api/health output across all sources, regardless of domain.
from app.integrations.production_report.base import SourceStatus

__all__ = [
    "IntervalMetricPoint",
    "IntervalMetricSubject",
    "IntervalMetricSource",
    "SourceStatus",
]


@dataclass(frozen=True)
class IntervalMetricPoint:
    """One time-series bucket for one (asset, metric) combination.

    The frozen-dataclass form keeps service layers independent of the
    Pydantic wire model -- same pattern as ``ProductionReportRow``.
    Routes convert these to ``IntervalMetricEntry`` at the boundary.

    Identifying attributes (``subject_type`` / ``subject_id`` /
    ``metric`` / ``interval`` / ``unit``) come from the row in
    ``[FLOW].[INTERVAL_METRIC_TAGS]`` -- the source layer already
    knows them by the time it's calling Flow. Per-bucket attributes
    (``bucket_start`` / ``bucket_end`` / ``value`` / ``quality_code``)
    come from Flow's response.
    """

    subject_type: str
    subject_id: str
    metric: str
    interval: str
    bucket_start: datetime
    bucket_end: datetime
    value: float
    unit: str | None = None
    quality_code: int | None = None


@dataclass(frozen=True)
class IntervalMetricSubject:
    """One asset's tag inventory at the source layer.

    Built by ``IntervalMetricSource.list_subjects`` from a single
    ``SELECT`` against the tag table -- no HTTP fan-out. Used by the
    ``/subjects`` discovery endpoint and any consumer that needs to
    enumerate available tags before fetching values.
    """

    subject_id: str
    department_id: str | None
    metric_names: tuple[str, ...]
    intervals: tuple[str, ...]
    last_seen: datetime | None


@runtime_checkable
class IntervalMetricSource(Protocol):
    """Contract every interval-metric source implements.

    ``name`` is a short identifier for /api/health output. Two
    methods cover the consumer surface:

    * ``fetch_points`` -- per-tag time-series for a window. Returns
      both the parsed points and a ``truncated`` flag indicating
      whether any per-tag fetch hit the upstream's per-call limit.
    * ``list_subjects`` -- inventory only, no fan-out. Cheap.
    """

    name: str

    async def ping(self) -> SourceStatus: ...

    async def fetch_points(
        self,
        *,
        site_id: str,
        from_date: date,
        to_date: date,
        subject_type: str,
        interval: str,
        department_id: str | None = None,
        subject_id: str | None = None,
        metric: str | None = None,
    ) -> "FetchPointsResult": ...

    async def list_subjects(
        self,
        *,
        site_id: str,
        subject_type: str,
        department_id: str | None = None,
    ) -> list[IntervalMetricSubject]: ...


@dataclass(frozen=True)
class FetchPointsResult:
    """Return type for ``fetch_points``.

    Carries the flat list of points plus a ``truncated`` flag. The
    flag is True when any upstream per-tag fetch returned exactly the
    upstream cap (Flow's ``limit=1000``), which means some buckets
    may be missing for that tag. The route surfaces this on the
    response envelope so the consumer can decide to narrow.
    """

    points: list[IntervalMetricPoint] = field(default_factory=list)
    truncated: bool = False
