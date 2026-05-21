"""TDS Printer central server — JSON API only.

Frontend lives in ``../frontend`` and is served separately (Vite dev or any
static host). See the project READMEs for the dev / prod flow.

Run:
    uvicorn app.main:app --host 0.0.0.0 --port 8000 \
        --reload --reload-dir app --reload-dir alembic
"""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import (
    auth_names,
    cart,
    history,
    import_ as import_api,
    imports as imports_api,
    labels,
    print as print_api,
    printers,
    projects,
    reasons,
    templates,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

app = FastAPI(title="TDS Printer Server", version="0.1.0")

# CORS — wide-open is fine for the LAN-only deployment. Tighten to the
# frontend's exact origin(s) when you move to a real prod environment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(printers.router)
app.include_router(templates.router)
app.include_router(projects.router)
app.include_router(reasons.router)
app.include_router(auth_names.router)
app.include_router(labels.router)
app.include_router(import_api.router)
app.include_router(imports_api.router)
app.include_router(cart.router)
app.include_router(print_api.router)
app.include_router(history.router)


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/")
def root() -> dict:
    """Root hint for anyone hitting the API host directly."""
    return {
        "service": "tds-printer-server",
        "docs": "/docs",
        "openapi": "/openapi.json",
        "health": "/health",
        "frontend": "served separately — see frontend/README.md",
    }
