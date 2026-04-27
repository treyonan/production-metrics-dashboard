"""Tests for /api/production-report/{latest,range,latest-date}.

Phase 7 (2026-04-24): ``/history?days=N`` was replaced by
``/range?from_date&to_date`` plus ``/latest-date?site_id=X``. The
history tests in this file were ported to the new endpoints; the
``/latest`` tests above are unchanged since that endpoint's contract
didn't move.
"""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

# ---- /latest --------------------------------------------------------------


def test_latest_returns_one_entry_per_workcenter_across_sites(client: TestClient) -> None:
    resp = client.get("/api/production-report/latest")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 4
    assert len(body["entries"]) == 4

    pairs = {(e["site_id"], e["department_id"]) for e in body["entries"]}
    assert pairs == {
        ("101", "127"),
        ("101", "130"),
        ("102", "127"),
        ("102", "130"),
    }


def test_latest_filters_by_site_id(client: TestClient) -> None:
    resp = client.get("/api/production-report/latest", params={"site_id": "101"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    assert {e["site_id"] for e in body["entries"]} == {"101"}
    assert {e["department_id"] for e in body["entries"]} == {"127", "130"}


def test_latest_unknown_site_returns_empty(client: TestClient) -> None:
    resp = client.get("/api/production-report/latest", params={"site_id": "999"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 0
    assert body["entries"] == []


def test_latest_entries_sorted_newest_first(client: TestClient) -> None:
    resp = client.get("/api/production-report/latest")
    body = resp.json()
    dates = [e["prod_date"] for e in body["entries"]]
    assert dates == sorted(dates, reverse=True)


def test_latest_payload_is_passthrough_dict(client: TestClient) -> None:
    resp = client.get("/api/production-report/latest")
    body = resp.json()
    for entry in body["entries"]:
        assert isinstance(entry["payload"], dict)
        assert "Metrics" in entry["payload"]
        metrics = entry["payload"]["Metrics"]
        assert "Workcenter" in metrics


def test_latest_includes_generated_at_and_count(client: TestClient) -> None:
    resp = client.get("/api/production-report/latest")
    body = resp.json()
    assert "generated_at" in body
    assert body["count"] == len(body["entries"])


# ---- /range ---------------------------------------------------------------
#
# These cover the same ground the old /history tests did plus the
# new date-window validations (from > to, oversized, missing, malformed).


# A window wide enough to cover every row in the sample CSV. Used by
# tests that want "give me everything for this site" without taking a
# dependency on the sample's exact dates -- which move as the fixture
# is refreshed.
_WIDE_FROM = "2020-01-01"
_WIDE_TO = "2029-12-31"
# Width = 3652 days, which is over the 400-day max. Both tests that
# reject oversized windows and tests that use a fully-populated window
# need this. Tests that want a fully-populated window WITHIN the max
# use _FULL_COVERAGE_* below instead.

# A slightly-under-max window that still covers any plausible sample
# date. 399 days from the earliest expected sample date.
_FULL_COVERAGE_FROM = "2025-05-01"
_FULL_COVERAGE_TO = "2026-06-04"  # 400 days inclusive


def test_range_returns_envelope_with_from_to_and_site_id(client: TestClient) -> None:
    resp = client.get(
        "/api/production-report/range",
        params={
            "from_date": _FULL_COVERAGE_FROM,
            "to_date": _FULL_COVERAGE_TO,
            "site_id": "101",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["from_date"] == _FULL_COVERAGE_FROM
    assert body["to_date"] == _FULL_COVERAGE_TO
    assert body["site_id"] == "101"
    assert "generated_at" in body
    assert body["count"] == len(body["entries"])
    # Envelope must also carry the Phase 5 conveyor_totals field.
    assert "conveyor_totals" in body
    assert isinstance(body["conveyor_totals"], dict)


def test_range_full_coverage_window_returns_all_site_rows(client: TestClient) -> None:
    # Sample has 33 rows for (101, 127) + 29 rows for (101, 130) = 62
    # real + 62 synthetic for site 102. A 400-day window spanning the
    # sample must return all 62 rows for site 101.
    resp = client.get(
        "/api/production-report/range",
        params={
            "from_date": _FULL_COVERAGE_FROM,
            "to_date": _FULL_COVERAGE_TO,
            "site_id": "101",
        },
    )
    body = resp.json()
    assert body["count"] >= 62
    assert {e["site_id"] for e in body["entries"]} == {"101"}


def test_range_entries_sorted_newest_first(client: TestClient) -> None:
    resp = client.get(
        "/api/production-report/range",
        params={
            "from_date": _FULL_COVERAGE_FROM,
            "to_date": _FULL_COVERAGE_TO,
            "site_id": "101",
        },
    )
    body = resp.json()
    keys = [(e["prod_date"], e["dtm"]) for e in body["entries"]]
    assert keys == sorted(keys, reverse=True)


def test_range_rejects_from_after_to(client: TestClient) -> None:
    resp = client.get(
        "/api/production-report/range",
        params={"from_date": "2026-05-01", "to_date": "2026-04-01"},
    )
    assert resp.status_code == 422
    # Body should name which bound went wrong.
    detail = resp.json().get("detail", "")
    assert "from_date" in str(detail).lower()


def test_range_rejects_missing_from_date(client: TestClient) -> None:
    resp = client.get("/api/production-report/range", params={"to_date": "2026-04-01"})
    assert resp.status_code == 422


def test_range_rejects_missing_to_date(client: TestClient) -> None:
    resp = client.get("/api/production-report/range", params={"from_date": "2026-04-01"})
    assert resp.status_code == 422


def test_range_rejects_oversized_window(client: TestClient) -> None:
    # 2020-01-01 -> 2029-12-31 is ~3652 days, far above the 400-day cap.
    resp = client.get(
        "/api/production-report/range",
        params={"from_date": _WIDE_FROM, "to_date": _WIDE_TO},
    )
    assert resp.status_code == 422
    detail = resp.json().get("detail", "")
    assert "400" in str(detail) or "Max" in str(detail) or "too large" in str(detail).lower()


def test_range_rejects_non_iso_date(client: TestClient) -> None:
    resp = client.get(
        "/api/production-report/range",
        params={"from_date": "not-a-date", "to_date": "2026-04-01"},
    )
    assert resp.status_code == 422


def test_range_inclusive_single_day_window(client: TestClient) -> None:
    # Pick any date present in the sample (discovered via /latest) and
    # ask for that day only. All returned rows must have that exact
    # prod_date.
    latest_date_body = client.get(
        "/api/production-report/latest-date", params={"site_id": "101"}
    ).json()
    pick = latest_date_body["latest_date"]
    assert pick, "sample must have data for site 101"

    resp = client.get(
        "/api/production-report/range",
        params={"from_date": pick, "to_date": pick, "site_id": "101"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] >= 1
    for entry in body["entries"]:
        # prod_date is "YYYY-MM-DDTHH:MM:SS"; compare on the date portion.
        assert entry["prod_date"].startswith(pick)


def test_range_empty_window_returns_empty_envelope(client: TestClient) -> None:
    # A date the sample certainly doesn't cover.
    resp = client.get(
        "/api/production-report/range",
        params={"from_date": "1999-01-01", "to_date": "1999-01-01"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 0
    assert body["entries"] == []
    assert body["conveyor_totals"] == {}


def test_range_unknown_site_returns_empty(client: TestClient) -> None:
    resp = client.get(
        "/api/production-report/range",
        params={
            "from_date": _FULL_COVERAGE_FROM,
            "to_date": _FULL_COVERAGE_TO,
            "site_id": "999",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 0
    assert body["entries"] == []


def test_range_400_day_window_accepted(client: TestClient) -> None:
    # Boundary test: exactly 400 days inclusive must be accepted.
    resp = client.get(
        "/api/production-report/range",
        params={"from_date": _FULL_COVERAGE_FROM, "to_date": _FULL_COVERAGE_TO},
    )
    assert resp.status_code == 200
    # Sanity-check: the window is exactly _MAX_RANGE_DAYS wide.
    f = date.fromisoformat(_FULL_COVERAGE_FROM)
    t = date.fromisoformat(_FULL_COVERAGE_TO)
    assert (t - f).days + 1 == 400


# ---- /latest-date ---------------------------------------------------------


def test_latest_date_returns_newest_prod_date_for_site(client: TestClient) -> None:
    resp = client.get("/api/production-report/latest-date", params={"site_id": "101"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["site_id"] == "101"
    assert body["latest_date"] is not None
    # ISO-8601 date, parseable.
    parsed = date.fromisoformat(body["latest_date"])
    # Cross-check: max prod_date from /range full-coverage must match.
    range_body = client.get(
        "/api/production-report/range",
        params={
            "from_date": _FULL_COVERAGE_FROM,
            "to_date": _FULL_COVERAGE_TO,
            "site_id": "101",
        },
    ).json()
    assert range_body["entries"], "fixture must have rows for site 101"
    max_from_range = max(
        date.fromisoformat(e["prod_date"][:10]) for e in range_body["entries"]
    )
    assert parsed == max_from_range


def test_latest_date_null_for_unknown_site(client: TestClient) -> None:
    resp = client.get("/api/production-report/latest-date", params={"site_id": "999"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["site_id"] == "999"
    assert body["latest_date"] is None


def test_latest_date_requires_site_id(client: TestClient) -> None:
    resp = client.get("/api/production-report/latest-date")
    assert resp.status_code == 422


# ---- /history removed ------------------------------------------------------
#
# The previous /history?days=N endpoint was removed in Phase 7 (see
# tasks/decisions/002-absolute-time-filter.md). A regression check
# guards against it being silently reintroduced.


def test_history_endpoint_removed(client: TestClient) -> None:
    resp = client.get("/api/production-report/history", params={"days": 7})
    assert resp.status_code == 404



# ---- /monthly-rollup --------------------------------------------------


def test_monthly_rollup_returns_envelope_shape(client) -> None:
    """Happy-path: returns a populated envelope for the sample window."""
    resp = client.get(
        "/api/production-report/monthly-rollup",
        params={
            "site_id": "101",
            "from_month": "2025-05",
            "to_month": "2026-06",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["site_id"] == "101"
    assert body["from_month"] == "2025-05"
    assert body["to_month"] == "2026-06"
    assert "generated_at" in body
    assert isinstance(body["rollups"], list)
    # Sample data has multiple departments under site 101 across
    # multiple months -- expect at least one rollup.
    assert len(body["rollups"]) > 0


def test_monthly_rollup_rollup_entry_fields_present(client) -> None:
    resp = client.get(
        "/api/production-report/monthly-rollup",
        params={
            "site_id": "101",
            "from_month": "2025-05",
            "to_month": "2026-06",
        },
    )
    body = resp.json()
    sample = body["rollups"][0]
    expected = {
        "department_id", "month", "total_tons",
        "total_runtime_minutes", "tph", "report_count",
    }
    assert expected.issubset(sample.keys())
    # Month always YYYY-MM.
    import re as _re
    assert _re.match(r"^\d{4}-\d{2}$", sample["month"])


def test_monthly_rollup_filter_by_department(client) -> None:
    resp = client.get(
        "/api/production-report/monthly-rollup",
        params={
            "site_id": "101",
            "from_month": "2025-05",
            "to_month": "2026-06",
            "department_id": "127",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["department_id"] == "127"
    assert all(r["department_id"] == "127" for r in body["rollups"])


def test_monthly_rollup_rejects_inverted_window(client) -> None:
    resp = client.get(
        "/api/production-report/monthly-rollup",
        params={
            "site_id": "101",
            "from_month": "2026-06",
            "to_month": "2026-01",
        },
    )
    assert resp.status_code == 422
    assert "from_month" in resp.json()["detail"].lower()


def test_monthly_rollup_rejects_bad_month_format(client) -> None:
    resp = client.get(
        "/api/production-report/monthly-rollup",
        params={
            "site_id": "101",
            "from_month": "April-2026",
            "to_month": "2026-04",
        },
    )
    assert resp.status_code == 422


def test_monthly_rollup_rejects_oversized_window(client) -> None:
    resp = client.get(
        "/api/production-report/monthly-rollup",
        params={
            "site_id": "101",
            "from_month": "2020-01",
            "to_month": "2026-12",
        },
    )
    assert resp.status_code == 422


def test_monthly_rollup_unknown_site_returns_empty(client) -> None:
    resp = client.get(
        "/api/production-report/monthly-rollup",
        params={
            "site_id": "999",
            "from_month": "2026-01",
            "to_month": "2026-04",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["rollups"] == []


def test_monthly_rollup_tph_null_when_runtime_zero(client) -> None:
    """In a window where the sample has zero runtime, tph must be null
    (not Inf, not NaN, not divide-by-zero error). The committed CSV
    sample has at least one C3 row with Runtime=0.0."""
    resp = client.get(
        "/api/production-report/monthly-rollup",
        params={
            "site_id": "101",
            "from_month": "2025-05",
            "to_month": "2026-06",
        },
    )
    body = resp.json()
    # At least one rollup with runtime > 0 should have a numeric tph;
    # any rollup with runtime == 0 should have tph == None.
    for r in body["rollups"]:
        if r["total_runtime_minutes"] == 0:
            assert r["tph"] is None
        else:
            assert isinstance(r["tph"], (int, float))
