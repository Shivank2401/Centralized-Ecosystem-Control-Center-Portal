from __future__ import annotations

from fastapi import APIRouter

from backend.utils.responses import ok

router = APIRouter()


@router.get("/health")
def health():
    return ok({"status": "ok", "service": "inventory-ecosystem-portal", "phase": 6})
