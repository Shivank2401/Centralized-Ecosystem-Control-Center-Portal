"""Validation API service wrapping PipelineValidator."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from pipeline_engine.registry import ConfigRegistry
from pipeline_engine.validation import PipelineValidator


class ValidationService:
    def __init__(
        self,
        registry: ConfigRegistry | None = None,
        validator: PipelineValidator | None = None,
    ) -> None:
        self.registry = registry or ConfigRegistry()
        self.validator = validator or PipelineValidator(self.registry)

    def validate_run(
        self,
        clients: Sequence[str],
        geos: Sequence[str],
        reports: Sequence[str],
    ) -> Dict[str, Any]:
        report = self.validator.validate_run(clients, geos, reports)
        return report.to_dict()

    def validate_ecosystem(self, client: Optional[str] = None) -> Dict[str, Any]:
        """Validate env + modules for one or all clients with their geos and enabled reports."""
        clients_cfg = self.registry.clients(include_disabled=False)
        if client:
            code = client.upper()
            if code not in clients_cfg:
                return {
                    "ok": False,
                    "checks": [
                        {
                            "name": f"client:{code}",
                            "ok": False,
                            "level": "ERROR",
                            "message": f"Unknown or disabled client: {code}",
                            "expected": None,
                        }
                    ],
                }
            targets = [code]
        else:
            targets = list(clients_cfg.keys())

        all_checks: List[Dict[str, Any]] = []
        overall_ok = True
        for code in targets:
            geos = list(self.registry.geographies(code).keys())
            reports = [
                r
                for r, meta in self.registry.all_reports().items()
                if meta.get("enabled", True) and self.registry.matches_clients(meta, [code])
            ]
            result = self.validator.validate_run([code], geos, reports)
            for c in result.checks:
                all_checks.append(c.to_dict())
            if not result.ok:
                overall_ok = False

        by_name: Dict[str, Dict[str, Any]] = {}
        for d in all_checks:
            prev = by_name.get(d["name"])
            if prev is None or (prev.get("ok") and not d.get("ok")):
                by_name[d["name"]] = d

        checks = list(by_name.values())
        hard = [c for c in checks if not c["ok"] and c["level"] == "ERROR"]
        return {"ok": overall_ok and len(hard) == 0, "checks": checks}
