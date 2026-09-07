"""Upload quarantine + transactional report registration into report.yaml / report_script."""

from __future__ import annotations

import importlib
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import yaml

from pipeline_engine.ast_validator import analyze_file, analyze_source, validate_filename
from pipeline_engine.discovery import ReportDiscovery
from pipeline_engine.registry import STAGE_PATHS, ConfigRegistry, normalize_stage_key

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_UPLOADS = _PROJECT_ROOT / "runtime" / "uploads"
_BACKUPS = _PROJECT_ROOT / "runtime" / "backups"
_REPORT_YAML = _PROJECT_ROOT / "config_manager" / "report.yaml"
_MAX_BYTES = 1_000_000
_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


class ReportRegistrationService:
    def __init__(self, registry: Optional[ConfigRegistry] = None) -> None:
        self.registry = registry or ConfigRegistry()
        self.discovery = ReportDiscovery(self.registry)
        _UPLOADS.mkdir(parents=True, exist_ok=True)
        _BACKUPS.mkdir(parents=True, exist_ok=True)

    def stage_package_rel(self, stage_key: str) -> str:
        key = normalize_stage_key(stage_key)
        return STAGE_PATHS.get(key) or f"report_script/{key}"

    def list_stages_for_ui(self) -> List[Dict[str, Any]]:
        meta = self.registry.report_stages_meta()
        out = []
        for key, cfg in meta.items():
            nk = normalize_stage_key(key)
            out.append(
                {
                    "key": nk,
                    "label": cfg.get("label") or f"Stage: {nk}",
                    "order": cfg.get("order"),
                    "clients": cfg.get("clients"),
                    "package_path": self.stage_package_rel(nk),
                }
            )
        out.sort(key=lambda x: (int(x.get("order") or 999), x["key"]))
        return out

    def quarantine_upload(self, *, filename: str, content: bytes) -> Dict[str, Any]:
        err = validate_filename(filename)
        if err:
            raise ValueError(err)
        if len(content) > _MAX_BYTES:
            raise ValueError(f"File too large (max {_MAX_BYTES} bytes)")
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("Uploaded file must be UTF-8 text") from exc

        upload_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "_" + uuid.uuid4().hex[:8]
        dest_dir = _UPLOADS / upload_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / Path(filename).name
        dest.write_text(text, encoding="utf-8")

        analysis = analyze_source(text, filename=dest.name)
        suggested_code = dest.stem
        if suggested_code.endswith("_report"):
            suggested_code = suggested_code[: -len("_report")]
        suggested_code = re.sub(r"[^a-z0-9_]+", "_", suggested_code.lower()).strip("_") or "new_report"

        return {
            "upload_id": upload_id,
            "filename": dest.name,
            "bytes": len(content),
            "suggested_code": suggested_code,
            "suggested_label": suggested_code.replace("_", " ").title(),
            "analysis": analysis.to_dict(),
            "quarantine_path": str(dest.relative_to(_PROJECT_ROOT)),
        }

    def get_quarantine_file(self, upload_id: str) -> Path:
        safe = Path(upload_id).name
        folder = _UPLOADS / safe
        if not folder.is_dir():
            raise KeyError(f"Unknown upload: {upload_id}")
        pys = list(folder.glob("*.py"))
        if not pys:
            raise KeyError(f"No .py file in upload {upload_id}")
        return pys[0]

    def register(
        self,
        *,
        upload_id: str,
        code: str,
        label: str,
        stage: str,
        clients: Optional[Sequence[str]] = None,
        menu_order: Optional[int] = None,
        enabled: bool = True,
        output_subdir: Optional[str] = None,
        description: Optional[str] = None,
        create_stage: Optional[Dict[str, Any]] = None,
        overwrite: bool = False,
    ) -> Dict[str, Any]:
        code_l = code.strip().lower()
        if not _CODE_RE.match(code_l):
            raise ValueError("Report code must be lowercase snake_case (2–64 chars)")

        src = self.get_quarantine_file(upload_id)
        analysis = analyze_file(src)
        if not analysis.ok:
            raise ValueError("AST validation failed: " + "; ".join(analysis.errors))

        self.registry.refresh()
        existing = self.registry.all_reports()
        if code_l in existing and not overwrite:
            raise ValueError(f"Report code already registered: {code_l}")

        stage_key = normalize_stage_key(stage)
        package_rel = self.stage_package_rel(stage_key)
        package_dir = _PROJECT_ROOT / package_rel
        dest_file = package_dir / src.name
        module_path = f"{package_rel.replace('/', '.')}.{src.stem}"

        for other_code, meta in existing.items():
            if other_code == code_l and overwrite:
                continue
            if str(meta.get("module") or "") == module_path:
                raise ValueError(f"Module path already used by report '{other_code}': {module_path}")

        if dest_file.exists() and not overwrite:
            raise ValueError(f"Script already exists: {dest_file.relative_to(_PROJECT_ROOT)}")

        backup = self._backup_report_yaml()
        previous_script: Optional[bytes] = dest_file.read_bytes() if dest_file.exists() else None
        wrote_script = False
        created_init = False
        init_py = package_dir / "__init__.py"

        try:
            package_dir.mkdir(parents=True, exist_ok=True)
            if not init_py.exists():
                init_py.write_text('"""Report package."""\n', encoding="utf-8")
                created_init = True

            shutil.copy2(src, dest_file)
            wrote_script = True

            doc = self._load_report_yaml()
            if create_stage:
                self._apply_stage(doc, stage_key, create_stage)

            reports = doc.setdefault("reports", {})
            if not isinstance(reports, dict):
                raise ValueError("report.yaml reports section is invalid")

            entry: Dict[str, Any] = {
                "label": label.strip() or code_l,
                "stage": stage_key,
                "module": module_path,
                "menu_order": int(menu_order)
                if menu_order is not None
                else self._next_menu_order(stage_key),
                "enabled": bool(enabled),
            }
            if description:
                entry["description"] = description.strip()
            if output_subdir:
                entry["output_subdir"] = output_subdir.strip()
            if clients:
                entry["clients"] = [c.strip().upper() for c in clients]

            reports[code_l] = entry
            self._write_report_yaml(doc)
            self.registry.refresh()

            importlib.invalidate_caches()
            try:
                mod = importlib.import_module(module_path)
                if not callable(getattr(mod, "run", None)):
                    raise ValueError("Module imported but run() is missing")
            except Exception as exc:
                raise ValueError(f"Module import failed: {exc}") from exc

            return {
                "code": code_l,
                "module": module_path,
                "script_path": str(dest_file.relative_to(_PROJECT_ROOT)),
                "yaml_backup": str(backup.relative_to(_PROJECT_ROOT)),
                "enabled": bool(enabled),
                "importable": True,
                "entry": entry,
                "analysis": analysis.to_dict(),
            }
        except Exception:
            if wrote_script:
                if previous_script is None:
                    dest_file.unlink(missing_ok=True)
                else:
                    dest_file.write_bytes(previous_script)
            if created_init and init_py.exists() and init_py.stat().st_size < 80:
                # only remove if we created an empty package init and folder may be new
                try:
                    init_py.unlink(missing_ok=True)
                except OSError:
                    pass
            self._restore_report_yaml(backup)
            self.registry.refresh()
            raise

    def set_enabled(self, code: str, enabled: bool) -> Dict[str, Any]:
        code_l = code.strip().lower()
        backup = self._backup_report_yaml()
        try:
            doc = self._load_report_yaml()
            reports = doc.get("reports") or {}
            if code_l not in reports:
                raise KeyError(f"Unknown report: {code_l}")
            reports[code_l]["enabled"] = bool(enabled)
            self._write_report_yaml(doc)
            self.registry.refresh()
            return {"code": code_l, "enabled": bool(enabled)}
        except Exception:
            self._restore_report_yaml(backup)
            self.registry.refresh()
            raise

    def test_import(self, code: str) -> Dict[str, Any]:
        code_l = code.strip().lower()
        self.registry.refresh()
        meta = self.registry.all_reports().get(code_l)
        if meta is None:
            raise KeyError(f"Unknown report: {code_l}")
        module = str(meta.get("module") or "")
        path = self.discovery.module_file_path(module)
        ok = False
        error = None
        try:
            importlib.invalidate_caches()
            mod = importlib.import_module(module)
            ok = callable(getattr(mod, "run", None))
            if not ok:
                error = "Module imported but run() is missing"
        except Exception as exc:
            error = str(exc)
        return {
            "code": code_l,
            "module": module,
            "file_exists": path is not None,
            "import_ok": ok,
            "error": error,
        }

    def _apply_stage(self, doc: Dict[str, Any], stage_key: str, spec: Dict[str, Any]) -> None:
        stages = doc.setdefault("report_stages", {})
        existing_keys = {normalize_stage_key(k) for k in stages}
        if stage_key in existing_keys:
            return
        stages[stage_key] = {
            "label": spec.get("label") or f"Stage: {stage_key}",
            "order": int(spec.get("order") or 50),
        }
        if spec.get("clients"):
            stages[stage_key]["clients"] = [c.strip().upper() for c in spec["clients"]]

    def _next_menu_order(self, stage_key: str) -> int:
        orders = [
            int(m.get("menu_order") or 0)
            for m in self.registry.all_reports().values()
            if normalize_stage_key(m.get("stage", "")) == stage_key
        ]
        return (max(orders) + 1) if orders else 1

    def _backup_report_yaml(self) -> Path:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        dest = _BACKUPS / f"report.yaml.{stamp}"
        shutil.copy2(_REPORT_YAML, dest)
        return dest

    def _restore_report_yaml(self, backup: Path) -> None:
        if backup.is_file():
            shutil.copy2(backup, _REPORT_YAML)

    def _load_report_yaml(self) -> Dict[str, Any]:
        with _REPORT_YAML.open(encoding="utf-8") as f:
            doc = yaml.safe_load(f) or {}
        if not isinstance(doc, dict):
            raise ValueError("report.yaml root must be a mapping")
        return doc

    def _write_report_yaml(self, doc: Dict[str, Any]) -> None:
        header = (
            "# Report registry — maps CLI choices to scripts / output folders.\n"
            "# Updated by Inventory Ecosystem Portal (Phase 5 registration).\n"
            "# Interactive CLI: Clients → Geographies → Stage → Report(s within stage).\n\n"
        )
        with _REPORT_YAML.open("w", encoding="utf-8") as f:
            f.write(header)
            yaml.safe_dump(doc, f, sort_keys=False, allow_unicode=True)
