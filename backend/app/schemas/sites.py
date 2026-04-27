"""Pydantic schemas for /api/sites."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SiteInfo(BaseModel):
    """One site available in the current data source."""

    id: str = Field(description="Site identifier (maps to SITE_ID in the underlying data).")
    name: str = Field(description="Human-readable site label.")


class SitesResponse(BaseModel):
    """Envelope for the sites list."""

    count: int = Field(description="Number of sites returned.")
    sites: list[SiteInfo] = Field(description="Sites present in the data source, sorted by id.")
