"""Diagnostics, environment, and validation endpoints."""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from backend.services.diagnostics_service import DiagnosticsService
from backend.services.environment_service import EnvironmentService
from backend.services.run_service import run_service
from backend.services.validation_service import ValidationService
from backend.utils.responses import fail, ok

router = APIRouter()
_diagnostics = DiagnosticsService()
_environment = EnvironmentService()
_validation = ValidationService()


class ValidateRunBody(BaseModel):
    clients: List[str] = Field(min_length=1)
    geos: List[str] = Field(min_length=1)
    reports: List[str] = Field(min_length=1)


@router.get("/diagnostics")
def get_diagnostics():
    return ok(_diagnostics.snapshot())


@router.get("/environment")
def get_environment():
    return ok(_environment.snapshot())


@router.post("/validate")
def validate_run(body: ValidateRunBody):
    try:
        return ok(_validation.validate_run(body.clients, body.geos, body.reports))
    except Exception as exc:
        return fail("VALIDATION_FAILED", str(exc), status_code=500)


@router.get("/validate/ecosystem")
def validate_ecosystem(client: Optional[str] = Query(None)):
    try:
        return ok(_validation.validate_ecosystem(client=client))
    except Exception as exc:
        return fail("VALIDATION_FAILED", str(exc), status_code=500)


@router.post("/sequences/{sequence_id}/run")
def run_sequence(sequence_id: str):
    """Resolve a saved sequence and start a background pipeline run."""
    from backend.services.config_service import ConfigService

    sequences = ConfigService().list_sequences()
    match = next((s for s in sequences if s.get("id") == sequence_id), None)
    if match is None:
        return fail("SEQUENCE_NOT_FOUND", f"Unknown sequence: {sequence_id}", status_code=404)
    try:
        record = run_service.create_and_start(
            clients=match["clients"],
            geos=match["geos"],
            reports=match["reports"],
            source=f"sequence:{sequence_id}",
        )
        return ok(run_service.to_dict(record), message=f"Started sequence {sequence_id}", status_code=201)
    except RuntimeError as exc:
        return fail("PIPELINE_BUSY", str(exc), status_code=409)
    except ValueError as exc:
        return fail("RUN_VALIDATION_FAILED", str(exc), status_code=400)
    except Exception as exc:
        return fail("RUN_START_FAILED", str(exc), status_code=500)
