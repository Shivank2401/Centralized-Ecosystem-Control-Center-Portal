"""Discover report modules and filesystem layout."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Dict, List, Optional

from pipeline_engine.registry import STAGE_PATHS, ConfigRegistry, normalize_stage_key

_PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ReportDiscovery:
    def __init__(self, registry: Optional[ConfigRegistry] = None) -> None:
        self.registry = registry or ConfigRegistry()

    def module_file_path(self, module_path: str) -> Optional[Path]:
        if not module_path:
            return None
        rel = Path(*module_path.split("."))
        for path in (_PROJECT_ROOT / f"{rel}.py", _PROJECT_ROOT / rel / "__init__.py"):
            if path.is_file():
                return path
        return None

    def module_importable(self, module_path: str) -> bool:
        if not module_path:
            return False
        try:
            return importlib.util.find_spec(module_path) is not None
        except (ModuleNotFoundError, ValueError, ImportError):
            return False

    def discover_report_summaries(self) -> List[Dict[str, Any]]:
        summaries: List[Dict[str, Any]] = []
        for code, meta in self.registry.all_reports().items():
            module = str(meta.get("module") or "")
            stage = normalize_stage_key(meta.get("stage", "common"))
            path = self.module_file_path(module)
            summaries.append(
                {
                    "code": code,
                    "label": meta.get("label", code),
                    "stage": stage,
                    "module": module,
                    "clients": meta.get("clients"),
                    "enabled": bool(meta.get("enabled", True)),
                    "output_subdir": meta.get("output_subdir"),
                    "menu_order": meta.get("menu_order"),
                    "module_file_exists": path is not None,
                    "module_importable": self.module_importable(module) if module else False,
                    "package_path": STAGE_PATHS.get(stage),
                }
            )
        summaries.sort(
            key=lambda r: (r.get("stage") or "", int(r.get("menu_order") or 999), r["code"])
        )
        return summaries
