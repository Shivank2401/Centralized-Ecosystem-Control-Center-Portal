"""System diagnostics — connectivity between portal, config, and pipeline."""

from __future__ import annotations

import os
import platform
import sys
from pathlib import Path
from typing import Any, Dict, List

from config_manager import paths as path_mod
from pipeline_engine.discovery import ReportDiscovery
from pipeline_engine.registry import ConfigRegistry
from pipeline_engine.run_manager import RunManager

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class DiagnosticsService:
    def __init__(
        self,
        registry: ConfigRegistry | None = None,
        discovery: ReportDiscovery | None = None,
        run_manager: RunManager | None = None,
    ) -> None:
        self.registry = registry or ConfigRegistry()
        self.discovery = discovery or ReportDiscovery(self.registry)
        self.run_manager = run_manager or RunManager()

    def snapshot(self) -> Dict[str, Any]:
        clients = self.registry.clients(include_disabled=True)
        reports = self.discovery.discover_report_summaries()
        enabled_reports = [r for r in reports if r["enabled"]]
        missing_files = [r["code"] for r in reports if r["module"] and not r["module_file_exists"]]
        not_importable = [
            r["code"]
            for r in reports
            if r["module"] and r["module_file_exists"] and not r["module_importable"]
        ]

        checks: List[Dict[str, Any]] = []

        def add(name: str, ok: bool, level: str, message: str) -> None:
            checks.append({"name": name, "ok": ok, "level": level, "message": message})

        add("python", True, "PASS", f"{sys.version.split()[0]} ({platform.system()})")
        add(
            "project_root",
            _PROJECT_ROOT.is_dir(),
            "PASS" if _PROJECT_ROOT.is_dir() else "ERROR",
            str(_PROJECT_ROOT),
        )

        try:
            self.registry.refresh()
            add("config_yaml", True, "PASS", "client / geography / report YAML loadable")
        except Exception as exc:
            add("config_yaml", False, "ERROR", str(exc))

        add(
            "clients",
            len(clients) > 0,
            "PASS" if clients else "ERROR",
            f"{len(clients)} client(s) configured",
        )
        add(
            "reports",
            len(reports) > 0,
            "PASS" if reports else "ERROR",
            f"{len(reports)} reports · {len(enabled_reports)} enabled",
        )
        add(
            "report_modules",
            len(missing_files) == 0 and len(not_importable) == 0,
            "ERROR" if missing_files or not_importable else "PASS",
            (
                "All modules resolve"
                if not missing_files and not not_importable
                else f"missing={missing_files[:8]} not_importable={not_importable[:8]}"
            ),
        )

        # Data / output roots (Phase 6)
        try:
            sanity = path_mod.sanity_data_root()
            writable = False
            if sanity.exists():
                probe = sanity / ".portal_write_probe"
                try:
                    probe.write_text("ok", encoding="utf-8")
                    probe.unlink(missing_ok=True)
                    writable = True
                except OSError:
                    writable = False
            add(
                "sanity_data_root",
                sanity.exists(),
                "WARNING" if not sanity.exists() else ("PASS" if writable else "ERROR"),
                f"{sanity} · {'writable' if writable else ('missing' if not sanity.exists() else 'not writable')}",
            )
        except Exception as exc:
            add("sanity_data_root", False, "ERROR", str(exc))

        for code, cfg in clients.items():
            raw = os.getenv(cfg.data_root_env, "").strip()
            exists = False
            if raw:
                try:
                    exists = Path(raw.strip('"')).exists()
                except OSError:
                    exists = False
            add(
                f"data_root:{code}",
                bool(raw) and exists,
                "ERROR" if not raw else ("WARNING" if not exists else "PASS"),
                f"{cfg.data_root_env}={'set' if raw else 'missing'}"
                + (f" · path {'exists' if exists else 'missing'}" if raw else ""),
            )

        cogs = _PROJECT_ROOT / "cogs"
        add(
            "cogs_dir",
            cogs.is_dir(),
            "WARNING" if not cogs.is_dir() else "PASS",
            str(cogs),
        )
        try:
            pin = path_mod.pincode_data_dir()
            add(
                "pincode_dir",
                pin.is_dir(),
                "WARNING" if not pin.is_dir() else "PASS",
                str(pin),
            )
        except Exception as exc:
            add("pincode_dir", False, "WARNING", str(exc))

        runtime_runs = _PROJECT_ROOT / "runtime" / "runs"
        add(
            "runtime_dir",
            True,
            "PASS",
            f"{runtime_runs} ({'exists' if runtime_runs.is_dir() else 'will be created'})",
        )

        active = self.run_manager.get_active_run()
        add(
            "pipeline_idle",
            active is None,
            "WARNING" if active else "PASS",
            f"Active run {active.run_id}" if active else "No active run",
        )

        hard = [c for c in checks if not c["ok"] and c["level"] == "ERROR"]
        return {
            "ok": len(hard) == 0,
            "phase": 6,
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "project_root": str(_PROJECT_ROOT),
            "counts": {
                "clients": len(clients),
                "reports": len(reports),
                "enabled_reports": len(enabled_reports),
                "missing_modules": len(missing_files),
                "not_importable": len(not_importable),
            },
            "active_run_id": active.run_id if active else None,
            "checks": checks,
        }
