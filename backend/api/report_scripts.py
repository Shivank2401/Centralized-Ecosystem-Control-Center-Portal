from __future__ import annotations

from fastapi import APIRouter

from backend.utils.responses import fail, ok
from pipeline_engine.discovery import ReportDiscovery

router = APIRouter()
_discovery = ReportDiscovery()


@router.get("/report-scripts")
def list_report_script_packages():
    """Folders under report_script/ with registered / runnable script metadata."""
    return ok(_discovery.discover_script_packages())


@router.get("/report-scripts/{package}")
def get_report_script_package(package: str):
    data = _discovery.get_script_package(package)
    if data is None:
        return fail("NOT_FOUND", f"Unknown report_script package: {package}", status_code=404)
    return ok(data)
