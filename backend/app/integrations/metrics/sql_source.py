"""SQL-backed interval-metric source.

The source's job is two-step: SQL lookup then HTTP fan-out.

1. Read matching rows from ``[FLOW].[INTERVAL_METRIC_TAGS]`` via
   the aioodbc pool. Each row carries the tag's pre-templated
   ``history_url`` plus its identifying fields (asset, metric,
   interval, department_id, etc.).
2. Fan out per-tag fetches to Flow's REST API via ``FlowClient``,
   using ``asyncio.gather`` so all tags are fetched concurrently.
3. Parse each Flow response into ``IntervalMetricPoint``s,
   stamping the identifying fields from the tag row (Flow returns
   only buckets + values, not the tag's name / metric / unit).
4. Surface a ``truncated`` flag if any per-tag fetch hit the
   per-URL ``limit=`` cap.

Discovery (``list_subjects``) is one SQL call, aggregated per asset
in Python. No HTTP fan-out -- cheap.

The source's ``ping()`` checks the SQL pool only. Flow API
reachability is its own concern (``FlowClient`` exposes its own
state); /api/health can grow a separate Flow check later.
"""

from __future__ import annotations

import asyncio
import re
from collections import defaultdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.integrations.external.flow_client import FlowClient, format_flow_iso
from app.integrations.sql.queries import load_query

from .base import (
    FetchPointsResult,
    IntervalMetricPoint,
    IntervalMetricSubject,
    SourceStatus,
)

if TYPE_CHECKING:
    import aioodbc

_QUERIES_DIR = Path(__file__).parent / "queries"

# Flow's response timestamps look like
# "2026-03-24T11:30:06.018Z" -- ISO-8601 with millisecond precision and
# a trailing Z. fromisoformat in Python 3.11+ accepts the Z suffix.
# We trim trailing fractional precision beyond microseconds defensively
# in case Flow ever emits 7-digit fractional seconds (.NET-style).
_TRAILING_FRACTION_RE = re.compile(r"\.(\d{6})\d+(Z?)$")


def _parse_flow_timestamp(s: str) -> datetime:
    """Parse a Flow API timestamp into a UTC datetime.

    Accepts:
        2026-03-24T11:30:06.018Z          (millisecond)
        2026-03-24T11:30:06.0180000Z      (.NET DateTimeOffset, 7-digit)
        2026-03-24T11:30:06Z              (no fractional)

    Returns a timezone-aware UTC datetime.
    """
    # Trim sub-microsecond fractional digits so fromisoformat parses cleanly.
    cleaned = _TRAILING_FRACTION_RE.sub(r".\1\2", s)
    # Replace trailing Z with +00:00 for fromisoformat.
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    return datetime.fromisoformat(cleaned).astimezone(UTC)


class SqlIntervalMetricSource:
    """Reads tag rows from SQL, fans out per-tag fetches to Flow."""

    name = "sql:interval_metrics"

    def __init__(
        self,
        *,
        pool: aioodbc.Pool,
        flow_client: FlowClient,
    ) -> None:
        self._pool = pool
        self._flow = flow_client
        # Load queries at construction time -- fail fast on missing files.
        self._select_tags_sql = load_query(_QUERIES_DIR, "select_tags")
        self._select_subjects_sql = load_query(_QUERIES_DIR, "select_subjects")
        # Reuse production-report's ping query; it's just SELECT 1.
        from app.integrations.production_report import sql_source as _pr_sql
        self._ping_sql = load_query(
            Path(_pr_sql.__file__).parent / "queries", "ping"
        )

    async def ping(self) -> SourceStatus:
        """Check the SQL pool. Never raises."""
        now = datetime.now(UTC)
        try:
            async with (
                self._pool.acquire() as conn,
                conn.cursor() as cur,
            ):
                await cur.execute(self._ping_sql)
                row = await cur.fetchone()
            if row is not None and row[0] == 1:
                return SourceStatus(ok=True, detail="SELECT 1 returned 1", checked_at=now)
            return SourceStatus(
                ok=False, detail=f"Unexpected ping result: {row!r}", checked_at=now
            )
        except Exception as exc:  # noqa: BLE001 -- diagnostic on any error
            return SourceStatus(
                ok=False, detail=f"{type(exc).__name__}: {exc}", checked_at=now
            )

    async def fetch_points(
        self,
        *,
        site_id: str,
        from_date: date,
        to_date: date,
        subject_type: str,
        interval: str,
        department_id: str | None = None,
        subject_id: str | None = None,
        metric: str | None = None,
    ) -> FetchPointsResult:
        """Look up matching tags, fan out to Flow, return parsed points.

        ``interval`` is required at the route layer (path param), so
        callers always pass it here. Other filters are optional --
        narrowing them reduces the fan-out width.

        Window bounds (from_date, to_date) become inclusive midnight-
        UTC ISO-8601 strings substituted into each tag's
        ``history_url`` template.
        """
        tags = await self._select_tags(
            site_id=site_id,
            subject_type=subject_type,
            department_id=department_id,
            subject_id=subject_id,
            metric=metric,
            interval=interval,
        )
        if not tags:
            return FetchPointsResult(points=[], truncated=False)

        # Convert from_date -> 00:00:00 of that day, to_date -> 00:00:00
        # of the day AFTER (so the window is inclusive of to_date).
        start_dt = datetime(from_date.year, from_date.month, from_date.day, tzinfo=UTC)
        end_dt = datetime(to_date.year, to_date.month, to_date.day, tzinfo=UTC)
        # Add a day to make to_date inclusive.
        from datetime import timedelta as _td
        end_dt = end_dt + _td(days=1)

        # Fan out concurrently. asyncio.gather preserves order; each
        # task returns (tag_row, FlowFetchResult) pairs we then walk.
        tasks = [
            self._flow.fetch_history(tag["history_url"], start=start_dt, end=end_dt)
            for tag in tags
        ]
        results = await asyncio.gather(*tasks)

        points: list[IntervalMetricPoint] = []
        truncated = False
        for tag, result in zip(tags, results, strict=True):
            if result.hit_limit:
                truncated = True
            for bucket in result.raw_data:
                points.append(
                    IntervalMetricPoint(
                        subject_type=tag["subject_type"],
                        subject_id=tag["asset"],
                        metric=tag["metric_name"],
                        interval=tag["interval"],
                        bucket_start=_parse_flow_timestamp(bucket["start"]),
                        bucket_end=_parse_flow_timestamp(bucket["end"]),
                        value=float(bucket.get("value") or 0),
                        unit=None,  # Tag table doesn't carry unit yet (Phase 9.x)
                        quality_code=(
                            bucket.get("detail", {}).get("quality", {}).get("value")
                        ),
                    )
                )
        return FetchPointsResult(points=points, truncated=truncated)

    async def list_subjects(
        self,
        *,
        site_id: str,
        subject_type: str,
        department_id: str | None = None,
    ) -> list[IntervalMetricSubject]:
        """Return one IntervalMetricSubject per asset matching the filters.

        Aggregates the SQL grouped result (per asset, metric, interval)
        up to per asset (with metric_names + intervals as tuples and
        last_seen as max DTM).
        """
        async with (
            self._pool.acquire() as conn,
            conn.cursor() as cur,
        ):
            await cur.execute(
                self._select_subjects_sql,
                (
                    site_id,
                    subject_type,
                    department_id,
                    department_id,  # repeated for the (? IS NULL OR ...) pattern
                ),
            )
            rows = await cur.fetchall()

        # Aggregate in Python: one entry per asset.
        # Row tuple order matches the SELECT in select_subjects.sql:
        #   0 asset, 1 department_id, 2 metric_name, 3 interval, 4 last_seen
        per_asset_metrics: dict[str, set[str]] = defaultdict(set)
        per_asset_intervals: dict[str, set[str]] = defaultdict(set)
        per_asset_last_seen: dict[str, datetime | None] = {}
        per_asset_dept: dict[str, str | None] = {}

        for row in rows:
            asset = str(row[0])
            dept = str(row[1]) if row[1] is not None else None
            metric_name = str(row[2])
            interval = str(row[3])
            last_seen = row[4]  # datetime | None from the driver

            per_asset_metrics[asset].add(metric_name)
            per_asset_intervals[asset].add(interval)
            current = per_asset_last_seen.get(asset)
            if last_seen is not None and (current is None or last_seen > current):
                per_asset_last_seen[asset] = last_seen
            elif current is None and asset not in per_asset_last_seen:
                per_asset_last_seen[asset] = None
            per_asset_dept[asset] = dept

        return [
            IntervalMetricSubject(
                subject_id=asset,
                department_id=per_asset_dept[asset],
                metric_names=tuple(sorted(per_asset_metrics[asset])),
                intervals=tuple(sorted(per_asset_intervals[asset])),
                last_seen=per_asset_last_seen.get(asset),
            )
            for asset in sorted(per_asset_metrics.keys())
        ]

    # ---- internal helpers ----

    async def _select_tags(
        self,
        *,
        site_id: str,
        subject_type: str,
        department_id: str | None,
        subject_id: str | None,
        metric: str | None,
        interval: str | None,
    ) -> list[dict[str, Any]]:
        """Run select_tags.sql with the optional-filter parameter pattern."""
        params = (
            site_id,
            subject_type,
            department_id, department_id,
            subject_id, subject_id,
            metric, metric,
            interval, interval,
        )
        async with (
            self._pool.acquire() as conn,
            conn.cursor() as cur,
        ):
            await cur.execute(self._select_tags_sql, params)
            rows = await cur.fetchall()

        # Column order matches select_tags.sql:
        # 0=site_id, 1=asset, 2=metric_name, 3=interval, 4=history_url,
        # 5=department_id, 6=subject_type, 7=DTM
        return [
            {
                "site_id": str(r[0]),
                "asset": str(r[1]),
                "metric_name": str(r[2]),
                "interval": str(r[3]),
                "history_url": str(r[4]),
                "department_id": str(r[5]) if r[5] is not None else None,
                "subject_type": str(r[6]),
                "DTM": r[7],
            }
            for r in rows
        ]


__all__ = ["SqlIntervalMetricSource", "format_flow_iso"]
