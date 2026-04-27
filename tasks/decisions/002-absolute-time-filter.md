# ADR 002 — Absolute-window time filter

**Status:** Accepted, 2026-04-24
**Context:** Phase 7 redesign of the dashboard's time filter. See
`tasks/todo.md` Phase 7 for the full scope; this document records the
decision + rationale.

## Context

Phase 2.1 shipped a three-button time filter (Today / Week / Month)
backed by a single ``GET /api/production-report/history?days=N``
endpoint. Each button mapped to a rolling window: 1 day, 7 days, 31
days relative to today (UTC).

Operational experience surfaced two problems:

1. **"Today" is almost always empty.** Production reports are
   end-of-shift artifacts. Before the first shift completes, Today
   has nothing in it. Operators and engineers learned to distrust
   the Today view because the useful questions were "yesterday,"
   "last Thursday," or "this month so far" -- not "the last 24
   hours rolling."
2. **"Week" is an awkward unit.** Production cadence is monthly.
   Seven days relative to today straddles whatever day of the month
   you happen to be on; it doesn't line up with any reporting
   boundary.

## Decision

Replace the rolling three-button filter with two absolute-window
controls:

- **Day mode:** a native ``<input type=date>`` picker. Defaults to
  "the most recent day with data" via a new
  ``GET /api/production-report/latest-date?site_id=X`` bootstrap
  endpoint.
- **Month mode:** month + year dropdowns (year spanning the last 5
  years). For the current month, the window auto-caps at today
  (month-to-date). Past months render the full calendar month.
  Future months render an empty-state window rather than clamping.

Backend:

- Add ``GET /api/production-report/range?from_date&to_date&site_id``
  with inclusive bounds, max window 400 days, 422 on any violation.
- Add ``GET /api/production-report/latest-date?site_id`` returning
  ``{site_id, latest_date: date | null}``.
- **Remove** ``GET /api/production-report/history``. No deprecation
  window -- no external consumers, and git retains the revert path
  if needed.

Frontend:

- Selection state (``{mode, dayDate, monthYear, monthMonth}``)
  persists via ``localStorage['pmd-time-filter']``.
- Rendering dispatches per-workcenter: a workcenter with one report
  in the window renders as KPI cards + asset table (the old Today
  layout); two or more reports render as the history table. Two
  workcenters on the same day can therefore have different layouts
  if one had a multi-shift day.
- Polling (30s) pauses when the selected window is fully in the
  past; re-arms when the selection pulls today back into range.
- XLSX export (Phase 6) now uses a single unified asset-row schema
  with Prod. Date + Report ID columns, so single-shift and
  multi-shift exports have consistent layout. Filename reflects the
  selection: ``_<YYYY-MM-DD>_`` for day mode,
  ``_<YYYY-MM>_`` for month mode.

## Consequences

Positive:

- Operators land on data they can actually read on first open
  (latest-date default), not an empty "Today" tile.
- Each mode's semantic question ("on this day" / "in this month")
  matches how production is actually discussed.
- Routes split by concern: ``/latest`` for "newest regardless of
  date," ``/range`` for absolute windows, ``/latest-date`` for the
  bootstrap. No dual-mode endpoints.
- Export becomes unambiguous -- one sheet shape regardless of
  window, all the identifying columns are present.
- Polling behavior becomes proportional to "does this view change":
  30s for current-day/month, paused otherwise.

Negative:

- One additional bootstrap call (``/latest-date``) on page load
  when no saved selection exists. Small cost; only runs on
  first-ever visit or after localStorage is cleared.
- Month-mode UI adds a second dropdown vs. the old single button.
  Two clicks instead of one to select "March." Acceptable given
  the gain in specificity.
- Removing ``/history`` breaks anything else that polled it.
  Nothing else does today, and git revert is the rollback path.

## Alternatives considered

- **Extend ``/history`` with optional ``from_date``/``to_date``.**
  Conflates rolling and absolute semantics in one endpoint;
  implicit precedence rule ("if ``from_date`` present, ``days`` is
  ignored") is a permanent documentation tax. Rejected.
- **Keep ``/history`` as a convenience for rolling-N-days.** Buys
  nothing -- clients wanting "last N days" can build
  ``from = today - (N-1); to = today`` against ``/range`` in one
  line. Dead code is not a safety net; git is. Rejected.
- **Date-range picker (two arbitrary dates).** More flexible than
  day + month but requires two date inputs and more user attention.
  Day + month covers the 95th-percentile workflow; full range is
  v2+ if operators ask for it.
- **Schema-driven month names.** Month-name list is committed
  in-tree for v1. Localization is not in scope.

## Related

- `tasks/todo.md` Phase 7 -- full implementation plan
- `tasks/decisions/001-stack-and-source-boundary.md` -- the
  Protocol-based source pattern that made the backend change
  trivial (service-level filter predicate swap, no integration
  changes)
- `backend/ARCHITECTURE.md` §6 -- endpoint reference
- `RUNBOOK.md` -- operator-facing documentation of the new filter
