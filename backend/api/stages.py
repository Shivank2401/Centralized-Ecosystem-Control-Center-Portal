from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

from backend.services.config_service import ConfigService
from backend.utils.responses import ok

router = APIRouter()
_service = ConfigService()


@router.get("/stages")
def list_stages(client: Optional[str] = Query(None)):
    clients = [c.strip().upper() for c in client.split(",")] if client else None
    return ok(_service.list_stages(clients))
