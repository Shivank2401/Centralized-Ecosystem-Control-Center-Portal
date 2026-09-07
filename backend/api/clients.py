from __future__ import annotations

from fastapi import APIRouter

from backend.services.config_service import ConfigService
from backend.utils.responses import fail, ok

router = APIRouter()
_service = ConfigService()


@router.get("/clients")
def list_clients():
    return ok(_service.list_clients())


@router.get("/clients/{client_code}")
def get_client(client_code: str):
    try:
        return ok(_service.get_client(client_code))
    except KeyError as exc:
        return fail("CLIENT_NOT_FOUND", str(exc), status_code=404)
