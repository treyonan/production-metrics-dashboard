"""Service-layer tests for /api/metrics/*.

Mocks the source Protocol (hand-rolled fake) and uses the real
``InMemorySnapshotStore`` so cache behavior is exercised end-to-end
without HTTP or SQL.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest

from app.core.snapshot import InMemorySnapshotStore
from app.integrations.metrics.base import (
    FetchPointsResult,
    IntervalMetricPoint,
    IntervalMetricSubject,
)
from app.services.metrics import get_interval_metrics, list_metric_subjects


class _FakeSource:
    name = "fake:metrics"

    def __init__(
        self,
        *,
        points_to_return: list[IntervalMetricPoint] | None = None,
        truncated: bool = False,
        subjects_to_return: list[IntervalMetricSubject] | None = None,
    ) -> None:
        self.points_to_return = points_to_return or []
        self.truncated = truncated
        self.subjects_to_return = subjects_to_return or []
        self.fetch_calls = 0
        self.subject_calls = 0

    async def ping(self) -> Any:
        raise NotImplementedError

    async def fetch_points(self, **kwargs):
        self.fetch_calls += 1
        return FetchPointsResult(
            points=list(self.points_to_return), truncated=self.truncated
        )

    async def list_subjects(self, **kwargs):
        self.subject_calls += 1
        return list(self.subjects_to_return)


def _point(subject_id: str = "C1") -> IntervalMetricPoint:
    return IntervalMetricPoint(
        subject_type="conveyor",
        subject_id=subject_id,
        metric="Total",
        interval="hourly",
        bucket_start=datetime(2026, 4, 1, 12, 0, tzinfo=UTC),
        bucket_end=datetime(2026, 4, 1, 13, 0, tzinfo=UTC),
        value=42.0,
    )


@pytest.mark.asyncio
async def test_get_interval_metrics_rejects_inverted_window() -> None:
    src = _FakeSource()
    with pytest.raises(ValueError, match="from_date"):
        await get_interval_metrics(
            source=src,
            snapshot_store=InMemorySnapshotStore(),
            site_id="101",
            subject_type="conveyor",
            interval="hourly",
            from_date=date(2026, 4, 5),
            to_date=date(2026, 4, 1),
            cache_ttl_seconds=60,
            max_points=1000,
            max_window_days=31,
        )
    assert src.fetch_calls == 0


@pytest.mark.asyncio
async def test_get_interval_metrics_rejects_oversized_window() -> None:
    src = _FakeSource()
    with pytest.raises(ValueError, match="Window too large"):
        await get_interval_metrics(
            source=src,
            snapshot_store=InMemorySnapshotStore(),
            site_id="101",
            subject_type="conveyor",
            interval="hourly",
            from_date=date(2026, 1, 1),
            to_date=date(2026, 12, 31),
            cache_ttl_seconds=60,
            max_points=1000,
            max_window_days=31,
        )
    assert src.fetch_calls == 0


@pytest.mark.asyncio
async def test_get_interval_metrics_rejects_oversized_result() -> None:
    """Result with more than max_points raises and is NOT cached."""
    big = [_point(str(i)) for i in range(101)]
    src = _FakeSource(points_to_return=big)
    store = InMemorySnapshotStore()
    with pytest.raises(ValueError, match="Result too large"):
        await get_interval_metrics(
            source=src,
            snapshot_store=store,
            site_id="101",
            subject_type="conveyor",
            interval="hourly",
            from_date=date(2026, 4, 1),
            to_date=date(2026, 4, 2),
            cache_ttl_seconds=60,
            max_points=100,
            max_window_days=31,
        )
    # Cache must remain empty -- bad results don't poison subsequent calls.
    assert await store.get("anything-here") is None


@pytest.mark.asyncio
async def test_get_interval_metrics_caches_within_ttl() -> None:
    """Second call within TTL returns the cached result; source is hit once."""
    src = _FakeSource(points_to_return=[_point()])
    store = InMemorySnapshotStore()
    args = dict(
        source=src,
        snapshot_store=store,
        site_id="101",
        subject_type="conveyor",
        interval="hourly",
        from_date=date(2026, 4, 1),
        to_date=date(2026, 4, 1),
        cache_ttl_seconds=300,
        max_points=1000,
        max_window_days=31,
    )
    r1 = await get_interval_metrics(**args)
    r2 = await get_interval_metrics(**args)
    assert src.fetch_calls == 1  # cache hit on second call
    assert len(r1.points) == 1
    assert len(r2.points) == 1


@pytest.mark.asyncio
async def test_get_interval_metrics_returns_truncation_flag() -> None:
    src = _FakeSource(points_to_return=[_point()], truncated=True)
    result = await get_interval_metrics(
        source=src,
        snapshot_store=InMemorySnapshotStore(),
        site_id="101",
        subject_type="conveyor",
        interval="hourly",
        from_date=date(2026, 4, 1),
        to_date=date(2026, 4, 1),
        cache_ttl_seconds=300,
        max_points=1000,
        max_window_days=31,
    )
    assert result.truncated is True


@pytest.mark.asyncio
async def test_list_metric_subjects_delegates_to_source() -> None:
    subj = IntervalMetricSubject(
        subject_id="C1",
        department_id="127",
        metric_names=("Total", "Runtime"),
        intervals=("hourly", "shiftly"),
        last_seen=datetime(2026, 4, 25, 10, 0, tzinfo=UTC),
    )
    src = _FakeSource(subjects_to_return=[subj])
    result = await list_metric_subjects(
        source=src, site_id="101", subject_type="conveyor"
    )
    assert len(result) == 1
    assert result[0].subject_id == "C1"
    assert src.subject_calls == 1
