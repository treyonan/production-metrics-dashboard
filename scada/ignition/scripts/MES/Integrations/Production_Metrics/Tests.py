"""
PMD API smoke tests.

Place in the same Project Library package as API.py
(MES.Integrations.Production_Metrics.Tests). Run from Script Console:

    MES.Integrations.Production_Metrics.Tests.run_all_tests()

Each test prints PASS / FAIL with a short reason; the runner returns a
summary dict with counts so callers can branch on success.

The runner exercises:
  * Health / catalog: /api/health, /api/__ping, /api/sites
  * Production reports: /latest, /range, /latest-date,
    /rollup/{monthly|yearly}, /circuit-rollup/{monthly}
  * Interval metrics: /metrics/{subject_type}/subjects,
    /metrics/{subject_type}/{interval}
  * Dataset wrappers (Perspective Table-friendly variants)
  * Negative cases: bad bucket / subject_type / interval -> ValueError

Edit the SITE_ID / SUBJECT_ID / INTERVAL constants below if your test
setup differs from the Phase 15 verified data (Big_Canyon site 101,
Secondary workcenter, shiftly).
"""

import system
from datetime import date, timedelta

# Ignition Project Library import. Adjust the package path if the
# project library lives elsewhere.
from MES.Integrations.Production_Metrics import API as PMD


# ---- Configuration -- edit if your test setup differs ----

SITE_ID = 101
SUBJECT_ID = "Secondary"   # Phase 15 verified workcenter subject
INTERVAL = "shiftly"       # the only interval loaded today
DEPARTMENT_ID = 127        # Phase 12-style department id


# ---- Internal helpers ----

def _date(d):
    """date -> YYYY-MM-DD string."""
    return d.isoformat()


def _last_30_days():
    today = date.today()
    return _date(today - timedelta(days=30)), _date(today)


def _last_12_months():
    """Return (first_of_12-months-ago, last_of_current-month) as ISO
    YYYY-MM-DD strings. Covers exactly 12 monthly buckets when the
    range is bucketed monthly, with no partial edges."""
    today = date.today()
    # Start at the first of the month 11 months back -- 12 buckets total
    # including the current month.
    yr = today.year
    mo = today.month - 11
    while mo <= 0:
        mo += 12
        yr -= 1
    start = date(yr, mo, 1)
    # End-of-current-month.
    if today.month == 12:
        end = date(today.year, 12, 31)
    else:
        end = date(today.year, today.month + 1, 1) - timedelta(days=1)
    return _date(start), _date(end)


def _last_3_years():
    """Return (Jan 1 of (year - 2), Dec 31 of current year). 3 yearly
    buckets, all complete."""
    today = date.today()
    return _date(date(today.year - 2, 1, 1)), _date(date(today.year, 12, 31))


def _result(name, passed, msg=""):
    return {"name": name, "passed": passed, "msg": msg}


def _try(name, fn):
    """Run a test function; capture exceptions as failures. Each test
    function returns a short detail string on success and raises on
    failure (assert / explicit raise)."""
    try:
        msg = fn()
        return _result(name, True, msg or "")
    except Exception as exc:
        return _result(name, False, "%s: %s" % (type(exc).__name__, exc))


# ---- Endpoint tests ----

def test_health():
    payload = PMD.get_health()
    assert isinstance(payload, dict), "expected dict envelope"
    return "%d keys" % len(payload)


def test_ping():
    payload = PMD.get_ping()
    assert isinstance(payload, dict)
    assert "build_tag" in payload, "missing build_tag"
    return "build_tag=%s" % payload.get("build_tag")


def test_sites():
    payload = PMD.get_sites()
    sites = payload.get("sites", [])
    assert isinstance(sites, list)
    return "%d sites" % len(sites)


def test_production_report_latest():
    payload = PMD.get_production_report_latest(SITE_ID)
    entries = payload.get("entries", [])
    return "%d entries" % len(entries)


def test_production_report_range():
    fr, to = _last_30_days()
    payload = PMD.get_production_report_range(SITE_ID, fr, to)
    entries = payload.get("entries", [])
    return "%d entries from %s to %s" % (len(entries), fr, to)


def test_production_report_latest_date():
    payload = PMD.get_production_report_latest_date(SITE_ID)
    return "latest_date=%s" % payload.get("latest_date")


def test_rollup_monthly():
    fr, to = _last_12_months()
    payload = PMD.get_rollup("monthly", SITE_ID, fr, to)
    assert payload.get("bucket") == "monthly", "envelope bucket mismatch"
    return "%d rollups (%s -> %s)" % (len(payload.get("rollups", [])), fr, to)


def test_rollup_yearly():
    fr, to = _last_3_years()
    payload = PMD.get_rollup("yearly", SITE_ID, fr, to)
    assert payload.get("bucket") == "yearly", "envelope bucket mismatch"
    return "%d rollups (%s -> %s)" % (len(payload.get("rollups", [])), fr, to)


def test_circuit_rollup_monthly():
    fr, to = _last_12_months()
    payload = PMD.get_circuit_rollup("monthly", SITE_ID, fr, to)
    return "%d departments" % len(payload.get("departments", []))


def test_metric_subjects():
    payload = PMD.get_metric_subjects("workcenter", SITE_ID)
    return "%d subjects" % len(payload.get("subjects", []))


def test_metric_history():
    fr, to = _last_30_days()
    payload = PMD.get_metric_history(
        "workcenter", INTERVAL, SITE_ID, fr, to,
        subject_id=SUBJECT_ID,
    )
    return "%d entries (truncated=%s)" % (
        len(payload.get("entries", [])), payload.get("truncated"),
    )


# ---- Dataset wrapper tests ----
#
# These confirm the wrappers produce a real Ignition Dataset (Java
# class) with the expected column set. Useful for Perspective Table
# bindings -- if these pass, the bindings will populate.

def test_dataset_production_report_latest():
    ds = PMD.production_report_latest_dataset(SITE_ID)
    return "Dataset: %d rows, %d cols" % (ds.getRowCount(), ds.getColumnCount())


def test_dataset_rollup_monthly():
    fr, to = _last_12_months()
    ds = PMD.rollup_dataset("monthly", SITE_ID, fr, to)
    cols = list(ds.getColumnNames())
    assert "bucket_label" in cols, "rollup_dataset missing bucket_label column"
    return "Dataset: %d rows, cols=%s" % (ds.getRowCount(), cols)


def test_dataset_rollup_yearly():
    fr, to = _last_3_years()
    ds = PMD.rollup_dataset("yearly", SITE_ID, fr, to)
    return "Dataset: %d rows" % ds.getRowCount()


def test_dataset_metric_subjects():
    ds = PMD.metric_subjects_dataset("workcenter", SITE_ID)
    return "Dataset: %d rows" % ds.getRowCount()


def test_dataset_metric_history():
    fr, to = _last_30_days()
    ds = PMD.metric_history_dataset(
        "workcenter", INTERVAL, SITE_ID, fr, to,
        subject_id=SUBJECT_ID,
    )
    return "Dataset: %d rows" % ds.getRowCount()


# ---- Negative tests (validation guards) ----

def test_invalid_bucket_rejected():
    try:
        PMD.get_rollup("weekly", SITE_ID, "2026-01-01", "2026-04-30")
    except ValueError:
        return "got expected ValueError"
    raise AssertionError("expected ValueError not raised")


def test_invalid_subject_type_rejected():
    try:
        PMD.get_metric_subjects("foo", SITE_ID)
    except ValueError:
        return "got expected ValueError"
    raise AssertionError("expected ValueError not raised")


def test_invalid_interval_rejected():
    try:
        PMD.get_metric_history(
            "workcenter", "daily", SITE_ID, "2026-01-01", "2026-04-30",
        )
    except ValueError:
        return "got expected ValueError"
    raise AssertionError("expected ValueError not raised")


# ---- Main runner ----

def run_all_tests():
    """Run every PMD API smoke test. No parameters; safe to call from
    Script Console:

        MES.Integrations.Production_Metrics.Tests.run_all_tests()

    Prints PASS/FAIL per test plus a final summary. Returns a dict with
    {passed, failed, results} for callers that want to branch on the
    outcome.
    """
    suite = [
        # Health / catalog
        ("health",                          test_health),
        ("ping",                            test_ping),
        ("sites",                           test_sites),
        # Production reports
        ("production_report.latest",        test_production_report_latest),
        ("production_report.range",         test_production_report_range),
        ("production_report.latest_date",   test_production_report_latest_date),
        ("rollup.monthly",                  test_rollup_monthly),
        ("rollup.yearly",                   test_rollup_yearly),
        ("circuit_rollup.monthly",          test_circuit_rollup_monthly),
        # Interval metrics
        ("metrics.subjects",                test_metric_subjects),
        ("metrics.history",                 test_metric_history),
        # Datasets
        ("dataset.production_report_latest",test_dataset_production_report_latest),
        ("dataset.rollup_monthly",          test_dataset_rollup_monthly),
        ("dataset.rollup_yearly",           test_dataset_rollup_yearly),
        ("dataset.metric_subjects",         test_dataset_metric_subjects),
        ("dataset.metric_history",          test_dataset_metric_history),
        # Negative cases
        ("invalid.bucket",                  test_invalid_bucket_rejected),
        ("invalid.subject_type",            test_invalid_subject_type_rejected),
        ("invalid.interval",                test_invalid_interval_rejected),
    ]

    print "=" * 78
    print "PMD API smoke tests"
    print "  BASE_URL   =", PMD.BASE_URL
    print "  SITE_ID    =", SITE_ID
    print "  SUBJECT_ID =", SUBJECT_ID
    print "  INTERVAL   =", INTERVAL
    print "=" * 78

    results = []
    for name, fn in suite:
        r = _try(name, fn)
        results.append(r)
        flag = "PASS" if r["passed"] else "FAIL"
        detail = ("  -- " + r["msg"]) if r["msg"] else ""
        print "  [%s] %-36s%s" % (flag, name, detail)

    passed = sum(1 for r in results if r["passed"])
    failed = sum(1 for r in results if not r["passed"])

    print "-" * 78
    print "Summary: %d passed, %d failed (of %d total)" % (passed, failed, len(results))
    if failed:
        print
        print "Failures:"
        for r in results:
            if not r["passed"]:
                print "  -", r["name"], "--", r["msg"]

    # Mirror the summary to the gateway log so a failure that the
    # console scrolled past still leaves a trace.
    logger = system.util.getLogger("PMD.Tests")
    logger.info(
        "PMD API smoke tests: %d passed, %d failed" % (passed, failed)
    )
    if failed:
        for r in results:
            if not r["passed"]:
                logger.warn("FAIL %s -- %s" % (r["name"], r["msg"]))

    return {"passed": passed, "failed": failed, "results": results}
