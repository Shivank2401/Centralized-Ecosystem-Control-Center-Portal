"""Phase 4 system / validation API smoke tests."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fastapi.testclient import TestClient

from backend.main import app
from backend.services.environment_service import EnvironmentService


def test_diagnostics_endpoint():
    client = TestClient(app)
    res = client.get("/api/diagnostics")
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert "checks" in body["data"]
    assert body["data"]["phase"] >= 4


def test_environment_never_returns_values():
    snap = EnvironmentService().snapshot()
    assert "variables" in snap
    for var in snap["variables"]:
        assert var["value"] is None


def test_environment_endpoint():
    client = TestClient(app)
    res = client.get("/api/environment")
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    for var in body["data"]["variables"]:
        assert var["value"] is None


def test_validate_run_endpoint():
    client = TestClient(app)
    res = client.post(
        "/api/validate",
        json={"clients": ["ESH"], "geos": ["US"], "reports": ["manage_fba"]},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert "ok" in body["data"]
    assert isinstance(body["data"]["checks"], list)


def test_health_phase_at_least_4():
    client = TestClient(app)
    res = client.get("/api/health")
    assert res.json()["data"]["phase"] >= 4
