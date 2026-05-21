# TDS Printer

Centralised label-printing system for multi-tablet kiosks. Replaces the
per-tablet Android app: one backend keeps the state (printers, templates,
projects, label data, history), N tablets open the web UI to search and print.

```
TDS-Printer/
├── server/    FastAPI + SQLite (Alembic-migrated) — pure JSON API
└── frontend/  Vue 3 + TS + Vite + Tailwind v4 + PrimeVue + Pinia — kiosk UI
```

## Quick start

Two processes — backend on `:8000`, frontend on `:5173`. Vite proxies `/api`
to FastAPI in dev so the SPA always calls relative `/api/*` regardless of
where it's served from.

```bash
# Terminal 1 — backend
cd server
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
alembic upgrade head            # creates / migrates SQLite
uvicorn app.main:app --host 0.0.0.0 --port 8000 \
    --reload --reload-dir app --reload-dir alembic

# Terminal 2 — frontend
cd frontend
npm install
npm run dev                     # opens http://localhost:5173
```

Production build:

```bash
cd frontend && npm run build    # → dist/
# Serve dist/ with `npm run preview`, nginx, or any static host.
# When backend lives on a different host, bake the URL in:
#   VITE_API_BASE_URL=http://10.0.0.5:8000 npm run build
```

## Reference docs

- [`server/README.md`](server/README.md) — backend layout, migrations,
  print engine, `--reload-dir` gotcha
- [`frontend/README.md`](frontend/README.md) — UI structure, OpenAPI
  client gen, deploy options

## High-level architecture

```
┌────────────────────────────────────────┐    ┌──────────────────────────┐
│ server (FastAPI + SQLite)              │←───│ frontend (Vue SPA)       │
│ ────────────────────────────           │    │ (Vite dev / nginx / …)   │
│ /api/printers   → CRUD + ping          │    │                          │
│ /api/templates  → CRUD (27-field cfg)  │    │ kiosk browser            │
│ /api/projects   → CRUD                 │    │ → search & print         │
│ /api/halls      → CRUD                 │    │ → cart                   │
│ /api/disciplines→ CRUD                 │    │ → admin                  │
│ /api/labels     → search               │    └──────────────────────────┘
│ /api/import     → upload XLSX          │              ↑
│ /api/cart       → list/add/print-all   │      3+ tablets on LAN
│ /api/print      → render + raw-TCP     │
│ /api/history    → log                  │              │
│ /docs           → Swagger              │              ↓ raw TCP :9100
│ /openapi.json   → typed-client source  │      ┌──────────────────┐
└────────────────────────────────────────┘      │ Panduit printers │
                                                └──────────────────┘
```
