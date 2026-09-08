"""Discover report modules and filesystem layout."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from pipeline_engine.registry import STAGE_PATHS, ConfigRegistry, normalize_stage_key

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_REPORT_SCRIPT_ROOT = _PROJECT_ROOT / "report_script"
_RUN_DEF_RE = re.compile(r"^\s*def\s+run\s*\(", re.MULTILINE)


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

    def _module_to_reports(self) -> Dict[str, List[Dict[str, Any]]]:
        by_module: Dict[str, List[Dict[str, Any]]] = {}
        for code, meta in self.registry.all_reports().items():
            module = str(meta.get("module") or "").strip()
            if not module:
                continue
            by_module.setdefault(module, []).append(
                {
                    "code": code,
                    "label": meta.get("label", code),
                    "enabled": bool(meta.get("enabled", True)),
                    "clients": meta.get("clients"),
                    "stage": normalize_stage_key(meta.get("stage", "")),
                }
            )
        return by_module

    def _package_stage_key(self, package: str) -> Optional[str]:
        rel = f"report_script/{package}".replace("\\", "/")
        for stage_key, path in STAGE_PATHS.items():
            if path.replace("\\", "/") == rel:
                return stage_key
        return None

    @staticmethod
    def _file_has_run(path: Path) -> bool:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return False
        return bool(_RUN_DEF_RE.search(text))

    def discover_script_packages(self) -> List[Dict[str, Any]]:
        """List first-level folders under report_script/ with script summaries."""
        self.registry.refresh()
        by_module = self._module_to_reports()
        stages_meta = self.registry.report_stages_meta()
        packages: List[Dict[str, Any]] = []

        if not _REPORT_SCRIPT_ROOT.is_dir():
            return packages

        for pkg_dir in sorted(_REPORT_SCRIPT_ROOT.iterdir(), key=lambda p: p.name.lower()):
            if not pkg_dir.is_dir() or pkg_dir.name.startswith((".", "_")):
                continue
            scripts = self._scripts_in_package(pkg_dir, by_module)
            stage_key = self._package_stage_key(pkg_dir.name)
            stage_label = None
            if stage_key:
                meta: Dict[str, Any] = {}
                for k, v in stages_meta.items():
                    if normalize_stage_key(k) == stage_key:
                        meta = v if isinstance(v, dict) else {}
                        break
                stage_label = str(meta.get("label") or stage_key)
            packages.append(
                {
                    "name": pkg_dir.name,
                    "path": f"report_script/{pkg_dir.name}",
                    "stage_key": stage_key,
                    "stage_label": stage_label,
                    "script_count": len(scripts),
                    "registered_count": sum(1 for s in scripts if s["registered"]),
                    "runnable_count": sum(1 for s in scripts if s["can_run"]),
                    "scripts": scripts,
                }
            )
        return packages

    def get_script_package(self, package: str) -> Optional[Dict[str, Any]]:
        name = str(package or "").strip()
        if not name or "/" in name or "\\" in name or name.startswith("."):
            return None
        for pkg in self.discover_script_packages():
            if pkg["name"] == name:
                return pkg
        return None

    def _scripts_in_package(
        self, pkg_dir: Path, by_module: Dict[str, List[Dict[str, Any]]]
    ) -> List[Dict[str, Any]]:
        scripts: List[Dict[str, Any]] = []
        for py in sorted(pkg_dir.glob("*.py"), key=lambda p: p.name.lower()):
            if py.name == "__init__.py":
                continue
            stem = py.stem
            module = f"report_script.{pkg_dir.name}.{stem}"
            linked = by_module.get(module) or []
            has_run = self._file_has_run(py)
            primary = linked[0] if linked else None
            can_run = bool(primary and primary.get("enabled") and has_run)
            scripts.append(
                {
                    "file": py.name,
                    "stem": stem,
                    "module": module,
                    "has_run": has_run,
                    "registered": bool(linked),
                    "can_run": can_run,
                    "reports": linked,
                    "report_code": primary["code"] if primary else None,
                    "label": (primary["label"] if primary else stem.replace("_", " ")),
                    "clients": primary.get("clients") if primary else None,
                    "enabled": primary.get("enabled") if primary else None,
                    "size_bytes": py.stat().st_size,
                }
            )
        scripts.sort(
            key=lambda s: (
                0 if s["can_run"] else 1 if s["registered"] else 2,
                str(s["label"]).lower(),
            )
        )
        return scripts
