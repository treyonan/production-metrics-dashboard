"""Pydantic schemas for /api/metrics/* endpoints.

Two shapes:

* ``IntervalMetricsResponse`` -- envelope for the data endpoint
  (one entry per (asset, metric, bucket)).
* ``IntervalMetricSubjectsResponse`` -- envelope for the discovery
  endpoint (one entry per asset, listing what metrics + intervals
  are available without fetching their values).

The wire ``interval`` field is the truthful aggregation regime
(``hourly`` / ``shiftly``), set by the Ignition trigger from the MQTT
payload's structural shape -- not from the upstream tag's
``measure.intervalType``. See ``docs/data-flows.md`` Domain 2 and
``scada/ignition/upsert_interval_metric_tag.py`` for the rule.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class IntervalMetricEntry(BaseModel):
    """One time-series bucket for one (asset, metric) combination."""

    subject_type: str = Field(
        description="Class of asset producing the metric (e.g. 'conveyor').",
    )
    subject_id: str = Field(
        description="Specific asset identifier (e.g. 'C4').",
    )
    metric: str = Field(description="Metric name (e.g. 'Total', 'Runtime').")
    interval: str = Field(
        description="Bucket regime: 'hourly' or 'shiftly' today.",
    )
    bucket_start: datetime = Field(
        description="Inclusive start of the bucket window (UTC).",
    )
    bucket_end: datetime = Field(
        description="Exclusive end of the bucket window (UTC).",
    )
    value: float = Field(description="Aggregated value for the bucket.")
    unit: str | None = Field(
        default=None,
        description=(
            "Unit of measure as recorded in [FLOW].[INTERVAL_METRIC_TAGS] "
            "(e.g. 'short_tons', 'min', '%'). Null when the tag has no "
            "unit on file."
        ),
    )
    quality_code: int | None = Field(
        default=None,
        description=(
            "Vendor's quality flag for this bucket (Flow returns 192 for "
            "good, 0 for bad). Null when the source didn't supply one. "
            "Consumers can filter or surface visually as needed."
        ),
    )


class IntervalMetricsResponse(BaseModel):
    """Envelope for /api/metrics/{subject_type}/{interval}.

    ``entries`` is the flat per-bucket list; consumers group by
    ``subject_id`` / ``metric`` client-side. ``truncated`` flags
    when at least one upstream fetch hit Flow's per-tag ``limit=1000``
    cap, which means some data may be missing -- the consumer should
    narrow the window and re-request.
    """

    count: int = Field(description="Number of entries in the response.")
    subject_type: str = Field(description="Echo of the path-param subject type.")
    interval: str = Field(description="Echo of the path-param interval.")
    site_id: str = Field(description="Echo of the site_id filter.")
    department_id: str | None = Field(
        default=None, description="Echo of the optional department_id filter."
    )
    subject_id: str | None = Field(
        default=None, description="Echo of the optional subject_id filter."
    )
    metric: str | None = Field(
        default=None, description="Echo of the optional metric filter."
    )
    from_date: date = Field(description="Echo of the inclusive window start.")
    to_date: date = Field(description="Echo of the inclusive window end.")
    generated_at: datetime = Field(description="UTC timestamp the response was assembled.")
    truncated: bool = Field(
        default=False,
        description=(
            "True when at least one upstream tag fetch returned exactly "
            "the per-tag cap (1000 points) -- some buckets may be missing. "
            "Narrow the window or filter to a single tag and re-request."
        ),
    )
    entries: list[IntervalMetricEntry] = Field(
        description="Flat list of buckets, one per (asset, metric, bucket) tuple.",
    )


class IntervalMetricSubject(BaseModel):
    """One asset's tag inventory: which metrics + intervals it publishes."""

    subject_id: str = Field(description="Asset identifier (e.g. 'C4').")
    department_id: str | None = Field(
        default=None,
        description="Department / workcenter identifier when known.",
    )
    metric_names: list[str] = Field(
        description="Metric names this asset publishes (e.g. ['Total', 'Runtime']).",
    )
    intervals: list[str] = Field(
        description="Distinct intervals available across this asset's metrics.",
    )
    last_seen: datetime | None = Field(
        default=None,
        description=(
            "Most recent DTM across this asset's tag rows -- the last time "
            "any of its metrics published. Null only when no rows match "
            "(shouldn't happen given how subjects are derived)."
        ),
    )


class IntervalMetricSubjectsResponse(BaseModel):
    """Envelope for /api/metrics/{subject_type}/subjects.

    Cheap to compute -- a single ``SELECT`` against
    ``[FLOW].[INTERVAL_METRIC_TAGS]`` with no upstream HTTP fan-out.
    """

    count: int = Field(description="Number of subjects in the response.")
    subject_type: str = Field(description="Echo of the path-param subject type.")
    site_id: str = Field(description="Echo of the site_id filter.")
    department_id: str | None = Field(
        default=None, description="Echo of the optional department_id filter."
    )
    generated_at: datetime = Field(description="UTC timestamp the response was assembled.")
    subjects: list[IntervalMetricSubject] = Field(
        description="One entry per asset, sorted by subject_id.",
    )
