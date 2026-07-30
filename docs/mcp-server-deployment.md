# Standing Up a Containerized MCP Server on a Linux Host

A reusable runbook for building, running (with **Docker Compose**), and
**connecting Claude to** a containerized MCP server on a Linux host. It
covers both cases — the app **lives in a git repo** (clone it) and the app
is **just a folder of files** (copy it over) — and how to wire the running
server into the **Claude config** for **both transports (stdio and SSE/HTTP
over a port)**.

---

## 0. First decide the transport — it changes everything

| Transport | What it is | Where it can run | How you run it |
|---|---|---|---|
| **stdio** | Claude launches the server as a child process over stdin/stdout. No port. | **Local only** — same machine as Claude. | Not a service. Claude launches it per session (see §9). |
| **SSE / Streamable HTTP** | The server listens on an HTTP port; clients connect over the network. | **Local or remote** — any host Claude can reach. | A persistent, port-published, auto-restarting Compose service (main path). |

**Key decision:** if the server runs on a *separate Linux box* from your
Claude app, it **must be SSE/HTTP** — stdio can't cross the network. Use
stdio only when the container runs on the same machine as Claude. The main
path below assumes an SSE/HTTP server on a port (we'll use `8000`).

---

## 1. Prepare the host (one-time)

```bash
curl -fsSL https://get.docker.com | sudo sh     # Docker Engine
docker --version && docker compose version      # expect 24.x+, Compose v2.x

sudo usermod -aG docker "$USER" && newgrp docker   # run docker without sudo
sudo systemctl enable --now docker                 # start on boot (so restart policies survive reboots)
```

---

## 2. What files the build needs

A Docker image is built from a **build context** — a directory the
Dockerfile can `COPY` from. The Dockerfile is only the *recipe*; it pulls in
your source, so you need the whole app folder, not just the Dockerfile.

| File | Required? | Purpose |
|---|---|---|
| **`Dockerfile`** | Yes | Build recipe: base image, install deps, copy source, start command. |
| **App source + dependency manifest** (`requirements.txt`, `package.json`, …) | Yes | The code and pinned deps the image installs. |
| **`docker-compose.yml`** | Yes (your setup) | Holds the run config — port map, restart policy, env file, volumes — in one file. |
| **`.dockerignore`** | Recommended | Keeps `.git/`, `venv/`, `node_modules/`, caches, `.env` out of the build context. |
| **`.env`** | If it needs secrets/config | Runtime config (keys, tokens). **Never baked into the image**; injected at start. |

> **You can't copy just the Dockerfile** — it `COPY`s your source, so the
> whole project folder must be present wherever you build.

---

## 3. Set up the directory, user, and permissions

Create the deploy directory and hand it to your login user so nothing runs
as root:

```bash
APP=my-mcp-server
sudo mkdir -p /opt/$APP
sudo chown "$USER":"$USER" /opt/$APP      # own it as your user
sudo chmod 755 /opt/$APP                   # you: rwx; others: read/traverse
```

Optional — run it under a dedicated non-login system user (must be in the
`docker` group):

```bash
sudo useradd --system --create-home --shell /usr/sbin/nologin mcpsvc
sudo usermod -aG docker mcpsvc
sudo chown -R mcpsvc:mcpsvc /opt/$APP
# then run compose as that user:  sudo -u mcpsvc docker compose ...
```

---

## 4. Get the files into that directory (both cases)

### Case A — the app is in a git repo → clone

```bash
git config --global credential.helper store   # optional: cache the PAT for private repos
cd /opt/my-mcp-server
git clone https://github.com/you/your-mcp-server.git .   # trailing dot = clone flat into THIS dir
ls   # expect: Dockerfile  docker-compose.yml  <source>  ...
```

The trailing `.` matters: `git clone <url>` nests a subfolder; `git clone
<url> .` clones flat into the current directory.

### Case B — not in a repo (or the host can't reach it) → copy it over

From the **project root on your dev machine** (`rsync` preferred — skips
heavy paths, re-runnable for updates):

```bash
rsync -av --delete \
  --exclude '.git/' --exclude 'venv/' --exclude '.venv/' \
  --exclude 'node_modules/' --exclude '__pycache__/' --exclude '*.py[cod]' \
  ./ deployuser@LINUX_HOST:/opt/my-mcp-server/
```

No `rsync`? `scp -r ./ deployuser@LINUX_HOST:/opt/my-mcp-server/` works — then
`rm -rf` any bulky `venv/` / `node_modules/` on the server. Confirm the
Dockerfile and source landed at the top level: `cd /opt/my-mcp-server && ls`.

---

## 5. Configuration & secrets (`.env`)

Keep secrets out of the image and out of git. Create `.env` **on the server**
and lock it down:

```bash
cp .env.example .env    # if the project ships a template; else create it
nano .env               # keys, tokens, connection strings, PORT, etc.
chmod 600 .env          # owner read/write only
```

Values are injected at start via Compose `env_file:` — never baked into the
image. Ensure `.env` is in `.dockerignore` and `.gitignore`.

---

## 6. Write the Dockerfile

Slim base, install deps in their own layer (so code edits don't bust the dep
cache), copy source, expose the port, set the start command.

**Python (SSE/HTTP server):**

```dockerfile
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
# Bind 0.0.0.0 so the published port reaches it. Adjust module/flags.
CMD ["python", "-m", "your_mcp_server", "--host", "0.0.0.0", "--port", "8000"]
```

**Node / TypeScript (SSE/HTTP server):**

```dockerfile
FROM node:22-slim
WORKDIR /app
COPY package*.json ./
RUN npm ci --omit=dev
COPY . .
# If TypeScript: RUN npm run build
EXPOSE 8000
ENV PORT=8000
CMD ["node", "dist/index.js"]
```

Two gotchas: **bind `0.0.0.0`** (not `127.0.0.1`, which is unreachable
through the port), and use **exec-form `CMD`** (JSON array) so `docker stop`
shuts down cleanly.

---

## 7. `docker-compose.yml`

Place it next to the Dockerfile. Every run setting lives here:

```yaml
services:
  mcp:
    build:
      context: .              # build context = this dir (holds the source)
      dockerfile: Dockerfile
    image: my-mcp-server:local
    container_name: my-mcp-server

    restart: unless-stopped   # auto-restart on crash + host reboot; respects a manual stop

    ports:
      - "8000:8000"           # host:container — the left side is what you connect to

    env_file:
      - .env                  # runtime secrets/config; never baked in

    # volumes:                # only if the server persists data / overlays config
    #   - ./data:/app/data
```

`restart:` values: `no` (default), `on-failure`, `unless-stopped` (the safe
server default — crash + boot, but not after a manual stop), `always`.

---

## 8. Build, run, and verify

You have Compose, so it's one command (build + start detached, with the
restart policy from §7):

```bash
cd /opt/my-mcp-server
docker compose up -d --build
```

`--build` is needed on the first run and after any code/dependency change. A
`docker-compose.yml`-only change just needs `docker compose up -d`.

```bash
# verify
docker compose ps
docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' my-mcp-server   # unless-stopped
docker compose logs -f mcp
curl -s -i http://localhost:8000/mcp/sse    # or your server's actual MCP path
docker kill my-mcp-server && sleep 3 && docker compose ps   # proves auto-restart
```

Note the URL your server exposes — host, the published port, and the exact
path (e.g. `http://<host>:8000/mcp/sse`). You need it for the config below.

---

## 9. Point Claude at your server — editing the Claude config

The two transports are configured differently. **Fully quit and reopen
Claude Desktop after any config edit** — `mcpServers` is only read at startup.

**Config file location (Claude Desktop):**

| OS | Path |
|---|---|
| **macOS** | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| **Windows** | `%APPDATA%\Claude\claude_desktop_config.json` |
| **Linux** (community builds) | `~/.config/Claude/claude_desktop_config.json` |

Or open it from the app: **Settings → Developer → Edit Config**.

### Case 1 — stdio server (local, container-launched)

Claude launches the container itself, once per session, over stdin/stdout —
no `-d`, no `-p`, no `--restart`; `-i` (keep stdin open) and `--rm`
(ephemeral) are the key flags:

```json
{
  "mcpServers": {
    "My_MCP_Server": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "--env-file", "/opt/my-mcp-server/.env", "my-mcp-server:local"]
    }
  }
}
```

(Not containerized? Point `command`/`args` at the binary directly, e.g.
`"command": "node", "args": ["/opt/my-mcp-server/dist/index.js"]`, with an
optional `"env": { … }` block.) **stdio only works on the same machine as
Claude.**

### Case 2 — SSE / HTTP server over a port (local or remote)

`claude_desktop_config.json` only validates *stdio* servers — a raw `"url"` /
`"type":"http"` entry is silently ignored. So you bridge the networked
server into a stdio command with **`mcp-remote`** (a small `npx` shim; needs
Node/`npx` on the machine running Claude). Point it at `host:port/path` and
force the transport.

**SSE endpoint** — same shape as your working Flow MCP config:

```json
{
  "mcpServers": {
    "My_MCP_Server": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote",
        "http://LINUX_HOST:8000/mcp/sse",
        "--transport",
        "sse-only",
        "--allow-http"
      ]
    }
  }
}
```

**Streamable HTTP endpoint** — identical, just a different transport flag and
(usually) path:

```json
{
  "mcpServers": {
    "My_MCP_Server": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote",
        "http://LINUX_HOST:8000/mcp",
        "--transport",
        "http-only",
        "--allow-http"
      ]
    }
  }
}
```

The args, decoded:
- **URL** — host/IP, the published port (§7's left-hand port), and the exact
  MCP path your server serves (`/mcp/sse` for SSE, often `/mcp` for HTTP).
- **`--transport sse-only` / `http-only`** — force the transport instead of
  auto-negotiating. Match it to your endpoint. (Omit the flag entirely to let
  `mcp-remote` auto-detect.)
- **`--allow-http`** — allow a plain, non-TLS `http://` URL. **Omit it when
  the server is behind `https://`** — `mcp-remote` refuses non-TLS without it.

> Your real, working reference (Flow MCP over SSE on port 80):
> ```json
> "BCQ_Flow_MCP": {
>   "command": "npx",
>   "args": ["-y", "mcp-remote", "http://10.44.135.12:80/mcp/sse", "--transport", "sse-only", "--allow-http"]
> }
> ```

**Prefer no file editing?** For an **HTTPS**-reachable endpoint, use
**Settings → Connectors → Add custom connector** and paste the URL instead.

### If you use Claude Code (CLI) instead of Desktop

Claude Code takes SSE/HTTP natively — no `mcp-remote` bridge:

```bash
claude mcp add --transport sse  My_MCP_Server http://LINUX_HOST:8000/mcp/sse   # SSE
claude mcp add --transport http My_MCP_Server http://LINUX_HOST:8000/mcp       # Streamable HTTP
claude mcp add My_MCP_Server -- docker run -i --rm --env-file /opt/my-mcp-server/.env my-mcp-server:local  # stdio
claude mcp list
```

### Confirm

Restart Claude Desktop (or `claude mcp list`). The server's tools should show
under the tools/plug icon.

---

## 10. Updating later

- **Cloned (Case A):** `git pull` → `docker compose up -d --build`.
- **Copied (Case B):** re-run the same `rsync` → `docker compose up -d --build`.
- `docker-compose.yml`-only change: `docker compose up -d` (recreates without rebuild).
- **Claude config** change: full **restart of Claude Desktop** (not a container action).

---

## Appendix — exposing an HTTP/SSE server safely (if it leaves the LAN)

Fine on a trusted network on a raw port. If it's reachable more broadly:
put it behind a reverse proxy (Caddy / nginx / Traefik) for **TLS** (then
drop `--allow-http` and use the `https://` URL); add **authentication** (an
open MCP endpoint = open tool access); and bind the port to a specific
interface (`-p 127.0.0.1:8000:8000`) fronted only by the proxy.

---

## Quick checklist

- [ ] Transport decided — remote host ⇒ **SSE/HTTP**; same machine ⇒ stdio ok
- [ ] Host has Docker + Compose v2; daemon enabled on boot
- [ ] Deploy dir under `/opt`, `chown`ed to the run user, `chmod 755`
- [ ] Build context on the host: **`git clone .`** (repo) **or** **`rsync`/`scp`** (folder)
- [ ] Dockerfile present; SSE/HTTP binds `0.0.0.0`; exec-form `CMD`
- [ ] `.env` on the server, `chmod 600`, in `.dockerignore` + `.gitignore`
- [ ] `docker-compose.yml` with `restart: unless-stopped` + port map; `docker compose up -d --build`
- [ ] Verified: `docker compose ps`, restart policy, port responds, kill-test heals
- [ ] **Claude config edited:** stdio ⇒ `command/args`; SSE/HTTP ⇒ `mcp-remote` (`--transport sse-only`/`http-only`, `--allow-http` for plain http) or `claude mcp add --transport …`
- [ ] Claude Desktop fully restarted; tools visible
- [ ] (If exposed beyond LAN) TLS + auth in front of it
