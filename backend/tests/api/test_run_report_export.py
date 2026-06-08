"""API tests for GET /api/production-report/run-report-export (Phase 31).

The configured-run-report SQL source is overridden with a fake (the live
SP can't run in CI); the production-report source stays the CSV fixture
from conftest, which supplies the department enumeration for site 101.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from app.api.dependencies import get_configured_run_report_source
from app.main import app


class _FakeRunReportSource:
    async def fetch_report(
        self, *, site_id: str, department_id: str, start: datetime, end: datetime
    ) -> tuple[list[str], list[list[Any]]]:
        return ["Date", "PROD_ID"], [["04/01/2026", f"PR-{department_id}"]]


@pytest.fixture
def client_with_runreport(client):
    """The conftest ``client`` plus a fake configured-run-report source.

    The conftest fixture clears all dependency overrides on teardown, so
    no explicit cleanup is needed here.
    """
    app.dependency_overrides[get_configured_run_report_source] = _FakeRunReportSource
    return client


def test_run_report_export_happy_path(client_with_runreport) -> None:
    resp = client_with_runreport.get(
        "/api/production-report/run-report-export",
        params={"site_id": "101", "from_date": "2026-04-01", "to_date": "2026-04-22"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["site_id"] == "101"
    assert body["from_date"] == "2026-04-01"
    assert body["to_date"] == "2026-04-22"
    assert "generated_at" in body
    assert isinstance(body["departments"], list)
    assert len(body["departments"]) > 0
    d0 = body["departments"][0]
    assert {"department_id", "department_name", "columns", "rows"}.issubset(d0.keys())
    assert d0["columns"] == ["Date", "PROD_ID"]
    assert d0["rows"] and d0["rows"][0][0] == "04/01/2026"


def test_run_report_export_rejects_inverted_window(client_with_runreport) -> None:
    resp = client_with_runreport.get(
        "/api/production-report/run-report-export",
        params={"site_id": "101", "from_date": "2026-04-22", "to_date": "2026-04-01"},
    )
    assert resp.status_code == 422


def test_run_report_export_rejects_oversized_window(client_with_runreport) -> None:
    resp = client_with_runreport.get(
        "/api/production-report/run-report-export",
        params={"site_id": "101", "from_date": "2024-01-01", "to_date": "2026-12-31"},
    )
    assert resp.status_code == 422


def test_run_report_export_unknown_site_returns_empty(client_with_runreport) -> None:
    resp = client_with_runreport.get(
        "/api/production-report/run-report-export",
        params={"site_id": "999", "from_date": "2026-04-01", "to_date": "2026-04-22"},
    )
    assert resp.status_code == 200
    assert resp.json()["departments"] == []
