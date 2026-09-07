"""Shared API response helpers."""

from __future__ import annotations

from typing import Any, Optional

from fastapi.responses import JSONResponse


def ok(data: Any = None, message: Optional[str] = None, status_code: int = 200) -> JSONResponse:
    body: dict = {"success": True, "data": data}
    if message:
        body["message"] = message
    return JSONResponse(content=body, status_code=status_code)


def fail(code: str, message: str, *, status_code: int = 400, details: Any = None) -> JSONResponse:
    error: dict = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return JSONResponse(content={"success": False, "error": error}, status_code=status_code)
