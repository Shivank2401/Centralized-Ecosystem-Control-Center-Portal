"""Azure blob export helpers for utility upload (esh / knc / emm containers)."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, Query, UploadFile

from backend.utils.responses import fail, ok
from report_script.utility_codes import d_export_file_to_azure as azure_util

router = APIRouter(prefix="/azure")

_ALLOWED = azure_util.DEFAULT_ALLOWED_EXTENSIONS


@router.get("/containers")
def list_containers():
    try:
        options = azure_util.list_container_options()
    except Exception as exc:
        return fail("AZURE_ERROR", str(exc), status_code=500)
    return ok({"containers": options})


@router.get("/folders")
def list_folders(
    container: str = Query(..., description="esh | knc | emm"),
    prefix: str = Query("", description="Blob folder prefix"),
):
    try:
        data = azure_util.list_blob_folders(container, prefix=prefix or "")
    except ValueError as exc:
        return fail("AZURE_BAD_REQUEST", str(exc), status_code=400)
    except EnvironmentError as exc:
        return fail("AZURE_CONFIG", str(exc), status_code=503)
    except Exception as exc:
        return fail("AZURE_ERROR", str(exc), status_code=500)
    return ok(data)


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    container: str = Form(..., description="esh | knc | emm"),
    blob_folder: str = Form("", description="Folder / prefix inside container"),
    blob_name: Optional[str] = Form(
        None,
        description="Optional destination name; empty keeps uploaded filename",
    ),
):
    original = Path(file.filename or "upload.bin").name
    ext = Path(original).suffix.lower()
    if ext not in _ALLOWED:
        return fail(
            "FILE_TYPE",
            f"Unsupported file type {ext!r}. Allowed: {', '.join(sorted(_ALLOWED))}",
            status_code=400,
        )

    dest_name = (blob_name or "").strip() or None
    tmp_dir = Path(tempfile.mkdtemp(prefix="azure_upload_"))
    tmp_path = tmp_dir / original
    try:
        with tmp_path.open("wb") as out:
            shutil.copyfileobj(file.file, out)

        result = azure_util.upload_local_file(
            tmp_path,
            container_key=container,
            blob_folder=blob_folder or "",
            blob_name=dest_name,
        )
    except ValueError as exc:
        return fail("AZURE_BAD_REQUEST", str(exc), status_code=400)
    except EnvironmentError as exc:
        return fail("AZURE_CONFIG", str(exc), status_code=503)
    except FileNotFoundError as exc:
        return fail("FILE_MISSING", str(exc), status_code=400)
    except Exception as exc:
        return fail("AZURE_UPLOAD_FAILED", str(exc), status_code=500)
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
            tmp_dir.rmdir()
        except OSError:
            pass

    return ok(result)
