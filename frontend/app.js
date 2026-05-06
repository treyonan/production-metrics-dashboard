/* Production Metrics Dashboard client.
 *
 * Polls the FastAPI backend:
 *   GET /api/health                                                  - overall + per-source status
 *   GET /api/sites                                                   - site selector population
 *   GET /api/production-report/latest?site_id=X                      - 'latest per workcenter regardless of date'
 *   GET /api/production-report/range?from_date=&to_date=&site_id=    - records within an absolute date window
 *   GET /api/production-report/latest-date?site_id=X                 - bootstrap default for the day picker
 *
 * No framework, no build step. `fetch` + a 30s interval for the poll cycle;
 * user interactions (site toggle, date / month pickers) fire an IMMEDIATE
 * fetch rather than waiting for the next tick.
 *
 * Phase 7 (2026-04-24): replaced the rolling Today/Week/Month button group
 * with absolute-window controls:
 *   - Day mode: native <input type=date> picker, defaults to the newest
 *     date with data via /latest-date.
 *   - Month mode: month + year dropdowns. Current month auto-caps at
 *     today (month-to-date); past months render the full month.
 *   - localStorage persistence; polling pauses when the selected window
 *     is fully in the past.
 *
 * Phase 6 (2026-04-23): Export button in the topbar writes the current
 * selection's table data to .xlsx via the vendored SheetJS build.
 *
 * Theme (light/dark) is stored in localStorage under 'pmd-theme'. Initial
 * value is applied by the inline <script> in index.html to prevent a flash
 * of the wrong theme before this file loads.
 */

(() => {
  "use strict";

  const REFRESH_MS = parseInt(
    new URLSearchParams(location.search).get("refresh") || "30000",
    10
  );
  const THEME_STORAGE_KEY = "pmd-theme";
  const TIME_FILTER_STORAGE_KEY = "pmd-time-filter";
  const YEAR_SPAN_BACK = 4;  // current year + last 4 = 5 options in the year dropdown
  const MONTH_NAMES = [
    "January","February","March","April","May","June",
    "July","August","September","October","November","December",
  ];

  // --- state ---
  let currentSiteId = null;
  let currentSelection = null;  // { mode:'day'|'month', dayDate, monthYear, monthMonth }
  let sites = [];
  let refreshTimer = null;
  // Conveyor totals are stashed per-poll before panel renderers run so
  // they can read per-workcenter aggregates without a signature change.
  let _currentConveyorTotals = null;
  // Most recent /range payload; used for theme-toggle rerender (Phase 5)
  // and Export (Phase 6) without hitting the API again.
  let _lastPayload = null;
  const _chartInstances = new Set();
  // Phase 8: element that had focus when the details modal opened.
  // Restored on close so keyboard users don't lose their place.
  let _modalLastFocus = null;
  // Phase 10b: which top-level view is active. Hash-routed:
  //   no hash / #dashboard -> 'dashboard'
  //   #trends              -> 'trends'
  let currentView = 'dashboard';
  // Chart.js instances for the trends view (Total Tons + TPH charts).
  // Tracked separately from _chartInstances so a poll-cycle wipe of
  // the dashboard doesn't kill them.
  const _trendChartInstances = new Set();
  // Cached most-recent trends payload, mirrors _lastPayload's role.
  let _lastTrendsPayload = null;
  // Phase 14b: cache the circuit-rollup payload alongside the
  // workcenter rollup so theme-triggered re-renders pass both into
  // renderTrends -- otherwise the circuit subsections silently
  // disappear when the user flips light/dark while on the Trends tab.
  let _lastTrendsCircuitPayload = null;
  // Phase 14b restructure: which tab is currently shown on the
  // Trends view. Persists across refresh / theme-toggle re-renders
  // when the same section still exists in the new render; falls
  // back to "overview" otherwise.
  let _activeTrendsTab = "overview";
  // Phase 18: which bucket the Trends view currently shows. Persists in
  // localStorage so the choice carries across reloads. Toggles between
  // "monthly" and "yearly"; future buckets (weekly/quarterly) extend the
  // Literal in the backend route -- this state goes wherever they go.
  let _activeTrendsBucket = "monthly";
  try {
    const _storedBucket = localStorage.getItem("pmd-trends-bucket");
    if (_storedBucket === "monthly" || _storedBucket === "yearly") {
      _activeTrendsBucket = _storedBucket;
    }
  } catch (_e) { /* localStorage unavailable in some embeds */ }

  // Phase 19/20: Production ID prefix filter for the dashboard's
  // per-workcenter tables and Excel export. Three states:
  //   "all" -- show all rows (default)
  //   "PR"  -- show rows whose prod_id starts with PR but not PRM
  //   "PRM" -- show rows whose prod_id starts with PRM
  let _activeProdIdFilter = "all";
  try {
    const _storedProdId = localStorage.getItem("pmd-prodid-filter");
    if (_storedProdId === "all" || _storedProdId === "PR" || _storedProdId === "PRM") {
      _activeProdIdFilter = _storedProdId;
    }
  } catch (_e) {}

  // Phase 23: Workcenter Scheduled_Status filter. "all" / "Scheduled"
  // / "Unscheduled". Note: PRM-prefixed reports have null Status, so
  // combining PRM + (Scheduled or Unscheduled) returns an empty set.
  let _activeStatusFilter = "all";
  try {
    const _storedStatus = localStorage.getItem("pmd-status-filter");
    if (_storedStatus === "all" || _storedStatus === "Scheduled" || _storedStatus === "Unscheduled") {
      _activeStatusFilter = _storedStatus;
    }
  } catch (_e) {}

  // --- generic helpers ---
  const $ = (id) => document.getElementById(id);
  const el = (tag, attrs = {}, children = []) => {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") e.className = v;
      else if (k === "dataset") Object.assign(e.dataset, v);
      else if (k.startsWith("on") && typeof v === "function") e.addEventListener(k.slice(2), v);
      else if (v !== null && v !== undefined) e.setAttribute(k, v);
    }
    for (const c of [].concat(children)) {
      if (c === null || c === undefined) continue;
      e.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    }
    return e;
  };
  const pad2 = (n) => String(n).padStart(2, "0");
  const fmt1 = (v) => (v === null || v === undefined ? "\u2014" : Number(v).toFixed(1));
  const fmtInt = (v) => (v === null || v === undefined ? "\u2014" : Math.round(Number(v)).toString());
  const placeholderize = (s) => (s === "_" || s === "None" || !s ? "\u2014" : s);
  const fmtDate = (iso) => new Date(iso).toLocaleDateString();
  // Phase 12: department display helpers.
  // deptName  -> bare name string; falls back to "Dept <id>" so chart
  //              legends and other label-only contexts always read.
  // deptHeader -> "Department: <Name>" with id-style fallback used by
  //              workcenter / history panel headers.
  // Both treat any non-string / empty-trim value as null.
  const deptName = (name, id) => {
    if (name && typeof name === "string" && name.trim()) return name;
    return `Dept ${id}`;
  };
  const deptHeader = (name, id) => {
    if (name && typeof name === "string" && name.trim()) return `Department: ${name}`;
    return `Department ID: ${id}`;
  };
  const timeAgo = (isoStr) => {
    if (!isoStr) return "\u2014";
    const d = new Date(isoStr);
    const secs = Math.round((Date.now() - d.getTime()) / 1000);
    if (secs < 60) return `${secs}s ago`;
    if (secs < 3600) return `${Math.round(secs / 60)}m ago`;
    return d.toLocaleString();
  };
  const statusClassForPct = (v) => {
    if (v === null || v === undefined) return "sk";
    if (v >= 85) return "sp";
    if (v >= 60) return "so";
    return "sr";
  };

  // --- theme management ---
  const SUN_SVG = `
    <svg viewBox="0 0 14 14" aria-hidden="true">
      <circle cx="7" cy="7" r="2.4" fill="currentColor"/>
      <g stroke="currentColor" stroke-width="1.2" stroke-linecap="round">
        <line x1="7" y1="1"    x2="7"  y2="2.6"/>
        <line x1="7" y1="11.4" x2="7"  y2="13"/>
        <line x1="1" y1="7"    x2="2.6" y2="7"/>
        <line x1="11.4" y1="7" x2="13" y2="7"/>
        <line x1="2.8" y1="2.8"  x2="3.9" y2="3.9"/>
        <line x1="10.1" y1="10.1" x2="11.2" y2="11.2"/>
        <line x1="11.2" y1="2.8" x2="10.1" y2="3.9"/>
        <line x1="3.9"  y1="10.1" x2="2.8" y2="11.2"/>
      </g>
    </svg>`;
  const MOON_SVG = `
    <svg viewBox="0 0 14 14" aria-hidden="true">
      <path fill="currentColor"
            d="M11.2 8.8a4.6 4.6 0 0 1-5.9-5.9.4.4 0 0 0-.54-.5 5.6 5.6 0 1 0 6.94 6.94.4.4 0 0 0-.5-.54z"/>
    </svg>`;

  function getTheme() {
    const t = document.documentElement.getAttribute("data-theme");
    return t === "dark" ? "dark" : "light";
  }
  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    try { localStorage.setItem(THEME_STORAGE_KEY, theme); } catch (e) { /* quota */ }
    const btn = $("theme-toggle");
    if (btn) {
      btn.innerHTML = theme === "dark" ? SUN_SVG : MOON_SVG;
      const label = theme === "dark" ? "Switch to light theme" : "Switch to dark theme";
      btn.setAttribute("aria-label", label);
      btn.setAttribute("title", label);
    }
  }
  function toggleTheme() {
    applyTheme(getTheme() === "dark" ? "light" : "dark");
    if (_lastPayload) renderData(_lastPayload);
    if (currentView === "trends" && _lastTrendsPayload) {
      renderTrends(_lastTrendsPayload, _lastTrendsCircuitPayload);
    }
  }

  // --- fetch layer ---
  async function fetchJSON(url) {
    const resp = await fetch(url, { headers: { Accept: "application/json" } });
    if (!resp.ok) throw new Error(`${url} -> HTTP ${resp.status}`);
    return resp.json();
  }

  // --- time-filter state helpers (Phase 7) ---
  //
  // The selection object is the single source of truth for what
  // window the dashboard is currently showing. It persists across
  // refreshes via localStorage. Everything else (URL builder, polling
  // gate, chips, empty-state wording, export filename) derives from it.

  function todayISO() {
    const d = new Date();
    return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
  }

  function defaultSelection() {
    const now = new Date();
    return {
      mode: "day",
      dayDate: todayISO(),
      monthYear: now.getFullYear(),
      monthMonth: now.getMonth() + 1,
    };
  }

  function isValidSelection(s) {
    if (!s || (s.mode !== "day" && s.mode !== "month")) return false;
    if (typeof s.dayDate !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(s.dayDate)) return false;
    if (typeof s.monthYear !== "number" || typeof s.monthMonth !== "number") return false;
    if (s.monthMonth < 1 || s.monthMonth > 12) return false;
    return true;
  }

  function saveSelection(sel) {
    try { localStorage.setItem(TIME_FILTER_STORAGE_KEY, JSON.stringify(sel)); }
    catch (e) { /* quota / disabled; non-fatal */ }
  }

  function loadSelection() {
    try {
      const raw = localStorage.getItem(TIME_FILTER_STORAGE_KEY);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      return isValidSelection(parsed) ? parsed : null;
    } catch (e) { return null; }
  }

  function lastDayOfMonth(year, month) {
    // `month` is 1-12. JS Date with day 0 of next month = last day of this month.
    return new Date(year, month, 0).getDate();
  }

  function monthBoundsISO(year, month) {
    const from = `${year}-${pad2(month)}-01`;
    const now = new Date();
    const isCurrent = year === now.getFullYear() && month === now.getMonth() + 1;
    // Current month caps at today (month-to-date). Past months render
    // the full calendar month. Future months render the full calendar
    // month and yield an empty-state window (decided in OQ1).
    const lastDay = isCurrent ? now.getDate() : lastDayOfMonth(year, month);
    const to = `${year}-${pad2(month)}-${pad2(lastDay)}`;
    return { from, to };
  }

  function selectionBoundsISO(sel) {
    if (sel.mode === "day") return { from: sel.dayDate, to: sel.dayDate };
    return monthBoundsISO(sel.monthYear, sel.monthMonth);
  }

  function dataUrlForSelection(sel, siteId) {
    const { from, to } = selectionBoundsISO(sel);
    const params = new URLSearchParams({
      from_date: from,
      to_date: to,
      site_id: siteId,
    });
    return `/api/production-report/range?${params.toString()}`;
  }

  function selectionIncludesToday(sel) {
    const today = todayISO();
    const { from, to } = selectionBoundsISO(sel);
    return from <= today && today <= to;
  }

  function selectionLabel(sel) {
    if (sel.mode === "day") return sel.dayDate;
    return `${MONTH_NAMES[sel.monthMonth - 1]} ${sel.monthYear}`;
  }

  function selectionSlug(sel) {
    // Filename + sheet-name fragment. Day => YYYY-MM-DD. Month => YYYY-MM.
    if (sel.mode === "day") return sel.dayDate;
    return `${sel.monthYear}-${pad2(sel.monthMonth)}`;
  }

  async function fetchLatestDate(siteId) {
    try {
      const resp = await fetchJSON(
        `/api/production-report/latest-date?site_id=${encodeURIComponent(siteId)}`
      );
      return resp.latest_date || null;
    } catch (err) {
      console.error("latest-date fetch failed", err);
      return null;
    }
  }

  // --- time-filter UI wiring (Phase 7) ---

  function populateYearOptions() {
    const sel = $("month-year");
    if (!sel) return;
    sel.innerHTML = "";
    const thisYear = new Date().getFullYear();
    for (let y = thisYear; y >= thisYear - YEAR_SPAN_BACK; y--) {
      const opt = document.createElement("option");
      opt.value = String(y);
      opt.textContent = String(y);
      sel.appendChild(opt);
    }
  }

  function updateModeVisibility() {
    const mode = currentSelection ? currentSelection.mode : "day";
    for (const btn of document.querySelectorAll("#mode-toggle .gb")) {
      const on = btn.dataset.mode === mode;
      btn.classList.toggle("on", on);
      btn.setAttribute("aria-selected", on ? "true" : "false");
    }
    const dayBody = $("day-body");
    const monthBody = $("month-body");
    if (dayBody) dayBody.style.display = mode === "day" ? "" : "none";
    if (monthBody) monthBody.style.display = mode === "month" ? "" : "none";
  }

  function reflectSelectionInControls() {
    // Push currentSelection back into the UI controls so they agree
    // with state after bootstrap or localStorage restore.
    updateModeVisibility();
    const dayInput = $("day-date");
    if (dayInput) {
      dayInput.setAttribute("max", todayISO());
      dayInput.value = currentSelection.dayDate;
    }
    const monthSel = $("month-month");
    const yearSel = $("month-year");
    if (monthSel) monthSel.value = String(currentSelection.monthMonth);
    if (yearSel) yearSel.value = String(currentSelection.monthYear);
  }

  function onSelectionChanged() {
    saveSelection(currentSelection);
    renderChips();
    retunePolling();
    refreshData();  // immediate fetch, don't wait for the 30s tick
  }

  function wireTimeFilterControls() {
    for (const btn of document.querySelectorAll("#mode-toggle .gb")) {
      btn.addEventListener("click", () => {
        const next = btn.dataset.mode;
        if (!next || !currentSelection || currentSelection.mode === next) return;
        currentSelection = { ...currentSelection, mode: next };
        updateModeVisibility();
        onSelectionChanged();
      });
    }
    // Phase 19/20: Production ID prefix filter. Client-side; no
    // refetch on toggle. Sync visible state to the saved filter on
    // every wire call (boot + any later re-wire).
    for (const btn of document.querySelectorAll("#prodid-filter .gb")) {
      btn.addEventListener("click", () => {
        _setActiveProdIdFilter(btn.dataset.prodid);
      });
    }
    _applyProdIdFilterUi(_activeProdIdFilter);

    // Phase 23: Status filter. Same wire pattern.
    for (const btn of document.querySelectorAll("#status-filter .gb")) {
      btn.addEventListener("click", () => {
        _setActiveStatusFilter(btn.dataset.status);
      });
    }
    _applyStatusFilterUi(_activeStatusFilter);
    const dayInput = $("day-date");
    if (dayInput) {
      dayInput.addEventListener("change", () => {
        if (!dayInput.value || !currentSelection) return;
        currentSelection = { ...currentSelection, dayDate: dayInput.value };
        onSelectionChanged();
      });
    }
    const monthSel = $("month-month");
    const yearSel = $("month-year");
    const onMonthYearChange = () => {
      if (!currentSelection || !monthSel || !yearSel) return;
      const m = parseInt(monthSel.value, 10);
      const y = parseInt(yearSel.value, 10);
      if (!Number.isFinite(m) || !Number.isFinite(y)) return;
      currentSelection = { ...currentSelection, monthMonth: m, monthYear: y };
      onSelectionChanged();
    };
    if (monthSel) monthSel.addEventListener("change", onMonthYearChange);
    if (yearSel) yearSel.addEventListener("change", onMonthYearChange);
  }

  // --- site + filter panel rendering ---
  function renderSiteToggle() {
    const host = $("site-tog");
    host.innerHTML = "";
    for (const s of sites) {
      const btn = el("button", {
        class: "stbtn" + (s.id === currentSiteId ? " on" : ""),
        role: "tab",
        "aria-selected": s.id === currentSiteId ? "true" : "false",
        onclick: () => {
          if (s.id !== currentSiteId) {
            currentSiteId = s.id;
            renderSiteToggle();
            renderSiteStrip();
            renderChips();
            // Refresh whichever view is currently active. Dashboard
            // and Trends both need the new site's data; polling only
            // ever drives the dashboard.
            if (currentView === "trends") refreshTrends();
            else refreshData();
          }
        },
      }, s.name);
      host.appendChild(btn);
    }
  }
  function renderSiteStrip() {
    const s = sites.find((x) => x.id === currentSiteId);
    $("site-strip-id").textContent = s ? `Site ${s.id}` : "\u2014";
    $("site-strip-name").textContent = s ? s.name : "\u2014";
  }
  function renderChips() {
    const host = $("chips");
    host.innerHTML = "";
    const s = sites.find((x) => x.id === currentSiteId);
    if (s) host.appendChild(el("span", { class: "chip" }, s.name));
    if (currentSelection) {
      host.appendChild(el("span", { class: "chip" }, selectionLabel(currentSelection)));
    }
  }

  function renderHealth(health) {
    const pill = $("health-pill");
    pill.textContent = health.status;
    pill.classList.remove("ok", "degraded", "down");
    pill.classList.add(health.status);
    const src = health.sources[0];
    if (src) {
      $("src-name").textContent = src.name;
      $("src-status").textContent = src.ok ? "OK" : "FAIL";
      $("src-detail").textContent = src.detail;
      $("src-checked").textContent = timeAgo(src.checked_at);
    }
  }

  // --- single-report panel (KPI cards + asset table) ---
  function assetRow(label, m, wc) {
    // wc is accepted for signature parity but no longer read here --
    // the single-report panel's asset table omits the workcenter-level
    // Total (tons) column because the same number already appears in
    // the KPI card at the top of the panel and the per-conveyor outputs
    // live in the bar chart below. Repeating it on every asset row
    // was misleading (read as per-conveyor).
    void wc;
    const item = placeholderize(m.Produced_Item_Code);
    const itemDesc = placeholderize(m.Produced_Item_Description);
    return el("tr", {}, [
      el("td", {}, label),
      el("td", {}, fmt1(m.Availability)),
      el("td", {}, fmt1(m.Runtime)),
      el("td", {}, m.Performance === null ? "\u2014" : fmt1(m.Performance)),
      el("td", {}, item === "\u2014" ? "\u2014" : `${item} (${itemDesc})`),
      el("td", {}, m.Belt_Scale_Availability === undefined ? "\u2014" : fmt1(m.Belt_Scale_Availability)),
    ]);
  }

  function kpiGridFromWorkcenter(wc) {
    return el("div", { class: "kg" }, [
      el("div", { class: "kc " + statusClassForPct(wc.Availability) }, [
        el("div", { class: "kl" }, "Availability"),
        el("div", { class: "kv" }, fmt1(wc.Availability) + "%"),
      ]),
      el("div", { class: "kc " + statusClassForPct(wc.Performance) }, [
        el("div", { class: "kl" }, "Performance"),
        el("div", { class: "kv" }, wc.Performance === null ? "\u2014" : fmt1(wc.Performance) + "%"),
      ]),
      el("div", { class: "kc sk" }, [
        el("div", { class: "kl" }, "Runtime (hours)"),
        el("div", { class: "kv" }, fmt1(wc.Runtime)),
        el("div", { class: "km" }, wc.Scheduled_Runtime ? `Scheduled: ${fmt1(wc.Scheduled_Runtime)}` : ""),
      ]),
      el("div", { class: "kc sk" }, [
        el("div", { class: "kl" }, "Total (tons)"),
        el("div", { class: "kv" }, wc.Total === null || wc.Total === undefined ? "\u2014" : fmtInt(wc.Total)),
      ]),
    ]);
  }

  function statusPillFor(wc) {
    if (wc.Scheduled_Status === "Scheduled") return el("span", { class: "chip g" }, "Scheduled");
    if (wc.Scheduled_Status === "Unscheduled") return el("span", { class: "chip w" }, "Unscheduled");
    return el("span", { class: "chip" }, wc.Scheduled_Status || "\u2014");
  }

  function renderSingleReportPanel(entry) {
    // Used when a workcenter has exactly one report in the selected
    // window. KPI cards + asset table + conveyor chart. Equivalent to
    // the old Today-mode panel, now dispatched per-workcenter rather
    // than per-mode.
    const metrics = entry.payload?.Metrics || {};
    const wc = metrics.Workcenter || {};
    const assetKeys = Object.keys(metrics)
      .filter((k) => /^C\d+$/.test(k))
      .sort((a, b) => parseInt(a.slice(1)) - parseInt(b.slice(1)));
    const rows = assetKeys.map((k) => assetRow(k, metrics[k], wc));
    const table = el("table", { class: "mx" }, [
      el("thead", {}, el("tr", {}, [
        el("th", {}, "Asset"),
        el("th", {}, "Availability %"),
        el("th", {}, "Runtime (hours)"),
        el("th", {}, "Performance %"),
        el("th", {}, "Product"),
        el("th", {}, "Belt Scale %"),
      ])),
      el("tbody", {}, rows.length ? rows : [el("tr", {}, el("td", { colspan: "6", class: "muted" }, "No asset metrics in this payload."))]),
    ]);

    // Phase 8: Shift joins the metadata row; weather goes as a chip
    // strip after the metadata; Details button sits next to the status
    // pill. The chip strip is inline so it folds cleanly below the
    // metadata on narrow viewports.
    const headerChildren = [
      el("span", { class: "wc-title" }, deptHeader(entry.department_name, entry.department_id)),
      el("span", { class: "wc-sub" }, [
        el("span", { class: "wc-label" }, "Prod. Date: "),
        el("span", { class: "wc-value" }, fmtDate(entry.prod_date)),
      ]),
      el("span", { class: "wc-sub" }, [
        el("span", { class: "wc-label" }, "Production ID: "),
        el("span", { class: "wc-value mono" }, entry.prod_id),
      ]),
    ];
    if (entry.shift) {
      headerChildren.push(el("span", { class: "wc-sub" }, [
        el("span", { class: "wc-label" }, "Shift: "),
        el("span", { class: "wc-value" }, entry.shift),
      ]));
    }
    const weatherEl = weatherStrip(entry);
    if (weatherEl) headerChildren.push(weatherEl);
    headerChildren.push(el("span", { class: "wc-spacer" }));
    headerChildren.push(statusPillFor(wc));
    headerChildren.push(detailsButton(entry, "Report Details"));

    return el("section", { class: "wc-panel" }, [
      el("div", { class: "wc-header" }, headerChildren),
      el("div", { class: "wc-body" }, [
        kpiGridFromWorkcenter(wc),
        el("div", { class: "mxw" }, table),
        (() => {
          const chartHost = el("div", { class: "wc-chart" });
          renderConveyorChart(chartHost, getConveyorTotalsFor(entry.site_id, entry.department_id));
          return chartHost;
        })(),
      ]),
    ]);
  }

  // --- multi-report panel (history table) ---
  function historyRow(entry) {
    const wc = entry.payload?.Metrics?.Workcenter || {};
    return el("tr", {}, [
      el("td", {}, fmtDate(entry.prod_date)),
      el("td", { class: "mono" }, entry.prod_id),
      // Per-row Scheduled/Unscheduled pill. Prior UI showed a single
      // pill in the panel header derived from the LATEST entry --
      // misleading for multi-report windows where statuses could
      // differ across reports. Rendering per-row makes each table
      // entry self-describing and obviates the header pill.
      el("td", { class: "status-cell" }, statusPillFor(wc)),
      // Phase 8: Shift + Weather + Details. Shift comes straight from
      // the enrichment field; weatherSummary produces "<Cond> <Temp>".
      // The Details button opens a modal with the full weather grid
      // and the notes block.
      el("td", {}, entry.shift || "\u2014"),
      el("td", {}, weatherSummary(entry)),
      el("td", {}, fmt1(wc.Availability)),
      el("td", {}, wc.Performance === null ? "\u2014" : fmt1(wc.Performance)),
      el("td", {}, fmt1(wc.Runtime)),
      el("td", {}, wc.Total === null || wc.Total === undefined ? "\u2014" : fmtInt(wc.Total)),
      el("td", {}, detailsButton(entry)),
    ]);
  }

  function renderHistoryPanel(deptId, entries) {
    // Used when a workcenter has 2+ reports in the selected window
    // (typical for multi-shift days and for month-view). Entries are
    // pre-sorted newest-first by the backend.
    const latest = entries[0];
    const oldestDate = fmtDate(entries[entries.length - 1].prod_date);
    const newestDate = fmtDate(latest.prod_date);
    const rangeLabel = entries.length === 1 ? newestDate : `${oldestDate} - ${newestDate}`;

    const table = el("table", { class: "mx" }, [
      el("thead", {}, el("tr", {}, [
        el("th", {}, "Prod. Date"),
        el("th", {}, "Production ID"),
        el("th", {}, "Status"),
        el("th", {}, "Shift"),
        el("th", {}, "Weather"),
        el("th", {}, "Availability %"),
        el("th", {}, "Performance %"),
        el("th", {}, "Runtime (hours)"),
        el("th", {}, "Total (tons)"),
        el("th", {}, "Details"),
      ])),
      el("tbody", {}, entries.map(historyRow)),
    ]);

    // Phase 12: name lifted off any entry in the group -- they all share
    // the same department_id and therefore the same Departments lookup
    // result. Falls back to id-only display when name is null.
    const deptDisplayName = entries.length ? entries[0].department_name : null;
    return el("section", { class: "wc-panel" }, [
      el("div", { class: "wc-header" }, [
        el("span", { class: "wc-title" }, deptHeader(deptDisplayName, deptId)),
        el("span", { class: "wc-sub" }, [
          el("span", { class: "wc-label" }, "Range: "),
          el("span", { class: "wc-value" }, rangeLabel),
        ]),
        el("span", { class: "wc-sub" }, [
          el("span", { class: "wc-label" }, "Reports: "),
          el("span", { class: "wc-value" }, String(entries.length)),
        ]),
      ]),
      el("div", { class: "wc-body" }, [
        el("div", { class: "mxw" }, table),
        (() => {
          const chartHost = el("div", { class: "wc-chart" });
          renderConveyorChart(chartHost, getConveyorTotalsFor(latest.site_id, deptId));
          return chartHost;
        })(),
      ]),
    ]);
  }

  function renderData(payload) {
    const host = $("wc-panels");
    destroyAllCharts();
    host.innerHTML = "";
    const empty = $("empty-state");
    const allEntries = payload.entries || [];

    // Phase 19/20 + 23: apply both client-side filters before grouping
    // so departments with no matching reports drop out cleanly. Filters
    // compose via AND. The cached payload in _lastPayload still holds
    // the full envelope so toggling either filter re-renders without
    // a refetch.
    const entries = allEntries.filter(_matchesAllFilters);

    // Phase 19/20 + 23: when no filter is active, use the backend's
    // pre-computed conveyor_totals (cheaper, authoritative). When
    // either the prod-id or status filter is narrowing, recompute
    // client-side from the filtered entries so the chart matches the
    // visible table rows.
    if (_activeProdIdFilter === "all" && _activeStatusFilter === "all") {
      _currentConveyorTotals = payload.conveyor_totals || null;
    } else {
      _currentConveyorTotals = _computeConveyorTotalsFromEntries(entries);
    }

    if (allEntries.length === 0) {
      empty.style.display = "";
      empty.textContent = currentSelection
        ? `Nothing reported for ${selectionLabel(currentSelection)}.`
        : "No production data for this selection.";
      $("refresh-lbl").textContent =
        `Refreshed ${new Date(payload.generated_at).toLocaleTimeString()} (no data in window)`;
      return;
    }
    if (entries.length === 0) {
      // Data exists in the window but nothing matches the active filter
      // combination. List which filters are narrowing the result so the
      // operator knows what to relax.
      empty.style.display = "";
      const active = [];
      if (_activeProdIdFilter !== "all") {
        active.push("Production ID = " + _activeProdIdFilter
          + (_activeProdIdFilter === "PR" ? " (excluding PRM)" : ""));
      }
      if (_activeStatusFilter !== "all") {
        active.push("Status = " + _activeStatusFilter);
      }
      const desc = active.length ? active.join(" + ") : "current filters";
      empty.textContent =
        `No reports match ${desc} for ${selectionLabel(currentSelection)}. ` +
        `Adjust the filters in the sidebar (set either to All) to widen the view.`;
      $("refresh-lbl").textContent =
        `Refreshed ${new Date(payload.generated_at).toLocaleTimeString()} (filtered)`;
      return;
    }
    empty.style.display = "none";

    // Per-workcenter rendering dispatch (Phase 7 OQ3):
    //   single report in window  -> KPI cards + asset table layout
    //   multiple reports in window -> history table layout
    // Two workcenters on the same day can have different shift counts
    // and therefore different layouts side-by-side. The chart at the
    // bottom of each panel reads from conveyor_totals regardless.
    const grouped = new Map();
    for (const e of entries) {
      if (!grouped.has(e.department_id)) grouped.set(e.department_id, []);
      grouped.get(e.department_id).push(e);
    }
    const sortedDepts = [...grouped.keys()].sort();
    for (const deptId of sortedDepts) {
      const group = grouped.get(deptId);
      if (group.length === 1) {
        host.appendChild(renderSingleReportPanel(group[0]));
      } else {
        host.appendChild(renderHistoryPanel(deptId, group));
      }
    }
    $("refresh-lbl").textContent =
      `Refreshed ${new Date(payload.generated_at).toLocaleTimeString()}`;
  }

  function showError(msg) {
    const bar = $("err-bar");
    bar.style.display = "";
    bar.textContent = msg;
  }
  function clearError() {
    $("err-bar").style.display = "none";
  }

  // --- conveyor totals chart (Phase 5) ---------------------------------
  function destroyAllCharts() {
    for (const chart of _chartInstances) {
      try { chart.destroy(); } catch (_) { /* already gone */ }
    }
    _chartInstances.clear();
  }

  function getConveyorTotalsFor(siteId, deptId) {
    if (!_currentConveyorTotals) return null;
    return _currentConveyorTotals[`${siteId}:${deptId}`] || null;
  }

  function _themeColors() {
    const cs = getComputedStyle(document.documentElement);
    const pick = (name, fallback) => (cs.getPropertyValue(name).trim() || fallback);
    return {
      accent: pick("--accent", "#0078d4"),
      grid:   pick("--border", "#e1dfdd"),
      ink:    pick("--text", "#201f1e"),
    };
  }

  function renderConveyorChart(hostEl, totals) {
    const empty =
      !totals ||
      !totals.per_conveyor ||
      Object.keys(totals.per_conveyor).length === 0 ||
      !(totals.grand_total > 0);
    if (empty) {
      hostEl.appendChild(el("div", { class: "chart-empty muted" }, "No belt-scale data in window."));
      return;
    }

    const convLabel = totals.conveyors_counted === 1 ? "conveyor" : "conveyors";
    const reportLabel = totals.reports_counted === 1 ? "report" : "reports";
    hostEl.appendChild(el("div", { class: "chart-subtitle" }, [
      el("span", { class: "chart-subtitle-label" }, "Conveyor Total"),
      el("span", { class: "chart-subtitle-value" }, `${fmtInt(totals.grand_total)} tons`),
      el("span", { class: "chart-subtitle-meta muted" },
        `${totals.conveyors_counted} ${convLabel}, ${totals.reports_counted} ${reportLabel}`),
    ]));

    // Sort conveyors ascending by numeric suffix (C1, C2, C3, ...)
    // regardless of insertion order in totals.per_conveyor. Backend
    // already returns sorted keys; the client-side recomputation path
    // (filter != "all") inherits whatever order the iteration produced,
    // so sort here defensively.
    const conveyorNames = Object.keys(totals.per_conveyor)
      .sort((a, b) => parseInt(a.slice(1), 10) - parseInt(b.slice(1), 10));
    const data = conveyorNames.map((k) => totals.per_conveyor[k]);
    const labels = conveyorNames.map((k) => {
      const rawProduct = (totals.product_mode && totals.product_mode[k]) || null;
      return [k, placeholderize(rawProduct)];
    });

    const canvas = el("canvas", { class: "conveyor-chart-canvas" });
    hostEl.appendChild(el("div", { class: "chart-wrap" }, canvas));

    const colors = _themeColors();
    const chart = new Chart(canvas.getContext("2d"), {
      type: "bar",
      data: {
        labels,
        datasets: [{
          label: "Tons", data,
          backgroundColor: colors.accent, borderColor: colors.accent,
          borderWidth: 0, maxBarThickness: 48,
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false, animation: false,
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: (ctx) => `${fmtInt(ctx.parsed.y)} tons` } },
        },
        scales: {
          y: { beginAtZero: true, grid: { color: colors.grid }, ticks: { color: colors.ink, callback: (v) => fmtInt(v) } },
          x: { grid: { display: false }, ticks: { color: colors.ink } },
        },
      },
    });
    _chartInstances.add(chart);
  }

  // --- XLSX export (Phase 6 / Phase 7) -------------------------------
  //
  // Phase 7 unifies the export shape: one asset-row per
  // (workcenter, report, asset) regardless of single-shift vs.
  // multi-shift vs. month. Columns include Prod. Date + Production ID so
  // each row is self-identifying; a plant engineer can pivot in Excel
  // to get back to workcenter- or shift-level aggregates. Filename
  // reflects the current selection via selectionSlug().

  function slugifySite(name, id) {
    if (name) {
      const s = String(name)
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "-")
        .replace(/^-+|-+$/g, "");
      if (s) return s;
    }
    return `site-${id != null ? id : "unknown"}`;
  }

  function timestampSlug(date) {
    const d = date || new Date();
    return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}_${pad2(d.getHours())}${pad2(d.getMinutes())}`;
  }

  // Null / undefined -> truly-blank cell. Return `null` so that
  // XLSX.utils.json_to_sheet OMITS the cell entirely (so =COUNTA()
  // returns 0 on a blank, =AVERAGE skips it). See Phase 6 tests for
  // the empty-string vs null distinction.
  function numOrEmpty(v) {
    if (v === null || v === undefined) return null;
    const n = typeof v === "number" ? v : Number(v);
    return Number.isFinite(n) ? n : null;
  }
  function strOrEmpty(v) {
    if (v === null || v === undefined) return null;
    const s = String(v);
    return (s === "_" || s === "None") ? null : s;
  }

  // Phase 11b: value mapping for Site:* export columns. Same null /
  // None / "" -> blank-cell convention as strOrEmpty, but kept separate
  // so it can also pass numbers / booleans through (Site values are
  // mostly strings per payload-schema.md, but Loads_15_Ton is numeric-
  // looking and future fields may be too) and JSON-stringify any
  // nested object that turns up later.
  function _siteValueForExport(v) {
    if (v === null || v === undefined) return null;
    if (typeof v === "string") {
      const trimmed = v.trim();
      if (trimmed === "" || trimmed === "None") return null;
      return v;
    }
    if (typeof v === "number" || typeof v === "boolean") return v;
    try { return JSON.stringify(v); } catch { return String(v); }
  }

  function shapeAssetRows(payload, siteMeta) {
    // One row per (workcenter, report, asset). Groups by department
    // then by newest-first within the group so the exported order
    // mirrors what the dashboard renders.
    const rows = [];
    const entries = (payload.entries || []).filter(_matchesAllFilters);

    // Phase 11b: discover the union of payload.Metrics.Site keys across
    // every entry in the current selection. We use this list to append
    // one column per known Site field at the tail of every row --
    // consistent column set across the whole sheet even when individual
    // reports have different Site shapes. Column order matches the
    // modal: grouped by base type via _sortSiteKeys (Phase 11.1) so
    // exporters and on-screen viewers see the same field ordering.
    const discoveredSiteKeys = [];
    const seenSiteKeys = new Set();
    for (const e of entries) {
      const so = e.payload && e.payload.Metrics && e.payload.Metrics.Site;
      if (so && typeof so === "object") {
        for (const k of Object.keys(so)) {
          if (!seenSiteKeys.has(k)) {
            seenSiteKeys.add(k);
            discoveredSiteKeys.push(k);
          }
        }
      }
    }
    const siteKeys = _sortSiteKeys(discoveredSiteKeys);

    // Phase 19/20: Crusher columns. Discover the union of CrusherN keys
    // across the current selection. Variable count per site; older
    // reports may have none. Same union-by-discovery approach as
    // Site keys above.
    const discoveredCrusherKeys = [];
    const seenCrusherKeys = new Set();
    for (const e of entries) {
      const _m = e.payload && e.payload.Metrics;
      if (_m) {
        for (const _ck of _extractCrusherKeys(_m)) {
          if (!seenCrusherKeys.has(_ck)) {
            seenCrusherKeys.add(_ck);
            discoveredCrusherKeys.push(_ck);
          }
        }
      }
    }
    const crusherKeys = discoveredCrusherKeys
      .slice()
      .sort((a, b) => parseInt(a.slice(7), 10) - parseInt(b.slice(7), 10));

    const grouped = new Map();
    for (const e of entries) {
      if (!grouped.has(e.department_id)) grouped.set(e.department_id, []);
      grouped.get(e.department_id).push(e);
    }
    const sortedDepts = [...grouped.keys()].sort();
    for (const deptId of sortedDepts) {
      for (const entry of grouped.get(deptId)) {
        const metrics = entry.payload && entry.payload.Metrics ? entry.payload.Metrics : {};
        const wc = (metrics.Workcenter && typeof metrics.Workcenter === "object") ? metrics.Workcenter : {};
        const siteObj = (metrics.Site && typeof metrics.Site === "object") ? metrics.Site : {};
        const assetKeys = Object.keys(metrics)
          .filter((k) => /^C\d+$/.test(k))
          .sort((a, b) => parseInt(a.slice(1), 10) - parseInt(b.slice(1), 10));
        for (const k of assetKeys) {
          const m = metrics[k] || {};
          const row = {
            "Site": siteMeta.name || "",
            "Site ID": entry.site_id,
            "Department ID": entry.department_id,
            // Phase 12: Department Name column sits next to the ID.
            // Both are kept in the export per the "export mirrors
            // display" rule. strOrEmpty turns null -> truly blank cell.
            "Department": strOrEmpty(entry.department_name),
            "Prod. Date": entry.prod_date || "",
            "Production ID": entry.prod_id || "",
            "Asset": k,
            "Availability %": numOrEmpty(m.Availability),
            "Runtime (hours)": numOrEmpty(m.Runtime),
            "Performance %": numOrEmpty(m.Performance),
            // Total (tons) is the WORKCENTER-level total (tons fed),
            // repeated across every asset row of the same report --
            // matches the dashboard table behavior.
            "Total (tons)": numOrEmpty(wc.Total),
            "Product Code": strOrEmpty(m.Produced_Item_Code),
            "Product Description": strOrEmpty(m.Produced_Item_Description),
            "Belt Scale %": numOrEmpty(m.Belt_Scale_Availability),
            // Phase 8: enrichment columns tail-appended. These repeat
            // across assets for a given report (same shift / same
            // weather / same notes for every asset in one report);
            // Excel pivots collapse the repetition if needed.
            "Shift": strOrEmpty(entry.shift),
            "Weather Conditions": strOrEmpty(entry.weather_conditions),
            "Avg Temp": numOrEmpty(entry.avg_temp),
            "Avg Humidity": numOrEmpty(entry.avg_humidity),
            "Max Wind": numOrEmpty(entry.max_wind_speed),
            "Notes": strOrEmpty(entry.notes),
          };
          // Phase 11b: dynamically discovered Site:* columns appended
          // at the end of the row. Same key formatting as the modal so
          // the column header reads identically to the modal label. A
          // report whose Site lacks a discovered key gets a blank cell
          // (per _siteValueForExport's null-on-missing rule).
          for (const sk of siteKeys) {
            row[_formatSiteLabel(sk)] = _siteValueForExport(siteObj[sk]);
          }
          // Phase 19/20: Crusher columns at the very tail. Three per
          // discovered crusher (Description / Setpoint / Runtime hrs).
          // A row whose Metrics lacks a given CrusherN gets blank cells.
          for (const ck of crusherKeys) {
            const cnode = (metrics[ck] && typeof metrics[ck] === "object") ? metrics[ck] : {};
            const label = _humanizeCrusherKey(ck);
            row[label + " Description"] = _siteValueForExport(cnode.Description);
            row[label + " Setpoint"] = _siteValueForExport(cnode.Setpoint);
            row[label + " Runtime (hrs)"] = numOrEmpty(cnode.Runtime);
          }
          rows.push(row);
        }
      }
    }
    return rows;
  }

  function applyColumnFormats(ws, rows, columnFormats) {
    if (!rows.length || !ws["!ref"]) return;
    const headers = Object.keys(rows[0]);
    const range = XLSX.utils.decode_range(ws["!ref"]);
    for (let colIdx = 0; colIdx <= range.e.c; colIdx++) {
      const header = headers[colIdx];
      const fmt = columnFormats[header];
      for (let rowIdx = 1; rowIdx <= range.e.r; rowIdx++) {
        const addr = XLSX.utils.encode_cell({ r: rowIdx, c: colIdx });
        const cell = ws[addr];
        if (fmt && cell && cell.t === "n") cell.z = fmt;
      }
    }
    ws["!cols"] = headers.map((h) => {
      let w = String(h).length;
      for (const row of rows) {
        const v = row[h];
        if (v === null || v === undefined || v === "") continue;
        const vs = String(v);
        if (vs.length > w) w = vs.length;
      }
      return { wch: Math.min(Math.max(w + 2, 8), 40) };
    });
  }

  function exportCurrentSelection() {
    if (!_lastPayload || !(_lastPayload.entries || []).length) return;
    if (typeof XLSX === "undefined") {
      showError("Export unavailable: XLSX library failed to load.");
      return;
    }
    try {
      const siteMeta = sites.find((s) => s.id === currentSiteId)
        || { id: currentSiteId, name: "" };
      const rows = shapeAssetRows(_lastPayload, siteMeta);
      if (!rows.length) return;

      const columnFormats = {
        "Availability %": '0.0"%"',
        "Runtime (hours)": "0.0",
        "Performance %": '0.0"%"',
        "Total (tons)": "#,##0",
        "Belt Scale %": '0.0"%"',
        // Phase 8: enrichment numeric columns.
        "Avg Temp": '0.0"\u00B0F"',
        "Avg Humidity": '0.0"%"',
        "Max Wind": "0.0",
      };

      const ws = XLSX.utils.json_to_sheet(rows);
      applyColumnFormats(ws, rows, columnFormats);
      const wb = XLSX.utils.book_new();
      const selSlug = selectionSlug(currentSelection);
      XLSX.utils.book_append_sheet(wb, ws, selSlug);

      const filename = `production-metrics_${slugifySite(siteMeta.name, siteMeta.id)}_${selSlug}_${timestampSlug()}.xlsx`;
      XLSX.writeFile(wb, filename);
    } catch (err) {
      console.error("export failed", err);
      showError(`Export failed: ${err.message}`);
    }
  }

  function updateExportButtonState() {
    const btn = $("export-btn");
    if (!btn) return;
    let canExport;
    let title;
    if (currentView === "trends") {
      canExport = !!(_lastTrendsPayload && (_lastTrendsPayload.rollups || []).length);
      title = "Download Trends data as Excel (.xlsx)";
    } else {
      canExport = !!(_lastPayload && (_lastPayload.entries || []).length);
      title = "Download current view as Excel (.xlsx)";
    }
    btn.disabled = !canExport;
    btn.setAttribute("title", title);
    btn.setAttribute("aria-label", title);
  }

  // --- Phase 8.1: weather icons + severity-ranked picker -----------

  // Inline SVG weather icons. Stroke-only where possible so they pick
  // up the current text color via ``currentColor`` and track the
  // light/dark theme alongside other text. 14x14 viewBox matches the
  // existing sun/moon icons in the theme toggle.
  const WEATHER_ICONS = {
    "thunderstorm": `<svg viewBox="0 0 14 14" class="wi" aria-hidden="true"><path d="M2 5.5 Q2 3 4.5 3 Q5.5 3 6 3.5 Q7 2 8.5 2.5 Q10 3 10 4.5 Q11.5 4.5 11.5 6 Q11.5 7.5 10 7.5 L3.5 7.5 Q2 7.5 2 5.5 Z" fill="none" stroke="currentColor" stroke-width="1" stroke-linejoin="round"/><polygon points="8,8 5.5,11.5 7.5,11.5 6.5,13.5 9.5,10 7.5,10 8.5,8" fill="currentColor" stroke="currentColor" stroke-width="0.3" stroke-linejoin="round"/></svg>`,
    "heavy-rain": `<svg viewBox="0 0 14 14" class="wi" aria-hidden="true"><path d="M2 6 Q2 3.5 4.5 3.5 Q5.5 3.5 6 4 Q7 2.5 8.5 3 Q10 3.5 10 5 Q11.5 5 11.5 6.5 Q11.5 8 10 8 L3.5 8 Q2 8 2 6 Z" fill="currentColor" fill-opacity="0.22" stroke="currentColor" stroke-width="1.1" stroke-linejoin="round"/><g stroke="currentColor" stroke-width="1.3" stroke-linecap="round"><line x1="2.8" y1="9.5" x2="2.3" y2="12.5"/><line x1="5" y1="9.5" x2="4.5" y2="12.5"/><line x1="7" y1="9.5" x2="6.5" y2="12.5"/><line x1="9" y1="9.5" x2="8.5" y2="12.5"/><line x1="11.2" y1="9.5" x2="10.7" y2="12.5"/></g></svg>`,
    "rain": `<svg viewBox="0 0 14 14" class="wi" aria-hidden="true"><path d="M2 6 Q2 3.5 4.5 3.5 Q5.5 3.5 6 4 Q7 2.5 8.5 3 Q10 3.5 10 5 Q11.5 5 11.5 6.5 Q11.5 8 10 8 L3.5 8 Q2 8 2 6 Z" fill="none" stroke="currentColor" stroke-width="1" stroke-linejoin="round"/><g stroke="currentColor" stroke-width="1.1" stroke-linecap="round"><line x1="3.5" y1="9.5" x2="3" y2="12.5"/><line x1="6" y1="9.5" x2="5.5" y2="12.5"/><line x1="8.5" y1="9.5" x2="8" y2="12.5"/><line x1="11" y1="9.5" x2="10.5" y2="12.5"/></g></svg>`,
    "light-rain": `<svg viewBox="0 0 14 14" class="wi" aria-hidden="true"><path d="M2 6.5 Q2 4 4.5 4 Q5.5 4 6 4.5 Q7 3 8.5 3.5 Q10 4 10 5.5 Q11.5 5.5 11.5 7 Q11.5 8.5 10 8.5 L3.5 8.5 Q2 8.5 2 6.5 Z" fill="none" stroke="currentColor" stroke-width="1" stroke-linejoin="round"/><g stroke="currentColor" stroke-width="1.2" stroke-linecap="round"><line x1="5" y1="10" x2="4.5" y2="12.5"/><line x1="9" y1="10" x2="8.5" y2="12.5"/></g></svg>`,
    "snow": `<svg viewBox="0 0 14 14" class="wi" aria-hidden="true"><path d="M2 6 Q2 3.5 4.5 3.5 Q5.5 3.5 6 4 Q7 2.5 8.5 3 Q10 3.5 10 5 Q11.5 5 11.5 6.5 Q11.5 8 10 8 L3.5 8 Q2 8 2 6 Z" fill="none" stroke="currentColor" stroke-width="1" stroke-linejoin="round"/><g stroke="currentColor" stroke-width="0.9" stroke-linecap="round"><line x1="4" y1="9.5" x2="4" y2="12.5"/><line x1="2.8" y1="11" x2="5.2" y2="11"/><line x1="7" y1="9.5" x2="7" y2="12.5"/><line x1="5.8" y1="11" x2="8.2" y2="11"/><line x1="10" y1="9.5" x2="10" y2="12.5"/><line x1="8.8" y1="11" x2="11.2" y2="11"/></g></svg>`,
    "mist": `<svg viewBox="0 0 14 14" class="wi" aria-hidden="true"><g stroke="currentColor" stroke-width="1.1" stroke-linecap="round" fill="none"><path d="M1 4 Q3 3, 5 4 Q7 5, 9 4 Q11 3, 13 4"/><path d="M1 7 Q3 6, 5 7 Q7 8, 9 7 Q11 6, 13 7"/><path d="M1 10 Q3 9, 5 10 Q7 11, 9 10 Q11 9, 13 10"/></g></svg>`,
    "overcast": `<svg viewBox="0 0 14 14" class="wi" aria-hidden="true"><path d="M1.5 8 Q1.5 5 4 5 Q5 5 5.5 5.5 Q6.5 3.5 8.5 4 Q10.5 4.5 10.5 6.5 Q12.5 6.5 12.5 8.5 Q12.5 10.5 10.5 10.5 L3 10.5 Q1.5 10.5 1.5 8 Z" fill="currentColor" fill-opacity="0.2" stroke="currentColor" stroke-width="1" stroke-linejoin="round"/></svg>`,
    "broken-clouds": `<svg viewBox="0 0 14 14" class="wi" aria-hidden="true"><path d="M1 5 Q1 3 3 3 Q4 3 4.5 3.5 Q5.5 2.5 6.5 3 Q7.5 3.5 7.5 4.5 Q8 4.5 8 5.5 Q8 6.5 7 6.5 L2.5 6.5 Q1 6.5 1 5 Z" fill="none" stroke="currentColor" stroke-width="0.9" stroke-linejoin="round"/><path d="M4 10.5 Q4 8.5 6 8.5 Q7 8.5 7.5 9 Q8.5 8 9.5 8.5 Q10.5 9 10.5 10 Q12 10 12 11 Q12 12 10.5 12 L5.5 12 Q4 12 4 10.5 Z" fill="none" stroke="currentColor" stroke-width="0.9" stroke-linejoin="round"/></svg>`,
    "scattered-clouds": `<svg viewBox="0 0 14 14" class="wi" aria-hidden="true"><path d="M2 8 Q2 5.5 4.5 5.5 Q5.5 5.5 6 6.2 Q7 5 8.5 5.5 Q10 6 10 7.5 Q11.5 7.5 11.5 9 Q11.5 10.5 10 10.5 L3.5 10.5 Q2 10.5 2 8 Z" fill="none" stroke="currentColor" stroke-width="1.1" stroke-linejoin="round"/></svg>`,
    "few-clouds": `<svg viewBox="0 0 14 14" class="wi" aria-hidden="true"><circle cx="4" cy="4" r="1.8" fill="none" stroke="currentColor" stroke-width="1"/><g stroke="currentColor" stroke-width="0.9" stroke-linecap="round"><line x1="4" y1="0.5" x2="4" y2="1.5"/><line x1="0.5" y1="4" x2="1.5" y2="4"/><line x1="1.8" y1="1.8" x2="2.5" y2="2.5"/><line x1="6.2" y1="1.8" x2="5.5" y2="2.5"/></g><path d="M6 10 Q6 8 8 8 Q9 8 9.5 8.7 Q10.5 8 11.5 8.7 Q12.5 9 12.5 10 Q12.5 11.5 11 11.5 L7 11.5 Q6 11.5 6 10 Z" fill="none" stroke="currentColor" stroke-width="1" stroke-linejoin="round"/></svg>`,
    "clear": `<svg viewBox="0 0 14 14" class="wi" aria-hidden="true"><circle cx="7" cy="7" r="2.5" fill="none" stroke="currentColor" stroke-width="1.1"/><g stroke="currentColor" stroke-width="1.1" stroke-linecap="round"><line x1="7" y1="1" x2="7" y2="2.3"/><line x1="7" y1="11.7" x2="7" y2="13"/><line x1="1" y1="7" x2="2.3" y2="7"/><line x1="11.7" y1="7" x2="13" y2="7"/><line x1="2.5" y1="2.5" x2="3.5" y2="3.5"/><line x1="10.5" y1="10.5" x2="11.5" y2="11.5"/><line x1="11.5" y1="2.5" x2="10.5" y2="3.5"/><line x1="3.5" y1="10.5" x2="2.5" y2="11.5"/></g></svg>`,
  };

  // Severity-ranked matchers, ordered WORST first. STUFF'd WEATHER_CONDITIONS
  // often contain multiple conditions ("broken clouds, clear sky, light rain");
  // we scan this list in order and pick the first icon whose matchers appear
  // anywhere in the (lower-cased) string. That means a shift that had ANY
  // rain during the window gets the rain icon, regardless of what else was
  // logged -- which matches operator priorities. Modal shows the full list.
  const WEATHER_SEVERITY = [
    [["thunderstorm", "tornado", "squall"], "thunderstorm"],
    [["heavy rain", "heavy intensity rain", "extreme rain"], "heavy-rain"],
    [["rain"], "rain"],          // catches "rain", "moderate rain", "shower rain"
    [["drizzle"], "light-rain"], // drizzle first (matches "light drizzle" before "light rain")
    [["light rain"], "light-rain"],
    [["snow", "sleet"], "snow"],
    [["mist", "fog", "haze", "smoke", "dust", "sand"], "mist"],
    [["overcast"], "overcast"],
    [["broken clouds"], "broken-clouds"],
    [["scattered clouds"], "scattered-clouds"],
    [["few clouds"], "few-clouds"],
    [["clear"], "clear"],        // catches "clear sky"
  ];

  function pickWeatherIcon(weatherConditions) {
    if (!weatherConditions || typeof weatherConditions !== "string") return null;
    const lower = weatherConditions.toLowerCase();
    for (const [matchers, iconKey] of WEATHER_SEVERITY) {
      if (matchers.some((m) => lower.includes(m))) return iconKey;
    }
    // Unknown condition phrasing. Log once per unique string so a
    // maintainer notices and can extend WEATHER_SEVERITY. Swallow the
    // console call if console isn't present.
    if (typeof console !== "undefined" && console.warn) {
      console.warn("[weather] no icon mapping for:", weatherConditions);
    }
    return null;
  }

  function renderWeatherIcon(iconKey, extraClass) {
    const span = document.createElement("span");
    span.className = "wi-wrap" + (extraClass ? " " + extraClass : "");
    span.innerHTML = WEATHER_ICONS[iconKey] || "";
    return span;
  }

  // --- details modal + weather helpers (Phase 8) ---------------------

  // Compact summary for the Weather column in the history table.
  // Returns a DOM element: [icon] + temp when both available, icon
  // alone if no temp, temp alone if no mappable icon, em-dash if
  // neither. The full comma-separated condition list is available in
  // the Details modal.
  function weatherSummary(entry) {
    const iconKey = pickWeatherIcon(entry.weather_conditions);
    const hasTemp = entry.avg_temp !== null && entry.avg_temp !== undefined;
    if (!iconKey && !hasTemp) return "\u2014";
    const children = [];
    if (iconKey) children.push(renderWeatherIcon(iconKey));
    if (hasTemp) {
      children.push(el("span", { class: "weather-temp" }, `${Math.round(entry.avg_temp)}\u00B0F`));
    }
    return el("span", { class: "weather-summary-inline" }, children);
  }

  // Weather chip strip for the single-report panel header. Returns
  // null when the report has no weather data so the caller can skip
  // appending an empty chip row.
  function weatherStrip(entry) {
    const hasAny =
      (entry.weather_conditions && entry.weather_conditions.trim()) ||
      entry.avg_temp !== null && entry.avg_temp !== undefined ||
      entry.avg_humidity !== null && entry.avg_humidity !== undefined ||
      entry.max_wind_speed !== null && entry.max_wind_speed !== undefined;
    if (!hasAny) return null;
    const children = [];
    children.push(el("span", { class: "wc-label" }, "Weather:"));
    const iconKey = pickWeatherIcon(entry.weather_conditions);
    if (iconKey) children.push(renderWeatherIcon(iconKey, "wi-strip"));
    if (entry.avg_temp !== null && entry.avg_temp !== undefined) {
      children.push(el("span", { class: "weather-strip-sep" }, "\u00B7"));
      children.push(el("span", { class: "weather-strip-value" }, `${Math.round(entry.avg_temp)}\u00B0F`));
    }
    if (entry.avg_humidity !== null && entry.avg_humidity !== undefined) {
      children.push(el("span", { class: "weather-strip-sep" }, "\u00B7"));
      children.push(el("span", { class: "weather-strip-value" }, `${Math.round(entry.avg_humidity)}% RH`));
    }
    if (entry.max_wind_speed !== null && entry.max_wind_speed !== undefined) {
      children.push(el("span", { class: "weather-strip-sep" }, "\u00B7"));
      children.push(el("span", { class: "weather-strip-value" }, `${Math.round(entry.max_wind_speed)} mph`));
    }
    return el("span", { class: "weather-strip" }, children);
  }

  // Small button that opens the Details modal for a given entry.
  // Used inline in table rows and in the single-report panel header.
  function detailsButton(entry, label) {
    return el("button", {
      type: "button",
      class: "details-btn",
      "aria-label": "Open details for this production report",
      title: "Open details",
      onclick: () => openDetailsModal(entry),
    }, label || "View");
  }

  function fmtWithUnit(v, unit) {
    if (v === null || v === undefined) return "\u2014";
    return `${Number(v).toFixed(1)}${unit}`;
  }

  function _weatherCell(label, value) {
    return el("div", { class: "dm-weather-cell" }, [
      el("div", { class: "dm-weather-label" }, label),
      el("div", { class: "dm-weather-value" }, value),
    ]);
  }

  // Phase 11 helpers: dynamic rendering of entry.payload.Metrics.Site.
  // The Site object is operator-captured plant context (loader operators,
  // shot numbers, manual loads, ...). payload-schema.md explicitly calls
  // it "open-ended" -- new keys may show up upstream and the modal must
  // render them without a frontend change. Hence: dynamic key iteration
  // over Object.keys() rather than a hard-coded field list.

  function _formatSiteLabel(key) {
    // snake_case -> "Title Case With Spaces". Preserves the upstream
    // "One"/"Two" word forms rather than rewriting to "1"/"2" -- matches
    // what operators see in the source system.
    return String(key)
      .split("_")
      .map(part => part.length > 0 ? part[0].toUpperCase() + part.slice(1) : part)
      .join(" ");
  }

  // Phase 11.1: Site fields display grouped by base type instead of
  // upstream insertion order. Upstream emits keys interleaved by
  // ordinal (Loader_Operator_One, Shot_Number_One, Loader_Operator_Two,
  // ...) but the operator's mental model is "all loader operators, then
  // all shot numbers." Grouping by prefix matches that.
  const _ORDINAL_WORDS = [
    "One", "Two", "Three", "Four", "Five",
    "Six", "Seven", "Eight", "Nine", "Ten",
  ];

  function _parseSiteOrdinal(key) {
    // Detect trailing "_One".."_Ten" or "_1","_2",... suffixes.
    // ordinal=0 means "no trailing ordinal" -- the whole key is the
    // prefix and the field forms a one-member group on its own.
    const parts = String(key).split("_");
    if (parts.length >= 2) {
      const last = parts[parts.length - 1];
      const wordIdx = _ORDINAL_WORDS.indexOf(last);
      if (wordIdx !== -1) {
        return { prefix: parts.slice(0, -1).join("_"), ordinal: wordIdx + 1 };
      }
      if (/^\d+$/.test(last)) {
        return { prefix: parts.slice(0, -1).join("_"), ordinal: parseInt(last, 10) };
      }
    }
    return { prefix: String(key), ordinal: 0 };
  }

  function _sortSiteKeys(keys) {
    // Stable sort: across prefix groups, keep first-seen order; within
    // a group, ordinal ascending. Keys with no ordinal go in their own
    // single-member group at whatever first-seen position they hold.
    // E.g. given:
    //   Loader_Operator_One, Shot_Number_One, Loader_Operator_Two,
    //   Loads_15_Ton, Shot_Number_Two
    // returns:
    //   Loader_Operator_One, Loader_Operator_Two, Shot_Number_One,
    //   Shot_Number_Two, Loads_15_Ton
    const parsed = keys.map((k, idx) => ({ key: k, idx, ..._parseSiteOrdinal(k) }));
    const prefixIndex = new Map();
    for (const p of parsed) {
      if (!prefixIndex.has(p.prefix)) prefixIndex.set(p.prefix, prefixIndex.size);
    }
    return parsed
      .slice()
      .sort((a, b) => {
        const pi = prefixIndex.get(a.prefix) - prefixIndex.get(b.prefix);
        if (pi !== 0) return pi;
        // same prefix: ordinal ascending. Ties (shouldn't happen but
        // be defensive) fall back to original insertion order.
        const oi = a.ordinal - b.ordinal;
        if (oi !== 0) return oi;
        return a.idx - b.idx;
      })
      .map(p => p.key);
  }

  function _formatSiteValue(v) {
    // Match the rest of the modal's null/missing convention: render
    // null, undefined, "", and the literal placeholder string "None"
    // (per payload-schema.md Quirks) all as em-dash so the eye treats
    // "field not filled" uniformly.
    if (v === null || v === undefined) return "—";
    if (typeof v === "string") {
      const trimmed = v.trim();
      if (trimmed === "" || trimmed === "None") return "—";
      return v;
    }
    if (typeof v === "number" || typeof v === "boolean") return String(v);
    // Defensive: payload-schema.md warns the Site shape is fluid and
    // future fields may nest. JSON-stringify rather than printing
    // "[object Object]" or throwing.
    try { return JSON.stringify(v); } catch { return String(v); }
  }

  // Phase 19/20: Production ID filter helpers. The "PR" branch must
  // exclude PRM matches -- bare "PR..." is one logical group, "PRM..."
  // is a separate group, and "All" is the union.
  // Phase 19/20: client-side recomputation of payload.conveyor_totals
  // for cases where the prod-id filter is active. Mirrors the backend's
  // compute_conveyor_totals shape -- keyed "site_id:department_id" ->
  // { per_conveyor, product_mode, grand_total, conveyors_counted,
  //   reports_counted } -- so getConveyorTotalsFor() needs no change.
  // Strict CX selection (/^C\d+$/) and placeholder filtering for
  // product_mode mirror the Python side. Tie-break for the mode picks
  // the value seen first in iteration order; entries are pre-sorted
  // newest-first by /api/production-report/range, so first-seen ==
  // newest, matching the backend's tie rule.
  function _computeConveyorTotalsFromEntries(entries) {
    const out = {};
    const byKey = new Map();
    for (const e of entries) {
      const k = e.site_id + ":" + e.department_id;
      if (!byKey.has(k)) byKey.set(k, []);
      byKey.get(k).push(e);
    }
    for (const [key, group] of byKey) {
      const perConveyor = {};
      const productCounts = {};   // conveyor -> { value -> count }
      const productFirstSeen = {}; // conveyor -> { value -> first idx }
      let reportsContributing = 0;
      for (let i = 0; i < group.length; i++) {
        const e = group[i];
        const metrics = (e.payload && e.payload.Metrics) || {};
        let contributed = false;
        for (const ck of Object.keys(metrics)) {
          if (!/^C\d+$/.test(ck)) continue;
          const node = metrics[ck];
          if (!node || typeof node !== "object") continue;
          const v = Number(node.Total);
          if (Number.isFinite(v)) {
            perConveyor[ck] = (perConveyor[ck] || 0) + v;
            contributed = true;
          }
          const desc = node.Produced_Item_Description;
          if (typeof desc === "string") {
            const trimmed = desc.trim();
            if (trimmed && trimmed !== "None" && trimmed !== "_") {
              if (!productCounts[ck]) {
                productCounts[ck] = {};
                productFirstSeen[ck] = {};
              }
              productCounts[ck][desc] = (productCounts[ck][desc] || 0) + 1;
              if (productFirstSeen[ck][desc] === undefined) {
                productFirstSeen[ck][desc] = i;
              }
            }
          }
        }
        if (contributed) reportsContributing++;
      }
      const productMode = {};
      for (const ck of Object.keys(perConveyor)) {
        const counts = productCounts[ck];
        if (!counts) { productMode[ck] = null; continue; }
        const firstSeen = productFirstSeen[ck];
        let best = null, bestCount = -1, bestFirst = Infinity;
        for (const v of Object.keys(counts)) {
          const c = counts[v];
          const fs = firstSeen[v];
          if (c > bestCount || (c === bestCount && fs < bestFirst)) {
            best = v;
            bestCount = c;
            bestFirst = fs;
          }
        }
        productMode[ck] = best;
      }
      let grandTotal = 0;
      for (const v of Object.values(perConveyor)) grandTotal += v;
      out[key] = {
        per_conveyor: perConveyor,
        product_mode: productMode,
        grand_total: grandTotal,
        conveyors_counted: Object.keys(perConveyor).length,
        reports_counted: reportsContributing,
      };
    }
    return out;
  }

  function _matchesProdIdFilter(prodId) {
    if (_activeProdIdFilter === "all") return true;
    const p = String(prodId || "");
    if (_activeProdIdFilter === "PRM") return p.indexOf("PRM") === 0;
    if (_activeProdIdFilter === "PR")  return p.indexOf("PR") === 0 && p.indexOf("PRM") !== 0;
    return true;
  }

  function _setActiveProdIdFilter(filter) {
    if (filter !== "all" && filter !== "PR" && filter !== "PRM") return;
    if (filter === _activeProdIdFilter) return;
    _activeProdIdFilter = filter;
    try { localStorage.setItem("pmd-prodid-filter", filter); } catch (_e) {}
    _applyProdIdFilterUi(filter);
    // Re-render with the new filter from the cached payload (no
    // network refetch needed -- filtering is purely client-side).
    if (currentView === "dashboard" && _lastPayload) {
      renderData(_lastPayload);
      updateExportButtonState();
    }
  }

  function _applyProdIdFilterUi(filter) {
    for (const btn of document.querySelectorAll("#prodid-filter .gb")) {
      const on = btn.dataset.prodid === filter;
      btn.classList.toggle("on", on);
      btn.setAttribute("aria-selected", on ? "true" : "false");
    }
  }

  // Phase 23: Status filter. Reads entry.payload.Metrics.Workcenter
  // .Scheduled_Status, which is "Scheduled", "Unscheduled", or null.
  function _matchesStatusFilter(entry) {
    if (_activeStatusFilter === "all") return true;
    const wc = (entry.payload && entry.payload.Metrics && entry.payload.Metrics.Workcenter) || {};
    return wc.Scheduled_Status === _activeStatusFilter;
  }

  function _setActiveStatusFilter(filter) {
    if (filter !== "all" && filter !== "Scheduled" && filter !== "Unscheduled") return;
    if (filter === _activeStatusFilter) return;
    _activeStatusFilter = filter;
    try { localStorage.setItem("pmd-status-filter", filter); } catch (_e) {}
    _applyStatusFilterUi(filter);
    if (currentView === "dashboard" && _lastPayload) {
      renderData(_lastPayload);
      updateExportButtonState();
    }
  }

  function _applyStatusFilterUi(filter) {
    for (const btn of document.querySelectorAll("#status-filter .gb")) {
      const on = btn.dataset.status === filter;
      btn.classList.toggle("on", on);
      btn.setAttribute("aria-selected", on ? "true" : "false");
    }
  }

  // Composite predicate -- both filters AND'd together.
  function _matchesAllFilters(entry) {
    return _matchesProdIdFilter(entry.prod_id) && _matchesStatusFilter(entry);
  }

  // Phase 19/20: Crusher discovery + label helpers. Crushers live at
  // payload.Metrics.CrusherN (variable count per site). Each Crusher
  // node carries Description, Setpoint, and Runtime (decimal hours,
  // matching the rest of the payload).
  function _extractCrusherKeys(metrics) {
    if (!metrics || typeof metrics !== "object") return [];
    return Object.keys(metrics)
      .filter((k) => /^Crusher\d+$/.test(k))
      .sort((a, b) => parseInt(a.slice(7), 10) - parseInt(b.slice(7), 10));
  }

  function _humanizeCrusherKey(key) {
    // "Crusher1" -> "Crusher 1"
    return String(key).replace(/^Crusher(\d+)$/, "Crusher $1");
  }

  function _fmtRuntimeHours(v) {
    if (v === null || v === undefined || v === "") return "—";
    const n = Number(v);
    if (!isFinite(n)) return "—";
    return n.toFixed(1);
  }

  function _siteMetaRows(siteObj) {
    // Flat list of alternating key/value DOM nodes for the dm-meta
    // 2-column grid. Keys are grouped by base type via _sortSiteKeys
    // (e.g. all loader operators together, then all shot numbers),
    // not raw upstream insertion order -- upstream emits ordinals
    // interleaved (One, One, Two, Two) and that's confusing to read.
    const rows = [];
    for (const key of _sortSiteKeys(Object.keys(siteObj))) {
      rows.push(el("div", { class: "dm-meta-key" }, _formatSiteLabel(key)));
      rows.push(el("div", { class: "dm-meta-value" }, _formatSiteValue(siteObj[key])));
    }
    return rows;
  }

  function _onBackdropClick(e) {
    // Only close on backdrop click, not on clicks inside the dialog.
    const modal = $("details-modal");
    if (e.target === modal) closeDetailsModal();
  }
  function _onEscKey(e) {
    if (e.key === "Escape") closeDetailsModal();
  }

  function openDetailsModal(entry) {
    const modal = $("details-modal");
    const body = $("details-modal-body");
    if (!modal || !body) return;

    body.innerHTML = "";

    // Section: Report metadata.
    body.appendChild(el("div", {}, [
      el("div", { class: "dm-section-label" }, "Report"),
      el("div", { class: "dm-meta" }, [
        el("div", { class: "dm-meta-key" }, "Department ID"),
        el("div", { class: "dm-meta-value" }, String(entry.department_id)),
        // Phase 12: Department Name row sits directly below the ID. Both
        // are kept visible -- the dashboard hides ID from primary UI but
        // the modal is a "show me everything we have on this report" view.
        // Em-dash on null since the ID row above already covers identity.
        el("div", { class: "dm-meta-key" }, "Department Name"),
        el("div", { class: "dm-meta-value" },
          (entry.department_name && typeof entry.department_name === "string"
            && entry.department_name.trim()) ? entry.department_name : "—"),
        el("div", { class: "dm-meta-key" }, "Prod. Date"),
        el("div", { class: "dm-meta-value" }, fmtDate(entry.prod_date)),
        el("div", { class: "dm-meta-key" }, "Production ID"),
        el("div", { class: "dm-meta-value mono" }, entry.prod_id),
        el("div", { class: "dm-meta-key" }, "Shift"),
        el("div", { class: "dm-meta-value" }, entry.shift || "\u2014"),
      ]),
    ]));

    // Section: Site (Phase 11). Operator-captured plant context --
    // loader operators, shot numbers, manual load counts, and any
    // future fields the upstream system adds. Rendered dynamically:
    // iterates whatever keys are present in payload.Metrics.Site so
    // a new field appears in the modal without a frontend change.
    // See payload-schema.md "Section: Site" for current known fields
    // and the Quirks list for "None"/placeholder semantics.
    const siteObj = entry.payload && entry.payload.Metrics && entry.payload.Metrics.Site;
    const siteSection = [el("div", { class: "dm-section-label" }, "Site")];
    if (siteObj && typeof siteObj === "object" && Object.keys(siteObj).length > 0) {
      siteSection.push(el("div", { class: "dm-meta" }, _siteMetaRows(siteObj)));
    } else {
      siteSection.push(el("div", { class: "dm-empty" }, "No site data for this report."));
    }
    body.appendChild(el("div", {}, siteSection));

    // Section: Crushers (Phase 19/20). Variable count of CrusherN nodes
    // under payload.Metrics. Each row in the table is one crusher with
    // its Description, Setpoint, and Runtime in decimal hours. Section
    // is skipped entirely when no CrusherN keys are present -- not all
    // reports / older data carry them.
    {
      const _metrics = entry.payload && entry.payload.Metrics;
      const _crusherKeys = _extractCrusherKeys(_metrics);
      if (_crusherKeys.length > 0) {
        const _thead = el("thead", {}, [
          el("tr", {}, [
            el("th", {}, "Crusher"),
            el("th", {}, "Description"),
            el("th", {}, "Setpoint"),
            el("th", { class: "num" }, "Runtime (hrs)"),
          ]),
        ]);
        const _tbody = el("tbody", {});
        for (const _ck of _crusherKeys) {
          const _c = (_metrics[_ck] && typeof _metrics[_ck] === "object") ? _metrics[_ck] : {};
          _tbody.appendChild(el("tr", {}, [
            el("td", {}, _humanizeCrusherKey(_ck)),
            el("td", {}, _formatSiteValue(_c.Description)),
            el("td", {}, _formatSiteValue(_c.Setpoint)),
            el("td", { class: "num" }, _fmtRuntimeHours(_c.Runtime)),
          ]));
        }
        body.appendChild(el("div", {}, [
          el("div", { class: "dm-section-label" }, "Crushers"),
          el("table", { class: "dm-crusher-table" }, [_thead, _tbody]),
        ]));
      }
    }

    // Section: Weather. Header row shows the severity-picked icon as
    // the at-a-glance summary; three numeric cells show the shift
    // aggregates; a trailing muted line prints the FULL condition list
    // so the user sees everything that happened (not just the worst).
    const hasWeather =
      (entry.weather_conditions && entry.weather_conditions.trim()) ||
      entry.avg_temp !== null && entry.avg_temp !== undefined ||
      entry.avg_humidity !== null && entry.avg_humidity !== undefined ||
      entry.max_wind_speed !== null && entry.max_wind_speed !== undefined;
    const weatherSection = [el("div", { class: "dm-section-label" }, "Weather")];
    if (hasWeather) {
      const iconKey = pickWeatherIcon(entry.weather_conditions);
      // Icon + primary picked condition in a header row.
      const header = [];
      if (iconKey) header.push(renderWeatherIcon(iconKey, "wi-modal"));
      header.push(el("span", { class: "dm-weather-primary" },
        entry.weather_conditions ? entry.weather_conditions.split(",")[0].trim() : "\u2014"));
      weatherSection.push(el("div", { class: "dm-weather-header" }, header));
      // Three numeric cells (temp / humidity / wind).
      weatherSection.push(el("div", { class: "dm-weather dm-weather-3" }, [
        _weatherCell("Avg Temp", fmtWithUnit(entry.avg_temp, "\u00B0F")),
        _weatherCell("Avg Humidity", fmtWithUnit(entry.avg_humidity, "%")),
        _weatherCell("Max Wind", fmtWithUnit(entry.max_wind_speed, " mph")),
      ]));
      // Full list of conditions (shows comma-separated STUFF text so
      // the user sees every condition that occurred, not just the
      // severity-picked one).
      if (entry.weather_conditions && entry.weather_conditions.trim()) {
        weatherSection.push(el("div", { class: "dm-weather-full" }, [
          el("span", { class: "dm-weather-full-label" }, "All conditions: "),
          el("span", { class: "dm-weather-full-text" }, entry.weather_conditions),
        ]));
      }
    } else {
      weatherSection.push(el("div", { class: "dm-empty" }, "No weather data for this report."));
    }
    body.appendChild(el("div", {}, weatherSection));

    // Section: Notes (pre-wrapped).
    const hasNotes = typeof entry.notes === "string" && entry.notes.trim().length > 0;
    body.appendChild(el("div", {}, [
      el("div", { class: "dm-section-label" }, "Notes"),
      hasNotes
        ? el("div", { class: "dm-notes" }, entry.notes)
        : el("div", { class: "dm-empty" }, "No notes for this report."),
    ]));

    // Show the modal + wire transient listeners.
    _modalLastFocus = document.activeElement;
    modal.style.display = "";
    const closeBtn = modal.querySelector(".details-modal-close");
    if (closeBtn) closeBtn.focus();
    modal.addEventListener("click", _onBackdropClick);
    document.addEventListener("keydown", _onEscKey);
  }

  function closeDetailsModal() {
    const modal = $("details-modal");
    if (!modal || modal.style.display === "none") return;
    modal.style.display = "none";
    modal.removeEventListener("click", _onBackdropClick);
    document.removeEventListener("keydown", _onEscKey);
    if (_modalLastFocus && typeof _modalLastFocus.focus === "function") {
      _modalLastFocus.focus();
    }
    _modalLastFocus = null;
  }

  // --- refresh cycle + polling gate ---
  async function refreshHealth() {
    try {
      renderHealth(await fetchJSON("/api/health"));
    } catch (err) {
      console.error("health fetch failed", err);
    }
  }

  async function refreshData() {
    if (!currentSiteId || !currentSelection) return;
    try {
      const payload = await fetchJSON(dataUrlForSelection(currentSelection, currentSiteId));
      _lastPayload = payload;  // cached for theme-toggle rerender + export
      updateExportButtonState();
      renderData(payload);
      clearError();
    } catch (err) {
      console.error("data fetch failed", err);
      showError(`Failed to load production data: ${err.message}`);
    }
  }

  function retunePolling() {
    // Poll only when the selected window includes today. Fixed-past
    // windows are settled -- no new data will land, so the 30s tick
    // is wasted work. Re-arm when a change pulls today back in.
    const shouldPoll = currentSelection && selectionIncludesToday(currentSelection);
    if (shouldPoll) {
      if (!refreshTimer) {
        refreshTimer = setInterval(() => {
          refreshHealth();
          refreshData();
        }, REFRESH_MS);
      }
    } else if (refreshTimer) {
      clearInterval(refreshTimer);
      refreshTimer = null;
    }
  }

  // --- bootstrap ---
  async function bootstrap() {
    applyTheme(getTheme());
    const themeBtn = $("theme-toggle");
    if (themeBtn) themeBtn.addEventListener("click", toggleTheme);

    const exportBtn = $("export-btn");
    if (exportBtn) exportBtn.addEventListener("click", () => {
      // Route to the right export based on which view is active.
      // Both functions read their own cached payload; if neither
      // has data the button is already disabled.
      if (currentView === "trends") exportTrends();
      else exportCurrentSelection();
    });

    // Phase 8: Details modal's close (X) button. Backdrop click + ESC
    // are wired transiently inside openDetailsModal/closeDetailsModal.
    const modalCloseBtn = document.querySelector("#details-modal .details-modal-close");
    if (modalCloseBtn) modalCloseBtn.addEventListener("click", closeDetailsModal);

    // Phase 10b: view tabs + hash routing + trends month-range inputs.
    wireViewTabs();
    populateTrendsRangeDefaults();
    wireTrendsControls();
    window.addEventListener("hashchange", () => applyViewFromHash());
    applyViewFromHash();  // initial paint based on current URL

    populateYearOptions();
    wireTimeFilterControls();

    try {
      const sitesResp = await fetchJSON("/api/sites");
      sites = sitesResp.sites || [];
    } catch (err) {
      showError(`Failed to load sites: ${err.message}`);
      return;
    }
    if (sites.length === 0) {
      showError("No sites available in the data source.");
      return;
    }
    currentSiteId = sites[0].id;

    // Selection bootstrap: localStorage wins, else /latest-date for
    // the default site, else today.
    const saved = loadSelection();
    if (saved) {
      currentSelection = saved;
    } else {
      const latest = await fetchLatestDate(currentSiteId);
      currentSelection = defaultSelection();
      if (latest) currentSelection.dayDate = latest;
    }

    renderSiteToggle();
    renderSiteStrip();
    reflectSelectionInControls();
    renderChips();

    await Promise.all([refreshHealth(), refreshData()]);
    retunePolling();
  }


  // --- Phase 10b: Trends view ----------------------------------------
  //
  // Hash-routed. #trends shows multi-month line charts of monthly
  // rollups computed by the backend at /api/production-report/rollup/{bucket}.
  // No client-side math -- the frontend just groups by department_id
  // and feeds Chart.js. When Flow eventually publishes monthly aggregate
  // measures, the swap happens inside the backend service; this code
  // doesn\'t need to change.

  // Distinct colors for multi-line charts. Workcenter N gets the Nth
  // entry (modulo). Picked to read in both light and dark themes.
  const TREND_COLORS = [
    "#0078d4",  // accent blue
    "#107c10",  // green
    "#e66c37",  // orange
    "#7a4800",  // amber
    "#a4262c",  // crimson
    "#5c2d91",  // purple
    "#2b88d8",  // brighter blue
    "#6ccb5f",  // light green
  ];

  function _destroyTrendCharts() {
    for (const c of _trendChartInstances) {
      try { c.destroy(); } catch (_) { /* already gone */ }
    }
    _trendChartInstances.clear();
  }

  function wireViewTabs() {
    for (const btn of document.querySelectorAll("#view-tabs .vtab")) {
      btn.addEventListener("click", () => {
        const next = btn.dataset.view;
        if (!next || next === currentView) return;
        // Setting the hash triggers our hashchange listener which
        // calls applyViewFromHash(); single source of truth.
        location.hash = "#" + next;
      });
    }
  }

  function applyViewFromHash() {
    const target = (location.hash || "").replace(/^#/, "");
    const next = target === "trends" ? "trends" : "dashboard";
    if (next === currentView && document.querySelector("#" + next + "-view").style.display !== "none") {
      // No-op if already on this view AND it\'s visible (initial bootstrap covers
      // the case where currentView matches default but view containers are still hidden).
    }
    currentView = next;

    // Toggle the view containers.
    const dashView = $("dashboard-view");
    const trendsView = $("trends-view");
    if (dashView) dashView.style.display = next === "dashboard" ? "" : "none";
    if (trendsView) trendsView.style.display = next === "trends" ? "" : "none";

    // Tab visual state.
    for (const btn of document.querySelectorAll("#view-tabs .vtab")) {
      const on = btn.dataset.view === next;
      btn.classList.toggle("on", on);
      btn.setAttribute("aria-selected", on ? "true" : "false");
    }

    // Export button is visible on both Dashboard and Trends. Its
    // click handler routes based on currentView, and its enabled
    // state reflects whichever view's cached payload exists.
    updateExportButtonState();

    // First time we land on trends, fetch + render.
    if (next === "trends" && currentSiteId) {
      refreshTrends();
    }
  }

  function populateTrendsRangeDefaults() {
    // Default monthly range: last 12 calendar months ending at the
    // current month.
    const now = new Date();
    const toY = now.getFullYear();
    const toM = now.getMonth() + 1;
    let fromY = toY;
    let fromM = toM - 11;
    while (fromM <= 0) { fromM += 12; fromY -= 1; }
    const fromInput = $("trends-from-month");
    const toInput = $("trends-to-month");
    if (fromInput) fromInput.value = `${fromY}-${pad2(fromM)}`;
    if (toInput) toInput.value = `${toY}-${pad2(toM)}`;

    // Phase 18: populate yearly selects with 2020..currentYear.
    // Default selection: last 5 years ending at current year.
    const fromYearSel = $("trends-from-year");
    const toYearSel = $("trends-to-year");
    if (fromYearSel && fromYearSel.children.length === 0) {
      for (let y = 2020; y <= toY; y++) {
        const opt = document.createElement("option");
        opt.value = String(y);
        opt.textContent = String(y);
        fromYearSel.appendChild(opt);
      }
      fromYearSel.value = String(Math.max(2020, toY - 4));
    }
    if (toYearSel && toYearSel.children.length === 0) {
      for (let y = 2020; y <= toY; y++) {
        const opt = document.createElement("option");
        opt.value = String(y);
        opt.textContent = String(y);
        toYearSel.appendChild(opt);
      }
      toYearSel.value = String(toY);
    }

    // Sync the toggle button + picker visibility to the saved bucket.
    _applyBucketUi(_activeTrendsBucket);
  }

  function wireTrendsControls() {
    const monthInputs = ["trends-from-month", "trends-to-month",
                         "trends-from-year", "trends-to-year"];
    const onChange = () => {
      if (currentView === "trends" && currentSiteId) refreshTrends();
    };
    for (const id of monthInputs) {
      const el = $(id);
      if (el) el.addEventListener("change", onChange);
    }

    // Phase 18: bucket toggle (Monthly/Yearly).
    const toggle = $("trends-bucket-toggle");
    if (toggle) {
      toggle.addEventListener("click", (ev) => {
        const btn = ev.target.closest(".bucket-btn");
        if (!btn) return;
        _setActiveTrendsBucket(btn.dataset.bucket);
      });
    }
  }

  // Phase 18: switch between Monthly and Yearly bucket modes. Persists
  // to localStorage so the choice survives reloads.
  function _setActiveTrendsBucket(bucket) {
    if (bucket !== "monthly" && bucket !== "yearly") return;
    if (bucket === _activeTrendsBucket) return;
    _activeTrendsBucket = bucket;
    try { localStorage.setItem("pmd-trends-bucket", bucket); } catch (_e) {}
    _applyBucketUi(bucket);
    // Clear cached payloads immediately so neither the export nor any
    // theme-toggle re-render uses the previous bucket's data while the
    // refetch is in flight. updateExportButtonState() flips Excel to
    // disabled because rollups.length will be 0.
    _lastTrendsPayload = null;
    _lastTrendsCircuitPayload = null;
    updateExportButtonState();
    if (currentView === "trends" && currentSiteId) refreshTrends();
  }

  // Visual sync only: button "on" state + picker group visibility.
  // Separated so populateTrendsRangeDefaults can call it on boot
  // without triggering a refetch.
  function _applyBucketUi(bucket) {
    for (const btn of document.querySelectorAll("#trends-bucket-toggle .bucket-btn")) {
      const on = btn.dataset.bucket === bucket;
      btn.classList.toggle("on", on);
      btn.setAttribute("aria-selected", on ? "true" : "false");
    }
    for (const elx of document.querySelectorAll(".trends-monthly-only")) {
      elx.style.display = bucket === "monthly" ? "" : "none";
    }
    for (const elx of document.querySelectorAll(".trends-yearly-only")) {
      elx.style.display = bucket === "yearly" ? "" : "none";
    }
  }

  function _trendsRange() {
    if (_activeTrendsBucket === "yearly") {
      const fromY = parseInt(($("trends-from-year") || {}).value || "0", 10);
      const toY = parseInt(($("trends-to-year") || {}).value || "0", 10);
      if (!fromY || !toY) return null;
      return {
        bucket: "yearly",
        from_date: `${fromY}-01-01`,
        to_date: `${toY}-12-31`,
      };
    }
    const fromMonth = ($("trends-from-month") || {}).value || "";
    const toMonth = ($("trends-to-month") || {}).value || "";
    if (!fromMonth || !toMonth) return null;
    const [fy, fm] = fromMonth.split("-");
    const [ty, tm] = toMonth.split("-");
    // Last day of the to-month: JS Date with day=0 of next month.
    const lastDay = new Date(parseInt(ty, 10), parseInt(tm, 10), 0).getDate();
    return {
      bucket: "monthly",
      from_date: `${fy}-${fm}-01`,
      to_date: `${ty}-${tm}-${pad2(lastDay)}`,
    };
  }

  async function refreshTrends() {
    if (!currentSiteId) return;
    const range = _trendsRange();
    if (!range) return;

    const status = $("trends-status");
    if (status) status.textContent = "Loading...";

    const baseQs =
        `?site_id=${encodeURIComponent(currentSiteId)}`
      + `&from_date=${encodeURIComponent(range.from_date)}`
      + `&to_date=${encodeURIComponent(range.to_date)}`;
    const rollupUrl  = `/api/production-report/rollup/${range.bucket}${baseQs}`;
    const circuitUrl = `/api/production-report/circuit-rollup/${range.bucket}${baseQs}`;

    try {
      // Phase 14b: both rollups in parallel. The dashboard pairs
      // workcenter and circuit views per department in a single render.
      const [payload, circuitPayload] = await Promise.all([
        fetchJSON(rollupUrl),
        fetchJSON(circuitUrl),
      ]);
      _lastTrendsPayload = payload;
      _lastTrendsCircuitPayload = circuitPayload;
      renderTrends(payload, circuitPayload);
      updateExportButtonState();
      _clearTrendsError();
      // Status text intentionally cleared on success -- the
      // dashboard's topbar "Refreshed HH:MM" already conveys the
      // freshness signal; a duplicate rollup-count line in the
      // trends-controls bar was visual noise.
      if (status) status.textContent = "";
    } catch (err) {
      console.error("trends fetch failed", err);
      _showTrendsError(`Failed to load trends data: ${err.message}`);
      if (status) status.textContent = "error";
    }
  }

  function _showTrendsError(msg) {
    const bar = $("trends-err-bar");
    if (!bar) return;
    bar.style.display = "";
    bar.textContent = msg;
  }
  function _clearTrendsError() {
    const bar = $("trends-err-bar");
    if (bar) bar.style.display = "none";
  }

  // Phase 22: extract the latest bucket's Calcs.<metric> formula for
  // an entity (workcenter / circuit / line). Buckets are sorted by
  // bucket_label ascending; iterate from the end so the freshest one
  // wins. Returns the formula string or null.
  function _calcsLatest(buckets, metric) {
    if (!buckets) return null;
    // Accept both Array (circuit.buckets, line.buckets) and Map
    // (renderTrends' per-dept Map keyed by bucket_label). Materialize
    // the Map's values in insertion order so latest-bucket-wins still
    // means walking from the end.
    const list = Array.isArray(buckets) ? buckets : [...buckets.values()];
    if (!list.length) return null;
    for (let i = list.length - 1; i >= 0; i--) {
      const c = list[i] && list[i].calcs;
      if (c && typeof c === "object" && typeof c[metric] === "string" && c[metric]) {
        return c[metric];
      }
    }
    return null;
  }

  // Single-entity calcs line (per-workcenter / circuit / line).
  // Returns "Calcs.<metric> = <formula>" or null when absent.
  function _singleCalcsLine(buckets, metric) {
    const f = _calcsLatest(buckets, metric);
    return f ? `Calcs.${metric} = ${f}` : null;
  }

  // Multi-entity calcs line (Overview Total Tons by Workcenter,
  // Tons-per-Line). `items` is [{label, buckets}, ...]. Builds
  // "Calcs.<metric> — Label1: f1  •  Label2: f2"; null when no entity
  // surfaces a formula.
  function _multiCalcsLine(items, metric) {
    const parts = [];
    for (const item of items) {
      const f = _calcsLatest(item.buckets, metric);
      if (f) parts.push(`${item.label}: ${f}`);
    }
    if (!parts.length) return null;
    return `Calcs.${metric} \u2014 ${parts.join("  \u2022  ")}`;
  }

  function renderTrends(payload, circuitPayload) {
    const grid = $("trends-grid");
    const tablist = $("trends-tablist");
    const empty = $("trends-empty-state");
    if (!grid) return;

    _destroyTrendCharts();
    grid.innerHTML = "";
    if (tablist) tablist.innerHTML = "";

    const rollups = payload.rollups || [];
    if (rollups.length === 0) {
      if (empty) empty.style.display = "";
      return;
    }
    if (empty) empty.style.display = "none";

    // Build the X-axis: union of distinct months across all rollups,
    // sorted lexicographically (YYYY-MM sorts naturally).
    const monthSet = new Set();
    for (const r of rollups) monthSet.add(r.bucket_label);
    const months = [...monthSet].sort();

    // Group rollups by department_id, indexed by month for fast lookup.
    const byDept = new Map();
    for (const r of rollups) {
      if (!byDept.has(r.department_id)) byDept.set(r.department_id, new Map());
      byDept.get(r.department_id).set(r.bucket_label, r);
    }
    const deptIds = [...byDept.keys()].sort();

    const deptLabel = (dept) => {
      const firstRollup = byDept.get(dept).values().next().value;
      const name = firstRollup ? firstRollup.department_name : null;
      return deptName(name, dept);
    };

    const buildDatasets = (extractor) => deptIds.map((dept, idx) => {
      const data = months.map((m) => {
        const r = byDept.get(dept).get(m);
        if (!r) return null;
        const v = extractor(r);
        return (v === null || v === undefined) ? null : v;
      });
      return {
        label: deptLabel(dept),
        data,
        borderColor: TREND_COLORS[idx % TREND_COLORS.length],
        backgroundColor: TREND_COLORS[idx % TREND_COLORS.length],
        spanGaps: false,
        tension: 0.2,
        pointRadius: 3,
      };
    });

    const buildBarDataset = (dept, extractor, idx) => {
      const color = TREND_COLORS[idx % TREND_COLORS.length];
      const data = months.map((m) => {
        const r = byDept.get(dept).get(m);
        if (!r) return null;
        const v = extractor(r);
        return (v === null || v === undefined) ? null : v;
      });
      return {
        label: deptLabel(dept),
        data,
        backgroundColor: color,
        borderColor: color,
        borderWidth: 1,
      };
    };

    // Phase 14b restructure: every renderable section becomes a tab.
    // `sections` is built up as (id, label, indent, build) records;
    // each `build` closure populates a section container with chart
    // panels. The tablist is rendered in parallel so order matches.
    const sections = [];

    sections.push({
      id: "overview",
      label: "Overview",
      indent: 0,
      build: (s) => {
        s.appendChild(_renderTrendPanel({
          title: "Total Tons by Workcenter",
          subtitle: "Sum of Workcenter.Total across the selected range, per workcenter.",
          calcsLine: _multiCalcsLine(
            deptIds.map((d) => ({ label: deptLabel(d), buckets: byDept.get(d) || [] })),
            "Total"
          ),
          labels: months,
          datasets: buildDatasets((r) => r.total_tons),
          yLabel: "Tons",
          yFormat: (v) => `${fmtInt(v)} t`,
        }));
        s.appendChild(_renderTrendPanel({
          title: "TPH by Workcenter",
          subtitle: "Average of per-report Workcenter.Rate (with fallback to Total/Runtime), per workcenter.",
          calcsLine: _multiCalcsLine(
            deptIds.map((d) => ({ label: deptLabel(d), buckets: byDept.get(d) || [] })),
            "Rate"
          ),
          labels: months,
          datasets: buildDatasets((r) => r.avg_tph_fed),
          yLabel: "Tons/hr",
          yFormat: (v) => `${fmt1(v)} tph`,
        }));
      },
    });

    const circuitDepts = (circuitPayload && circuitPayload.departments) || [];
    const circuitsByDeptId = new Map();
    for (const d of circuitDepts) circuitsByDeptId.set(d.department_id, d.circuits || []);

    deptIds.forEach((dept, idx) => {
      sections.push({
        id: `wc-${dept}`,
        label: deptLabel(dept),
        indent: 0,
        build: (s) => {
          const _wcBuckets = byDept.get(dept) || [];
          s.appendChild(_renderTrendPanel({
            title: "Total TPH Fed",
            subtitle: "Average of Workcenter.Rate per month.",
            calcsLine: _singleCalcsLine(_wcBuckets, "Rate"),
            labels: months,
            datasets: [buildBarDataset(dept, (r) => r.avg_tph_fed, idx)],
            yLabel: "Tons/hr",
            yFormat: (v) => `${fmtInt(v)} tph`,
            chartType: "bar",
          }));
          s.appendChild(_renderTrendPanel({
            title: "Runtime %",
            subtitle: "Average of Workcenter.Availability per month.",
            calcsLine: _singleCalcsLine(_wcBuckets, "Availability"),
            labels: months,
            datasets: [buildBarDataset(dept, (r) => r.avg_runtime_pct, idx)],
            yLabel: "%",
            yFormat: (v) => `${fmt1(v)}%`,
            chartType: "bar",
          }));
          s.appendChild(_renderTrendPanel({
            title: "Performance %",
            subtitle: "Average of Workcenter.Performance (Rate / Ideal_Rate * 100) per month.",
            calcsLine: _singleCalcsLine(_wcBuckets, "Performance"),
            labels: months,
            datasets: [buildBarDataset(dept, (r) => r.avg_performance_pct, idx)],
            yLabel: "%",
            yFormat: (v) => `${fmt1(v)}%`,
            chartType: "bar",
          }));
        },
      });

      const deptCircuits = circuitsByDeptId.get(dept) || [];
      deptCircuits.forEach((circuit, cidx) => {
        sections.push({
          id: `circuit-${dept}-${circuit.circuit_id}`,
          label: circuit.description || circuit.circuit_id,
          indent: 1,
          build: (s) => _renderCircuitSection(s, circuit, months, idx, cidx),
        });
      });
    });

    sections.forEach((sec) => {
      const sectionEl = el(
        "div",
        { class: "trend-section", "data-section-id": sec.id },
      );
      sec.build(sectionEl);
      grid.appendChild(sectionEl);

      if (tablist) {
        const tabBtn = el(
          "button",
          {
            type: "button",
            class: "trends-tab" + (sec.indent ? " nested" : ""),
            "data-section-id": sec.id,
            role: "tab",
            onclick: () => _setActiveTrendsTab(sec.id),
          },
          sec.label,
        );
        tablist.appendChild(tabBtn);
      }
    });

    const sectionIds = sections.map((s) => s.id);
    const targetTab = sectionIds.includes(_activeTrendsTab) ? _activeTrendsTab : "overview";
    _setActiveTrendsTab(targetTab);
  }

  function _setActiveTrendsTab(id) {
    _activeTrendsTab = id;
    const tablist = $("trends-tablist");
    const grid = $("trends-grid");
    if (tablist) {
      for (const btn of tablist.querySelectorAll(".trends-tab")) {
        btn.classList.toggle("active", btn.dataset.sectionId === id);
      }
    }
    if (grid) {
      for (const sec of grid.querySelectorAll(".trend-section")) {
        sec.classList.toggle("active", sec.dataset.sectionId === id);
      }
    }
  }

  // Phase 14b: render one circuit subsection. For circuits with sub-lines
  // we emit 6 chart panels (per-line + total for each of TPH, Yield, Tons);
  // for line-less circuits (e.g. CR Circuit) we emit 3 single-series panels.
  // All labels come from the circuit/line `description` fields -- the
  // dashboard never hard-codes "57-1" or "Main Circuit".
  function _renderCircuitSection(grid, circuit, months, deptIdx, circuitIdx) {
    // Phase 14b restructure: section header is now provided by the
    // tab list on the left; we append only chart panels here.

    // Per-month lookup for the circuit-level series.
    const cMap = new Map();
    for (const m of (circuit.buckets || [])) cMap.set(m.bucket_label, m);

    const buildCircuitDataset = (extractor, color) => {
      const data = months.map((m) => {
        const e = cMap.get(m);
        if (!e) return null;
        const v = extractor(e);
        return (v === null || v === undefined) ? null : v;
      });
      return {
        label: circuit.description || circuit.circuit_id,
        data,
        backgroundColor: color,
        borderColor: color,
        borderWidth: 1,
      };
    };

    const hasLines = (circuit.lines || []).length > 0;
    // Pick a base color slot deterministically from (deptIdx, circuitIdx)
    // so adjacent circuits visually distinguish from each other but each
    // workcenter's circuit family stays in its own color band.
    const baseColor = TREND_COLORS[(deptIdx * 2 + circuitIdx) % TREND_COLORS.length];

    if (hasLines) {
      // Build per-line datasets once -- reused across the three
      // paired-bar panels (TPH/Yield/Tons by Line).
      const lineMaps = circuit.lines.map((l, i) => {
        const m = new Map();
        for (const e of (l.buckets || [])) m.set(e.bucket_label, e);
        return { line: l, map: m, color: TREND_COLORS[(deptIdx * 2 + circuitIdx + i + 1) % TREND_COLORS.length] };
      });
      const buildPerLineDatasets = (extractor) => lineMaps.map(({ line, map, color }) => {
        const data = months.map((m) => {
          const e = map.get(m);
          if (!e) return null;
          const v = extractor(e);
          return (v === null || v === undefined) ? null : v;
        });
        return {
          label: line.description || line.line_id,
          data,
          backgroundColor: color,
          borderColor: color,
          borderWidth: 1,
        };
      });

      // 6 panels: paired-line + circuit-total for each of TPH / Yield / Tons.
      grid.appendChild(_renderTrendPanel({
        title: "TPH per Line",
        subtitle: "Mean of per-report Total/Runtime per line per month.",
        calcsLine: _multiCalcsLine(
          (circuit.lines || []).map((l) => ({ label: l.description || l.line_id, buckets: l.buckets || [] })),
          "Rate"
        ),
        labels: months,
        datasets: buildPerLineDatasets((e) => e.avg_tph),
        yLabel: "Tons/hr",
        yFormat: (v) => `${fmtInt(v)} tph`,
        chartType: "bar",
      }));
      grid.appendChild(_renderTrendPanel({
        title: "Total TPH",
        subtitle: "Circuit-level mean of per-report Total/Runtime per month.",
        calcsLine: _singleCalcsLine(circuit.buckets || [], "Rate"),
        labels: months,
        datasets: [buildCircuitDataset((e) => e.avg_tph, baseColor)],
        yLabel: "Tons/hr",
        yFormat: (v) => `${fmtInt(v)} tph`,
        chartType: "bar",
      }));

      grid.appendChild(_renderTrendPanel({
        title: "Yield per Line",
        subtitle: "Mean of per-report Yield (mass-conversion ratio) per line per month.",
        calcsLine: _multiCalcsLine(
          (circuit.lines || []).map((l) => ({ label: l.description || l.line_id, buckets: l.buckets || [] })),
          "Yield"
        ),
        labels: months,
        datasets: buildPerLineDatasets((e) => e.avg_yield),
        yLabel: "Yield",
        yFormat: (v) => fmt1(v),
        chartType: "bar",
      }));
      grid.appendChild(_renderTrendPanel({
        title: "Total Yield",
        subtitle: "Circuit-level mean of per-report Yield per month.",
        calcsLine: _singleCalcsLine(circuit.buckets || [], "Yield"),
        labels: months,
        datasets: [buildCircuitDataset((e) => e.avg_yield, baseColor)],
        yLabel: "Yield",
        yFormat: (v) => fmt1(v),
        chartType: "bar",
      }));

      grid.appendChild(_renderTrendPanel({
        title: "Tons per Line",
        subtitle: "Sum of node.Total per line per month.",
        calcsLine: _multiCalcsLine(
          (circuit.lines || []).map((l) => ({ label: l.description || l.line_id, buckets: l.buckets || [] })),
          "Total"
        ),
        labels: months,
        datasets: buildPerLineDatasets((e) => e.total_tons),
        yLabel: "Tons",
        yFormat: (v) => `${fmtInt(v)} t`,
        chartType: "bar",
      }));
      grid.appendChild(_renderTrendPanel({
        title: "Total Tons",
        subtitle: "Circuit-level sum of node.Total per month.",
        calcsLine: _singleCalcsLine(circuit.buckets || [], "Total"),
        labels: months,
        datasets: [buildCircuitDataset((e) => e.total_tons, baseColor)],
        yLabel: "Tons",
        yFormat: (v) => `${fmtInt(v)} t`,
        chartType: "bar",
      }));
    } else {
      // Line-less circuit: 3 single-series panels for TPH / Yield / Tons.
      grid.appendChild(_renderTrendPanel({
        title: "TPH",
        subtitle: "Mean of per-report Total/Runtime per month.",
        calcsLine: _singleCalcsLine(circuit.buckets || [], "Rate"),
        labels: months,
        datasets: [buildCircuitDataset((e) => e.avg_tph, baseColor)],
        yLabel: "Tons/hr",
        yFormat: (v) => `${fmtInt(v)} tph`,
        chartType: "bar",
      }));
      grid.appendChild(_renderTrendPanel({
        title: "Yield",
        subtitle: "Mean of per-report Yield per month.",
        calcsLine: _singleCalcsLine(circuit.buckets || [], "Yield"),
        labels: months,
        datasets: [buildCircuitDataset((e) => e.avg_yield, baseColor)],
        yLabel: "Yield",
        yFormat: (v) => fmt1(v),
        chartType: "bar",
      }));
      grid.appendChild(_renderTrendPanel({
        title: "Tons",
        subtitle: "Sum of node.Total per month.",
        calcsLine: _singleCalcsLine(circuit.buckets || [], "Total"),
        labels: months,
        datasets: [buildCircuitDataset((e) => e.total_tons, baseColor)],
        yLabel: "Tons",
        yFormat: (v) => `${fmtInt(v)} t`,
        chartType: "bar",
      }));
    }
  }

  function _renderTrendPanel({ title, subtitle, calcsLine, labels, datasets, yLabel, yFormat, chartType }) {
    const colors = _themeColors();
    // Phase 14a/b: chartType defaults to "line" for backward compat.
    // Legend visibility follows dataset count -- multi-series shows,
    // single-series hides -- regardless of chart type. This handles
    // both the existing multi-workcenter line charts (legend on,
    // one line per dept) AND the Phase 14b paired-bar charts (legend
    // on, one bar series per circuit Line) without per-call config.
    const _type = chartType || "line";
    const _showLegend = (datasets || []).length > 1;
    // Phase 22: optional Calcs footnote rendered below the subtitle.
    // Falsy/empty -> no extra row.
    const _headerKids = [
      el("span", { class: "trend-panel-title" }, title),
      el("span", { class: "trend-panel-meta" }, subtitle),
    ];
    if (calcsLine) _headerKids.push(el("span", { class: "trend-panel-calcs" }, calcsLine));
    const panel = el("section", { class: "trend-panel" }, [
      el("div", { class: "trend-panel-header" }, _headerKids),
      (() => {
        const wrap = el("div", { class: "trend-chart-wrap" });
        const canvas = el("canvas", { class: "trend-chart-canvas" });
        wrap.appendChild(canvas);
        // Defer chart instantiation to next tick so the canvas is in
        // the DOM when Chart.js measures it. Otherwise width/height
        // can come back as 0.
        setTimeout(() => {
          const chart = new Chart(canvas.getContext("2d"), {
            type: _type,
            data: { labels, datasets },
            options: {
              responsive: true,
              maintainAspectRatio: false,
              animation: false,
              plugins: {
                legend: {
                  display: _showLegend,
                  position: "bottom",
                  labels: { color: colors.ink, font: { size: 10 } },
                },
                tooltip: {
                  callbacks: {
                    label: (ctx) => `${ctx.dataset.label}: ${yFormat(ctx.parsed.y)}`,
                  },
                },
              },
              scales: {
                x: {
                  grid: { color: colors.grid },
                  ticks: { color: colors.ink, font: { size: 10 } },
                },
                y: {
                  beginAtZero: true,
                  grid: { color: colors.grid },
                  ticks: {
                    color: colors.ink,
                    font: { size: 10 },
                    callback: (v) => yFormat(v),
                  },
                  title: {
                    display: true,
                    text: yLabel,
                    color: colors.ink,
                    font: { size: 10 },
                  },
                },
              },
            },
          });
          _trendChartInstances.add(chart);
        }, 0);
        return wrap;
      })(),
    ]);
    return panel;
  }

  // --- Phase 14e: Trends data export ----------------------------------
  //
  // Builds a multi-sheet XLSX from the cached Trends payloads:
  //   * Overview          -- cross-workcenter monthly rollup
  //   * <workcenter name> -- per-workcenter monthly metrics
  //   * <circuit name>    -- per-circuit (with optional per-line) monthly metrics
  // Frontend-only; no backend round-trip. Reuses the same SheetJS
  // library and helpers as the Dashboard export.

  function _truncateSheetName(name) {
    // Excel sheet-name rules: <= 31 chars, no [ ] : * ? / \\.
    let n = String(name || "Sheet").replace(/[:\\/?*\[\]]/g, "_");
    return n.length > 31 ? n.slice(0, 31) : n;
  }

  function _appendSheet(wb, rows, formats, name) {
    if (!rows || !rows.length) return;
    const sheet = XLSX.utils.json_to_sheet(rows);
    applyColumnFormats(sheet, rows, formats || {});
    XLSX.utils.book_append_sheet(wb, sheet, _truncateSheetName(name));
  }

  async function exportTrends() {
    if (typeof XLSX === "undefined") {
      _showTrendsError("Export unavailable: XLSX library failed to load.");
      return;
    }
    // Defense in depth: if the cache's bucket doesn't match the current
    // toggle (e.g. user clicked Export immediately after toggling, before
    // _setActiveTrendsBucket's refresh landed), force a sync refresh
    // first. Without this, the export would write whichever bucket's
    // data happened to be cached.
    if (
      !_lastTrendsPayload
      || _lastTrendsPayload.bucket !== _activeTrendsBucket
    ) {
      await refreshTrends();
    }
    if (
      !_lastTrendsPayload
      || _lastTrendsPayload.bucket !== _activeTrendsBucket
    ) {
      // Refresh failed or still mismatches; nothing useful to export.
      return;
    }
    const payload = _lastTrendsPayload;
    const circuitPayload = _lastTrendsCircuitPayload;
    const rollups = payload.rollups || [];
    if (!rollups.length) return;

    try {
      const siteMeta = sites.find((s) => s.id === currentSiteId)
        || { id: currentSiteId, name: "" };

      // dept_id -> human-readable name lookup. Same logic the
      // dashboard renderer uses.
      const deptNameById = new Map();
      for (const r of rollups) deptNameById.set(r.department_id, r.department_name);
      const deptIds = [...deptNameById.keys()].sort();
      const labelFor = (dept) => deptName(deptNameById.get(dept), dept);

      // Circuit lookup keyed by department_id -- mirrors what
      // renderTrends does so sheet ordering matches the tab order.
      const circuitDepts = (circuitPayload && circuitPayload.departments) || [];
      const circuitsByDeptId = new Map();
      for (const d of circuitDepts) circuitsByDeptId.set(d.department_id, d.circuits || []);

      const wb = XLSX.utils.book_new();

      // ---- Overview sheet (mirrors the cross-workcenter line charts).
      const overviewRows = rollups.map((r) => ({
        "Bucket":             r.bucket_label,
        "Workcenter":         labelFor(r.department_id),
        "Total Tons":         numOrEmpty(r.total_tons),
        "Avg TPH Fed":        numOrEmpty(r.avg_tph_fed),
        "Avg Runtime %":      numOrEmpty(r.avg_runtime_pct),
        "Avg Performance %":  numOrEmpty(r.avg_performance_pct),
        "Reports":            r.report_count,
      }));
      _appendSheet(wb, overviewRows, {
        "Total Tons": "#,##0",
        "Avg TPH Fed": "0.0",
        "Avg Runtime %": '0.0"%"',
        "Avg Performance %": '0.0"%"',
      }, "Overview");

      // ---- Per-workcenter sheets, each followed by its circuit sheets.
      deptIds.forEach((dept) => {
        const wcRows = rollups
          .filter((r) => r.department_id === dept)
          .map((r) => ({
            "Bucket":               r.bucket_label,
            "Total Tons":           numOrEmpty(r.total_tons),
            "Total Runtime (hours)": numOrEmpty(r.total_runtime_hours),
            "Avg TPH Fed":          numOrEmpty(r.avg_tph_fed),
            "Avg Runtime %":        numOrEmpty(r.avg_runtime_pct),
            "Avg Performance %":    numOrEmpty(r.avg_performance_pct),
            "Reports":              r.report_count,
          }));
        _appendSheet(wb, wcRows, {
          "Total Tons": "#,##0",
          "Total Runtime (hours)": "0.0",
          "Avg TPH Fed": "0.0",
          "Avg Runtime %": '0.0"%"',
          "Avg Performance %": '0.0"%"',
        }, labelFor(dept));

        // Circuit sheets under this workcenter.
        const deptCircuits = circuitsByDeptId.get(dept) || [];
        deptCircuits.forEach((circuit) => {
          const hasLines = (circuit.lines || []).length > 0;
          let rows;
          if (hasLines) {
            // Circuit-with-lines: one long-format table with a Level
            // column. "Circuit" rows first, then per-line rows.
            rows = [];
            for (const m of (circuit.buckets || [])) {
              rows.push({
                "Level":            "Circuit",
                "Bucket":           m.bucket_label,
                "Total Tons":       numOrEmpty(m.total_tons),
                "Runtime (hours)":  numOrEmpty(m.runtime_hours),
                "TPH":              numOrEmpty(m.avg_tph),
                "Yield":            numOrEmpty(m.avg_yield),
                "Reports":          m.report_count,
              });
            }
            for (const line of circuit.lines) {
              for (const m of (line.buckets || [])) {
                rows.push({
                  "Level":            line.description || line.line_id,
                  "Bucket":           m.bucket_label,
                  "Total Tons":       numOrEmpty(m.total_tons),
                  "Runtime (hours)":  numOrEmpty(m.runtime_hours),
                  "TPH":              numOrEmpty(m.avg_tph),
                  "Yield":            numOrEmpty(m.avg_yield),
                  "Reports":          m.report_count,
                });
              }
            }
          } else {
            rows = (circuit.buckets || []).map((m) => ({
              "Bucket":           m.bucket_label,
              "Total Tons":       numOrEmpty(m.total_tons),
              "Runtime (hours)":  numOrEmpty(m.runtime_hours),
              "TPH":              numOrEmpty(m.avg_tph),
              "Yield":            numOrEmpty(m.avg_yield),
              "Reports":          m.report_count,
            }));
          }
          _appendSheet(wb, rows, {
            "Total Tons": "#,##0",
            "Runtime (hours)": "0.0",
            "TPH": "0.0",
            "Yield": "0.000",
          }, circuit.description || circuit.circuit_id);
        });
      });

      const fromMonth = (payload.from_date || "").replace(/[^0-9-]/g, "");
      const toMonth = (payload.to_date || "").replace(/[^0-9-]/g, "");
      const filename =
        `production-metrics_${slugifySite(siteMeta.name, siteMeta.id)}` +
        `_trends_${fromMonth}_${toMonth}_${timestampSlug()}.xlsx`;
      XLSX.writeFile(wb, filename);
    } catch (err) {
      console.error("trends export failed", err);
      _showTrendsError(`Trends export failed: ${err.message}`);
    }
  }

  document.addEventListener("DOMContentLoaded", bootstrap);
})();
