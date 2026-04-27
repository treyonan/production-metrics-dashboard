# Production-metrics-dashboard backend — single-stage Linux container.
#
# Target: Docker Desktop + WSL2 on Windows dev boxes; same image
# suitable for any Linux host with Docker. Companion to (not a
# replacement for) the local venv dev loop — `uvicorn app.main:app`
# from VSCode keeps working against the same backend/.env.
#
# Build context is the repo root (see docker-compose.yml), which is
# why COPY paths are `backend/...`, `context/...`, `frontend/...`
# rather than relative to this Dockerfile.

FROM python:3.12-slim-bookworm

# Standard Python-in-Docker hygiene:
#   PYTHONDONTWRITEBYTECODE: skip .pyc files — they're noise in a container
#   PYTHONUNBUFFERED:       flush stdout/stderr line-by-line so `docker logs`
#                           shows structlog JSON events as they happen, not
#                           in 4KB buffered chunks
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install ODBC Driver 17 for SQL Server from Microsoft's apt repo.
# Matches the version installed on the Windows host so the same DSN
# string in backend/.env works in both code paths. The
# ACCEPT_EULA=Y and msodbcsql17 pair is Microsoft's documented
# unattended-install incantation:
#   https://learn.microsoft.com/en-us/sql/connect/odbc/linux-mac/installing-the-microsoft-odbc-driver-for-sql-server
#
# Why `--no-install-recommends` everywhere: keeps image size down by
# skipping suggested-but-unused packages.
#
# Why purge gnupg/curl after use: they're only needed to fetch and
# verify the MS apt key, not at runtime.
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        curl \
        gnupg2 \
        apt-transport-https \
        ca-certificates \
 && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
        | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
 && echo "deb [signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" \
        > /etc/apt/sources.list.d/mssql-release.list \
 && apt-get update \
 && ACCEPT_EULA=Y apt-get install -y --no-install-recommends \
        msodbcsql17 \
        unixodbc \
 && apt-get purge -y --auto-remove curl gnupg2 apt-transport-https \
 && rm -rf /var/lib/apt/lists/*

# Mirror the repo layout inside the container so core/config.py's
# `parents[3]` logic resolves the same way it does in the venv path:
#   /app/backend/app/core/config.py → parents[3] = /app/
#   → /app/context/sample-data/...  and  /app/frontend/  both reachable.
WORKDIR /app/backend

# Install Python deps first so the pip layer is cached across code edits.
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install -r requirements.txt

# App + data sibling dirs. Baked-in so the image can run standalone
# (e.g. in CI or production). docker-compose.yml layers read-only
# bind mounts on top for dev ergonomics — edits to sample data or the
# frontend show up without a rebuild.
COPY backend/app /app/backend/app
COPY context     /app/context
COPY frontend    /app/frontend

# Document the port uvicorn binds inside the container. Host-side
# mapping lives in docker-compose.yml.
EXPOSE 8000

# Exec form (JSON array) so SIGTERM from `docker stop` reaches uvicorn
# directly, triggering FastAPI's lifespan shutdown (pool.close(),
# pool.wait_closed()) instead of being swallowed by /bin/sh -c.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
