"""Shared pytest fixtures.

``client`` gives you a FastAPI ``TestClient`` wired to a deterministic,
file-backed test source. The production code path is SQL-only as of
Phase 13 (2026-04-28); the CSV reader survives under
``tests/_fixtures/csv_source.py`` purely as test infrastructure so the
api tests can run without a SQL Server connection.

Performance (2026-06-08): the app lifespan does real startup I/O -- it
opens an aioodbc SQL pool and runs the chart-label query. Running that
per-test made the api suite crawl (one SQL connect + query for every
test). The lifespan is now entered ONCE per session via
``_app_lifespan``; the function-scoped ``client`` fixture layers the
per-test DI override + state reset on top and is cheap.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_production_report_source
from app.main import app
from tests._fixtures.csv_source import CsvProductionReportSource

_REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_CSV_PATH = _REPO_ROOT / "context" / "sample-data" / "production-report" / "sample.csv"


@pytest.fixture
def sample_csv_path() -> Path:
    assert SAMPLE_CSV_PATH.exists(), (
        f"Missing test fixture: {SAMPLE_CSV_PATH} -- tests depend on the "
        "committed sample TSV under context/sample-data/."
    )
    return SAMPLE_CSV_PATH


@pytest.fixture(scope="session")
def _app_lifespan() -> Iterator[TestClient]:
    """Enter the app lifespan ONCE for the whole test session.

    Startup opens a real SQL pool and loads chart labels; doing that
    per-test was the dominant cost across the api suite. Entering the
    TestClient context here runs startup a single time and keeps it warm
    for every test. Per-test isolation (DI overrides, timebase state)
    lives in the function-scoped ``client`` fixture below.
    """
    with TestClient(app) as c:
        yield c


@pytest.fixture
def client(_app_lifespan: TestClient, sample_csv_path: Path) -> Iterator[TestClient]:
    """TestClient with the production-report DI bound to the test fixture.

    Reuses the session-scoped lifespan (no per-test startup I/O). The
    fixture is a CSV reader (test-only, lives under tests/_fixtures/)
    that returns deterministic rows. Production never sees CSV.

    Timebase state is nulled on every test -- cheap, no I/O -- so
    /api/health doesn't try to ping a (dev-unreachable) historian, and so
    a timebase test that repopulated app.state in between doesn't leak
    into the next test. Tests that exercise Timebase directly use the
    dedicated ``wire_timebase`` fixture in ``tests/api/test_timebase.py``.
    """
    app.dependency_overrides[get_production_report_source] = lambda: CsvProductionReportSource(
        sample_csv_path
    )
    app.state.timebase_clients = None
    app.state.timebase_catalog = None
    yield _app_lifespan
    app.dependency_overrides.clear()
