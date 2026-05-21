# TDS Printer — frontend

Vue 3 + TypeScript + Vite + Tailwind v4 + PrimeVue + Pinia. Talks to the
FastAPI backend in `../tds-server/`.

## Setup

```bash
cd frontend
npm install
```

## Dev

Two processes — backend on `:8000`, Vite on `:5173`. Vite proxies `/api`
calls to FastAPI so we don't need CORS in dev.

```bash
# Terminal 1 — backend
cd ../tds-server
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 \
    --reload --reload-dir app --reload-dir alembic

# Terminal 2 — frontend
cd frontend
npm run dev          # opens http://localhost:5173
```

## Generate typed API client

After backend API changes, regenerate types from OpenAPI:

```bash
npm run gen:api      # writes src/api/schema.d.ts
```

(Backend must be running on `:8000`. Until you regenerate, the
hand-written DTOs in `src/api/types.ts` are used — they mirror the backend
models for the current set of endpoints.)

## Build for production

```bash
npm run build        # → dist/
```

The bundled SPA lives in `dist/` and is served **separately** from the
backend. Pick whatever fits your deploy:

| Option | Command | Notes |
|---|---|---|
| Vite's built-in static server | `npm run preview -- --host 0.0.0.0` | Smallest setup; `:5173` by default, proxies `/api` to `VITE_API_TARGET` |
| `python -m http.server` | `cd dist && python3 -m http.server 5173` | Won't proxy — set `VITE_API_BASE_URL` at build time or use a reverse proxy |
| nginx / Caddy | serve `dist/` + reverse-proxy `/api → backend:8000` | The "real" prod path; both processes on the same machine or different machines |
| Cloud static (Cloudflare Pages, Netlify, …) | upload `dist/`, set `VITE_API_BASE_URL` at build | Backend must allow CORS for the deploy origin |

## How the SPA reaches the API

Per build/runtime, the SPA calls `${API_BASE}/api/...` where `API_BASE` is
the `VITE_API_BASE_URL` env var captured at build time. Empty string
(the default) means "same origin" — only works when something proxies
`/api` to the backend (Vite dev/preview do this automatically; nginx
needs a `location /api { proxy_pass http://backend:8000; }` block).

For a kiosk-LAN deploy where backend lives on a fixed IP, bake it in:

```bash
VITE_API_BASE_URL=http://10.0.0.5:8000 npm run build
```

Then any static host can serve `dist/` without proxy gymnastics — the
JS calls the backend's absolute URL directly. The backend's
`CORSMiddleware` (`allow_origins=["*"]`) already permits it.

## Layout

```
src/
├── main.ts                  Vue + Pinia + PrimeVue bootstrap
├── App.vue                  Top bar + <RouterView>
├── style.css                Tailwind v4 entry + PrimeIcons
├── router/                  vue-router routes
├── api/
│   ├── client.ts            Typed fetch wrapper
│   ├── types.ts             Hand-written DTOs (until gen:api)
│   └── schema.d.ts          openapi-typescript output (regenerated)
├── stores/                  Pinia: session, cart, projects, printers
├── pages/
│   ├── PrintPanel.vue       /
│   └── Admin.vue            /admin
└── components/
    ├── PingPill.vue
    ├── print/               ResultCard, CartPanel
    └── admin/               Printers, Templates, ProjectsTree, Imports,
                              Lists, History
```
