"""Pipeline runs API — create, list, status, cancel, live logs (SSE)."""

from __future__ import annotations

import asyncio
import json
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from backend.schemas.run import CreateRunRequest
from backend.services.run_service import run_service
from backend.utils.responses import fail, ok

router = APIRouter()


@router.post("/runs")
def create_run(body: CreateRunRequest):
    try:
        record = run_service.create_and_start(
            clients=body.clients,
            geos=body.geos,
            reports=body.reports,
            source="api",
        )
        return ok(run_service.to_dict(record), message="Run queued", status_code=201)
    except RuntimeError as exc:
        return fail("PIPELINE_BUSY", str(exc), status_code=409)
    except ValueError as exc:
        return fail("RUN_VALIDATION_FAILED", str(exc), status_code=400)
    except Exception as exc:
        return fail("RUN_START_FAILED", str(exc), status_code=500)


@router.get("/runs")
def list_runs(
    limit: int = Query(50, ge=1, le=200),
    status: Optional[str] = Query(None),
    client: Optional[str] = Query(None),
):
    records = run_service.list_runs(limit=limit, status=status, client=client)
    return ok([run_service.to_dict(r) for r in records])


@router.get("/runs/active")
def active_run():
    record = run_service.get_active()
    return ok(run_service.to_dict(record) if record else None)


@router.get("/runs/{run_id}")
def get_run(run_id: str):
    record = run_service.get(run_id)
    if record is None:
        return fail("RUN_NOT_FOUND", f"Unknown run: {run_id}", status_code=404)
    return ok(run_service.to_dict(record))


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str):
    try:
        record = run_service.cancel(run_id)
        return ok(run_service.to_dict(record), message="Run cancelled")
    except KeyError:
        return fail("RUN_NOT_FOUND", f"Unknown run: {run_id}", status_code=404)
    except RuntimeError as exc:
        return fail("RUN_CANCEL_FAILED", str(exc), status_code=400)


@router.get("/runs/{run_id}/logs")
def get_logs(run_id: str, offset: int = Query(0, ge=0)):
    try:
        return ok(run_service.logs(run_id, offset=offset))
    except KeyError:
        return fail("RUN_NOT_FOUND", f"Unknown run: {run_id}", status_code=404)


@router.get("/runs/{run_id}/events")
async def run_events(run_id: str):
    """Server-Sent Events stream of status + log chunks."""
    if run_service.get(run_id) is None:
        return fail("RUN_NOT_FOUND", f"Unknown run: {run_id}", status_code=404)

    async def event_generator():
        offset = 0
        while True:
            try:
                payload = run_service.logs(run_id, offset=offset)
            except KeyError:
                yield f"event: error\ndata: {json.dumps({'message': 'run missing'})}\n\n"
                break

            offset = int(payload["offset"])
            yield f"event: update\ndata: {json.dumps(payload)}\n\n"

            if payload["status"] in {"SUCCESS", "FAILED", "CANCELLED"}:
                yield f"event: done\ndata: {json.dumps(payload)}\n\n"
                break

            await asyncio.sleep(0.8)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
