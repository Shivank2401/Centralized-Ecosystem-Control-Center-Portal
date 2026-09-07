"""Pre-run and configuration validation."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

from pipeline_engine.discovery import ReportDiscovery
from pipeline_engine.registry import ConfigRegistry


@dataclass
class CheckResult:
    name: str
    ok: bool
    level: str = "PASS"
    message: str = ""
    expected: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "ok": self.ok,
            "level": self.level,
            "message": self.message,
            "expected": self.expected,
        }


@dataclass
class ValidationReport:
    ok: bool
    checks: List[CheckResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"ok": self.ok, "checks": [c.to_dict() for c in self.checks]}


class PipelineValidator:
    def __init__(
        self,
        registry: Optional[ConfigRegistry] = None,
        discovery: Optional[ReportDiscovery] = None,
    ) -> None:
        self.registry = registry or ConfigRegistry()
        self.discovery = discovery or ReportDiscovery(self.registry)

    def validate_run(
        self,
        clients: Sequence[str],
        geos: Sequence[str],
        reports: Sequence[str],
    ) -> ValidationReport:
        checks: List[CheckResult] = []
        clients_u = [c.strip().upper() for c in clients]
        geos_u = [g.strip().upper() for g in geos]
        reports_l = [r.strip().lower() for r in reports]
        known_clients = self.registry.clients()

        for client in clients_u:
            if client not in known_clients:
                checks.append(
                    CheckResult(
                        name=f"client:{client}",
                        ok=False,
                        level="ERROR",
                        message=f"Unknown or disabled client: {client}",
                        expected=str(list(known_clients.keys())),
                    )
                )
                continue
            checks.append(
                CheckResult(name=f"client:{client}", ok=True, level="PASS", message="Client enabled")
            )
            cfg = known_clients[client]
            root_ok = bool(os.getenv(cfg.data_root_env, "").strip())
            checks.append(
                CheckResult(
                    name=f"env:{cfg.data_root_env}",
                    ok=root_ok,
                    level="ERROR" if not root_ok else "PASS",
                    message="Configured" if root_ok else f"Missing {cfg.data_root_env} in .env",
                )
            )
            allowed = self.registry.geographies(client)
            for geo in geos_u:
                if geo not in allowed:
                    checks.append(
                        CheckResult(
                            name=f"geo:{client}/{geo}",
                            ok=False,
                            level="WARNING",
                            message=f"Geo {geo} not enabled for {client} (will be skipped)",
                            expected=str(list(allowed.keys())),
                        )
                    )
                else:
                    checks.append(
                        CheckResult(
                            name=f"geo:{client}/{geo}",
                            ok=True,
                            level="PASS",
                            message="Geography enabled",
                        )
                    )

        all_reports = self.registry.all_reports()
        for report in reports_l:
            meta = all_reports.get(report)
            if meta is None:
                checks.append(
                    CheckResult(
                        name=f"report:{report}",
                        ok=False,
                        level="ERROR",
                        message=f"Unknown report: {report}",
                    )
                )
                continue
            if not meta.get("enabled", True):
                checks.append(
                    CheckResult(
                        name=f"report:{report}",
                        ok=False,
                        level="ERROR",
                        message=f"Report {report} is disabled",
                    )
                )
                continue
            if clients_u and not self.registry.matches_clients(meta, clients_u):
                checks.append(
                    CheckResult(
                        name=f"report:{report}:clients",
                        ok=False,
                        level="WARNING",
                        message=f"Report not available for selected clients {clients_u}",
                        expected=str(meta.get("clients")),
                    )
                )
            else:
                checks.append(
                    CheckResult(
                        name=f"report:{report}",
                        ok=True,
                        level="PASS",
                        message=str(meta.get("label", report)),
                    )
                )
            module = str(meta.get("module") or "")
            if not module:
                checks.append(
                    CheckResult(
                        name=f"module:{report}",
                        ok=False,
                        level="ERROR",
                        message="No module wired in report.yaml",
                    )
                )
            else:
                exists = self.discovery.module_file_path(module) is not None
                importable = self.discovery.module_importable(module)
                checks.append(
                    CheckResult(
                        name=f"module:{report}",
                        ok=exists and importable,
                        level="ERROR" if not (exists and importable) else "PASS",
                        message=(
                            f"Module OK: {module}"
                            if exists and importable
                            else f"Module missing or not importable: {module}"
                        ),
                    )
                )

        hard_errors = [c for c in checks if not c.ok and c.level == "ERROR"]
        return ValidationReport(ok=len(hard_errors) == 0, checks=checks)
