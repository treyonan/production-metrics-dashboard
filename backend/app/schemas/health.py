"""Pydantic schemas for /api/health."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

OverallStatus = Literal["ok", "degraded", "down"]


class SourceHealth(BaseModel):
    """Reachability of a single data source."""

    name: str = Field(description="Short source identifier, e.g. 'sql:production_report'.")
    ok: bool = Field(description="True when the source responded to a ping successfully.")
    detail: str = Field(description="Human-readable diagnostic message.")
    checked_at: datetime = Field(description="UTC timestamp the source ping completed.")


class HealthResponse(BaseModel):
    """Aggregate API health response."""

    status: OverallStatus = Field(
        description=(
            "Overall API health. 'ok' = all sources reachable; "
            "'degraded' = at least one source is down; "
            "'down' = every source is unreachable."
        )
    )
    version: str = Field(description="API version string.")
    environment: str = Field(description="Deployment environment identifier.")
    checked_at: datetime = Field(description="UTC timestamp the aggregate check ran.")
    sources: list[SourceHealth] = Field(description="Per-source reachability detail.")
