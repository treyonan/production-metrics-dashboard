"""Unit tests for SqlIntervalMetricSource.

Same fake-aioodbc pattern as the production-report SQL tests, plus
a fake FlowClient that records calls without HTTP. No real DB, no
real Flow API.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

import pytest

from app.integrations.external.flow_client import FlowFetchResult
from app.integrations.metrics.sql_source import (
    SqlIntervalMetricSource,
    _parse_flow_timestamp,
)


# ---- aioodbc-shaped fakes (same as production-report tests) ----


class _AsyncCtx:
    def __init__(self, value):
        self._value = value

    async def __aenter__(self):
        return self._value

    async def __aexit__(self, *exc):
        return False


class FakeCursor:
    def __init__(
        self,
        rows_per_query: list[list[tuple]] | None = None,
        *,
        fail_with: Exception | None = None,
    ) -> None:
        # Each call to execute consumes the next list of rows from the queue.
        self._queue = list(rows_per_query or [])
        self._current_rows: list[tuple] = []
        self._fail_with = fail_with
        self.executed: list[tuple[str, tuple]] = []

    async def execute(self, sql, params=()):
        self.executed.append((sql, params))
        if self._fail_with is not None:
            raise self._fail_with
        self._current_rows = self._queue.pop(0) if self._queue else []

    async def fetchone(self):
        return self._current_rows[0] if self._current_rows else None

    async def fetchall(self):
        return list(self._current_rows)


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return _AsyncCtx(self._cursor)


class FakePool:
    def __init__(self, cursor):
        self._cursor = cursor

    def acquire(self):
        return _AsyncCtx(FakeConnection(self._cursor))


# ---- Fake FlowClient ----


@dataclass
class _FlowCall:
    url_template: str
    start: datetime
    end: datetime


class FakeFlowClient:
    """Records calls; returns canned responses keyed by URL substring."""

    def __init__(
        self,
        *,
        responses: dict[str, FlowFetchResult] | None = None,
        default: FlowFetchResult | None = None,
    ) -> None:
        self.calls: list[_FlowCall] = []
        self._responses = responses or {}
        self._default = default or FlowFetchResult(raw_data=[], hit_limit=False)

    async def fetch_history(self, url_template, *, start, end):
        self.calls.append(_FlowCall(url_template, start, end))
        for substring, resp in self._responses.items():
            if substring in url_template:
                return resp
        return self._default


# ---- Helpers ----


def _tag_row(
    *, asset="C4", metric="Total", interval="shiftly",
    site_id=101, dept=127, url_marker="default", subject_type="conveyor",
    dtm=None,
) -> tuple:
    """Build a row tuple matching select_tags.sql's column order:
    site_id, asset, metric_name, interval, history_url, department_id,
    subject_type, DTM."""
    if dtm is None:
        dtm = datetime(2026, 4, 25, 12, 0, tzinfo=UTC)
    return (
        site_id,
        asset,
        metric,
        interval,
        f"http://flow/api?id=1644&start=[PeriodStart]&end=[PeriodEnd]&limit=1000&marker={url_marker}",
        dept,
        subject_type,
        dtm,
    )


# ---- Tests ----


def test_parse_flow_timestamp_handles_millisecond_z() -> None:
    dt = _parse_flow_timestamp("2026-04-01T12:30:45.018Z")
    assert dt.year == 2026 and dt.month == 4 and dt.day == 1
    assert dt.tzinfo is not None  # UTC


def test_parse_flow_timestamp_handles_dotnet_seven_digit_fraction() -> None:
    """Flow sometimes emits .NET DateTimeOffset 7-digit fractional seconds."""
    dt = _parse_flow_timestamp("2026-04-03T04:15:14.2051492Z")
    assert dt.microsecond == 205149  # trimmed to 6 digits


@pytest.mark.asyncio
async def test_ping_ok_when_select_one_returns_one() -> None:
    pool = FakePool(FakeCursor(rows_per_query=[[(1,)]]))
    src = SqlIntervalMetricSource(pool=pool, flow_client=FakeFlowClient())
    status = await src.ping()
    assert status.ok is True
    assert "returned 1" in status.detail


@pytest.mark.asyncio
async def test_fetch_points_fans_out_one_request_per_tag() -> None:
    """select_tags returns 2 rows -> 2 Flow calls -> points concatenated."""
    tag1 = _tag_row(asset="C1", url_marker="C1")
    tag2 = _tag_row(asset="C4", url_marker="C4")
    pool = FakePool(FakeCursor(rows_per_query=[[tag1, tag2]]))

    bucket1 = {
        "start": "2026-04-01T00:00:00.000Z",
        "end": "2026-04-01T08:00:00.000Z",
        "value": 100.5,
        "detail": {"quality": {"value": 192}},
    }
    bucket2 = {
        "start": "2026-04-01T08:00:00.000Z",
        "end": "2026-04-01T16:00:00.000Z",
        "value": 200.0,
        "detail": {"quality": {"value": 192}},
    }
    flow = FakeFlowClient(
        responses={
            "marker=C1": FlowFetchResult(raw_data=[bucket1], hit_limit=False),
            "marker=C4": FlowFetchResult(raw_data=[bucket2], hit_limit=False),
        }
    )
    src = SqlIntervalMetricSource(pool=pool, flow_client=flow)

    result = await src.fetch_points(
        site_id="101",
        from_date=date(2026, 4, 1),
        to_date=date(2026, 4, 1),
        subject_type="conveyor",
        interval="shiftly",
    )

    assert len(flow.calls) == 2  # one fan-out per tag
    assert {c.url_template[-2:] for c in flow.calls} == {"C1", "C4"}
    assert len(result.points) == 2
    assert result.truncated is False
    # Subject info comes from the tag row, not the bucket
    assert {p.subject_id for p in result.points} == {"C1", "C4"}
    assert all(p.metric == "Total" for p in result.points)
    assert all(p.interval == "shiftly" for p in result.points)


@pytest.mark.asyncio
async def test_fetch_points_truncated_when_any_fetch_hits_limit() -> None:
    pool = FakePool(FakeCursor(rows_per_query=[[_tag_row()]]))
    flow = FakeFlowClient(
        default=FlowFetchResult(
            raw_data=[
                {
                    "start": "2026-04-01T00:00:00.000Z",
                    "end": "2026-04-01T01:00:00.000Z",
                    "value": 1.0,
                    "detail": {"quality": {"value": 192}},
                }
            ],
            hit_limit=True,
        )
    )
    src = SqlIntervalMetricSource(pool=pool, flow_client=flow)
    result = await src.fetch_points(
        site_id="101",
        from_date=date(2026, 4, 1),
        to_date=date(2026, 4, 1),
        subject_type="conveyor",
        interval="shiftly",
    )
    assert result.truncated is True


@pytest.mark.asyncio
async def test_fetch_points_no_tags_short_circuits() -> None:
    """When no tags match the filter, no Flow calls and no points."""
    pool = FakePool(FakeCursor(rows_per_query=[[]]))  # empty rows
    flow = FakeFlowClient()
    src = SqlIntervalMetricSource(pool=pool, flow_client=flow)
    result = await src.fetch_points(
        site_id="999",
        from_date=date(2026, 4, 1),
        to_date=date(2026, 4, 1),
        subject_type="conveyor",
        interval="shiftly",
    )
    assert result.points == []
    assert result.truncated is False
    assert flow.calls == []


@pytest.mark.asyncio
async def test_list_subjects_aggregates_per_asset() -> None:
    """Multiple tag rows for the same asset collapse to one IntervalMetricSubject
    with metric_names + intervals tuples and last_seen = max(DTM)."""
    older = datetime(2026, 4, 24, 10, 0, tzinfo=UTC)
    newer = datetime(2026, 4, 25, 10, 0, tzinfo=UTC)
    rows = [
        # Aggregated row from select_subjects: (asset, dept, metric, interval, max_dtm)
        ("C1", 127, "Total", "hourly", older),
        ("C1", 127, "Total", "shiftly", newer),
        ("C1", 127, "Runtime", "hourly", older),
        ("C4", 127, "Total", "hourly", newer),
    ]
    pool = FakePool(FakeCursor(rows_per_query=[rows]))
    src = SqlIntervalMetricSource(pool=pool, flow_client=FakeFlowClient())

    subjects = await src.list_subjects(
        site_id="101", subject_type="conveyor", department_id="127"
    )
    assert len(subjects) == 2
    by_id = {s.subject_id: s for s in subjects}
    c1 = by_id["C1"]
    assert sorted(c1.metric_names) == ["Runtime", "Total"]
    assert sorted(c1.intervals) == ["hourly", "shiftly"]
    assert c1.last_seen == newer
    c4 = by_id["C4"]
    assert sorted(c4.metric_names) == ["Total"]
    assert sorted(c4.intervals) == ["hourly"]
