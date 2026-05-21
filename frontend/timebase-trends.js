// Timebase Trends -- page-scoped JS (no globals, no polling).
//
// Fires HTTP calls only when the user interacts. No setInterval.
// Wrapped in an IIFE so nothing leaks to window.
//
// To remove this page entirely: delete this file + timebase-trends.html
// + the nav link in index.html. Backend can stay or be disabled via
// PMD_TIMEBASE_ENABLED=false in backend/.env.

(function () {
  "use strict";

  // ============================================================
  // Constants
  // ============================================================
  // Window is adjustable: 2h min, 12h max, snapping to 2h increments.
  // Domain of either handle is [0..24] in 2h steps -> 13 positions.
  // The backend's hard cap is timebase_max_window_seconds=43200 (12h),
  // so the UI ceiling intentionally matches that to avoid 422s.
  const STEP_HOURS = 2;
  const WINDOW_MIN_HOURS = 2;
  const WINDOW_MAX_HOURS = 12;
  const DAY_HOURS = 24;
  const STORAGE_KEY = "pmd-timebase-trends";
  // Default window when no saved selection: last 8h ending at "now".
  const DEFAULT_WINDOW_HOURS = 8;

  // ============================================================
  // DOM helpers
  // ============================================================
  const $ = (id) => document.getElementById(id);
  const els = {
    site:        $("site_select"),
    dept:        $("dept_select"),
    cls:         $("class_select"),
    asset:       $("asset_select"),
    metric:      $("metric_select"),
    dayPrev:     $("day_prev"),
    dayNext:     $("day_next"),
    dayLabel:    $("day_label"),
    sliderEl:    $("range_slider"),
    fillEl:      $("range_fill"),
    handleStart: $("range_handle_start"),
    handleEnd:   $("range_handle_end"),
    ticks:       $("range_ticks"),
    windowLabel: $("window_label"),
    fetchBtn:    $("fetch_btn"),
    nowBtn:      $("now_btn"),
    status:      $("status"),
    chartTitle:  $("chart_title"),
    chartCanvas: $("trend_chart"),
    emptyState:  $("empty_state"),
    statCount:   $("stat_count"),
    statDropped: $("stat_dropped"),
    statCache:   $("stat_cache"),
    statFetched: $("stat_fetched"),
    themeToggle: $("theme_toggle"),
  };

  // ============================================================
  // State
  // ============================================================
  // startHours / endHours are integers in 2h steps:
  //   0 <= startHours < endHours <= 24
  //   2 <= (endHours - startHours) <= 12
  const state = {
    catalog: null,           // parsed /api/timebase/catalog response
    siteId: null,
    deptName: null,
    className: null,
    assetName: null,
    metricKey: null,
    dayDate: midnightLocal(new Date()),  // a Date at local 00:00
    startHours: 0,            // hours-into-day of window start (set in init)
    endHours: DEFAULT_WINDOW_HOURS,
    chart: null,
  };

  // ============================================================
  // Time helpers (plant-local = browser-local)
  // ============================================================
  function midnightLocal(d) {
    const out = new Date(d);
    out.setHours(0, 0, 0, 0);
    return out;
  }
  function isSameLocalDay(a, b) {
    return a.getFullYear() === b.getFullYear()
        && a.getMonth() === b.getMonth()
        && a.getDate() === b.getDate();
  }
  function formatDay(d) {
    return d.toLocaleDateString(undefined, {
      weekday: "short", year: "numeric", month: "short", day: "numeric",
    });
  }
  function pad2(n) { return String(n).padStart(2, "0"); }
  function formatHHMM(d) {
    return pad2(d.getHours()) + ":" + pad2(d.getMinutes());
  }
  function localISOWithOffset(d) {
    // Returns "YYYY-MM-DDTHH:mm:ss±HH:MM" -- a tz-aware ISO-8601 the
    // backend Pydantic datetime will accept and normalize to UTC.
    const tz = -d.getTimezoneOffset();
    const sign = tz >= 0 ? "+" : "-";
    const abs = Math.abs(tz);
    const offset = sign + pad2(Math.floor(abs / 60)) + ":" + pad2(abs % 60);
    return d.getFullYear() + "-" + pad2(d.getMonth() + 1) + "-" + pad2(d.getDate())
         + "T" + pad2(d.getHours()) + ":" + pad2(d.getMinutes()) + ":" + pad2(d.getSeconds())
         + offset;
  }
  function computeWindow() {
    const start = new Date(state.dayDate);
    start.setHours(state.startHours, 0, 0, 0);
    const end = new Date(state.dayDate);
    end.setHours(state.endHours, 0, 0, 0);
    return { start, end };
  }
  // For "today" the end can't exceed the most recent 2h boundary <= now,
  // since there are no future samples. For past days the entire 0..24
  // range is fair game.
  function endHoursCapForCurrentDay() {
    if (isSameLocalDay(state.dayDate, new Date())) {
      const now = new Date();
      const hoursFloat = now.getHours() + now.getMinutes() / 60;
      const snapped = Math.floor(hoursFloat / STEP_HOURS) * STEP_HOURS;
      // Always allow at least WINDOW_MIN_HOURS so the slider isn't unusable
      // right after local midnight.
      return Math.max(WINDOW_MIN_HOURS, snapped);
    }
    return DAY_HOURS;
  }
  function snapHours(v) {
    return Math.round(v / STEP_HOURS) * STEP_HOURS;
  }

  // ============================================================
  // Theme toggle (mirrors main dashboard behavior)
  // ============================================================
  const SUN_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"></circle><line x1="12" y1="1" x2="12" y2="3"></line><line x1="12" y1="21" x2="12" y2="23"></line><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line><line x1="1" y1="12" x2="3" y2="12"></line><line x1="21" y1="12" x2="23" y2="12"></line><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line></svg>';
  const MOON_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg>';
  function applyThemeIcon() {
    const t = document.documentElement.getAttribute("data-theme") || "light";
    els.themeToggle.innerHTML = t === "dark" ? SUN_SVG : MOON_SVG;
  }
  els.themeToggle.addEventListener("click", () => {
    const cur = document.documentElement.getAttribute("data-theme") || "light";
    const next = cur === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem("pmd-theme", next); } catch (e) {}
    applyThemeIcon();
    if (state.chart) renderChart(state.chart.__lastSamples, state.chart.__lastMeta);
  });
  applyThemeIcon();

  // ============================================================
  // localStorage persistence
  // ============================================================
  function saveState() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({
        siteId: state.siteId,
        deptName: state.deptName,
        className: state.className,
        assetName: state.assetName,
        metricKey: state.metricKey,
        // Window endpoints persist so refreshing the page keeps the
        // operator's chosen window. dayDate intentionally does NOT
        // persist -- a fresh page load defaults to "today".
        startHours: state.startHours,
        endHours: state.endHours,
      }));
    } catch (e) {}
  }
  function loadStoredState() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (e) { return null; }
  }

  // ============================================================
  // Status messages
  // ============================================================
  function showError(msg) {
    els.status.textContent = msg;
    els.status.className = "status show error";
  }
  function showInfo(msg) {
    els.status.textContent = msg;
    els.status.className = "status show info";
  }
  function clearStatus() { els.status.className = "status"; }

  // ============================================================
  // Catalog load + dropdown wiring
  // ============================================================
  async function loadCatalog() {
    clearStatus();
    try {
      const resp = await fetch("/api/timebase/catalog");
      if (!resp.ok) {
        const body = await resp.text();
        throw new Error("Catalog HTTP " + resp.status + ": " + body);
      }
      state.catalog = await resp.json();
    } catch (err) {
      showError("Failed to load catalog: " + err.message
        + ". Is the Timebase integration enabled (PMD_TIMEBASE_ENABLED) and the historian reachable?");
      return false;
    }
    return true;
  }

  function fillSelect(selectEl, values, labelOf = (v) => v) {
    selectEl.innerHTML = "";
    for (const v of values) {
      const opt = document.createElement("option");
      opt.value = typeof v === "object" ? v.value : v;
      opt.textContent = typeof v === "object" ? v.label : labelOf(v);
      selectEl.appendChild(opt);
    }
  }

  function rebuildSiteOptions() {
    const sites = state.catalog.sites;
    fillSelect(els.site,
      sites.map(s => ({ value: s.site_id, label: s.display_name + " (" + s.code + ")" })));
    if (state.siteId && sites.some(s => s.site_id === state.siteId)) {
      els.site.value = state.siteId;
    } else {
      state.siteId = sites[0].site_id;
      els.site.value = state.siteId;
    }
  }
  function rebuildDeptOptions() {
    const site = state.catalog.sites.find(s => s.site_id === state.siteId);
    const deptNames = site.departments.map(d => d.name);
    fillSelect(els.dept, deptNames);
    if (state.deptName && deptNames.includes(state.deptName)) {
      els.dept.value = state.deptName;
    } else {
      state.deptName = deptNames[0];
      els.dept.value = state.deptName;
    }
  }
  function rebuildClassOptions() {
    const site = state.catalog.sites.find(s => s.site_id === state.siteId);
    const dept = site.departments.find(d => d.name === state.deptName);
    const classNames = dept.asset_classes.map(ac => ac.class);
    fillSelect(els.cls, classNames);
    if (state.className && classNames.includes(state.className)) {
      els.cls.value = state.className;
    } else {
      state.className = classNames[0];
      els.cls.value = state.className;
    }
  }
  function rebuildAssetOptions() {
    const site = state.catalog.sites.find(s => s.site_id === state.siteId);
    const dept = site.departments.find(d => d.name === state.deptName);
    const cls = dept.asset_classes.find(ac => ac.class === state.className);
    const assetNames = cls.assets.map(a => a.asset);
    fillSelect(els.asset, assetNames);
    if (state.assetName && assetNames.includes(state.assetName)) {
      els.asset.value = state.assetName;
    } else {
      state.assetName = assetNames[0];
      els.asset.value = state.assetName;
    }
  }
  function rebuildMetricOptions() {
    const site = state.catalog.sites.find(s => s.site_id === state.siteId);
    const dept = site.departments.find(d => d.name === state.deptName);
    const cls = dept.asset_classes.find(ac => ac.class === state.className);
    const asset = cls.assets.find(a => a.asset === state.assetName);
    const metrics = asset.metrics;
    fillSelect(els.metric,
      metrics.map(m => ({ value: m.metric_key, label: m.display_name })));
    if (state.metricKey && metrics.some(m => m.metric_key === state.metricKey)) {
      els.metric.value = state.metricKey;
    } else {
      state.metricKey = metrics[0].metric_key;
      els.metric.value = state.metricKey;
    }
  }

  function currentSelectedMetric() {
    const site = state.catalog.sites.find(s => s.site_id === state.siteId);
    const dept = site.departments.find(d => d.name === state.deptName);
    const cls = dept.asset_classes.find(ac => ac.class === state.className);
    const asset = cls.assets.find(a => a.asset === state.assetName);
    return asset.metrics.find(m => m.metric_key === state.metricKey);
  }
  function tagPathForSelection() {
    // The catalog returns the full elementId; strip the dataset prefix
    // (everything up to and including the first ':') to get the tag_path
    // shape the /history endpoint wants.
    const m = currentSelectedMetric();
    if (!m) return null;
    const ix = m.element_id.indexOf(":");
    return ix < 0 ? m.element_id : m.element_id.substring(ix + 1);
  }

  // ============================================================
  // Day stepper + slider rendering
  // ============================================================
  function updateDayUI() {
    els.dayLabel.textContent = formatDay(state.dayDate);
    // Disable "next" if we're already on today.
    const today = midnightLocal(new Date());
    els.dayNext.disabled = state.dayDate.getTime() >= today.getTime();
    // Re-clamp window into the current day's allowed range (today's cap
    // may have shrunk since the last paint).
    clampWindow();
    paintSlider();
  }
  // Snap state.start/end back into valid bounds. Idempotent.
  function clampWindow() {
    const cap = endHoursCapForCurrentDay();
    // First snap whatever we have to the 2h grid.
    state.startHours = snapHours(state.startHours);
    state.endHours = snapHours(state.endHours);
    // Bound the end by the today-cap.
    if (state.endHours > cap) state.endHours = cap;
    if (state.endHours < WINDOW_MIN_HOURS) state.endHours = WINDOW_MIN_HOURS;
    // Window length must stay between MIN and MAX.
    let width = state.endHours - state.startHours;
    if (width < WINDOW_MIN_HOURS) {
      // Prefer growing the start backwards if there's room, otherwise
      // push the end forward (which may then re-hit the cap on the
      // next pass -- fine).
      const room = state.endHours - 0;
      if (room >= WINDOW_MIN_HOURS) {
        state.startHours = state.endHours - WINDOW_MIN_HOURS;
      } else {
        state.endHours = state.startHours + WINDOW_MIN_HOURS;
      }
    } else if (width > WINDOW_MAX_HOURS) {
      // Shrink from the start side -- end is the "anchor" the user
      // last positioned (typical for "this is the recent data").
      state.startHours = state.endHours - WINDOW_MAX_HOURS;
    }
    // Final guardrails.
    if (state.startHours < 0) state.startHours = 0;
    if (state.endHours > DAY_HOURS) state.endHours = DAY_HOURS;
    if (state.startHours >= state.endHours) {
      state.startHours = Math.max(0, state.endHours - WINDOW_MIN_HOURS);
    }
  }
  function paintSlider() {
    const width = els.sliderEl.clientWidth || 1;
    const startPx = (state.startHours / DAY_HOURS) * width;
    const endPx = (state.endHours / DAY_HOURS) * width;
    els.handleStart.style.left = startPx + "px";
    els.handleEnd.style.left = endPx + "px";
    els.fillEl.style.left = startPx + "px";
    els.fillEl.style.width = Math.max(0, endPx - startPx) + "px";
    els.handleStart.setAttribute("aria-valuenow", String(state.startHours));
    els.handleEnd.setAttribute("aria-valuenow", String(state.endHours));
    const cap = endHoursCapForCurrentDay();
    els.handleEnd.setAttribute("aria-valuemax", String(cap));
    updateWindowLabel();
  }
  function paintTicks() {
    // Render once -- pure presentational. Recomputed on resize via
    // paintSlider() (positions are percentages so they survive a
    // resize automatically).
    els.ticks.innerHTML = "";
    for (let h = 0; h <= DAY_HOURS; h += STEP_HOURS) {
      const tick = document.createElement("div");
      tick.className = "range-tick";
      tick.style.left = ((h / DAY_HOURS) * 100).toFixed(4) + "%";
      els.ticks.appendChild(tick);
    }
  }
  function updateWindowLabel() {
    const { start, end } = computeWindow();
    const width = state.endHours - state.startHours;
    els.windowLabel.textContent =
      formatHHMM(start) + " — " + formatHHMM(end) + "  (" + width + "h)";
  }

  // ============================================================
  // Slider interaction (custom -- no native range inputs)
  //
  // Layout: handles + fill are absolutely positioned inside .range-slider.
  // We convert pointer X to "hours-into-day" by ratio of pointer offset
  // to the slider's bounding rect width, then snap to STEP_HOURS.
  //
  // Three distinct drag intents:
  //   1. handleStart drag -- moves the start independently.
  //   2. handleEnd drag   -- moves the end independently.
  //   3. fillEl drag      -- moves both, preserving window width.
  // ============================================================
  function pointerHours(ev) {
    const rect = els.sliderEl.getBoundingClientRect();
    const ratio = (ev.clientX - rect.left) / Math.max(1, rect.width);
    return Math.max(0, Math.min(DAY_HOURS, ratio * DAY_HOURS));
  }
  function setStartHours(rawHours) {
    const cap = endHoursCapForCurrentDay();
    let h = snapHours(rawHours);
    // Don't let start cross or get within MIN of end.
    const maxStart = Math.min(state.endHours - WINDOW_MIN_HOURS, cap - WINDOW_MIN_HOURS);
    if (h > maxStart) h = maxStart;
    // Don't open a window wider than MAX.
    const minStart = state.endHours - WINDOW_MAX_HOURS;
    if (h < minStart) h = minStart;
    if (h < 0) h = 0;
    state.startHours = h;
    paintSlider();
  }
  function setEndHours(rawHours) {
    const cap = endHoursCapForCurrentDay();
    let h = snapHours(rawHours);
    const minEnd = state.startHours + WINDOW_MIN_HOURS;
    if (h < minEnd) h = minEnd;
    const maxEnd = Math.min(cap, state.startHours + WINDOW_MAX_HOURS);
    if (h > maxEnd) h = maxEnd;
    state.endHours = h;
    paintSlider();
  }
  // Translate the whole window. `deltaHours` is signed and may be any
  // multiple of STEP_HOURS; we clamp + snap inside.
  function translateWindow(deltaHours) {
    const cap = endHoursCapForCurrentDay();
    const width = state.endHours - state.startHours;
    let newStart = snapHours(state.startHours + deltaHours);
    let newEnd = newStart + width;
    if (newEnd > cap) {
      newEnd = cap;
      newStart = newEnd - width;
    }
    if (newStart < 0) {
      newStart = 0;
      newEnd = newStart + width;
    }
    state.startHours = newStart;
    state.endHours = newEnd;
    paintSlider();
  }

  function attachHandleDrag(handleEl, setter) {
    handleEl.addEventListener("pointerdown", (ev) => {
      ev.preventDefault();
      handleEl.setPointerCapture(ev.pointerId);
      handleEl.classList.add("dragging");
      const onMove = (mv) => setter(pointerHours(mv));
      const onUp = (up) => {
        handleEl.releasePointerCapture(up.pointerId);
        handleEl.classList.remove("dragging");
        handleEl.removeEventListener("pointermove", onMove);
        handleEl.removeEventListener("pointerup", onUp);
        handleEl.removeEventListener("pointercancel", onUp);
        saveState();
      };
      handleEl.addEventListener("pointermove", onMove);
      handleEl.addEventListener("pointerup", onUp);
      handleEl.addEventListener("pointercancel", onUp);
    });
    // Keyboard accessibility: arrows step by STEP_HOURS.
    handleEl.addEventListener("keydown", (ev) => {
      if (ev.key === "ArrowLeft" || ev.key === "ArrowDown") {
        ev.preventDefault();
        const cur = handleEl === els.handleStart ? state.startHours : state.endHours;
        setter(cur - STEP_HOURS);
        saveState();
      } else if (ev.key === "ArrowRight" || ev.key === "ArrowUp") {
        ev.preventDefault();
        const cur = handleEl === els.handleStart ? state.startHours : state.endHours;
        setter(cur + STEP_HOURS);
        saveState();
      }
    });
  }
  attachHandleDrag(els.handleStart, setStartHours);
  attachHandleDrag(els.handleEnd, setEndHours);

  els.fillEl.addEventListener("pointerdown", (ev) => {
    ev.preventDefault();
    els.fillEl.setPointerCapture(ev.pointerId);
    els.fillEl.classList.add("dragging");
    const startPointerHours = pointerHours(ev);
    const initialStart = state.startHours;
    const initialEnd = state.endHours;
    const onMove = (mv) => {
      const deltaHours = pointerHours(mv) - startPointerHours;
      // Translate from the captured initial window, not the running
      // one, so rounding doesn't drift cumulatively as the pointer moves.
      const cap = endHoursCapForCurrentDay();
      const width = initialEnd - initialStart;
      let newStart = snapHours(initialStart + deltaHours);
      let newEnd = newStart + width;
      if (newEnd > cap) { newEnd = cap; newStart = newEnd - width; }
      if (newStart < 0) { newStart = 0; newEnd = newStart + width; }
      state.startHours = newStart;
      state.endHours = newEnd;
      paintSlider();
    };
    const onUp = (up) => {
      els.fillEl.releasePointerCapture(up.pointerId);
      els.fillEl.classList.remove("dragging");
      els.fillEl.removeEventListener("pointermove", onMove);
      els.fillEl.removeEventListener("pointerup", onUp);
      els.fillEl.removeEventListener("pointercancel", onUp);
      saveState();
    };
    els.fillEl.addEventListener("pointermove", onMove);
    els.fillEl.addEventListener("pointerup", onUp);
    els.fillEl.addEventListener("pointercancel", onUp);
  });

  // Slider geometry is %-relative inside the wrap, but our positions
  // are in px (so the handles can extend slightly outside via -9px
  // margin). Re-paint on resize to keep handle positions accurate.
  window.addEventListener("resize", paintSlider);

  // ============================================================
  // Fetch + chart render
  // ============================================================
  async function fetchAndRender() {
    if (!state.catalog) {
      showError("Catalog not loaded.");
      return;
    }
    clearStatus();
    els.fetchBtn.disabled = true;
    els.fetchBtn.textContent = "Fetching…";
    try {
      const { start, end } = computeWindow();
      const tag = tagPathForSelection();
      if (!tag) {
        showError("No metric selected.");
        return;
      }
      const body = {
        tag_paths: [tag],
        start_time: localISOWithOffset(start),
        end_time: localISOWithOffset(end),
        max_depth: 1,
      };
      const url = "/api/timebase/history?site_id=" + encodeURIComponent(state.siteId);
      const t0 = performance.now();
      const resp = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const elapsedMs = Math.round(performance.now() - t0);

      if (!resp.ok) {
        const errBody = await resp.text();
        let detail = errBody;
        try { detail = JSON.parse(errBody).detail || errBody; } catch (e) {}
        showError("Fetch failed (" + resp.status + "): " + detail);
        renderChart([], null);
        return;
      }

      const data = await resp.json();
      const samples = (data[tag] && data[tag].data) || [];
      renderChart(samples, {
        tag,
        metric: currentSelectedMetric(),
        start, end,
        elapsedMs,
      });
    } catch (err) {
      showError("Fetch error: " + (err && err.message ? err.message : String(err)));
      renderChart([], null);
    } finally {
      els.fetchBtn.disabled = false;
      els.fetchBtn.textContent = "Fetch";
    }
  }

  function renderChart(samples, meta) {
    // Quality filter
    const goodSamples = [];
    let droppedCount = 0;
    for (const s of samples) {
      if (s.quality === "GOOD") goodSamples.push(s);
      else droppedCount++;
    }

    els.statCount.textContent = String(goodSamples.length);
    els.statDropped.textContent = String(droppedCount);
    els.statFetched.textContent = meta
      ? "Fetched in " + meta.elapsedMs + " ms"
      : "";
    // We don't surface a "cache hit" flag from the backend today;
    // sub-50ms fetch + same window strongly suggests one.
    els.statCache.textContent = (meta && meta.elapsedMs < 80) ? "(probable cache hit)" : "";

    // Title
    if (meta && meta.metric) {
      els.chartTitle.textContent =
        state.assetName + " — " + meta.metric.display_name
        + " (" + formatHHMM(meta.start) + " – " + formatHHMM(meta.end) + ")";
    } else {
      els.chartTitle.textContent = "Trend";
    }

    if (!goodSamples.length) {
      els.chartCanvas.style.display = "none";
      els.emptyState.style.display = "block";
      destroyChart();
      return;
    }
    els.chartCanvas.style.display = "block";
    els.emptyState.style.display = "none";

    // Cumulative metric handling: belt_scale_total is monotonic, so
    // for charts subtract the first value to show delta-from-start
    // ("tons produced in this window"). Drives the metric_key naming
    // convention -- anything ending in "_total" gets delta'd.
    const isCumulative = !!(meta && meta.metric && /_total$/i.test(meta.metric.metric_key));
    const dataPoints = [];
    if (isCumulative) {
      const baseline = goodSamples[0].value;
      for (const s of goodSamples) {
        dataPoints.push({ x: new Date(s.timestamp).getTime(), y: Number(s.value) - Number(baseline) });
      }
    } else {
      for (const s of goodSamples) {
        dataPoints.push({ x: new Date(s.timestamp).getTime(), y: Number(s.value) });
      }
    }

    const unit = meta && meta.metric ? meta.metric.unit : "";
    const labelPrefix = meta && meta.metric ? meta.metric.display_name : "value";
    const yLabel = (isCumulative ? "Δ " : "") + (unit ? labelPrefix + " (" + unit + ")" : labelPrefix);

    destroyChart();
    const ctx = els.chartCanvas.getContext("2d");
    const accent = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() || "#00502f";
    let newChart;
    try {
      newChart = new Chart(ctx, {
        type: "line",
        data: {
          datasets: [{
            label: yLabel,
            data: dataPoints,
            parsing: false,
            showLine: true,
            pointRadius: 0,
            pointHoverRadius: 4,
            borderColor: accent,
            backgroundColor: accent,
            borderWidth: 1.5,
            tension: 0,
            spanGaps: true,
          }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          animation: false,
          plugins: {
            legend: { display: false },
            tooltip: {
              mode: "index",
              intersect: false,
              callbacks: {
                title: (items) => {
                  if (!items.length) return "";
                  const d = new Date(items[0].parsed.x);
                  return d.toLocaleString();
                },
                label: (item) => {
                  const v = item.parsed.y;
                  const formatted = (Number.isFinite(v) ? v.toLocaleString(undefined, { maximumFractionDigits: 2 }) : v);
                  return labelPrefix + ": " + formatted + (unit ? " " + unit : "");
                },
              },
            },
          },
          scales: {
            x: {
              type: "linear",
              ticks: {
                autoSkip: true,
                maxTicksLimit: 8,
                callback: function (val) {
                  const d = new Date(val);
                  return d.toLocaleTimeString(undefined, {
                    hour: "2-digit", minute: "2-digit", hour12: false,
                  });
                },
              },
              grid: { color: getCss("--border") },
            },
            y: {
              beginAtZero: false,
              title: { display: true, text: yLabel },
              grid: { color: getCss("--border") },
            },
          },
        },
      });
    } catch (chartErr) {
      showError("Chart render failed: "
        + (chartErr && chartErr.message ? chartErr.message : String(chartErr)));
      els.emptyState.style.display = "block";
      els.chartCanvas.style.display = "none";
      return;
    }
    state.chart = newChart;
    // Stash for theme-toggle re-render
    state.chart.__lastSamples = samples;
    state.chart.__lastMeta = meta;
  }
  function destroyChart() {
    // Defensive: ask Chart.js for whatever chart is registered to
    // this canvas, regardless of our local tracking. Solves the
    // "Canvas is already in use" error when state.chart and the
    // Chart.js registry get out of sync (which can happen after an
    // exception in the render path or during hot reload).
    if (typeof Chart !== "undefined" && typeof Chart.getChart === "function") {
      const existing = Chart.getChart(els.chartCanvas);
      if (existing) {
        try { existing.destroy(); } catch (e) { /* already gone */ }
      }
    }
    if (state.chart) {
      try { state.chart.destroy(); } catch (e) { /* already gone */ }
    }
    state.chart = null;
  }
  function getCss(varName) {
    return getComputedStyle(document.documentElement).getPropertyValue(varName).trim() || "#ddd";
  }

  // ============================================================
  // Event wiring
  // ============================================================
  els.site.addEventListener("change", () => {
    state.siteId = els.site.value;
    state.deptName = state.className = state.assetName = state.metricKey = null;
    rebuildDeptOptions();
    rebuildClassOptions();
    rebuildAssetOptions();
    rebuildMetricOptions();
    saveState();
  });
  els.dept.addEventListener("change", () => {
    state.deptName = els.dept.value;
    state.className = state.assetName = state.metricKey = null;
    rebuildClassOptions();
    rebuildAssetOptions();
    rebuildMetricOptions();
    saveState();
  });
  els.cls.addEventListener("change", () => {
    state.className = els.cls.value;
    state.assetName = state.metricKey = null;
    rebuildAssetOptions();
    rebuildMetricOptions();
    saveState();
  });
  els.asset.addEventListener("change", () => {
    state.assetName = els.asset.value;
    state.metricKey = null;
    rebuildMetricOptions();
    saveState();
  });
  els.metric.addEventListener("change", () => {
    state.metricKey = els.metric.value;
    saveState();
  });
  els.dayPrev.addEventListener("click", () => {
    const d = new Date(state.dayDate);
    d.setDate(d.getDate() - 1);
    state.dayDate = midnightLocal(d);
    // Stepping into a past day: keep the same window length, anchor
    // the end at 24:00 so the user sees the latest data of that day.
    const width = Math.max(WINDOW_MIN_HOURS, Math.min(WINDOW_MAX_HOURS,
      state.endHours - state.startHours));
    state.endHours = DAY_HOURS;
    state.startHours = DAY_HOURS - width;
    updateDayUI();
  });
  els.dayNext.addEventListener("click", () => {
    const d = new Date(state.dayDate);
    d.setDate(d.getDate() + 1);
    const today = midnightLocal(new Date());
    if (d.getTime() > today.getTime()) return;
    state.dayDate = midnightLocal(d);
    // Stepping forward: anchor end at the latest 2h boundary of the
    // new day (== full 24h on past days, today's cap on today).
    const width = Math.max(WINDOW_MIN_HOURS, Math.min(WINDOW_MAX_HOURS,
      state.endHours - state.startHours));
    const cap = endHoursCapForCurrentDay();
    state.endHours = cap;
    state.startHours = Math.max(0, cap - width);
    updateDayUI();
  });
  els.nowBtn.addEventListener("click", () => {
    state.dayDate = midnightLocal(new Date());
    const cap = endHoursCapForCurrentDay();
    state.endHours = cap;
    state.startHours = Math.max(0, cap - DEFAULT_WINDOW_HOURS);
    updateDayUI();
    fetchAndRender();
  });
  els.fetchBtn.addEventListener("click", fetchAndRender);

  // ============================================================
  // Init
  // ============================================================
  (async function init() {
    const ok = await loadCatalog();
    if (!ok) return;
    if (!state.catalog.sites.length) {
      showError("No Timebase sites configured. Check catalog.yaml.");
      return;
    }

    // Restore previous selection (best-effort -- if any value is no
    // longer in the catalog, the rebuild defaults to the first option).
    const stored = loadStoredState();
    if (stored) {
      state.siteId = stored.siteId;
      state.deptName = stored.deptName;
      state.className = stored.className;
      state.assetName = stored.assetName;
      state.metricKey = stored.metricKey;
      if (Number.isFinite(stored.startHours) && Number.isFinite(stored.endHours)) {
        state.startHours = stored.startHours;
        state.endHours = stored.endHours;
      }
    }

    // If no stored window (first visit), default to "last DEFAULT_WINDOW_HOURS
    // ending at today's most-recent 2h boundary".
    if (!stored || !Number.isFinite(stored.startHours) || !Number.isFinite(stored.endHours)) {
      const cap = endHoursCapForCurrentDay();
      state.endHours = cap;
      state.startHours = Math.max(0, cap - DEFAULT_WINDOW_HOURS);
    }

    rebuildSiteOptions();
    rebuildDeptOptions();
    rebuildClassOptions();
    rebuildAssetOptions();
    rebuildMetricOptions();
    paintTicks();
    updateDayUI();
    saveState();

    // Initial chart fetch on load -- this is user-initiated by virtue
    // of them opening the page; no polling. They want to see something.
    fetchAndRender();
  })();
})();
