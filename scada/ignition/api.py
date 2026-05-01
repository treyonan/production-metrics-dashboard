"""
Rich Ignition client for the production-metrics-dashboard FastAPI.

Project    : production-metrics-dashboard
Layer      : SCADA-side companion script (NOT part of the FastAPI)
Runtime    : Ignition Designer / Gateway, Jython 2.7

What this is
------------
A read-only client wrapping every endpoint the FastAPI exposes, in
a form Ignition Perspective views can call directly via property
bindings, expression scripts, or runScript().

The FastAPI is the system of record for shape; this file is just a
typed convenience over it. If a new endpoint lands in the FastAPI,
add a thin wrapper here.

Endpoints covered:

    Health / catalog
        get_health()                     -> /api/health
        get_ping()                       -> /api/__ping
        get_sites()                      -> /api/sites

    Production reports (Domain 1, curated by Flow)
        get_production_report_latest(site_id)
                                         -> /api/production-report/latest
        get_production_report_range(site_id, from_date, to_date)
                                         -> /api/production-report/range
        get_production_report_latest_date(site_id)
                                         -> /api/production-report/latest-date
        get_monthly_rollup(site_id)      -> /api/production-report/monthly-rollup
        get_circuit_monthly_rollup(site_id)
                                         -> /api/production-report/circuit-monthly-rollup

    Interval metrics (Domain 2, curated by Flow)
        get_metric_subjects(subject_type, site_id, department_id=None)
                                         -> /api/metrics/{subject_type}/subjects
        get_metric_history(subject_type, interval, site_id,
                           from_date, to_date,
                           subject_id=None, metric=None, department_id=None)
                                         -> /api/metrics/{subject_type}/{interval}

    Dataset wrappers (Perspective Table-friendly)
        production_report_latest_dataset(site_id)
        production_report_range_dataset(site_id, from_date, to_date)
        monthly_rollup_dataset(site_id)
        metric_subjects_dataset(subject_type, site_id, department_id=None)
        metric_history_dataset(subject_type, interval, site_id,
                               from_date, to_date,
                               subject_id=None, metric=None, department_id=None)

Where to put this in Ignition
-----------------------------
1. Open Ignition Designer for the project that needs to read PMD.
2. In the Project Library, create (or open) a script package, e.g.
   `PMD`.
3. Paste this file into that package as `api`.
4. Override BASE_URL below if your deployment differs.

Calling from Perspective views
------------------------------
Property binding -> Expression -> "runScript":

    runScript("PMD.api.production_report_latest_dataset", 0, 101)

Property binding -> Script transform:

    return PMD.api.metric_history_dataset(
        subject_type="workcenter",
        interval="shiftly",
        site_id=101,
        from_date="2026-04-01",
        to_date="2026-04-30",
        subject_id="Secondary",
        metric="Total",
    )

Tag change script (gateway scope), writing OEE to memory tags:

    payload = PMD.api.get_production_report_latest(site_id=101)
    for entry in payload["entries"]:
        # OEE-ish fields live inside the production-report payload.
        # See PAYLOAD-CONTRACT.md for the exact shape.
        availability = entry["payload"].get("Availability")
        performance  = entry["payload"].get("Performance")
        if availability is not None and performance is not None:
            system.tag.writeBlocking(
                "[default]Plant/Workcenter/" +
                    entry["department_name"] + "/Availability",
                availability,
            )

Configuration
-------------
BASE_URL    -- API base. Override at deployment time.
TIMEOUT_MS  -- per-request timeout. 30s default; bump for large
               /range or /metrics calls if upstream is slow.

Error handling
--------------
On a non-2xx response or a transport error, every wrapper raises
ValueError with a message that includes the URL and the upstream
status / body excerpt. In a Perspective binding this surfaces in
the binding overlay; in a tag script it surfaces in the gateway
log via system.util.getLogger("PMD.api").
"""

import system
import urllib  # Jython 2.7 stdlib

# Override at deployment time (or read from a gateway tag and patch
# this constant in the calling code if you need per-environment
# configuration).
BASE_URL = "https://productionmetrics.dolese.rocks"
TIMEOUT_MS = 30 * 1000  # 30 seconds


# ===================================================================
# Internal HTTP helpers
# ===================================================================

def _build_url(path, params=None):
    """Compose URL with query string. Skips None / empty values."""
    url = BASE_URL.rstrip("/") + "/" + path.lstrip("/")
    if params:
        clean = {}
        for k in params:
            v = params[k]
            if v is None:
                continue
            if v == "":
                continue
            clean[k] = v
        if clean:
            url = url + "?" + urllib.urlencode(clean)
    return url


def _get(path, params=None):
    """GET path with optional query params; return parsed JSON body.

    Raises ValueError on transport errors and on non-2xx responses.
    Logs to the gateway via system.util.getLogger('PMD.api') so the
    failure leaves a trail outside the immediate caller.
    """
    logger = system.util.getLogger("PMD.api")
    url = _build_url(path, params)

    try:
        client = system.net.httpClient(timeout=TIMEOUT_MS)
        response = client.get(url)
    except Exception as exc:
        logger.error("GET %s -- transport error: %s" % (url, exc))
        raise ValueError("PMD API transport error for %s: %s" % (url, exc))

    status = response.getStatusCode()
    body_text = response.getBody().tostring()

    if status < 200 or status >= 300:
        logger.error("GET %s -> %d: %s" % (url, status, body_text[:500]))
        raise ValueError(
            "PMD API %s returned %d: %s" % (url, status, body_text[:500])
        )

    try:
        return system.util.jsonDecode(body_text)
    except Exception:
        raise ValueError(
            "PMD API %s returned non-JSON body: %s" % (url, body_text[:200])
        )


# ===================================================================
# Health / catalog
# ===================================================================

def get_health():
    """GET /api/health -- per-source reachability for the dashboard's
    status pill. Useful as a Perspective tag-style heartbeat.
    """
    return _get("/api/health")


def get_ping():
    """GET /api/__ping -- build fingerprint. Confirms which build of
    the FastAPI is currently serving this URL; useful when verifying
    a deploy.
    """
    return _get("/api/__ping")


def get_sites():
    """GET /api/sites -- list of {id, name} site entries."""
    return _get("/api/sites")


# ===================================================================
# Production reports (Domain 1)
# ===================================================================

def get_production_report_latest(site_id):
    """GET /api/production-report/latest?site_id=<X>

    Most recent end-of-shift report per workcenter for the site.
    """
    return _get("/api/production-report/latest", {"site_id": site_id})


def get_production_report_range(site_id, from_date, to_date):
    """GET /api/production-report/range?site_id=&from_date=&to_date=

    Historical window, 1-400 days inclusive. Dates are YYYY-MM-DD
    strings.
    """
    return _get("/api/production-report/range", {
        "site_id": site_id,
        "from_date": from_date,
        "to_date": to_date,
    })


def get_production_report_latest_date(site_id):
    """GET /api/production-report/latest-date?site_id=<X>

    Most recent production date with data. Drives the dashboard's
    date-picker default; useful for any Perspective view that needs
    to anchor its time window to "the most recent shift the plant
    actually reported".
    """
    return _get("/api/production-report/latest-date", {"site_id": site_id})


def get_monthly_rollup(site_id):
    """GET /api/production-report/monthly-rollup?site_id=<X>

    Per-month KPI aggregates per workcenter, assembled from the
    curated production-report rows. Today this is a small convenience
    the API performs over already-curated data; Flow can publish
    equivalent rolled-up interval data directly in the future.
    """
    return _get("/api/production-report/monthly-rollup", {"site_id": site_id})


def get_circuit_monthly_rollup(site_id):
    """GET /api/production-report/circuit-monthly-rollup?site_id=<X>

    Hierarchical per-circuit and per-line monthly rollup driving the
    Trends view's circuit charts.
    """
    return _get("/api/production-report/circuit-monthly-rollup", {"site_id": site_id})


# ===================================================================
# Interval metrics (Domain 2)
# ===================================================================

VALID_SUBJECT_TYPES = (
    "conveyor", "workcenter", "circuit", "line", "equipment", "site",
)
VALID_INTERVALS = ("hourly", "shiftly")


def _check_subject_type(subject_type):
    if subject_type not in VALID_SUBJECT_TYPES:
        raise ValueError(
            "subject_type must be one of %s; got %r" %
            (list(VALID_SUBJECT_TYPES), subject_type)
        )


def _check_interval(interval):
    if interval not in VALID_INTERVALS:
        raise ValueError(
            "interval must be one of %s; got %r" %
            (list(VALID_INTERVALS), interval)
        )


def get_metric_subjects(subject_type, site_id, department_id=None):
    """GET /api/metrics/{subject_type}/subjects?site_id=[&department_id=]

    Cheap discovery: list of tags published for this (site,
    subject_type[, department]) triple. No upstream HTTP fan-out --
    just a SELECT against the SQL tag table. Use for Perspective
    dropdown menus, freshness checks (last_seen), inventory pages.
    """
    _check_subject_type(subject_type)
    return _get("/api/metrics/%s/subjects" % subject_type, {
        "site_id": site_id,
        "department_id": department_id,
    })


def get_metric_history(subject_type, interval, site_id,
                       from_date, to_date,
                       subject_id=None, metric=None, department_id=None):
    """GET /api/metrics/{subject_type}/{interval}
                ?site_id=&from_date=&to_date=
                [&subject_id=&metric=&department_id=]

    Fetches Flow's interval-metric history for the matched tags.
    Returns the unified envelope -- ``entries[]`` plus ``count``,
    ``truncated``, ``generated_at``, and the echoed filters.

    Filters compose: site_id + dates required, others optional. If
    ``truncated`` comes back True at least one upstream fetch hit
    Flow's per-tag cap; narrow the window or add a filter and
    re-request.
    """
    _check_subject_type(subject_type)
    _check_interval(interval)
    return _get("/api/metrics/%s/%s" % (subject_type, interval), {
        "site_id": site_id,
        "from_date": from_date,
        "to_date": to_date,
        "subject_id": subject_id,
        "metric": metric,
        "department_id": department_id,
    })


# ===================================================================
# Dataset wrappers (for Perspective Table / Power Chart bindings)
# ===================================================================

def _entries_to_dataset(entries, columns):
    """Project a list-of-dicts onto a fixed column order; return a
    Java/Ignition Dataset suitable for binding to a Perspective
    Table or charting component. Missing keys become None cells.
    """
    cols = list(columns)
    if not entries:
        return system.dataset.toDataSet(cols, [])
    rows = []
    for e in entries:
        row = []
        for c in cols:
            row.append(e.get(c))
        rows.append(row)
    return system.dataset.toDataSet(cols, rows)


# Default flat column set for production-report entries. The OEE-ish
# fields live inside ``payload`` and aren't in this list because the
# payload schema is documented as evolving (see PAYLOAD-CONTRACT.md);
# pull them with entry["payload"].get("Availability") etc. in calling
# code rather than baking them into a contract here.
PRODUCTION_REPORT_COLUMNS = (
    "id", "prod_date", "prod_id", "site_id",
    "department_id", "department_name",
    "shift", "dtm",
    "weather_conditions", "avg_temp", "avg_humidity", "max_wind_speed",
    "notes",
)

MONTHLY_ROLLUP_COLUMNS = (
    "department_id", "department_name", "month",
    "total_tons", "total_runtime_hours", "tph",
    "report_count",
    "avg_tph_fed", "avg_runtime_pct", "avg_performance_pct",
)

METRIC_SUBJECT_COLUMNS = (
    "subject_id", "department_id",
    "metric_names", "intervals",
    "last_seen",
)

METRIC_HISTORY_COLUMNS = (
    "bucket_start", "bucket_end",
    "subject_type", "subject_id", "metric", "interval",
    "value", "unit", "quality_code",
)


def production_report_latest_dataset(site_id):
    """Dataset wrapper around get_production_report_latest()."""
    payload = get_production_report_latest(site_id)
    return _entries_to_dataset(payload.get("entries", []),
                               PRODUCTION_REPORT_COLUMNS)


def production_report_range_dataset(site_id, from_date, to_date):
    """Dataset wrapper around get_production_report_range()."""
    payload = get_production_report_range(site_id, from_date, to_date)
    return _entries_to_dataset(payload.get("entries", []),
                               PRODUCTION_REPORT_COLUMNS)


def monthly_rollup_dataset(site_id):
    """Dataset wrapper around get_monthly_rollup()."""
    payload = get_monthly_rollup(site_id)
    # The monthly rollup envelope uses ``rollups`` rather than ``entries``.
    rows = payload.get("rollups") or payload.get("entries") or []
    return _entries_to_dataset(rows, MONTHLY_ROLLUP_COLUMNS)


def metric_subjects_dataset(subject_type, site_id, department_id=None):
    """Dataset wrapper around get_metric_subjects()."""
    payload = get_metric_subjects(subject_type, site_id,
                                  department_id=department_id)
    return _entries_to_dataset(payload.get("subjects", []),
                               METRIC_SUBJECT_COLUMNS)


def metric_history_dataset(subject_type, interval, site_id,
                           from_date, to_date,
                           subject_id=None, metric=None,
                           department_id=None):
    """Dataset wrapper around get_metric_history()."""
    payload = get_metric_history(
        subject_type, interval, site_id, from_date, to_date,
        subject_id=subject_id, metric=metric, department_id=department_id,
    )
    return _entries_to_dataset(payload.get("entries", []),
                               METRIC_HISTORY_COLUMNS)


# ===================================================================
# Backward compatibility -- keep the prior single-shot helper around
# for any binding that still calls it. New code should call
# get_production_report_latest(site_id) instead.
# ===================================================================

def get_production_report(url=None):
    """Legacy entry point. Prefer ``get_production_report_latest``."""
    if url:
        # Caller passed a full URL; honor it via the raw client.
        client = system.net.httpClient(timeout=TIMEOUT_MS)
        response = client.get(url)
        body = response.getBody()
        return system.util.jsonDecode(body.tostring())
    return get_production_report_latest(101)
