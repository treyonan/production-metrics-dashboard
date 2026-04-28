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
      renderTrends(_lastTrendsPayload);
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
  function assetRow(label, m) {
    const item = placeholderize(m.Produced_Item_Code);
    const itemDesc = placeholderize(m.Produced_Item_Description);
    return el("tr", {}, [
      el("td", {}, label),
      el("td", {}, fmt1(m.Availability)),
      el("td", {}, fmt1(m.Runtime)),
      el("td", {}, m.Performance === null ? "\u2014" : fmt1(m.Performance)),
      el("td", {}, fmtInt(m.Total)),
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
        el("div", { class: "kl" }, "Runtime (min)"),
        el("div", { class: "kv" }, fmt1(wc.Runtime ?? wc.Actual_Runtime_Hours * 60)),
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
    const rows = assetKeys.map((k) => assetRow(k, metrics[k]));
    const table = el("table", { class: "mx" }, [
      el("thead", {}, el("tr", {}, [
        el("th", {}, "Asset"),
        el("th", {}, "Availability %"),
        el("th", {}, "Runtime (min)"),
        el("th", {}, "Performance %"),
        el("th", {}, "Total (tons)"),
        el("th", {}, "Product"),
        el("th", {}, "Belt Scale %"),
      ])),
      el("tbody", {}, rows.length ? rows : [el("tr", {}, el("td", { colspan: "7", class: "muted" }, "No asset metrics in this payload."))]),
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
    headerChildren.push(detailsButton(entry));

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
      el("td", {}, fmt1(wc.Runtime ?? (wc.Actual_Runtime_Hours != null ? wc.Actual_Runtime_Hours * 60 : null))),
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
        el("th", {}, "Runtime (min)"),
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
    _currentConveyorTotals = payload.conveyor_totals || null;
    host.innerHTML = "";
    const empty = $("empty-state");
    const entries = payload.entries || [];

    if (entries.length === 0) {
      empty.style.display = "";
      empty.textContent = currentSelection
        ? `Nothing reported for ${selectionLabel(currentSelection)}.`
        : "No production data for this selection.";
      $("refresh-lbl").textContent =
        `Refreshed ${new Date(payload.generated_at).toLocaleTimeString()} (no data in window)`;
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

    const conveyorNames = Object.keys(totals.per_conveyor);
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
    const entries = payload.entries || [];

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

    const grouped = new Map();
    for (const e of entries) {
      if (!grouped.has(e.department_id)) grouped.set(e.department_id, []);
      grouped.get(e.department_id).push(e);
    }
    const sortedDepts = [...grouped.keys()].sort();
    for (const deptId of sortedDepts) {
      for (const entry of grouped.get(deptId)) {
        const metrics = entry.payload && entry.payload.Metrics ? entry.payload.Metrics : {};
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
            "Runtime (min)": numOrEmpty(m.Runtime),
            "Performance %": numOrEmpty(m.Performance),
            "Total (tons)": numOrEmpty(m.Total),
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
        "Runtime (min)": "0.0",
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
    const canExport = !!(_lastPayload && (_lastPayload.entries || []).length);
    btn.disabled = !canExport;
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
  function detailsButton(entry) {
    return el("button", {
      type: "button",
      class: "details-btn",
      "aria-label": "Open details for this production report",
      title: "Open details",
      onclick: () => openDetailsModal(entry),
    }, "View");
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
    if (exportBtn) exportBtn.addEventListener("click", exportCurrentSelection);

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
  // rollups computed by the backend at /api/production-report/monthly-rollup.
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

    // Export button only meaningful on dashboard for now.
    const exportBtn = $("export-btn");
    if (exportBtn) exportBtn.style.display = next === "dashboard" ? "" : "none";

    // First time we land on trends, fetch + render.
    if (next === "trends" && currentSiteId) {
      refreshTrends();
    }
  }

  function populateTrendsRangeDefaults() {
    // Default range: last 12 calendar months ending at the current month.
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
  }

  function wireTrendsControls() {
    const fromInput = $("trends-from-month");
    const toInput = $("trends-to-month");
    const onChange = () => {
      if (currentView === "trends" && currentSiteId) refreshTrends();
    };
    if (fromInput) fromInput.addEventListener("change", onChange);
    if (toInput) toInput.addEventListener("change", onChange);
  }

  function _trendsRange() {
    const from = ($("trends-from-month") || {}).value || "";
    const to = ($("trends-to-month") || {}).value || "";
    return { from, to };
  }

  async function refreshTrends() {
    if (!currentSiteId) return;
    const { from, to } = _trendsRange();
    if (!from || !to) return;

    const status = $("trends-status");
    if (status) status.textContent = "Loading...";

    const url = `/api/production-report/monthly-rollup`
      + `?site_id=${encodeURIComponent(currentSiteId)}`
      + `&from_month=${encodeURIComponent(from)}`
      + `&to_month=${encodeURIComponent(to)}`;

    try {
      const payload = await fetchJSON(url);
      _lastTrendsPayload = payload;
      renderTrends(payload);
      _clearTrendsError();
      if (status) {
        status.textContent =
          `${payload.rollups.length} rollups, generated ${new Date(payload.generated_at).toLocaleTimeString()}`;
      }
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

  function renderTrends(payload) {
    const grid = $("trends-grid");
    const empty = $("trends-empty-state");
    if (!grid) return;

    _destroyTrendCharts();
    grid.innerHTML = "";

    const rollups = payload.rollups || [];
    if (rollups.length === 0) {
      if (empty) empty.style.display = "";
      return;
    }
    if (empty) empty.style.display = "none";

    // Build the X-axis: union of distinct months across all rollups,
    // sorted lexicographically (YYYY-MM sorts naturally).
    const monthSet = new Set();
    for (const r of rollups) monthSet.add(r.month);
    const months = [...monthSet].sort();

    // Group rollups by department_id, indexed by month for fast lookup.
    const byDept = new Map();
    for (const r of rollups) {
      if (!byDept.has(r.department_id)) byDept.set(r.department_id, new Map());
      byDept.get(r.department_id).set(r.month, r);
    }
    const deptIds = [...byDept.keys()].sort();

    // Phase 12: dept_id -> human-readable name lookup. All rollup
    // entries for a given dept share the same department_name (Phase 12
    // backend guarantees), so we just take the first one we see. Falls
    // back to "Dept <id>" via deptName() when name is null (CSV path
    // or pre-Phase-12 server). Used as the chart-legend label.
    const deptLabel = (dept) => {
      const firstRollup = byDept.get(dept).values().next().value;
      const name = firstRollup ? firstRollup.department_name : null;
      return deptName(name, dept);
    };

    // Helper to build datasets for a particular metric extractor.
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

    grid.appendChild(_renderTrendPanel({
      title: "Total Tons by Workcenter",
      subtitle: "Sum of belt-scaled conveyor totals per month, per workcenter.",
      labels: months,
      datasets: buildDatasets((r) => r.total_tons),
      yLabel: "Tons",
      yFormat: (v) => `${fmtInt(v)} t`,
    }));

    grid.appendChild(_renderTrendPanel({
      title: "TPH by Workcenter",
      subtitle: "Tons per hour. Months with zero runtime are gapped.",
      labels: months,
      datasets: buildDatasets((r) => r.tph),
      yLabel: "Tons/hr",
      yFormat: (v) => `${fmt1(v)} tph`,
    }));
  }

  function _renderTrendPanel({ title, subtitle, labels, datasets, yLabel, yFormat }) {
    const colors = _themeColors();
    const panel = el("section", { class: "trend-panel" }, [
      el("div", { class: "trend-panel-header" }, [
        el("span", { class: "trend-panel-title" }, title),
        el("span", { class: "trend-panel-meta" }, subtitle),
      ]),
      (() => {
        const wrap = el("div", { class: "trend-chart-wrap" });
        const canvas = el("canvas", { class: "trend-chart-canvas" });
        wrap.appendChild(canvas);
        // Defer chart instantiation to next tick so the canvas is in
        // the DOM when Chart.js measures it. Otherwise width/height
        // can come back as 0.
        setTimeout(() => {
          const chart = new Chart(canvas.getContext("2d"), {
            type: "line",
            data: { labels, datasets },
            options: {
              responsive: true,
              maintainAspectRatio: false,
              animation: false,
              plugins: {
                legend: {
                  display: true,
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

  document.addEventListener("DOMContentLoaded", bootstrap);
})();
