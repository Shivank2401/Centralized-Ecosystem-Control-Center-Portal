"""Report upload, AST validation, and registration APIs."""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, File, UploadFile
from pydantic import BaseModel, Field

from backend.services.report_registration_service import ReportRegistrationService
from backend.utils.responses import fail, ok

router = APIRouter()
_service = ReportRegistrationService()


class CreateStageSpec(BaseModel):
    label: Optional[str] = None
    order: Optional[int] = 50
    clients: Optional[List[str]] = None


class RegisterReportBody(BaseModel):
    upload_id: str
    code: str = Field(min_length=2, max_length=64)
    label: str = Field(min_length=1, max_length=120)
    stage: str = Field(min_length=1)
    clients: Optional[List[str]] = None
    menu_order: Optional[int] = None
    enabled: bool = True
    output_subdir: Optional[str] = None
    description: Optional[str] = None
    create_stage: Optional[CreateStageSpec] = None
    overwrite: bool = False


class EnableBody(BaseModel):
    enabled: bool


@router.get("/registry/stages")
def registry_stages():
    return ok(_service.list_stages_for_ui())


@router.post("/registry/upload")
async def upload_report(file: UploadFile = File(...)):
    if not file.filename:
        return fail("UPLOAD_INVALID", "Missing filename", status_code=400)
    if not file.filename.lower().endswith(".py"):
        return fail("UPLOAD_INVALID", "Only .py files are allowed", status_code=400)
    content = await file.read()
    try:
        data = _service.quarantine_upload(filename=file.filename, content=content)
        return ok(data, message="Uploaded to quarantine", status_code=201)
    except ValueError as exc:
        return fail("UPLOAD_REJECTED", str(exc), status_code=400)
    except Exception as exc:
        return fail("UPLOAD_FAILED", str(exc), status_code=500)


@router.post("/registry/register")
def register_report(body: RegisterReportBody):
    try:
        data = _service.register(
            upload_id=body.upload_id,
            code=body.code,
            label=body.label,
            stage=body.stage,
            clients=body.clients,
            menu_order=body.menu_order,
            enabled=body.enabled,
            output_subdir=body.output_subdir,
            description=body.description,
            create_stage=body.create_stage.model_dump() if body.create_stage else None,
            overwrite=body.overwrite,
        )
        return ok(data, message="Report registered", status_code=201)
    except KeyError as exc:
        return fail("UPLOAD_NOT_FOUND", str(exc), status_code=404)
    except ValueError as exc:
        return fail("REGISTER_REJECTED", str(exc), status_code=400)
    except Exception as exc:
        return fail("REGISTER_FAILED", str(exc), status_code=500)


@router.post("/reports/{report_code}/enabled")
def set_report_enabled(report_code: str, body: EnableBody):
    try:
        return ok(_service.set_enabled(report_code, body.enabled))
    except KeyError:
        return fail("REPORT_NOT_FOUND", f"Unknown report: {report_code}", status_code=404)
    except Exception as exc:
        return fail("UPDATE_FAILED", str(exc), status_code=500)


@router.post("/reports/{report_code}/test-import")
def test_report_import(report_code: str):
    try:
        data = _service.test_import(report_code)
        return ok(data)
    except KeyError:
        return fail("REPORT_NOT_FOUND", f"Unknown report: {report_code}", status_code=404)
