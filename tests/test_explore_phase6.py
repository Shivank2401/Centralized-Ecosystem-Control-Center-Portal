"""Phase 6 explore / logs / outputs smoke tests."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fastapi.testclient import TestClient

from backend.main import app
from backend.services.explore_service import ExploreService


def test_path_traversal_blocked(tmp_path, monkeypatch):
    svc = ExploreService()
    monkeypatch.setattr(svc, "sanity_root", lambda: tmp_path)
    monkeypatch.setattr(
        svc,
        "allowed_roots",
        lambda: {"sanity": tmp_path, "cogs": tmp_path, "pincode": tmp_path, "runtime_runs": tmp_path},
    )
    try:
        svc.resolve_rel("sanity", "../secret.txt")
        assert False, "should raise"
    except ValueError:
        pass


def test_outputs_and_logs_with_fixture(tmp_path, monkeypatch):
    client_dir = tmp_path / "ESH"
    out_dir = client_dir / "unspressed_inventory"
    log_dir = client_dir / "logs" / "manage_fba"
    out_dir.mkdir(parents=True)
    log_dir.mkdir(parents=True)
    (out_dir / "US_manage_fba_inventory.parquet").write_bytes(b"PAR1")
    (log_dir / "latest.log").write_text("hello from manage_fba\n", encoding="utf-8")

    svc = ExploreService()
    monkeypatch.setattr(svc, "sanity_root", lambda: tmp_path)
    monkeypatch.setattr(
        svc,
        "allowed_roots",
        lambda: {
            "sanity": tmp_path,
            "cogs": tmp_path / "cogs",
            "pincode": tmp_path / "pincode",
            "runtime_runs": tmp_path / "runs",
        },
    )

    rows = svc.list_report_outputs(client="ESH", report="manage_fba")
    assert any(r["exists"] and r["file_count"] >= 1 for r in rows)

    logs = svc.list_log_index(client="ESH")
    assert logs[0]["exists"] is True
    assert any(r["report"] == "manage_fba" for r in logs[0]["reports"])

    content = svc.read_log_text(client="ESH", report="manage_fba", filename="latest.log")
    assert "hello from manage_fba" in content["text"]


def test_explore_api_endpoints():
    client = TestClient(app)
    assert client.get("/api/health").json()["data"]["phase"] == 6
    assert client.get("/api/explore/outputs").status_code == 200
    assert client.get("/api/explore/logs").status_code == 200
    assert client.get("/api/explore/pincode").status_code == 200
    assert client.get("/api/diagnostics").json()["data"]["phase"] == 6


def test_download_rejects_escape():
    client = TestClient(app)
    res = client.get("/api/explore/file/download", params={"root": "sanity", "rel": "../.env"})
    assert res.status_code == 400
