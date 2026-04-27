"""Route-layer tests for /api/metrics/*.

Uses TestClient + dependency_overrides + a small fake source so we
exercise the full request lifecycle (validation, route handlers,
response shape) without SQL or HTTP.

The conftest's ``client`` fixture overrides the production-report
source. We add the metrics-source override and snapshot-store on
top in this file so the existing fixture isn't disturbed.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from app.api.dependencies import (
    get_interval_metric_source,
    get_production_report_source,
)
from app.core.snapshot import InMemorySnapshotStore
from app.integrations.metrics.base import (
    FetchPointsResult,
    IntervalMetricPoint,
    IntervalMetricSubject,
)
from app.integrations.production_report.csv_source import CsvProductionReportSource
from app.main import app


class _FakeMetricsSource:
    name = "fake:metrics"

    def __init__(self, *, points=None, truncated=False, subjects=None):
        self._points = points or []
        self._truncated = truncated
        self._subjects = subjects or []

    async def ping(self):
        raise NotImplementedError

    async def fetch_points(self, **_kwargs):
        return FetchPointsResult(points=list(self._points), truncated=self._truncated)

    async def list_subjects(self, **_kwargs):
        return list(self._subjects)


@pytest.fixture
def metrics_client(sample_csv_path) -> Iterator[TestClient]:
    """TestClient with both production-report (CSV) and metrics (fake)
    sources wired. Each test sets ``app.state.fake_metrics_source`` /
    ``app.state.snapshot_store`` and the override pulls them out."""

    def metrics_override(request: Request):
        # Annotated request: Request so FastAPI's DI injects the
        # Request object instead of treating `request` as a missing
        # query param. request.app.state holds the per-test fake.
        return request.app.state.fake_metrics_source

    app.dependency_overrides[get_production_report_source] = (
        lambda: CsvProductionReportSource(sample_csv_path)
    )
    app.dependency_overrides[get_interval_metric_source] = metrics_override

    with TestClient(app) as c:
        # Ensure a fresh SnapshotStore per test session.
        app.state.snapshot_store = InMemorySnapshotStore()
        yield c

    app.dependency_overrides.clear()


def _attach_source(client, source):
    """Stash the fake source on app.state so the override returns it."""
    client.app.state.fake_metrics_source = source


def test_subjects_endpoint_returns_inventory(metrics_client) -> None:
    src = _FakeMetricsSource(
        subjects=[
            IntervalMetricSubject(
                subject_id="C1",
                department_id="127",
                metric_names=("Total", "Runtime"),
                intervals=("hourly", "shiftly"),
                last_seen=datetime(2026, 4, 25, 10, 0, tzinfo=UTC),
            )
        ]
    )
    _attach_source(metrics_client, src)
    resp = metrics_client.get(
        "/api/metrics/conveyor/subjects",
        params={"site_id": "101", "department_id": "127"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["subjects"][0]["subject_id"] == "C1"
    assert body["subjects"][0]["metric_names"] == ["Total", "Runtime"]
    assert body["subject_type"] == "conveyor"
    assert body["site_id"] == "101"
    assert body["department_id"] == "127"


def test_history_happy_path(metrics_client) -> None:
    src = _FakeMetricsSource(
        points=[
            IntervalMetricPoint(
                subject_type="conveyor",
                subject_id="C4",
                metric="Total",
                interval="hourly",
                bucket_start=datetime(2026, 4, 1, 12, 0, tzinfo=UTC),
                bucket_end=datetime(2026, 4, 1, 13, 0, tzinfo=UTC),
                value=42.5,
                quality_code=192,
            )
        ]
    )
    _attach_source(metrics_client, src)
    resp = metrics_client.get(
        "/api/metrics/conveyor/hourly",
        params={
            "site_id": "101",
            "from_date": "2026-04-01",
            "to_date": "2026-04-02",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["interval"] == "hourly"
    assert body["count"] == 1
    assert body["entries"][0]["value"] == 42.5
    assert body["entries"][0]["subject_id"] == "C4"
    assert body["entries"][0]["quality_code"] == 192
    assert body["truncated"] is False


def test_history_rejects_unknown_interval(metrics_client) -> None:
    """Path-param Literal validation: 'daily' isn't accepted today."""
    _attach_source(metrics_client, _FakeMetricsSource())
    resp = metrics_client.get(
        "/api/metrics/conveyor/daily",
        params={
            "site_id": "101",
            "from_date": "2026-04-01",
            "to_date": "2026-04-02",
        },
    )
    assert resp.status_code == 422


def test_history_rejects_inverted_window(metrics_client) -> None:
    _attach_source(metrics_client, _FakeMetricsSource())
    resp = metrics_client.get(
        "/api/metrics/conveyor/hourly",
        params={
            "site_id": "101",
            "from_date": "2026-04-10",
            "to_date": "2026-04-01",
        },
    )
    assert resp.status_code == 422
    assert "from_date" in resp.json()["detail"].lower()


def test_history_rejects_missing_site_id(metrics_client) -> None:
    _attach_source(metrics_client, _FakeMetricsSource())
    resp = metrics_client.get(
        "/api/metrics/conveyor/hourly",
        params={"from_date": "2026-04-01", "to_date": "2026-04-02"},
    )
    assert resp.status_code == 422


def test_history_truncation_flag_forwarded(metrics_client) -> None:
    src = _FakeMetricsSource(
        points=[
            IntervalMetricPoint(
                subject_type="conveyor",
                subject_id="C1",
                metric="Total",
                interval="hourly",
                bucket_start=datetime(2026, 4, 1, 0, 0, tzinfo=UTC),
                bucket_end=datetime(2026, 4, 1, 1, 0, tzinfo=UTC),
                value=1.0,
            )
        ],
        truncated=True,
    )
    _attach_source(metrics_client, src)
    resp = metrics_client.get(
        "/api/metrics/conveyor/hourly",
        params={
            "site_id": "101",
            "from_date": "2026-04-01",
            "to_date": "2026-04-02",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["truncated"] is True
