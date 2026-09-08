"""Configuration Management Center APIs — thin layer over config_manager YAML."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.services.config_management_service import config_management
from backend.utils.responses import fail, ok

router = APIRouter(prefix="/config")


class ClientBody(BaseModel):
    name: str
    client_id: str
    enabled: bool = True
    data_root_env: str
    cogs_path_env: str
    package: str = ""
    layout: str = ""
    geographies: List[str] = Field(default_factory=list)


class EnableBody(BaseModel):
    enabled: bool


class GeographyBody(BaseModel):
    country_code: Optional[str] = None
    cogs_sheet_name: str
    country_currency: str
    orders_sales_channel: str = ""
    enabled: bool = True


class ReportBody(BaseModel):
    label: str
    stage: str
    module: str
    clients: Optional[List[str]] = None
    enabled: bool = True
    menu_order: Optional[int] = None
    output_subdir: Optional[str] = None
    description: Optional[str] = None


class StageBody(BaseModel):
    label: str
    order: int = 50
    clients: Optional[List[str]] = None
    enabled: bool = True
    package_path: Optional[str] = None


class SequenceBody(BaseModel):
    label: str
    clients: List[str]
    geos: List[str]
    reports: List[str]
    enabled: bool = True


class FileSaveBody(BaseModel):
    content: str


class EnvPathBody(BaseModel):
    key: str
    value: str


def _handle(exc: Exception):
    if isinstance(exc, KeyError):
        return fail("NOT_FOUND", str(exc), status_code=404)
    if isinstance(exc, RuntimeError):
        return fail("PIPELINE_BUSY", str(exc), status_code=409)
    if isinstance(exc, ValueError):
        return fail("VALIDATION_FAILED", str(exc), status_code=400)
    return fail("CONFIG_ERROR", str(exc), status_code=500)


@router.get("/overview")
def overview():
    return ok(config_management.overview())


@router.post("/validate")
def validate_config():
    return ok(config_management.validate_all())


@router.get("/version")
def version():
    return ok({"version": config_management.version(), "pipeline_busy": config_management.pipeline_busy()})


# --- clients ---
@router.get("/clients")
def list_clients():
    return ok(config_management.list_clients())


@router.post("/clients")
def create_client(body: ClientBody):
    try:
        # code from name? require code in query — use body with code field
        return fail("VALIDATION_FAILED", "Use POST /api/config/clients/{code}", status_code=400)
    except Exception as exc:
        return _handle(exc)


@router.put("/clients/{code}")
def put_client(code: str, body: ClientBody):
    try:
        exists = True
        try:
            config_management.get_client(code)
        except KeyError:
            exists = False
        data = config_management.upsert_client(code, body.model_dump(), create=not exists)
        return ok(data, message="Client saved")
    except Exception as exc:
        return _handle(exc)


@router.post("/clients/{code}")
def create_client_code(code: str, body: ClientBody):
    try:
        return ok(config_management.upsert_client(code, body.model_dump(), create=True), status_code=201)
    except Exception as exc:
        return _handle(exc)


@router.post("/clients/{code}/enabled")
def enable_client(code: str, body: EnableBody):
    try:
        return ok(config_management.set_client_enabled(code, body.enabled))
    except Exception as exc:
        return _handle(exc)


# --- geographies ---
@router.get("/geographies")
def list_geographies(client: Optional[str] = None):
    return ok(config_management.list_geographies(client=client))


@router.post("/geographies/{client}/{geo}")
def create_geo(client: str, geo: str, body: GeographyBody):
    try:
        return ok(
            config_management.upsert_geography(client, geo, body.model_dump(), create=True),
            status_code=201,
        )
    except Exception as exc:
        return _handle(exc)


@router.put("/geographies/{client}/{geo}")
def put_geo(client: str, geo: str, body: GeographyBody):
    try:
        return ok(config_management.upsert_geography(client, geo, body.model_dump(), create=False))
    except Exception as exc:
        return _handle(exc)


# --- reports ---
@router.get("/reports")
def list_reports():
    return ok(config_management.list_reports_config())


@router.get("/reports/{code}")
def get_report(code: str):
    row = next((r for r in config_management.list_reports_config() if r["code"] == code.lower()), None)
    if row is None:
        return fail("NOT_FOUND", f"Unknown report: {code}", status_code=404)
    row = dict(row)
    row["sequence_refs"] = config_management.report_sequence_refs(code)
    return ok(row)


@router.put("/reports/{code}")
def put_report(code: str, body: ReportBody):
    try:
        return ok(config_management.update_report(code, body.model_dump()))
    except Exception as exc:
        return _handle(exc)


@router.post("/reports/{code}/enabled")
def enable_report(code: str, body: EnableBody):
    try:
        refs = config_management.report_sequence_refs(code)
        data = config_management.set_report_enabled(code, body.enabled)
        data["sequence_refs"] = refs
        return ok(data)
    except Exception as exc:
        return _handle(exc)


# --- stages ---
@router.get("/stages")
def list_stages():
    return ok(config_management.list_stages_config())


@router.post("/stages/{key}")
def create_stage(key: str, body: StageBody):
    try:
        return ok(config_management.upsert_stage(key, body.model_dump(), create=True), status_code=201)
    except Exception as exc:
        return _handle(exc)


@router.put("/stages/{key}")
def put_stage(key: str, body: StageBody):
    try:
        return ok(config_management.upsert_stage(key, body.model_dump(), create=False))
    except Exception as exc:
        return _handle(exc)


# --- sequences ---
@router.get("/sequences")
def list_sequences():
    return ok(config_management.list_sequences_config())


@router.post("/sequences")
def create_sequence(body: SequenceBody, id: Optional[str] = None):
    try:
        sid = id or body.label
        return ok(config_management.upsert_sequence(sid, body.model_dump(), create=True), status_code=201)
    except Exception as exc:
        return _handle(exc)


@router.put("/sequences/{seq_id}")
def put_sequence(seq_id: str, body: SequenceBody):
    try:
        return ok(config_management.upsert_sequence(seq_id, body.model_dump(), create=False))
    except Exception as exc:
        return _handle(exc)


@router.delete("/sequences/{seq_id}")
def delete_sequence(seq_id: str):
    try:
        return ok(config_management.delete_sequence(seq_id))
    except Exception as exc:
        return _handle(exc)


@router.post("/sequences/{seq_id}/duplicate")
def duplicate_sequence(seq_id: str):
    try:
        return ok(config_management.duplicate_sequence(seq_id), status_code=201)
    except Exception as exc:
        return _handle(exc)


@router.post("/sequences/validate")
def validate_sequence(body: SequenceBody):
    errors = config_management.validate_sequence_payload(body.model_dump())
    return ok({"ok": len(errors) == 0, "errors": errors})


# --- environment ---
@router.get("/environment")
def environment():
    return ok(config_management.environment_status())


@router.post("/environment/path")
def set_env_path(body: EnvPathBody):
    try:
        return ok(config_management.update_env_path(body.key, body.value))
    except Exception as exc:
        return _handle(exc)


@router.post("/environment/validate")
def validate_env():
    return ok(config_management.environment_status())


# --- files ---
@router.get("/files")
def list_files():
    return ok(config_management.list_files())


@router.get("/files/{name}")
def get_file(name: str):
    try:
        return ok(config_management.get_file(name))
    except Exception as exc:
        return _handle(exc)


@router.put("/files/{name}")
def save_file(name: str, body: FileSaveBody):
    try:
        return ok(config_management.save_file(name, body.content))
    except Exception as exc:
        return _handle(exc)


# --- history ---
@router.get("/history")
def history(limit: int = 100):
    return ok(config_management.history(limit=limit))


@router.get("/history/{entry_id}")
def history_one(entry_id: str):
    try:
        return ok(config_management.history_entry(entry_id))
    except Exception as exc:
        return _handle(exc)


@router.post("/history/{entry_id}/restore")
def restore(entry_id: str):
    try:
        return ok(config_management.restore_history(entry_id))
    except Exception as exc:
        return _handle(exc)
