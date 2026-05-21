"""Application configuration.

All settings are loaded from environment variables (prefixed ``PMD_``) with
sensible defaults for local dev. ``get_settings`` is cached so settings
evaluate once per process; tests that need overrides should call
``get_settings.cache_clear()`` after mutating env vars.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root = backend/app/core/config.py -> parents[3]
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_FRONTEND_DIR = _REPO_ROOT / "frontend"

# Human-readable names for site IDs present in the data. The source layer
# reports which IDs exist; the service layer joins in these labels. Missing
# IDs fall back to "Site <id>".
_DEFAULT_SITE_NAMES: dict[str, str] = {
    "100": "Ardmore Quarry",
    "101": "Big Canyon Quarry",
}


class Settings(BaseSettings):
    """Environment-driven configuration.

    Override any field via ``PMD_<FIELD_NAME>`` environment variables,
    or by dropping a ``.env`` file next to the backend.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="PMD_",
        case_sensitive=False,
        extra="ignore",
    )

    api_title: str = "Production Metrics Dashboard API"
    api_version: str = "0.1.0"
    environment: str = Field(
        default="local",
        description="Deployment identifier surfaced in /api/health (e.g. local, dev, prod).",
    )
    log_level: str = Field(
        default="INFO",
        description="structlog filtering level: DEBUG / INFO / WARNING / ERROR.",
    )

    site_names: dict[str, str] = Field(
        default_factory=lambda: dict(_DEFAULT_SITE_NAMES),
        description="Lookup of site_id -> display name. Unknown IDs fall back to 'Site <id>'.",
    )

    frontend_dir: Path = Field(
        default=_DEFAULT_FRONTEND_DIR,
        description=(
            "Directory to serve as static frontend under '/'. Set to an empty "
            "path to disable static serving (e.g. when fronted by IIS/nginx)."
        ),
    )

    # ---- SQL backend ----
    #
    # Phase 13 (2026-04-28) made SQL the only production-report source.
    # db_conn_string is required; if it's missing the lifespan logs the
    # error and the SQL pool stays None, which surfaces as a clean 503
    # from /api/production-report/* via the DI provider rather than a
    # crash.

    db_conn_string: SecretStr | None = Field(
        default=None,
        description=(
            "ODBC connection string for the SQL Server production-report "
            "source. Required in production -- if unset the SQL pool fails "
            "to initialize and /api/production-report/* returns 503. "
            "Stored as SecretStr so pydantic keeps it out of default "
            "logs and repr()s."
        ),
        validation_alias=AliasChoices("PMD_DB_CONN_STRING", "DB_CONN_STRING"),
    )

    # ---- Phase 9: Flow API integration for interval metrics ----

    flow_api_key: SecretStr | None = Field(
        default=None,
        description=(
            "Bearer token for Flow's REST API. Used as-is in the "
            "Authorization header by FlowClient (no exchange / refresh). "
            "When None, /api/metrics/* returns 503 from the DI provider."
        ),
        validation_alias=AliasChoices("PMD_FLOW_API_KEY", "FLOW_API_KEY"),
    )
    flow_api_timeout_seconds: float = Field(
        default=30.0,
        description=(
            "Per-request timeout for Flow API calls via httpx. 30s "
            "comfortably absorbs one stuck connection without hanging "
            "the dashboard."
        ),
    )
    metrics_cache_ttl_hourly_s: int = Field(
        default=300,
        description=(
            "SnapshotStore TTL for /api/metrics/.../hourly responses. "
            "Hourly buckets are append-only after they close, so a "
            "5-minute cache is safe against hotter polling."
        ),
    )
    metrics_cache_ttl_shiftly_s: int = Field(
        default=900,
        description=(
            "SnapshotStore TTL for /api/metrics/.../shiftly responses. "
            "Shiftly buckets close once per shift; 15-minute cache "
            "comfortably covers human polling cadence."
        ),
    )
    metrics_max_points: int = Field(
        default=50_000,
        description=(
            "Maximum entries a single /api/metrics/.../{interval} "
            "response can contain. Filters that would exceed this "
            "return 422 with a hint about narrowing."
        ),
    )
    metrics_max_window_days_hourly: int = Field(
        default=31,
        description="Maximum window span in days for hourly metrics requests.",
    )
    metrics_max_window_days_shiftly: int = Field(
        default=400,
        description="Maximum window span in days for shiftly metrics requests.",
    )

    # ---- Phase 26: Timebase i3X wrapper ----
    #
    # Each site's historian URL lives in the catalog YAML
    # (backend/app/integrations/timebase/catalog.yaml) under
    # sites.<id>.base_url, NOT in env vars -- each plant has its own
    # historian on its own network, and the URLs aren't secrets.
    # Tuning knobs below apply globally to all sites.

    timebase_timeout_seconds: float = Field(
        default=15.0,
        description=(
            "Per-request timeout for Timebase HTTP calls. Multi-day "
            "history pulls can return MBs of data so this is a hair "
            "shorter than Flow's 30s but still generous."
        ),
    )
    timebase_cache_ttl_seconds: int = Field(
        default=45,
        description=(
            "TTL for the in-process /api/timebase/history cache. "
            "45s comfortably covers a 1-5 min dashboard polling "
            "cadence without serving uselessly stale data."
        ),
    )
    timebase_cache_max_entries: int = Field(
        default=128,
        description=(
            "LRU entry-count cap on the Timebase history cache. "
            "Entries can be MB-sized for multi-day windows, so the "
            "cap is on count rather than bytes."
        ),
    )


@lru_cache
def get_settings() -> Settings:
    """Return a process-wide Settings instance."""
    return Settings()
