"""FastAPI application — Inventory Ecosystem Portal API (Phase 1)."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from backend.api import (
    clients,
    explore,
    geographies,
    health,
    registry,
    reports,
    runs,
    sequences,
    stages,
    system,
)

app = FastAPI(
    title="Inventory Ecosystem Portal API",
    version="0.6.0",
    description="Orchestration API around the existing inventory ETL pipeline.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(clients.router, prefix="/api", tags=["clients"])
app.include_router(geographies.router, prefix="/api", tags=["geographies"])
app.include_router(stages.router, prefix="/api", tags=["stages"])
app.include_router(reports.router, prefix="/api", tags=["reports"])
app.include_router(registry.router, prefix="/api", tags=["registry"])
app.include_router(sequences.router, prefix="/api", tags=["sequences"])
app.include_router(runs.router, prefix="/api", tags=["runs"])
app.include_router(system.router, prefix="/api", tags=["system"])
app.include_router(explore.router, prefix="/api", tags=["explore"])


@app.get("/")
def root():
    return {
        "success": True,
        "data": {
            "name": "Inventory Ecosystem Portal API",
            "version": "0.6.0",
            "phase": 6,
            "root": str(_PROJECT_ROOT),
            "docs": "/docs",
        },
    }
