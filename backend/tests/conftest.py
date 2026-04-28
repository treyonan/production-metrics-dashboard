"""Shared pytest fixtures.

``client`` gives you a FastAPI ``TestClient`` wired to a deterministic,
file-backed test source. The production code path is SQL-only as of
Phase 13 (2026-04-28); the CSV reader survives under
``tests/_fixtures/csv_source.py`` purely as test infrastructure so the
~30 API tests can run without a SQL Server connection.

The DI override is per-test so anything on ``app.state`` from the
normal startup doesn't leak between tests.
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


@pytest.fixture
def client(sample_csv_path: Path) -> Iterator[TestClient]:
    """TestClient with the production-report DI bound to the test fixture.

    The fixture is a CSV reader (test-only, lives under tests/_fixtures/)
    that returns deterministic rows. Production never sees CSV.
    """
    app.dependency_overrides[get_production_report_source] = lambda: CsvProductionReportSource(
        sample_csv_path
    )
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
