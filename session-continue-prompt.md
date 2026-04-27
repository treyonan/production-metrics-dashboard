I'm continuing work on production-metrics-dashboard after a previous
session. The project lives at
C:\Claude_Cowork\projects\production-metrics-dashboard.

Orient by reading (in order, per project CLAUDE.md):
1. CLAUDE.md (project root)
2. tasks/lessons.md
3. tasks/todo.md
4. PAYLOAD-CONTRACT.md (project root) -- draft contract for the
   production-report payload shape, pending team review
5. backend/ARCHITECTURE.md -- detailed FastAPI internals walkthrough
6. tasks/specs/002-interval-metric-sources.md -- draft spec for the
   next major domain (shiftly / hourly conveyor metrics etc.), pending
   my sample data

State as of end of last session:
- Phases 1-5 complete (see tasks/todo.md for details). Includes
  Dockerized deploy path, live SQL against Azure Managed SQL at
  IA_ENTERPRISE.[UNS].[SITE_PRODUCTION_RUN_REPORTS], per-conveyor
  bar chart under each workcenter panel with two-line x-axis labels
  (conveyor name + mode product description).
- pytest reports 56 passing on Python 3.12 Windows venv.
- Two-path dev loop works: uvicorn on port 8000, docker compose on
  port 8001.
- Frontend is bind-mounted into the container -- edits to frontend/
  and context/ don't require rebuild; backend edits do.

Open items ranked by my likely interest (pick any, or propose
something else):

1. Interval metrics (spec 002 drafted) -- blocked on me providing
   curated shiftly conveyor sample data. When I bring that, we
   resolve the Q1-Q9 open questions and start implementing.

2. Table "Total (tons)" column in the Week/Month history view --
   currently shows Workcenter.Total from the payload (often null,
   doesn't reconcile with the bar chart grand total). Candidate fix
   is to sum the CX.Total values per row. Frontend-only change; I
   wanted to decide separately from the KPI-grid removal we did.

3. Period-aggregate KPI view at the top of Week/Month -- deliberately
   NOT the latest-snapshot cards we just removed. Something like
   "avg Availability / avg Performance / SUM Runtime / SUM Total"
   over the window, clearly labeled. Frontend-only, optional.

4. Response caching via the SnapshotStore Protocol in
   backend/app/core/snapshot.py -- real load-risk mitigation before
   wide rollout. Shiftly/hourly metrics are more cache-friendly than
   production reports (append-only buckets).

5. Productionization (docker-compose.override.yml split for
   dev-only bind mounts, reverse proxy choice, image registry, prod
   .env provisioning).

Start by confirming you've read the orientation files, summarize the
project in 3-5 bullets so I can tell you have context, then ask me
which of the above I want to pursue (or if something else).