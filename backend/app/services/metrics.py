"""Service layer for /api/metrics/*.

Two responsibilities:

1. Validate window + size limits (raise ValueError; the route turns
   that into 422 with a useful detail).
2. Cache the source's per-request fetch via ``SnapshotStore`` with
   per-interval TTLs. Snapshot store is configured in the lifespan
   and passed in by the DI provider.

Source-agnostic: the service only knows ``IntervalMetricSource``,
not which concrete class is behind the Protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from app.core.snapshot import SnapshotStore
from app.integrations.metrics.base import (
    FetchPointsResult,
    IntervalMetricPoint,
    IntervalMetricSource,
    IntervalMetricSubject,
)


@dataclass(frozen=True)
class _CachedFetch:
    """What we stash in SnapshotStore for fetch_points results."""

    points: tuple[IntervalMetricPoint, ...]
    truncated: bool


def _make_cache_key(
    *,
    site_id: str,
    subject_type: str,
    interval: str,
    from_date: date,
    to_date: date,
    department_id: str | None,
    subject_id: str | None,
    metric: str | None,
) -> str:
    """Deterministic cache key for a metrics fetch.

    Sorted key=value pairs so the same filter combination always
    produces the same string regardless of param ordering at the
    call site. Pipe-separated to avoid collisions with values that
    might contain ``&`` or ``=``.
    """
    parts = [
        f"subject_type={subject_type}",
        f"interval={interval}",
        f"site_id={site_id}",
        f"department_id={department_id or ''}",
        f"subject_id={subject_id or ''}",
        f"metric={metric or ''}",
        f"from={from_date.isoformat()}",
        f"to={to_date.isoformat()}",
    ]
    return "metrics:fetch|" + "|".join(parts)


async def get_interval_metrics(
    *,
    source: IntervalMetricSource,
    snapshot_store: SnapshotStore,
    site_id: str,
    subject_type: str,
    interval: str,
    from_date: date,
    to_date: date,
    cache_ttl_seconds: int,
    max_points: int,
    max_window_days: int,
    department_id: str | None = None,
    subject_id: str | None = None,
    metric: str | None = None,
) -> FetchPointsResult:
    """Fetch with caching + validation.

    Raises:
        ValueError -- when the window is invalid or the result would
            exceed ``max_points``. The route handler converts this
            to ``HTTPException(422, ...)``.
    """
    # Window validation: from_date <= to_date, span <= max_window_days.
    if from_date > to_date:
        raise ValueError(
            f"from_date ({from_date.isoformat()}) must be <= "
            f"to_date ({to_date.isoformat()})."
        )
    window_days = (to_date - from_date).days + 1
    if window_days > max_window_days:
        raise ValueError(
            f"Window too large: {window_days} days exceeds the "
            f"{max_window_days}-day cap for interval='{interval}'. "
            f"Narrow the window."
        )

    cache_key = _make_cache_key(
        site_id=site_id,
        subject_type=subject_type,
        interval=interval,
        from_date=from_date,
        to_date=to_date,
        department_id=department_id,
        subject_id=subject_id,
        metric=metric,
    )

    # Cache check.
    snap = await snapshot_store.get(cache_key)
    if snap is not None:
        age = datetime.now(UTC) - snap.created_at
        if age.total_seconds() < cache_ttl_seconds:
            cached: _CachedFetch = snap.data
            return FetchPointsResult(
                points=list(cached.points), truncated=cached.truncated
            )

    # Cache miss / expired -- fan out to the source.
    result = await source.fetch_points(
        site_id=site_id,
        subject_type=subject_type,
        interval=interval,
        from_date=from_date,
        to_date=to_date,
        department_id=department_id,
        subject_id=subject_id,
        metric=metric,
    )

    if len(result.points) > max_points:
        raise ValueError(
            f"Result too large: {len(result.points)} points exceeds the "
            f"{max_points}-point cap. Narrow the window or add a "
            f"metric / subject_id filter."
        )

    # Stash in cache as a tuple (immutable, hashable across get/set).
    await snapshot_store.set(
        cache_key,
        _CachedFetch(points=tuple(result.points), truncated=result.truncated),
    )
    return result


async def list_metric_subjects(
    *,
    source: IntervalMetricSource,
    site_id: str,
    subject_type: str,
    department_id: str | None = None,
) -> list[IntervalMetricSubject]:
    """Pure delegation to the source. No caching today -- the SQL is
    cheap and the subjects list is small. Add caching here if it
    becomes a hot path."""
    return await source.list_subjects(
        site_id=site_id,
        subject_type=subject_type,
        department_id=department_id,
    )
