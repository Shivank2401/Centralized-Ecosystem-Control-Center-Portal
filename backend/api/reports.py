from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

from backend.services.config_service import ConfigService
from backend.utils.responses import fail, ok

router = APIRouter()
_service = ConfigService()


@router.get("/reports")
def list_reports(
    client: Optional[str] = Query(None),
    stage: Optional[str] = Query(None),
    enabled_only: bool = Query(True),
):
    clients = [c.strip().upper() for c in client.split(",")] if client else None
    return ok(_service.list_reports(clients=clients, stage=stage, enabled_only=enabled_only))


@router.get("/reports/{report_code}")
def get_report(report_code: str):
    data = _service.get_report(report_code)
    if data is None:
        return fail("REPORT_NOT_FOUND", f"Unknown report: {report_code}", status_code=404)
    return ok(data)


@router.post("/config/refresh")
def refresh_configuration():
    _service.refresh()
    # Keep run validation in sync (separate ConfigRegistry on RunService).
    from backend.services.run_service import run_service as _run_service

    if hasattr(_run_service, "refresh"):
        _run_service.refresh()
    return ok({"refreshed": True}, message="Configuration reloaded from YAML")
