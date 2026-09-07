"""Data explorers — outputs, report logs, COGS, pincode, file preview/download."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse

from backend.services.explore_service import ExploreService
from backend.utils.responses import fail, ok

router = APIRouter()
_service = ExploreService()


@router.get("/explore/outputs/clients")
def output_clients():
    return ok(_service.list_output_clients())


@router.get("/explore/outputs")
def list_outputs(
    client: Optional[str] = Query(None),
    report: Optional[str] = Query(None),
):
    return ok(_service.list_report_outputs(client=client, report=report))


@router.get("/explore/browse")
def browse(
    root: str = Query("sanity", pattern="^(sanity|cogs|pincode|runtime_runs)$"),
    rel: str = Query(""),
):
    try:
        return ok(_service.list_directory(root, rel))
    except ValueError as exc:
        return fail("PATH_INVALID", str(exc), status_code=400)
    except KeyError as exc:
        return fail("ROOT_UNKNOWN", str(exc), status_code=400)


@router.get("/explore/logs")
def list_logs(client: Optional[str] = Query(None)):
    return ok(_service.list_log_index(client=client))


@router.get("/explore/logs/content")
def log_content(
    client: str = Query(...),
    report: str = Query(...),
    file: str = Query("latest.log"),
):
    try:
        return ok(_service.read_log_text(client=client, report=report, filename=file))
    except FileNotFoundError as exc:
        return fail("LOG_NOT_FOUND", str(exc), status_code=404)
    except ValueError as exc:
        return fail("PATH_INVALID", str(exc), status_code=400)


@router.get("/explore/file")
def file_info(
    root: str = Query(..., pattern="^(sanity|cogs|pincode|runtime_runs)$"),
    rel: str = Query(...),
):
    try:
        return ok(_service.file_info(root, rel))
    except FileNotFoundError as exc:
        return fail("FILE_NOT_FOUND", str(exc), status_code=404)
    except ValueError as exc:
        return fail("PATH_INVALID", str(exc), status_code=400)


@router.get("/explore/file/preview")
def file_preview(
    root: str = Query(..., pattern="^(sanity|cogs|pincode|runtime_runs)$"),
    rel: str = Query(...),
    rows: int = Query(20, ge=1, le=100),
):
    try:
        return ok(_service.preview_file(root, rel, rows=rows))
    except FileNotFoundError as exc:
        return fail("FILE_NOT_FOUND", str(exc), status_code=404)
    except ValueError as exc:
        return fail("PATH_INVALID", str(exc), status_code=400)


@router.get("/explore/file/download")
def file_download(
    root: str = Query(..., pattern="^(sanity|cogs|pincode|runtime_runs)$"),
    rel: str = Query(...),
):
    try:
        path = _service.resolve_rel(root, rel)
        if not path.is_file():
            return fail("FILE_NOT_FOUND", str(path), status_code=404)
        return FileResponse(path, filename=path.name)
    except ValueError as exc:
        return fail("PATH_INVALID", str(exc), status_code=400)


@router.get("/explore/cogs")
def explore_cogs(client: Optional[str] = Query(None)):
    return ok(_service.list_cogs(client=client))


@router.get("/explore/pincode")
def explore_pincode():
    return ok(_service.list_pincode())
