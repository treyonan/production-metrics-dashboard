"""Pydantic schemas for the DIO / Days-of-Supply API (Spec 005)."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class DioRow(BaseModel):
    """One item's Days-of-Supply figures over the selected window.

    ``days_on_hand`` / ``days_after_shutdown`` are ``None`` when the item
    had zero sales in the window (the SP returns NULL); the frontend
    renders those as an em-dash.
    """

    item_code: str = Field(description="Item / SKU code, e.g. ST5450.")
    item_description: str = Field(description="Human-readable item description.")
    total_sales: float | None = Field(
        default=None, description="Tons sold, SUMMED over the window."
    )
    tpd_sales: float | None = Field(
        default=None, description="Average tons/day of sales (total / day_count)."
    )
    current_inventory: float | None = Field(
        default=None, description="Latest on-hand inventory (tons) in the window."
    )
    days_on_hand: float | None = Field(
        default=None,
        description=(
            "Days of supply = current inventory / average daily sales. "
            "Null when the item had no sales in the window."
        ),
    )
    days_after_shutdown: float | None = Field(
        default=None,
        description=(
            "Days of supply minus the outage range (67). Negative means "
            "short during the outage. Null when the item had no sales."
        ),
    )


class DioResponse(BaseModel):
    """Envelope for ``GET /api/dio/daily``."""

    site_id: str = Field(description="Site the records are for.")
    from_date: date = Field(description="Inclusive window start.")
    to_date: date = Field(description="Inclusive window end.")
    day_count: int = Field(description="Calendar days in the window (inclusive).")
    generated_at: datetime = Field(description="UTC timestamp the response was built.")
    rows: list[DioRow] = Field(default_factory=list, description="One row per item.")
