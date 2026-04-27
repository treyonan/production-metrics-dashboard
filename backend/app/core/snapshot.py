"""Snapshot-cache abstraction.

A ``SnapshotStore`` holds the latest computed payload for a key. The
intended usage pattern is a single background task that refreshes
snapshots on an interval; HTTP handlers hand out whatever snapshot is
current, without fanning out source calls per request.

Today's routes don't use the store yet -- it's shipped as an interface
so the migration to background refresh later becomes a DI change, not
an architectural one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class Snapshot[T]:
    """A single stored snapshot with its creation timestamp."""

    data: T
    created_at: datetime


class SnapshotStore(Protocol):
    """Minimal get/set interface over named snapshots."""

    async def get(self, key: str) -> Snapshot[Any] | None: ...
    async def set(self, key: str, data: Any) -> Snapshot[Any]: ...


class InMemorySnapshotStore:
    """Process-local snapshot store.

    Fine for single-worker deployments. When we outgrow that, the
    replacement is a Redis-backed store implementing the same Protocol
    -- no call-site changes required.
    """

    def __init__(self) -> None:
        self._store: dict[str, Snapshot[Any]] = {}

    async def get(self, key: str) -> Snapshot[Any] | None:
        return self._store.get(key)

    async def set(self, key: str, data: Any) -> Snapshot[Any]:
        snap = Snapshot(data=data, created_at=datetime.now(UTC))
        self._store[key] = snap
        return snap
