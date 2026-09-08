"""Configuration Management Center API tests."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fastapi.testclient import TestClient

from backend.main import app


def test_config_overview_and_validate():
    client = TestClient(app)
    ov = client.get("/api/config/overview")
    assert ov.status_code == 200
    body = ov.json()["data"]
    assert "counts" in body
    assert "health" in body
    assert "version" in body

    val = client.post("/api/config/validate")
    assert val.status_code == 200
    assert "ok" in val.json()["data"]


def test_list_config_entities():
    client = TestClient(app)
    assert client.get("/api/config/clients").status_code == 200
    assert client.get("/api/config/geographies").status_code == 200
    assert client.get("/api/config/reports").status_code == 200
    assert client.get("/api/config/stages").status_code == 200
    assert client.get("/api/config/sequences").status_code == 200
    assert client.get("/api/config/files").status_code == 200
    assert client.get("/api/config/environment").status_code == 200
    env = client.get("/api/config/environment").json()["data"]
    for var in env.get("variables", []):
        assert var.get("value") is None


def test_sequence_validate_rejects_unknown_report():
    client = TestClient(app)
    res = client.post(
        "/api/config/sequences/validate",
        json={
            "label": "Bad",
            "clients": ["ESH"],
            "geos": ["US"],
            "reports": ["does_not_exist_zzz"],
        },
    )
    assert res.status_code == 200
    assert res.json()["data"]["ok"] is False


def test_report_update_roundtrip_preserves_yaml():
    client = TestClient(app)
    reports = client.get("/api/config/reports").json()["data"]
    target = next(r for r in reports if r["code"] == "manage_fba")
    original_label = target["label"]
    res = client.put(
        "/api/config/reports/manage_fba",
        json={
            "label": original_label,
            "stage": target["stage"],
            "module": target["module"],
            "clients": target.get("clients"),
            "enabled": target["enabled"],
            "menu_order": target.get("menu_order"),
            "output_subdir": target.get("output_subdir"),
        },
    )
    assert res.status_code == 200, res.text
    hist = client.get("/api/config/history?limit=5").json()["data"]
    assert any(h["file"] == "report.yaml" for h in hist)


def test_invalid_yaml_file_save_rejected():
    client = TestClient(app)
    res = client.put("/api/config/files/client.yaml", json={"content": "not: valid: yaml: ["})
    assert res.status_code == 400
