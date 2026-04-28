# Linux Server Deployment

Runbook for deploying `production-metrics-dashboard` to an Ubuntu Linux
host running Docker. Companion to `RUNBOOK.md` (which covers the
Windows dev box). Cross-platform notes that apply to both hosts live
in the main RUNBOOK; everything Linux-server-specific lives here.

**Target host shape:** Ubuntu 22.04+ with Docker Engine and Docker
Compose v2.x installed, network reachability to the SQL Server host
and any Flow API hosts the deployed sites use, and outbound HTTPS to
GitHub for `git pull`.

## Repo layout invariant

The repo is rooted at the project level. After clone, the layout under
`/opt/production-metrics-dashboard/` MUST be flat:

```
/opt/production-metrics-dashboard/
├── backend/
├── frontend/
├── context/
├── docker-compose.yml
├── CLAUDE.md
└── ...
```

If you see anything like
`/opt/production-metrics-dashboard/Claude_Cowork/projects/production-metrics-dashboard/`,
the clone came from the pre-2026-04-27 workspace-rooted repo. Stop,
delete the directory, and re-clone from the current
`production-metrics-dashboard` remote (see "Re-deploy from scratch"
below). The build context paths in `docker-compose.yml` and
`backend/Dockerfile` assume the flat layout — nothing works with the
nested path.

## Prerequisites (one-time, per host)

### Docker engine + Compose v2

```bash
# Docker engine
curl -fsSL https://get.docker.com | sudo sh

# Compose v2 ships as a docker plugin in current Docker installs.
# Verify:
docker --version              # 24.x or newer
docker compose version        # v2.x (e.g. v2.39.4)

# Add yourself to the docker group so you don't need sudo for every command
sudo usermod -aG docker $USER
newgrp docker                 # apply group change in the current shell
```

### GitHub Personal Access Token

The repo at `https://github.com/treyonan/production-metrics-dashboard`
is private. HTTPS clones need a PAT, not a password.

1. Generate at <https://github.com/settings/tokens> → Tokens (classic)
   → Generate new token. Scope: `repo`. Set a sensible expiry.
2. Treat the token as a secret. The credential helper below caches it
   to `~/.git-credentials`; lock down with `chmod 600` if you want
   defense in depth.

### Network reachability

The container reaches SQL Server via the `dbp-bcq:10.44.135.12` static
host entry in `docker-compose.yml` (`services.api.extra_hosts`). Verify
the host can route to that IP before you build:

```bash
ping -c 2 10.44.135.12
```

Flow API endpoints are reached over the corporate network too. The
`extra_hosts:` list in `docker-compose.yml` is the single source of
truth for those mappings — see "Adding a new site to /api/metrics" in
`RUNBOOK.md` for the procedure when a new site comes online.

## First-time deploy

```bash
# 1. Configure git credential caching FIRST, before any clone. If the
#    helper isn't active when the clone prompts for the PAT, that PAT
#    won't be persisted and you'll be re-typing it on every pull.
git config --global credential.helper store
# Alternatives:
#   credential.helper cache  → in-memory only, evicts after 15 min
#   credential.helper 'cache --timeout=3600'  → 1 hour

# 2. Create the deploy directory and assign ownership BEFORE cloning.
#    /opt is owned by root, so the mkdir needs sudo. Handing the directory
#    to your user up-front means the clone (and all future git pulls) run
#    without sudo and don't leave root-owned files behind.
sudo mkdir -p /opt/production-metrics-dashboard
sudo chown $USER:$USER /opt/production-metrics-dashboard

# 3. Clone into the now-owned directory.
#
#    !!! IMPORTANT !!! The TRAILING DOT is what makes the layout flat.
#    `git clone <url>`     creates ./production-metrics-dashboard/  (nested — wrong)
#    `git clone <url> .`   clones into the current directory        (flat — right)
#
#    If you forget the dot and end up with a nested
#    /opt/production-metrics-dashboard/production-metrics-dashboard/, fix it:
#       rm -rf production-metrics-dashboard
#       git clone https://github.com/treyonan/production-metrics-dashboard.git .
#
cd /opt/production-metrics-dashboard
git clone https://github.com/treyonan/production-metrics-dashboard.git .
# Username: treyonan
# Password: <PAT, NOT GitHub password>
# This first clone is what triggers the credential helper to write the
# PAT to ~/.git-credentials. Future git pulls run silently.

# 4. Verify flat layout BEFORE moving on. If `ls` shows a single
#    "production-metrics-dashboard" directory instead of the expected
#    files, you missed the trailing dot — see step 3's fix box.
ls
# Expect: backend  context  docker-compose.yml  frontend  CLAUDE.md  ...
# NOT:    production-metrics-dashboard

# 5. Configure backend/.env
cp backend/.env.example backend/.env
nano backend/.env
```

Edit `backend/.env` and set the values that aren't placeholders:

- `DB_CONN_STRING` — SQL Server ODBC connection string. Reference the
  host alias defined in `docker-compose.yml` (`dbp-bcq`) so the same
  DSN works in both the Windows venv path and the Linux container.
  Single-brace driver name (`{ODBC Driver 17 for SQL Server}`),
  `tcp:` server prefix.
- `FLOW_API_KEY` — bearer token for Flow REST API. Per-deployment
  secret; never check in.
- `PRODUCTION_REPORT_BACKEND` — `sql` for live, `csv` for fallback /
  smoke testing.
- Anything else `.env.example` flags as required.

```bash
# 6. Build and start (detached so the shell is free)
docker compose up -d --build

# 7. Tail startup logs until you see sql_pool.created and flow_client.created
docker compose logs -f api
# Ctrl+C exits the tail without stopping the container

# 8. Smoke-test
curl -s http://localhost:8001/api/__ping
# Expect: {"alive":true,"build_tag":"..."}

curl -s http://localhost:8001/api/health | jq
# Expect: each source reports ok: true (sql:production_report,
# external:flow, etc. depending on configuration)
```

If `/api/health` reports a source down with a clear error, the API
stays up and degrades gracefully — see "Troubleshooting" below.

## Updates after dev-box changes

The dev-side workflow is `git push` from the Windows box. The server-side
update sequence is below — three steps in order, with a decision point in
the middle on whether a rebuild is required.

### Step 1 — Pull the latest

```bash
cd /opt/production-metrics-dashboard
git pull
```

### Step 2 — See what changed and decide on rebuild

```bash
# Files touched in this pull:
git log --stat HEAD@{1}..HEAD
```

Three buckets, only one applies per pull:

| What changed | Action | Why |
|---|---|---|
| **Only `frontend/` or `context/sample-data/`** | Nothing. Skip to Step 3. | Bind-mounted read-only at `./frontend:/app/frontend:ro` and `./context:/app/context:ro`. Container reads the file on every request, so the new bytes are live the moment `git pull` finishes. |
| **`backend/app/` Python, `backend/requirements.txt`, or `backend/Dockerfile`** | `docker compose up -d --build` | Python code + the image's installed dependencies are baked into the image at build time. Without `--build`, the container keeps running the old code. |
| **Only `docker-compose.yml`** (e.g. new `extra_hosts` entry, port change) | `docker compose up -d` | Compose detects the config diff and recreates the container *without* rebuilding the image. Faster than `--build`. |

If the pull touches both buckets — e.g. backend code AND `docker-compose.yml`
— `docker compose up -d --build` covers both.

### Step 3 — Verify the new code is running

```bash
# build_tag identifies the running image. Compare to BUILD_TAG in
# backend/app/main.py for the version you just pulled.
curl -s http://localhost:8001/api/__ping

# If you bumped BUILD_TAG and the response still shows the OLD tag,
# the rebuild didn't take. Re-run with --build.

# Frontend-only changes don't bump BUILD_TAG; verify those by
# hard-refreshing the browser (Ctrl+Shift+R) and looking at
# DevTools Network → app.js → Response for the new code.
```

### TL;DR for the common case (frontend-only push)

```bash
cd /opt/production-metrics-dashboard
git pull
# done — hard-refresh browser
```

### TL;DR for backend code changes

```bash
cd /opt/production-metrics-dashboard
git pull
docker compose up -d --build
docker compose logs -f api      # watch startup, Ctrl+C to detach
curl -s http://localhost:8001/api/__ping
```

## Re-deploy from scratch (blast radius: full)

When you need to reset the host completely — e.g. after a botched
clone, a major refactor, or to validate the deploy works on a clean
filesystem:

```bash
# 1. Stop containers cleanly so they release file handles
cd /opt/production-metrics-dashboard 2>/dev/null && docker compose down

# 2. Save backend/.env if it has real values you don't want to re-enter
cp /opt/production-metrics-dashboard/backend/.env ~/pmd-env-backup-$(date +%Y%m%d-%H%M%S)

# 3. Force-delete the directory
sudo rm -rf /opt/production-metrics-dashboard

# 4. Confirm gone
ls -la /opt/production-metrics-dashboard 2>&1 | head

# 5. Run "First-time deploy" from the top
```

`backend/.env` is the only piece of state on the host that doesn't
live in git. Everything else is reproducible from `git clone` +
`docker compose up --build`. Container volumes are not used —
SnapshotStore is in-process memory and clears on restart by design.

## Troubleshooting

### Nested clone path

```
/opt/production-metrics-dashboard/Claude_Cowork/projects/production-metrics-dashboard/
```

You cloned the wrong remote — that path comes from a workspace-rooted
repo that was retired on 2026-04-27. The current remote is
`https://github.com/treyonan/production-metrics-dashboard.git` and
clones flat. Fix: re-deploy from scratch (see above).

### `git clone` fails with auth error

- Make sure you're using a PAT, not your GitHub password (password
  auth was deprecated in 2021).
- The PAT needs `repo` scope (or `Contents: Read` on a fine-grained
  token scoped to the repo).
- If `credential.helper store` is on but cached the wrong PAT,
  `~/.git-credentials` has stale entries — delete the file and try
  again.

### `docker compose up --build` fails with "bind: address already in use"

Port 8001 on the host is taken. Either kill the process holding it:

```bash
sudo lsof -i :8001
sudo kill <pid>
```

Or change the host-side mapping in `docker-compose.yml` (`"8001:8000"`
→ `"8002:8000"`). The container-side port (8000) doesn't change.

### `/api/health` reports `sql:production_report` down

Container can't reach the SQL host. Check, in order:

1. **Static host entry exists.** `grep extra_hosts docker-compose.yml`
   should show `"dbp-bcq:10.44.135.12"` (or whatever site you're
   targeting). If missing, add it and `docker compose up -d` to
   reload.
2. **Host can ping the IP.** `ping -c 2 10.44.135.12` from the Linux
   host itself. If this fails, it's a network/firewall issue, not a
   container issue.
3. **Container can resolve the alias.** Shell into the container and
   confirm:
   ```bash
   docker compose exec api cat /etc/hosts | grep dbp-bcq
   docker compose exec api ping -c 1 dbp-bcq
   ```
   If `/etc/hosts` doesn't have the entry, `extra_hosts:` wasn't
   applied — `docker compose down && docker compose up -d` to force
   the recreation.
4. **DSN is correct.** `docker compose exec api sh -c 'echo $DB_CONN_STRING'`
   and eyeball it. Single-brace driver name; `tcp:` prefix on server.

### `/api/metrics/conveyor/*` returns 504 ConnectError

Flow API host unreachable. Same triage as SQL: check `extra_hosts`
for the Flow hostname, ping the IP, confirm the container can
resolve and reach it. Port 4501 must be open from the host's
outbound IP. See "Adding a new site to /api/metrics" in `RUNBOOK.md`.

### `sql_pool.create_failed` in the container log

Driver loaded but the connection failed. Same root causes as the
Windows path — see `RUNBOOK.md` → "sql_pool.create_failed in the
container log".

### Stale code running

The container bakes Python code in at build time. After a `git pull`
that touched `backend/app/`, you need `docker compose up -d --build`
or you'll keep running the old code. Confirm with `/api/__ping`:

```bash
curl -s http://localhost:8001/api/__ping
# Compare build_tag to BUILD_TAG in backend/app/main.py
```

If they don't match, rebuild.

## Change history

- **2026-04-27** — repo re-rooted at the project level. Prior history
  lived under workspace-rooted `treyonan/Claude_Cowork`; that remote
  is archived and clones from it are no longer valid. Current remote:
  `treyonan/production-metrics-dashboard`. First clean Linux deploy
  followed this re-root.

## Where things live (Linux deploy)

| Want | Look here |
|---|---|
| This runbook | `docs/server-deployment.md` |
| Windows dev box runbook | `RUNBOOK.md` |
| Big-picture architecture | `ARCHITECTURE.md` |
| Compose orchestration | `docker-compose.yml` |
| Container build | `backend/Dockerfile` |
| Runtime config (host secrets) | `backend/.env` (NOT in git) |
| Runtime config template | `backend/.env.example` |
