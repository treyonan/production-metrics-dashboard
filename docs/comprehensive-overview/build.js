// Build the comprehensive overview docx for the production-metrics-dashboard.
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, ImageRun,
  Header, Footer, AlignmentType, PageOrientation, LevelFormat, ExternalHyperlink,
  TabStopType, TabStopPosition, SectionType, TableOfContents, HeadingLevel,
  BorderStyle, WidthType, ShadingType, VerticalAlign, PageNumber, PageBreak,
} = require("docx");

// Paths -- resolved relative to this file. Run from this directory:
//   npm install   # one-time, fetches docx into ./node_modules
//   node build.js # writes production-metrics-dashboard-overview.docx in place
const PICS = path.join(__dirname, "pics");
const OUT = path.join(__dirname, "production-metrics-dashboard-overview.docx");

// Image helpers
function img(filename, widthPx, heightPx, altTitle) {
  return new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 120, after: 60 },
    children: [
      new ImageRun({
        type: "jpg",
        data: fs.readFileSync(path.join(PICS, filename)),
        transformation: { width: widthPx, height: heightPx },
        altText: { title: altTitle, description: altTitle, name: filename },
      }),
    ],
  });
}
function caption(text) {
  return new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 240 },
    children: [new TextRun({ text, italics: true, size: 18, color: "595959" })],
  });
}

// Text helpers
function p(text, opts = {}) {
  return new Paragraph({
    spacing: { after: opts.after ?? 120, line: 300 },
    children: [new TextRun({ text, ...(opts.run || {}) })],
  });
}
function h1(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    pageBreakBefore: true,
    children: [new TextRun({ text })],
  });
}
function h2(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2,
    children: [new TextRun({ text })],
  });
}
function h3(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_3,
    children: [new TextRun({ text })],
  });
}
function bullet(text) {
  return new Paragraph({
    numbering: { reference: "bullets", level: 0 },
    spacing: { after: 80, line: 290 },
    children: [new TextRun({ text })],
  });
}
function bulletRich(runs) {
  return new Paragraph({
    numbering: { reference: "bullets", level: 0 },
    spacing: { after: 80, line: 290 },
    children: runs,
  });
}
function code(text) {
  // Pre-formatted block: monospace, light gray background.
  const lines = text.split("\n");
  return lines.map(
    (line, i) =>
      new Paragraph({
        spacing: { after: i === lines.length - 1 ? 200 : 0, line: 240 },
        shading: { fill: "F4F4F4", type: ShadingType.CLEAR },
        indent: { left: 240 },
        children: [
          new TextRun({
            text: line || " ",
            font: "Consolas",
            size: 18,
          }),
        ],
      })
  );
}
function inlineCode(text) {
  return new TextRun({ text, font: "Consolas", size: 20 });
}

// =================== DOCUMENT BODY ===================

const children = [];

// ---------------- Cover Page ----------------
children.push(
  new Paragraph({ spacing: { before: 2400 }, children: [new TextRun(" ")] }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 200 },
    children: [new TextRun({ text: "PRODUCTION METRICS DASHBOARD", bold: true, size: 56 })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 200 },
    children: [new TextRun({ text: "Comprehensive Overview", size: 36, color: "595959" })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 1200 },
    children: [new TextRun({ text: "Dolese Bros Co — Plant Operations", size: 24, color: "595959" })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 4800, after: 60 },
    children: [new TextRun({ text: "May 1, 2026", size: 22 })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 60 },
    children: [new TextRun({ text: "Internal — Engineering and Management", size: 20, italics: true, color: "595959" })],
  })
);

// ---------------- Table of Contents ----------------
children.push(
  new Paragraph({ pageBreakBefore: true, children: [new TextRun(" ")] }),
  new Paragraph({
    spacing: { after: 240 },
    children: [new TextRun({ text: "Table of Contents", bold: true, size: 32 })],
  }),
  new TableOfContents("Contents", { hyperlink: true, headingStyleRange: "1-2" })
);

// ---------------- 1. Executive Summary ----------------
children.push(
  h1("1. Executive Summary"),
  p(
    "The production-metrics-dashboard is a read-only web application that collects SCADA data from three sources — a SQL Server database, the Flow Software REST API, and (planned) the Timebase API for site-server time-series data — and serves it to a polling browser dashboard for plant operators, engineers, and management."
  ),
  p(
    "The architecture is intentionally simple: a thin FastAPI backend with a clean abstraction (the Source Protocol) between routes/services and the underlying data sources. This separation enables one dashboard, one API, and a single response contract that can serve multiple consumers — the browser dashboard today, and tomorrow potentially Excel-based reports, Ignition operator screens, or external integrations — without the per-tool data-plumbing duplication that plant tools have historically suffered from."
  ),
  p(
    "The system runs in a Docker container on a standalone Linux microservices server, separate from the Windows hosts that run SQL Server and Flow. It is read-only by design at both the API level and the SQL grant level, dramatically reducing blast radius. It polls every 1–5 minutes — fast enough for the freshness budgets of end-of-shift production reports and sub-minute interval metrics, and slow enough to avoid the operational complexity of WebSockets or real-time streams. Today it serves three views: a per-shift Dashboard, a monthly Trends view, and a new Flow Interval Metrics page that exposes Flow’s aggregated time-series directly."
  )
);

// ---------------- 2. What This Is ----------------
children.push(
  h1("2. What This Is"),
  p(
    "Plant operations need a near-real-time view of production performance — tons produced per shift, runtime hours, OEE (computed by Flow as availability × performance × quality), per-conveyor breakdowns, monthly trend lines. All of these are already curated, governed, and controlled inside Flow; the API’s job is to surface them, not to derive them. The underlying data already exists in the plant’s SCADA systems, but it lives in three different shapes:"
  ),
  bullet("SQL Server (Flow_Curated): end-of-shift OEE summaries, one row per workcenter per report. Includes a JSON payload with finer detail like per-conveyor tons, downtime reasons, weather, and operator notes."),
  bullet("Flow Software REST API: aggregated interval metrics (shiftly Total tons, Rate TPH, etc.) on demand for any time window. Discovery of which metrics exist for a given asset is published via MQTT and indexed in a SQL tag table."),
  bullet("Timebase API (planned): time-series data captured at the site servers. Under consideration as a third source when Flow’s aggregations aren’t granular enough — e.g. tag-level history at sub-minute cadence."),
  p("The dashboard polls the FastAPI every 30–60 seconds and renders three views — each tailored to a different consumption pattern — from a single browser application.", { after: 200 }),
  img("dashboard-multiple-production-report.jpg", 612, 193, "Dashboard view showing multiple workcenter production reports for one site."),
  caption("Figure 1. Dashboard view — multiple workcenters at one site, end-of-shift production reports.")
);

// ---------------- 3. Why This Architecture ----------------
children.push(
  h1("3. Why This Architecture"),
  p(
    "Five design decisions shape the system. None of them are unusual on their own; together they keep the codebase small, the deployment surface manageable, and the path to future change open."
  ),

  h2("3.1. Fan-out from one backend"),
  p(
    "SCADA-adjacent tools at this site have historically each owned their own data plumbing — every Excel spreadsheet, every Ignition view, every web tool wrote its own SQL queries and HTTP calls to reach Flow’s curated data. The duplication had a real cost: each tool wired to a slightly different version of the schema, filtered nulls differently, or skipped a column that turned out to matter, and tools quietly drifted out of agreement with each other."
  ),
  p(
    "Centralizing the transport in one service means every consumer sees the same already-curated, Flow-governed data. The API does not compute OEE, run production math, or derive its own numbers — Flow is the system of record for all of that. The API’s job is to collect data from Flow (via the curated SQL tables and the Flow REST API), validate the shape, and package it behind a single Pydantic contract. New consumers — a future Ignition gateway script, an Excel report, a mobile app — call the same API endpoint and get the same numbers, with the same field names and the same null semantics, every time."
  ),

  h2("3.2. Source Protocol abstraction"),
  p(
    "Every data source (SQL Server today, Flow REST today, Timebase API tomorrow) implements a small Python Protocol — typically just a few async methods like fetch_for_range(). Routes call services; services call the source. Swapping SQL for Timebase in 2027 means writing one new module and changing one DI provider, not threading database concerns through every endpoint."
  ),
  p(
    "Critically, this also means tests don’t need a live database. The test suite injects a CSV-backed test fixture for the production-report tests and a fake-aioodbc plus mock-httpx test double for the interval-metric tests. The full suite (~91 tests) runs in seconds without the network."
  ),

  h2("3.3. Read-only by design"),
  p(
    "No endpoint mutates data. The SQL account used by the API has read-only grants at the database layer as defense in depth. This dramatically reduces the blast radius of any bug or compromise: at worst the dashboard returns wrong data, never wrong writes. It also simplifies deployment posture — no transaction concerns, no replication lag worries, no rollback procedures."
  ),

  h2("3.4. Polling, not real-time"),
  p(
    "The dashboard refreshes every 30 seconds. Production reports update at end-of-shift (twice per day); interval metrics update on Flow’s publish cadence (sub-minute). A 30-second polling loop is well within the freshness budget for either, and avoids the operational complexity of WebSockets or Server-Sent Events for an internal dashboard."
  ),
  p(
    "Periodic polls also enable simple TTL caching: a 30–60 second response cache means N concurrent clients fan into one upstream call. Today the cache is in-memory; if the deployment grows to multi-worker, Redis is a small swap behind the same SnapshotStore Protocol."
  ),

  h2("3.5. Linux Docker on a standalone microservices server"),
  p(
    "Production runs in a Docker container on a dedicated Linux microservices server, separate from the Windows hosts that run SQL Server and Flow. The separation is intentional: the API has no privileged co-location with any data source, talks to all of them over the network, and can be redeployed, restarted, or migrated without touching anything on the SQL or Flow boxes. The microservices host is single-purpose; an operations team can manage it independently of the data infrastructure."
  ),
  p(
    "ODBC Driver 18 has a Linux build that talks to SQL Server over network ODBC; httpx talks to the Flow REST API over HTTP; both flow over standard internal-network paths. The Linux Docker image is small (a few hundred MB) and rebuilds quickly. A separate dev path — venv on a Windows workstation — is used for local development, but production is Linux."
  )
);

// ---------------- 4. Data Flows ----------------
children.push(
  h1("4. Data Flows"),
  p(
    "The system’s data flows fall into two domains. Each domain has its own response contract, its own integration module, and its own URL namespace. They are deliberately not co-mingled at the API surface — a future migration of one domain (for example, swapping Flow REST out for Timebase as a third source) doesn’t require coordinated changes to the other."
  ),

  h2("4.1. Domain 1 — Production Reports"),
  p(
    "Flow Software runs end-of-shift calculations and writes one row per workcenter per shift to [Flow_Curated].[FLOW].[PRODUCTION_REPORT]. The row contains the basic OEE numbers (Availability, Performance, Quality, Total tons, Runtime hours) plus a JSON PAYLOAD blob with finer detail — per-conveyor tons, downtime reasons, weather, the operator name, etc."
  ),
  p("The API exposes four endpoints over this data, each tuned to a specific consumption pattern:"),
  bulletRich([inlineCode("GET /api/production-report/latest?site_id=101"), new TextRun(" — most recent report per workcenter, for the live dashboard.")]),
  bulletRich([inlineCode("GET /api/production-report/range?site_id=101&from_date=...&to_date=..."), new TextRun(" — historical window, for the day/month time filters.")]),
  bulletRich([inlineCode("GET /api/production-report/monthly-rollup?site_id=101"), new TextRun(" — monthly aggregates assembled from the curated production-report rows for the Trends view. Today this is a small convenience the API performs over already-curated data; Flow can publish equivalent rolled-up interval data directly when wired in.")]),
  bulletRich([inlineCode("GET /api/production-report/circuit-monthly-rollup?site_id=101"), new TextRun(" — hierarchical per-circuit and per-line rollup for the Trends circuit charts.")]),
  p("A typical request flows: Browser → FastAPI route handler (validates input) → service layer (validates window, applies caching, calls source) → SqlProductionReportSource (loads parameterized query from select_all.sql, executes via aioodbc) → service formats result → Pydantic envelope → JSON response. Cold latency for a 30-day window is roughly 150 ms; cached latency is single-digit milliseconds."),
  img("dashboard-single-production-report.jpg", 612, 197, "Single workcenter production report view."),
  caption("Figure 2. Dashboard view — single workcenter, current shift, with KPI cards and per-conveyor table."),
  p("The dashboard’s details modal exposes the JSON payload’s richer fields — weather, notes, operator metadata — grouped by base type for readability."),
  img("dashboard-report-details.jpg", 432, 301, "Production report details modal popup."),
  caption("Figure 3. Production report details modal — site metadata, weather, and operator notes from the JSON payload.")
);

children.push(
  h2("4.2. Domain 2 — Interval Metrics"),
  p("The interval-metrics path has two halves: a discovery side that runs entirely in Ignition, and a fetch side that runs in the FastAPI."),
  h3("Discovery (Ignition + MQTT → SQL tag table)"),
  p("When Flow Software publishes a value-change MQTT payload that includes a static history URL for a metric, an Ignition tag-change script (scada/ignition/upsert_interval_metric_tag.py) MERGEs a row into [FLOW].[INTERVAL_METRIC_TAGS] keyed by (site_id, department_id, asset, metric_name, interval). The row stores the URL to fetch that metric’s history. This piece runs on Ignition’s gateway in Jython 2.7; the FastAPI never sees MQTT directly."),
  p("The natural key is wider than a typical asset id because the same physical asset can carry per-department metrics independently — conveyor C4 in department 127 and the same conveyor in department 130 produce two distinct rows by design. The asset value is caller-supplied, which lets the same Ignition trigger handle conveyor metrics (asset = the conveyor number), workcenter metrics (asset = the area name), or sub-circuit metrics (asset = the description from the event payload) without a separate trigger per shape."),
  h3("Fetch (FastAPI → Flow REST API)"),
  p("When a consumer asks for interval-metric history, the API resolves matching tag rows, substitutes [PeriodStart]/[PeriodEnd] placeholders in the stored URL with ISO 8601 timestamps, fans out to the Flow REST API via httpx.AsyncClient, parses the responses, and returns a unified envelope. Six subject types are supported — conveyor, workcenter, circuit, line, equipment, site — with the Literal validator catching typos at the path layer before any database or HTTP work happens."),
  p("Two endpoints serve the read side:"),
  bulletRich([inlineCode("GET /api/metrics/{subject_type}/subjects?site_id=101"), new TextRun(" — cheap discovery, a single SELECT with no upstream HTTP fan-out. Useful for Ignition dropdowns, dashboard inventory pages, and freshness checks (last_seen tells you when the tag last published).")]),
  bulletRich([inlineCode("GET /api/metrics/{subject_type}/{interval}?site_id=...&from_date=...&to_date=..."), new TextRun(" — fetches the time series. Filters compose: site_id and dates are required; department_id, subject_id, and metric are optional and combine.")]),
  p("The Flow Interval Metrics page in the frontend is the human-facing tool for browsing this data. It is a standalone page (not a dashboard tab) reachable from the dashboard’s topbar via the Flow Metrics link. Its existence keeps the dashboard tabs focused on the production-report aggregations while still exposing the secondary data source through a polished UI rather than only through Swagger."),
  img("flow-metrics.jpg", 600, 299, "Flow Interval Metrics page."),
  caption("Figure 4. Flow Interval Metrics page — secondary data source with grouped form layout (Context / Filters / Date range) and results table.")
);

// ---------------- 5. API Surface ----------------
children.push(
  h1("5. API Surface"),
  p("The API is intentionally small. Endpoints follow a few consistent patterns; once you understand one, you understand the rest."),
  h2("5.1. Endpoint inventory"),
  bulletRich([inlineCode("GET /api/health"), new TextRun(" — per-source reachability for the dashboard’s status pill.")]),
  bulletRich([inlineCode("GET /api/sites"), new TextRun(" — site IDs and display names.")]),
  bulletRich([inlineCode("GET /api/production-report/latest?site_id="), new TextRun(" — current-shift report per workcenter.")]),
  bulletRich([inlineCode("GET /api/production-report/range?site_id=&from_date=&to_date="), new TextRun(" — historical window, 1–400 days.")]),
  bulletRich([inlineCode("GET /api/production-report/latest-date?site_id="), new TextRun(" — most recent date with data; drives the date picker.")]),
  bulletRich([inlineCode("GET /api/production-report/monthly-rollup?site_id="), new TextRun(" — per-month KPI aggregates.")]),
  bulletRich([inlineCode("GET /api/production-report/circuit-monthly-rollup?site_id="), new TextRun(" — hierarchical circuit/line monthly rollups.")]),
  bulletRich([inlineCode("GET /api/metrics/{subject_type}/subjects?site_id="), new TextRun(" — interval-metric tag inventory.")]),
  bulletRich([inlineCode("GET /api/metrics/{subject_type}/{interval}?site_id=&from_date=&to_date="), new TextRun(" — interval-metric history.")]),
  bulletRich([inlineCode("GET /api/__ping"), new TextRun(" — build fingerprint for verifying which build is live.")]),
  bulletRich([inlineCode("GET /docs"), new TextRun(" — Swagger UI for interactive exploration of all endpoints.")]),

  h2("5.2. Worked example — GET /api/production-report/range"),
  p("A 30-day window for site 101 is fetched with:"),
  ...code('GET /api/production-report/range?site_id=101&from_date=2026-04-01&to_date=2026-04-30'),
  p("The response is a Pydantic envelope (abridged):"),
  ...code(`{
  "count": 42,
  "site_id": "101",
  "from_date": "2026-04-01",
  "to_date": "2026-04-30",
  "generated_at": "2026-04-30T20:14:06Z",
  "entries": [ { ...one row per shift per workcenter... } ],
  "conveyor_totals": {
    "101:127": {
      "per_conveyor": { "C4": 3543.3, "C5": 2330.2, ... },
      "grand_total": 13966.3,
      "conveyors_counted": 7,
      "reports_counted": 1
    }
  }
}`),
  p("The implementation walks four layers, each with a single clear responsibility — none of which compute or derive a curated number; the curated values come straight from Flow:"),
  bulletRich([new TextRun({ text: "Route", bold: true }), new TextRun(" — backend/app/api/routes/production_report.py. Validates query parameters, calls the service, serialises the result.")]),
  bulletRich([new TextRun({ text: "Service", bold: true }), new TextRun(" — backend/app/services/production_report.py. Validates window length, applies SnapshotStore TTL caching, calls the source, packages the result for the route.")]),
  bulletRich([new TextRun({ text: "Source", bold: true }), new TextRun(" — backend/app/integrations/production_report/sql_source.py. Implements the Source Protocol against aioodbc.")]),
  bulletRich([new TextRun({ text: "Query", bold: true }), new TextRun(" — backend/app/integrations/production_report/queries/select_all.sql. Loaded at module import; parameterized with ? placeholders. Never built via string formatting.")]),

  h2("5.3. Common patterns across all endpoints"),
  p("Every response is a Pydantic model, never a bare dict. Even /api/health has a schema. This catches shape regressions during refactors and gives Swagger / ReDoc accurate documentation for free."),
  p("Caching lives at the service layer behind a SnapshotStore Protocol with TTL gating. Default TTLs: 5 minutes for hourly metric requests, 15 minutes for shiftly. Production-report endpoints use shorter TTLs since the underlying data updates less frequently and the queries are cheap."),
  p("Errors return structured HTTPException with status and detail: 503 when a source is unreachable, 422 for invalid input (window too wide, unknown literal value, date inversion), 502 when an upstream returns a non-2xx, 504 for upstream timeouts. The frontend renders per-tile status rather than blanking the whole page — a SQL outage means the production-report panel goes red while the metrics panel stays alive."),
  p("Every request gets a correlation ID via middleware. Structured JSON logs (via structlog) include the correlation ID on every line, so a problem reported by an operator can be traced from the browser through every layer.")
);

// ---------------- 6. Frontend Pages ----------------
children.push(
  h1("6. Frontend Pages"),
  p("The frontend is vanilla HTML, CSS, and JavaScript with no build step. Chart.js is vendored locally so the dashboard works offline-capable. Theme (light/dark) is persisted in localStorage and shared across all pages."),
  h2("6.1. Dashboard view"),
  p("Two layouts: single-workcenter (one big panel with KPI cards and per-conveyor table; see Figure 2) and multi-workcenter (one card per workcenter for at-a-glance comparison across the site; see Figure 1). Time filter mode switches between Day (single date picker) and Month (month + year pickers); the same /api/production-report/range endpoint serves both modes."),
  p("The Dashboard view is the operator and engineering view by default. Management readers tend to land on the Trends view instead."),
  h2("6.2. Trends view"),
  p("The Trends view shows monthly rollups of the same production-report data. A vertical tab sidebar provides navigation between subsections — Overview, per-Workcenter, Circuit (hierarchical), and Line. Charts are rendered with Chart.js. The vertical-tab UX scales better than horizontal tabs as more rollup categories are added."),
  img("trends.jpg", 600, 248, "Trends view with vertical tab sidebar and monthly rollup charts."),
  caption("Figure 5. Trends view — monthly rollups, vertical-tab navigation, Chart.js bar charts."),
  h2("6.3. Flow Interval Metrics page"),
  p("The Flow Interval Metrics page (see Figure 4) is the human-facing entry point to Domain 2. It is intentionally a separate page rather than a dashboard tab so the main dashboard layout stays focused on the production-report data; Flow data is presented as a secondary source alongside, not as a replacement."),
  p("The form layout groups inputs into Context (site_id, subject_type, interval), optional Filters (subject_id, department_id, metric), and Date range. The results table uses the same monospace timestamp formatting and right-aligned numeric columns as the dashboard tables, so a reader switching between the two pages reads numbers consistently."),
  h2("6.4. Excel export"),
  p("All visible tables and chart data are exportable to .xlsx via a single Excel button in the topbar. The exported file mirrors the displayed data — every field shown in the table or details modal is in the workbook by default; omissions are explicit. SheetJS (vendored) does the encoding entirely client-side, so no round-trip to the server is required.")
);

// ---------------- 7. What's TBD ----------------
children.push(
  h1("7. What’s TBD"),
  p("A few decisions are deliberately deferred. Each is recorded in tasks/decisions/ as it lands; the items below are still open at the time of writing."),
  bullet("Authentication. Today the API is deployed inside the corporate network and binds behind a reverse proxy. Decide between staying network-restricted, adding basic / bearer token auth, or integrating with Windows AD or OIDC. Must be resolved before any deployment beyond the internal network."),
  bullet("Frontend technology evolution. Vanilla HTML+JS shipped quickly and remains low-maintenance for a polling dashboard. A future React + Vite migration is plausible if interactivity needs grow; the trade-offs are documented in tasks/decisions/."),
  bullet("Audience-specific views. Engineers, operators, and management have different priorities. Today: one dashboard with a role-blind layout. Future: role-aware views or separate URL paths per audience."),
  bullet("Timebase API integration. Time-series data captured at the site servers (Timebase) is a possible additional source alongside Flow REST. Decide whether and when to wire it in based on the granularity needed — Flow covers shiftly and hourly aggregations today; Timebase would unlock sub-minute tag-level access when that’s required."),
  bullet("Multi-worker caching. The in-memory SnapshotStore is single-worker. Redis behind the same Protocol unlocks horizontal scaling when needed."),
  bullet("Migrating production-report rollups to Flow-sourced metrics. Phase 16 confirmed the Flow REST pipeline works end-to-end. A future phase would replace the in-service shiftly aggregation with direct Flow queries, removing one layer of math from the API.")
);

// ---------------- 8. Pointers ----------------
children.push(
  h1("8. Where to read more"),
  p("This overview deliberately stays at narrative depth. The detailed reference material lives elsewhere in the repository:"),
  bulletRich([new TextRun({ text: "ARCHITECTURE.md", font: "Consolas", size: 20 }), new TextRun(" — backend layer responsibilities, the Source Protocol pattern, recipes for adding endpoints and sources.")]),
  bulletRich([new TextRun({ text: "docs/data-flows.md", font: "Consolas", size: 20 }), new TextRun(" — both data-flow domains in detail with full response shapes and integration triggers.")]),
  bulletRich([new TextRun({ text: "RUNBOOK.md", font: "Consolas", size: 20 }), new TextRun(" — how to run the backend (venv and Docker paths), URLs, tests, lint, troubleshooting.")]),
  bulletRich([new TextRun({ text: "PAYLOAD-CONTRACT.md", font: "Consolas", size: 20 }), new TextRun(" — what the production-report JSON payload contains and how it is consumed.")]),
  bulletRich([new TextRun({ text: "docs/server-deployment.md", font: "Consolas", size: 20 }), new TextRun(" — Linux server deploy, Docker container build and run specifics, repository layout invariants.")]),
  bulletRich([new TextRun({ text: "tasks/todo.md", font: "Consolas", size: 20 }), new TextRun(" — phase-by-phase implementation history with decisions captured per phase.")]),
  bulletRich([new TextRun({ text: "tasks/decisions/", font: "Consolas", size: 20 }), new TextRun(" — ADR-style architectural decision records.")]),
  bulletRich([new TextRun({ text: "tasks/lessons.md", font: "Consolas", size: 20 }), new TextRun(" — patterns learned from prior corrections; reviewed at each new session start.")])
);

// =================== DOCUMENT BUILD ===================

const doc = new Document({
  creator: "Production Metrics Dashboard project",
  title: "Production Metrics Dashboard — Comprehensive Overview",
  description: "Internal overview document for engineering and management.",
  styles: {
    default: {
      document: { run: { font: "Arial", size: 22 } }, // 11pt body
    },
    paragraphStyles: [
      {
        id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 36, bold: true, font: "Arial", color: "1F3864" },
        paragraph: { spacing: { before: 360, after: 240 }, outlineLevel: 0 },
      },
      {
        id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 28, bold: true, font: "Arial", color: "2E74B5" },
        paragraph: { spacing: { before: 240, after: 120 }, outlineLevel: 1 },
      },
      {
        id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 24, bold: true, font: "Arial", color: "404040" },
        paragraph: { spacing: { before: 160, after: 80 }, outlineLevel: 2 },
      },
    ],
  },
  numbering: {
    config: [
      {
        reference: "bullets",
        levels: [
          { level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
            style: { paragraph: { indent: { left: 720, hanging: 360 } } } },
        ],
      },
    ],
  },
  sections: [{
    properties: {
      page: {
        size: { width: 12240, height: 15840 }, // US Letter
        margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 }, // 1 inch
      },
    },
    footers: {
      default: new Footer({
        children: [new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [
            new TextRun({ text: "Production Metrics Dashboard — Comprehensive Overview   •   Page ", size: 18, color: "808080" }),
            new TextRun({ children: [PageNumber.CURRENT], size: 18, color: "808080" }),
            new TextRun({ text: " of ", size: 18, color: "808080" }),
            new TextRun({ children: [PageNumber.TOTAL_PAGES], size: 18, color: "808080" }),
          ],
        })],
      }),
    },
    children,
  }],
});

Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync(OUT, buf);
  console.log("Wrote", OUT, buf.length, "bytes");
});
