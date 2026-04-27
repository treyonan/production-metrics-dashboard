"""Query-loading helpers.

Queries live on disk as ``.sql`` files alongside the integration that
uses them (per the project CLAUDE.md "SQL lives in files" rule). This
helper reads the file at import-or-first-call time and returns its
contents as a string. Parameterization is still the caller's
responsibility: use ``?`` placeholders and pass values through the
driver, never f-strings or ``.format()``.
"""

from __future__ import annotations

from pathlib import Path


def load_query(queries_dir: Path, name: str) -> str:
    """Return the contents of ``queries_dir / f'{name}.sql'``.

    Raises ``FileNotFoundError`` if the file doesn't exist -- surface
    this loudly at import time rather than at query time.
    """
    path = queries_dir / f"{name}.sql"
    return path.read_text(encoding="utf-8")
