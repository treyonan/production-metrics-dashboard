"""TTL + LRU history cache for Timebase i3X responses.

Why this exists
---------------
Timebase responses can be megabytes for multi-day windows of raw
sub-minute samples. Without a cache, every dashboard poll re-fetches.
With a small cache that normalizes timestamps to 10-second boundaries,
back-to-back polls of "the last hour ending now" hit a stable key for
~10s at a time and share one round trip.

Design points
-------------
* **In-memory**, single-worker. Same posture as ``SnapshotStore``.
  Multi-worker / Redis can be slotted in later behind the same
  interface; not preemptive.
* **Key**: ``(sorted_element_ids_tuple, normalized_start, normalized_end,
  max_depth)``. ``element_ids`` is sorted so two callers asking for the
  same set in different order share the cache slot.
* **Time normalization**: floor to a 10-second boundary in UTC. We
  normalize once and use the normalized values for **both** the cache
  key and the upstream call -- the client receives the normalized
  window in their response. Documented in the OpenAPI description.
* **TTL eviction** on read. Stale entries are removed and treated as a
  miss; no background reaper to keep the implementation tiny.
* **LRU eviction** on write when the entry count exceeds the cap.
  Eviction is on count, not bytes -- entries can be MB-sized, so the
  cap should be set conservatively (default 128 -- ~1 GB worst case
  with very large multi-day responses; in practice typical responses
  are 10-100 KB).

The cache is intentionally dumb. Routes call ``get_or_fetch`` with a
coroutine factory; if a hit, the cached value is returned; otherwise
the factory is awaited and the result stored.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

# Round to this boundary. 10s matches Timebase's typical sub-minute
# sample cadence (the reference response was ~10s-apart points).
_NORMALIZATION_SECONDS = 10


def normalize_timestamp(dt: datetime) -> datetime:
    """Floor ``dt`` to the nearest 10-second boundary in UTC.

    Naive datetimes are treated as UTC. Microseconds are dropped.

    >>> from datetime import datetime, timezone
    >>> normalize_timestamp(datetime(2026, 5, 1, 6, 6, 7, 555000, tzinfo=timezone.utc))
    datetime.datetime(2026, 5, 1, 6, 6, 0, tzinfo=datetime.timezone.utc)
    """
    dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    floored_second = (dt.second // _NORMALIZATION_SECONDS) * _NORMALIZATION_SECONDS
    return dt.replace(second=floored_second, microsecond=0)


CacheKey = tuple[tuple[str, ...], datetime, datetime, int]


def make_key(
    *,
    element_ids: list[str],
    start_time: datetime,
    end_time: datetime,
    max_depth: int,
) -> CacheKey:
    """Build a normalized cache key from caller args."""
    return (
        tuple(sorted(element_ids)),
        normalize_timestamp(start_time),
        normalize_timestamp(end_time),
        max_depth,
    )


@dataclass(frozen=True)
class _CacheEntry:
    value: dict[str, Any]
    expires_at: float  # monotonic seconds


class TimebaseHistoryCache:
    """TTL + LRU cache for ``TimebaseClient.get_history`` results.

    Not thread-safe -- relies on asyncio's single-threaded execution
    model. Multiple concurrent requests for the same key may each fire
    an upstream call (no single-flight); the dashboard's polling
    cadence makes this an acceptable trade for keeping the cache
    simple. Add single-flight later if real-world traffic warrants.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = 45.0,
        max_entries: int = 128,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self._ttl = ttl_seconds
        self._max = max_entries
        self._store: OrderedDict[CacheKey, _CacheEntry] = OrderedDict()

    # ------------------------------------------------------------------
    # Introspection (mostly for tests + diagnostics)
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._store)

    @property
    def ttl_seconds(self) -> float:
        return self._ttl

    @property
    def max_entries(self) -> int:
        return self._max

    # ------------------------------------------------------------------
    # Cache operations
    # ------------------------------------------------------------------

    def get(self, key: CacheKey) -> dict[str, Any] | None:
        """Return cached value or None on miss / expired.

        Expired entries are evicted on read. Hits are LRU-touched
        (moved to the end of the OrderedDict).
        """
        entry = self._store.get(key)
        if entry is None:
            return None
        if time.monotonic() >= entry.expires_at:
            # Expired -- drop it, treat as miss.
            del self._store[key]
            return None
        self._store.move_to_end(key)
        return entry.value

    def put(self, key: CacheKey, value: dict[str, Any]) -> None:
        """Store a value with TTL. Evicts LRU on overflow."""
        if key in self._store:
            # Refresh expiry + LRU position.
            self._store.move_to_end(key)
        self._store[key] = _CacheEntry(
            value=value,
            expires_at=time.monotonic() + self._ttl,
        )
        while len(self._store) > self._max:
            # popitem(last=False) is LRU eviction (oldest end).
            self._store.popitem(last=False)

    async def get_or_fetch(
        self,
        *,
        element_ids: list[str],
        start_time: datetime,
        end_time: datetime,
        max_depth: int,
        fetch: Callable[[list[str], datetime, datetime, int], Awaitable[dict[str, Any]]],
    ) -> tuple[dict[str, Any], bool, datetime, datetime]:
        """Return cached value or call ``fetch`` to obtain a fresh one.

        Normalizes start/end times once; the same normalized values are
        used for the cache key AND for the upstream fetch call, so the
        response covers the normalized window (caller can surface this
        in their response if they want).

        Returns ``(value, cache_hit, normalized_start, normalized_end)``
        so the route can populate response metadata + log diagnostics.
        """
        ns = normalize_timestamp(start_time)
        ne = normalize_timestamp(end_time)
        key = (tuple(sorted(element_ids)), ns, ne, max_depth)

        cached = self.get(key)
        if cached is not None:
            return cached, True, ns, ne

        fresh = await fetch(list(key[0]), ns, ne, max_depth)
        self.put(key, fresh)
        return fresh, False, ns, ne

    def clear(self) -> None:
        """Drop all entries. Tests + diagnostics."""
        self._store.clear()


# Convenience: also expose the normalization step in seconds for tests
# and OpenAPI docs.
NORMALIZATION_SECONDS = _NORMALIZATION_SECONDS


def normalization_window() -> timedelta:
    """Width of the time-normalization window. Surfaced in OpenAPI docs."""
    return timedelta(seconds=_NORMALIZATION_SECONDS)
