# SPEC-004 — Timebase Trends page

**Status:** Draft / Implemented — 2026-05-21
**Parent:** SPEC-003 (Timebase i3X wrapper, Phase 1).
**Build tag:** `2026-05-21-phase26-timebase-trends-page`

## Context

Phase 1 (SPEC-003) shipped a read-only wrapper around per-site Timebase
historians: catalog endpoint, /history endpoint with tag_paths +
server-side dataset composition, gitignored YAML catalog. Backend was
verified end-to-end against the real BCQ historian on port 4511.

Phase 2 adds the operator-facing UI: a trend chart that lets users
pick a conveyor + metric and see the last 8 hours of samples.

## UX (locked with Trey 2026-05-21)

* **Fixed 8h window** -- the slider always moves the START of an 8h
  window, never resizes it. Removes a UX dimension.
* **Day stepper**: ← / → buttons step the date by one day; "next" is
  disabled at today.
* **Time slider**: 15-minute steps (0–96 positions across 24h, capped
  at `24h − 8h = 16:00` start). On today, additionally capped so the
  end can't exceed "now".
* **Default**: last 8 hours ending now.
* **Time zone**: browser-local (plant operators are on-site at BCQ;
  no per-site TZ override needed for v1).
* **Cumulative metrics** (`belt_scale_total`): chart shows delta from
  the first sample of the window — "tons produced in this window" —
  not the raw monotonic counter. Trigger: metric_key ending in `_total`.
* **Quality filter**: drop non-GOOD samples; footer shows the count.
* **Auto-refresh**: off. User-driven only; fetch fires on `Fetch`
  click or `Last 8h ending now` button.
* **Persistence**: site/dept/class/asset/metric selections saved in
  `localStorage['pmd-timebase-trends']` (per-page key; doesn't leak).

## Page isolation guarantees

The trend page is its own HTML + JS pair, page-scoped IIFE, no
globals, no timers, no polling. The only cross-page touch is one nav
link in `index.html`. Other pages never make Timebase calls.

**Soft revert** (no code changes): set `PMD_TIMEBASE_ENABLED=false`
in `backend/.env` and restart. Lifespan skips all Timebase init.

**Hard revert** (delete the feature): remove three frontend files
and one nav link. Backend can stay or be deleted independently.

## Backend additions (Phase 27)

* `PMD_TIMEBASE_ENABLED` (default true) — kill switch in
  `app/core/config.py`. When false, lifespan logs `timebase.disabled`
  and skips catalog load + client registry. No /api/health pings.
* `timebase_max_window_seconds` (default 28800 = 8h) — server-side
  cap on `(end_time - start_time)`. 422 if exceeded. Defense in depth
  against a direct API call asking for a year.
* `<= 0`-duration windows are also 422 (end <= start is nonsense).

## Frontend additions

* `frontend/timebase-trends.html` — full standalone page. Banner
  mirrors the main dashboard (40px topbar, 2px brand-yellow stripe,
  Dolese tokens). FOUC-prevention script applies persisted theme
  before CSS resolves. Theme toggle shared via `localStorage['pmd-theme']`.
* `frontend/timebase-trends.js` — IIFE; loads catalog once, builds
  cascading dropdowns (site → dept → class → asset → metric),
  computes window from day + slider, fetches `/api/timebase/history`,
  renders a Chart.js line chart. Quality filter + delta computation
  for cumulative metrics included.
* `frontend/index.html` — one new `<a class="vtab">` link to
  `/timebase-trends.html` after the Metrics link.

## Endpoints used

* `GET /api/timebase/catalog` — once on page load to populate dropdowns.
* `POST /api/timebase/history?site_id=<id>` — fired on every Fetch
  click; debounced naturally by being user-driven.

Request shape (snake_case):
```json
{
  "tag_paths": ["Big_Canyon/Secondary/Conveyor/C1/Process_Data/Belt_Scale/TPH"],
  "start_time": "2026-05-21T08:00:00-05:00",
  "end_time":   "2026-05-21T16:00:00-05:00",
  "max_depth": 1
}
```

Response keys are the caller's `tag_path` (dataset prefix stripped).

## Tests

Backend:
- 70 unit tests still pass (catalog 33, cache 20, client 17).
- 3 new route tests for window-cap + zero-window + 8h-boundary.
- ruff check clean.

Frontend:
- `node --check` validates JS syntax.
- Manual browser test pending on dev machine (requires reachable
  historian on `10.44.135.12:4511`).

## Acceptance

1. Load `http://localhost:8001/timebase-trends.html` while backend is
   running with `PMD_TIMEBASE_ENABLED=true`.
2. Catalog populates dropdowns with site 101 / BCQ / Secondary /
   Conveyor / C1..C8 / [belt_scale_tph, belt_scale_total].
3. Default fetch on page load returns the last 8h of TPH samples.
4. Dragging the slider changes the time window; clicking Fetch
   re-queries.
5. Day arrows step the date; "next" disables at today.
6. Switching to `belt_scale_total` shows the delta-from-start ramp.
7. `PMD_TIMEBASE_ENABLED=false` + restart: page loads HTML but
   catalog call returns 503 with the kill-switch message.

## Revision history

- 2026-05-21 — Initial Phase 27 / SPEC-004. Implemented same day.
