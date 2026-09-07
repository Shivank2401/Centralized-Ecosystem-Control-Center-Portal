from __future__ import annotations

from fastapi import APIRouter, Query

from backend.services.config_service import ConfigService
from backend.utils.responses import fail, ok

router = APIRouter()
_service = ConfigService()


@router.get("/geographies")
def list_geographies(client: str = Query(..., description="Client code, e.g. ESH")):
    try:
        return ok(_service.list_geographies(client))
    except KeyError as exc:
        return fail("CLIENT_NOT_FOUND", str(exc), status_code=404)


@router.get("/geographies/{client_code}")
def get_client_geographies(client_code: str):
    try:
        return ok(_service.list_geographies(client_code))
    except KeyError as exc:
        return fail("CLIENT_NOT_FOUND", str(exc), status_code=404)
