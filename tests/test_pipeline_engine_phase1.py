"""Phase 1 smoke tests for pipeline_engine."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pipeline_engine.discovery import ReportDiscovery
from pipeline_engine.executor import adapt_result
from pipeline_engine.models import ReportResult
from pipeline_engine.registry import ConfigRegistry, normalize_stage_key
from pipeline_engine.validation import PipelineValidator


def test_project_root_is_portal_folder():
    assert _ROOT.name == "Centralized Ecosystem Portal"
    assert (_ROOT / "config_manager" / "report.yaml").exists()
    assert not (_ROOT / "client_pipeline").exists()


def test_resolve_report_code_case_insensitive():
    reg = ConfigRegistry()
    assert reg.resolve_report_code("threeG_nd_updike") == "threeG_nd_updike"
    assert reg.resolve_report_code("threeg_nd_updike") == "threeG_nd_updike"
    assert reg.resolve_report_code("missing_report_xyz") is None


def test_normalize_stage_key():
    assert normalize_stage_key("common") == "common"
    assert normalize_stage_key("Common Sanity Reports") == "common"
    assert normalize_stage_key("common_sanity_reports") == "common"
    assert normalize_stage_key("Supply Chain") == "helper_files_nd_saving"
    assert normalize_stage_key("helper_files_nd_saving") == "helper_files_nd_saving"
    assert normalize_stage_key("Retail") == "retail"


def test_registry_loads_clients():
    reg = ConfigRegistry()
    clients = reg.clients()
    assert "ESH" in clients


def test_registry_loads_reports():
    reg = ConfigRegistry()
    reports = reg.all_reports()
    assert "manage_fba" in reports
    assert reports["manage_fba"].get("module")


def test_discovery_manage_fba_exists():
    disc = ReportDiscovery()
    path = disc.module_file_path("report_script.common_sanity_report.manage_fba_report")
    assert path is not None and path.exists()


def test_adapt_result():
    r = adapt_result(None)
    assert isinstance(r, ReportResult)
    assert r.status == "success"


def test_validate_unknown_client():
    v = PipelineValidator()
    report = v.validate_run(["NOPE"], ["US"], ["manage_fba"])
    assert report.ok is False
