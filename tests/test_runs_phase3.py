"""Phase 3 run service / manager smoke tests."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pipeline_engine.models import PipelineRunStatus
from pipeline_engine.run_manager import RunManager


def test_run_manager_create_and_finish(tmp_path):
    mgr = RunManager(runs_root=tmp_path / "runs")
    record = mgr.create_run(
        clients=["ESH"], geos=["US"], reports=["manage_fba"], source="test"
    )
    assert record.status == PipelineRunStatus.QUEUED
    mgr.mark_running(record.run_id)
    mgr.append_log(record.run_id, "hello")
    text, offset = mgr.read_stdout(record.run_id, offset=0)
    assert "hello" in text
    assert offset > 0
    mgr.request_cancel(record.run_id)
    assert mgr.is_cancel_requested(record.run_id)
    finished = mgr.mark_finished(
        record.run_id, status=PipelineRunStatus.CANCELLED, error="Cancelled by user"
    )
    assert finished.status == PipelineRunStatus.CANCELLED
    assert mgr.get_active_run() is None


def test_api_create_run_validation():
    from fastapi.testclient import TestClient
    from backend.main import app

    client = TestClient(app)
    res = client.post("/api/runs", json={"clients": [], "geos": ["US"], "reports": ["manage_fba"]})
    assert res.status_code == 422 or res.json()["success"] is False
