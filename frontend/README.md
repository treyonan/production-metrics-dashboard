# Frontend

Vanilla HTML + CSS + JS. No build step. Served by FastAPI in dev
(see `backend/app/main.py` - the `StaticFiles` mount picks up this
directory by default). In production the frontend may be fronted by
IIS / Caddy / nginx instead.

## Layout

```
frontend/
  index.html         # shell (topbar, sidebar, main)
  app.css            # Fluent-inspired palette
  app.js             # polling loop + rendering
  vendor/
    chart.umd.js     # local Chart.js (loaded but unused in V1)
```

## Run

From `backend/` with the venv active:

```
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000/>. The site selector, KPI cards, and asset
table populate from the live API. Swagger at `/docs`.

## Polling

Defaults to 30s. Override per session via the `refresh` query param:

```
http://127.0.0.1:8000/?refresh=5000   # 5s poll (dev only)
http://127.0.0.1:8000/?refresh=300000 # 5 min (prod cadence)
```

## Aesthetic reference

`examples/dashboard-mockup/index.html` - Microsoft Fluent / Power BI
palette, Segoe UI, blue accent (`#0078d4`), dense business-intelligence
layout. V1 implements a subset: topbar + sidebar + workcenter panels
(KPI cards + asset table). Time-filter panels, cross-filter linking,
pivot tabs, and charts arrive in subsequent iterations.
