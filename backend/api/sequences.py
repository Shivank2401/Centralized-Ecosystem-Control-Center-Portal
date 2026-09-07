from __future__ import annotations

from fastapi import APIRouter

from backend.services.config_service import ConfigService
from backend.utils.responses import fail, ok

router = APIRouter()
_service = ConfigService()


@router.get("/sequences")
def list_sequences():
    return ok(_service.list_sequences())


@router.get("/sequences/{sequence_id}")
def get_sequence(sequence_id: str):
    data = _service.get_sequence(sequence_id)
    if data is None:
        return fail("SEQUENCE_NOT_FOUND", f"Unknown sequence: {sequence_id}", status_code=404)
    return ok(data)
