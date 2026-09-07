"""Phase 5 AST validation + registration smoke tests."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fastapi.testclient import TestClient

from backend.main import app
from pipeline_engine.ast_validator import analyze_source


GOOD_SCRIPT = '''\
"""Portal phase-5 smoke report — safe no-op."""

def run(*, client: str = "ESH", geos=None, **kwargs):
    return {"status": "success", "message": f"ok {client}", "client": client}
'''

BAD_SCRIPT = '''\
def run(x):
    eval("1+1")
'''


def test_ast_accepts_compatible_run():
    result = analyze_source(GOOD_SCRIPT, filename="portal_smoke_report.py")
    assert result.ok
    assert result.has_run
    assert result.accepts_client


def test_ast_rejects_eval():
    result = analyze_source(BAD_SCRIPT, filename="bad_report.py")
    assert not result.ok
    assert any("eval" in e.lower() or "client" in e.lower() for e in result.errors)


def test_upload_and_register_roundtrip(tmp_path):
    client = TestClient(app)
    files = {"file": ("portal_smoke_report.py", GOOD_SCRIPT.encode("utf-8"), "text/x-python")}
    up = client.post("/api/registry/upload", files=files)
    assert up.status_code == 201, up.text
    body = up.json()["data"]
    assert body["analysis"]["ok"] is True
    upload_id = body["upload_id"]

    code = "portal_smoke"
    # Ensure clean slate
    yaml_path = _ROOT / "config_manager" / "report.yaml"
    doc = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    if code in (doc.get("reports") or {}):
        client.post(f"/api/reports/{code}/enabled", json={"enabled": False})

    reg = client.post(
        "/api/registry/register",
        json={
            "upload_id": upload_id,
            "code": code,
            "label": "Portal Smoke",
            "stage": "utility_codes",
            "clients": ["ESH"],
            "output_subdir": "portal_smoke",
            "enabled": True,
            "overwrite": True,
        },
    )
    assert reg.status_code == 201, reg.text
    data = reg.json()["data"]
    assert data["code"] == code
    assert data["importable"] is True

    imp = client.post(f"/api/reports/{code}/test-import")
    assert imp.status_code == 200
    assert imp.json()["data"]["import_ok"] is True

    dis = client.post(f"/api/reports/{code}/enabled", json={"enabled": False})
    assert dis.status_code == 200
    assert dis.json()["data"]["enabled"] is False

    # Cleanup: remove script and drop YAML entry (restore backup then strip code)
    script = _ROOT / data["script_path"]
    if script.is_file():
        script.unlink()
    backup = _ROOT / data["yaml_backup"]
    raw = backup.read_text(encoding="utf-8") if backup.is_file() else yaml_path.read_text(encoding="utf-8")
    doc = yaml.safe_load(raw) or {}
    (doc.get("reports") or {}).pop(code, None)
    # Write via service helper to keep header consistent
    from backend.services.report_registration_service import ReportRegistrationService

    svc = ReportRegistrationService()
    svc._write_report_yaml(doc)


def test_health_phase_5():
    client = TestClient(app)
    assert client.get("/api/health").json()["data"]["phase"] >= 5
