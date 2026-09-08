"""Configuration management over existing config_manager YAML (single source of truth)."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from dotenv import set_key

from backend.services import config_io
from backend.services.environment_service import EnvironmentService
from backend.services.run_service import run_service
from pipeline_engine.discovery import ReportDiscovery
from pipeline_engine.models import PipelineRunStatus
from pipeline_engine.registry import STAGE_PATHS, ConfigRegistry, normalize_stage_key, slugify_sequence_id
from pipeline_engine.validation import PipelineValidator

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ENV_PATH = _PROJECT_ROOT / ".env"
_CODE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,31}$")
_REPORT_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_ENV_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


class ConfigManagementService:
    def __init__(self) -> None:
        self.registry = ConfigRegistry()
        self.discovery = ReportDiscovery(self.registry)
        self.validator = PipelineValidator(self.registry)
        self.env = EnvironmentService(self.registry)

    def reload(self) -> str:
        self.registry.refresh()
        self.discovery = ReportDiscovery(self.registry)
        self.validator = PipelineValidator(self.registry)
        self.env = EnvironmentService(self.registry)
        _reload_other_services()
        return config_io.config_version()

    def version(self) -> str:
        return config_io.config_version()

    def pipeline_busy(self) -> Optional[str]:
        active = run_service.get_active()
        if active and active.status in (PipelineRunStatus.QUEUED, PipelineRunStatus.RUNNING):
            return active.run_id
        return None

    # ----- overview / validate -----

    def overview(self) -> Dict[str, Any]:
        self.registry.refresh()
        clients = self._raw_clients()
        geos_flat = self._flat_geographies()
        reports = self.registry.all_reports()
        stages = self.registry.report_stages_meta()
        sequences = self.registry.load_sequences()
        validation = self.validate_all()
        last_mod = None
        for name in config_io.EDITABLE_FILES:
            meta = config_io.file_meta(name)
            if last_mod is None or meta["modified"] > last_mod:
                last_mod = meta["modified"]
        return {
            "version": self.version(),
            "counts": {
                "clients_total": len(clients),
                "clients_active": sum(1 for c in clients.values() if c.get("enabled", True)),
                "geographies_total": len(geos_flat),
                "geographies_active": sum(1 for g in geos_flat if g.get("enabled", True)),
                "stages_total": len(stages),
                "reports_total": len(reports),
                "reports_enabled": sum(1 for r in reports.values() if r.get("enabled", True)),
                "reports_disabled": sum(1 for r in reports.values() if not r.get("enabled", True)),
                "sequences": len(sequences),
            },
            "health": validation,
            "last_modified": last_mod,
            "pipeline_busy": self.pipeline_busy(),
        }

    def validate_all(self) -> Dict[str, Any]:
        self.registry.refresh()
        checks: List[Dict[str, Any]] = []

        def add(name: str, ok: bool, level: str, message: str) -> None:
            checks.append({"name": name, "ok": ok, "level": level, "message": message})

        for fname in config_io.EDITABLE_FILES:
            try:
                config_io.load_yaml_file(fname)
                add(f"yaml:{fname}", True, "PASS", "Valid YAML")
            except Exception as exc:
                add(f"yaml:{fname}", False, "ERROR", str(exc))

        clients = self._raw_clients()
        add("clients", len(clients) > 0, "ERROR" if not clients else "PASS", f"{len(clients)} client(s)")

        geos = self._flat_geographies()
        add("geographies", len(geos) > 0, "WARNING" if not geos else "PASS", f"{len(geos)} geography row(s)")

        reports = self.registry.all_reports()
        stages = {normalize_stage_key(k) for k in self.registry.report_stages_meta()}
        for code, meta in reports.items():
            stage = normalize_stage_key(meta.get("stage", ""))
            if stage and stage not in stages and stage not in STAGE_PATHS:
                add(f"report:{code}:stage", False, "WARNING", f"Stage '{stage}' not in report_stages")
            module = str(meta.get("module") or "")
            if module:
                exists = self.discovery.module_file_path(module) is not None
                add(
                    f"report:{code}:module",
                    exists,
                    "WARNING" if not exists else "PASS",
                    module if exists else f"Missing module file: {module}",
                )
            scope = meta.get("clients") or []
            for c in scope:
                if str(c).upper() not in clients:
                    add(f"report:{code}:client", False, "WARNING", f"Unknown client {c}")
                elif not clients[str(c).upper()].get("enabled", True):
                    add(
                        f"report:{code}:client_disabled",
                        False,
                        "WARNING",
                        f"Report references disabled client {c}",
                    )

        sequences = self.registry.load_sequences()
        for sid, seq in sequences.items():
            if seq.get("enabled", True) is False:
                continue
            for c in seq.get("clients") or []:
                if str(c).upper() not in clients:
                    add(f"sequence:{sid}:client", False, "ERROR", f"Unknown client {c}")
            for r in seq.get("reports") or []:
                if r not in reports:
                    add(f"sequence:{sid}:report", False, "ERROR", f"Unknown report {r}")
                elif not reports[r].get("enabled", True):
                    add(
                        f"sequence:{sid}:report_disabled",
                        False,
                        "WARNING",
                        f"Sequence uses disabled report {r}",
                    )

        env = self.env.snapshot()
        add(
            "environment",
            env.get("ok", False),
            "ERROR" if not env.get("ok") else "PASS",
            "Required env keys set" if env.get("ok") else f"Missing: {env.get('required_missing')}",
        )

        hard = [c for c in checks if not c["ok"] and c["level"] == "ERROR"]
        warns = [c for c in checks if not c["ok"] and c["level"] == "WARNING"]
        return {
            "ok": len(hard) == 0,
            "errors": hard,
            "warnings": warns,
            "checks": checks,
        }

    # ----- clients -----

    def list_clients(self) -> List[Dict[str, Any]]:
        self.registry.refresh()
        reports = self.registry.all_reports()
        out = []
        for code, cfg in self._raw_clients().items():
            report_count = sum(
                1
                for meta in reports.values()
                if self.registry.matches_clients(meta, [code])
            )
            out.append(
                {
                    "code": code,
                    "name": cfg.get("name"),
                    "client_id": str(cfg.get("client_id", "")),
                    "enabled": bool(cfg.get("enabled", True)),
                    "data_root_env": cfg.get("data_root_env"),
                    "cogs_path_env": cfg.get("cogs_path_env"),
                    "package": cfg.get("package", ""),
                    "layout": cfg.get("layout", ""),
                    "geographies": [g.upper() for g in cfg.get("geographies", [])],
                    "report_count": report_count,
                }
            )
        return out

    def upsert_client(self, code: str, body: Dict[str, Any], *, create: bool) -> Dict[str, Any]:
        code_u = code.strip().upper()
        if not _CODE_RE.match(code_u):
            raise ValueError("Invalid client code")
        self._guard_busy("client.yaml")
        doc = config_io.load_yaml_file("client.yaml")
        clients = doc.setdefault("clients", {})
        if create and code_u in clients:
            raise ValueError(f"Client already exists: {code_u}")
        if not create and code_u not in clients:
            raise KeyError(f"Unknown client: {code_u}")

        entry = {
            "name": str(body.get("name") or code_u).strip(),
            "client_id": str(body.get("client_id") or "").strip(),
            "enabled": bool(body.get("enabled", True)),
            "data_root_env": str(body.get("data_root_env") or f"{code_u}_DATA_ROOT").strip(),
            "cogs_path_env": str(body.get("cogs_path_env") or f"{code_u}_COGS_PATH").strip(),
            "package": str(body.get("package") or "").strip(),
            "layout": str(body.get("layout") or "").strip(),
            "geographies": [str(g).upper() for g in (body.get("geographies") or [])],
        }
        if not entry["client_id"]:
            raise ValueError("client_id is required")
        if not _ENV_KEY_RE.match(entry["data_root_env"]) or not _ENV_KEY_RE.match(entry["cogs_path_env"]):
            raise ValueError("Env var names must be UPPER_SNAKE_CASE (no absolute paths in YAML)")

        before = config_io.read_raw("client.yaml")
        clients[code_u] = entry
        return self._commit(
            "client.yaml",
            doc,
            action="create_client" if create else "update_client",
            summary=f"{'Added' if create else 'Updated'} client {code_u}",
            before=before,
            header="# Client registry — paths come from .env via data_root_env / cogs_path_env\n",
        ) or self.get_client(code_u)

    def get_client(self, code: str) -> Dict[str, Any]:
        for row in self.list_clients():
            if row["code"] == code.upper():
                return row
        raise KeyError(f"Unknown client: {code}")

    def set_client_enabled(self, code: str, enabled: bool) -> Dict[str, Any]:
        row = self.get_client(code)
        row["enabled"] = enabled
        self.upsert_client(code, row, create=False)
        return self.get_client(code)

    # ----- geographies -----

    def list_geographies(self, client: Optional[str] = None) -> List[Dict[str, Any]]:
        rows = self._flat_geographies()
        if client:
            rows = [r for r in rows if r["client"] == client.upper()]
        return rows

    def upsert_geography(
        self, client: str, geo: str, body: Dict[str, Any], *, create: bool
    ) -> Dict[str, Any]:
        client_u = client.strip().upper()
        geo_u = geo.strip().upper()
        if not _CODE_RE.match(client_u) or not re.match(r"^[A-Z]{2}$", geo_u):
            raise ValueError("Invalid client or geography code (geo must be 2-letter)")
        clients = self._raw_clients()
        if client_u not in clients:
            raise KeyError(f"Unknown client: {client_u}")
        self._guard_busy("geography.yaml")
        doc = config_io.load_yaml_file("geography.yaml")
        geos = doc.setdefault("geographies", {})
        client_geos = geos.setdefault(client_u, {})
        if create and geo_u in client_geos:
            raise ValueError(f"Geography already exists: {client_u}/{geo_u}")
        if not create and geo_u not in client_geos:
            raise KeyError(f"Unknown geography: {client_u}/{geo_u}")

        entry = {
            "country_code": str(body.get("country_code") or geo_u).upper(),
            "cogs_sheet_name": str(body.get("cogs_sheet_name") or "").strip(),
            "country_currency": str(body.get("country_currency") or "").strip(),
            "orders_sales_channel": str(body.get("orders_sales_channel") or "").strip(),
            "enabled": bool(body.get("enabled", True)),
        }
        if not entry["cogs_sheet_name"] or not entry["country_currency"]:
            raise ValueError("cogs_sheet_name and country_currency are required")

        before = config_io.read_raw("geography.yaml")
        client_geos[geo_u] = entry
        # Keep client.yaml geography list in sync
        cl_doc = config_io.load_yaml_file("client.yaml")
        cl = cl_doc.setdefault("clients", {}).setdefault(client_u, {})
        glist = [g.upper() for g in cl.get("geographies", [])]
        if geo_u not in glist and entry["enabled"]:
            glist.append(geo_u)
            cl["geographies"] = glist
            config_io.atomic_write_yaml(
                "client.yaml",
                cl_doc,
                header="# Client registry — paths come from .env via data_root_env / cogs_path_env\n",
            )

        self._commit(
            "geography.yaml",
            doc,
            action="create_geography" if create else "update_geography",
            summary=f"{'Added' if create else 'Updated'} geography {client_u}/{geo_u}",
            before=before,
            header="# Per-client geography settings (COGS sheet, currency, Amazon sales channel)\n",
        )
        return next(g for g in self.list_geographies(client_u) if g["country_code"] == geo_u)

    # ----- reports (config only — no upload) -----

    def list_reports_config(self) -> List[Dict[str, Any]]:
        self.registry.refresh()
        out = []
        for item in self.discovery.discover_report_summaries():
            raw = self.registry.all_reports().get(item["code"], {})
            out.append(
                {
                    **item,
                    "description": raw.get("description"),
                    "menu_order": raw.get("menu_order"),
                    "output_subdir": raw.get("output_subdir"),
                    "validation_ok": bool(item.get("module_file_exists") and item.get("module_importable")),
                }
            )
        return out

    def update_report(self, code: str, body: Dict[str, Any]) -> Dict[str, Any]:
        code_l = code.strip().lower()
        if not _REPORT_RE.match(code_l):
            raise ValueError("Invalid report code")
        self._guard_busy("report.yaml")
        doc = config_io.load_yaml_file("report.yaml")
        reports = doc.setdefault("reports", {})
        if code_l not in reports:
            raise KeyError(f"Unknown report: {code_l}")

        stage = normalize_stage_key(body.get("stage") or reports[code_l].get("stage") or "common")
        known_stages = {normalize_stage_key(k) for k in (doc.get("report_stages") or {})}
        known_stages.update(STAGE_PATHS.keys())
        for meta in (doc.get("reports") or {}).values():
            if isinstance(meta, dict):
                known_stages.add(normalize_stage_key(meta.get("stage", "")))
        if stage not in known_stages:
            raise ValueError(f"Unknown stage: {stage}")

        module = str(body.get("module") or reports[code_l].get("module") or "").strip()
        if not module.startswith("report_script."):
            raise ValueError("module must start with report_script.")
        if self.discovery.module_file_path(module) is None:
            raise ValueError(f"Module file not found: {module}")

        clients = body.get("clients", reports[code_l].get("clients"))
        if clients is not None:
            known = set(self._raw_clients())
            for c in clients:
                if str(c).upper() not in known:
                    raise ValueError(f"Unknown client: {c}")

        entry = dict(reports[code_l])
        entry["label"] = str(body.get("label") or entry.get("label") or code_l)
        entry["stage"] = stage
        entry["module"] = module
        entry["enabled"] = bool(body.get("enabled", entry.get("enabled", True)))
        if body.get("menu_order") is not None:
            entry["menu_order"] = int(body["menu_order"])
        if "description" in body:
            if body["description"]:
                entry["description"] = str(body["description"])
            else:
                entry.pop("description", None)
        if "output_subdir" in body:
            if body["output_subdir"]:
                entry["output_subdir"] = str(body["output_subdir"]).strip()
            else:
                entry.pop("output_subdir", None)
        if clients is None or (isinstance(clients, list) and len(clients) == 0):
            entry.pop("clients", None)
        else:
            entry["clients"] = [str(c).upper() for c in clients]

        # Sequences warning info
        seq_refs = [
            sid
            for sid, seq in self.registry.load_sequences().items()
            if code_l in (seq.get("reports") or [])
        ]
        before = config_io.read_raw("report.yaml")
        reports[code_l] = entry
        self._commit(
            "report.yaml",
            doc,
            action="update_report",
            summary=f"Updated report {code_l}",
            before=before,
            header="# Report registry — maps CLI choices to scripts / output folders.\n",
        )
        result = next(r for r in self.list_reports_config() if r["code"] == code_l)
        result["sequence_refs"] = seq_refs
        return result

    def set_report_enabled(self, code: str, enabled: bool) -> Dict[str, Any]:
        row = next((r for r in self.list_reports_config() if r["code"] == code.lower()), None)
        if row is None:
            raise KeyError(f"Unknown report: {code}")
        return self.update_report(
            code,
            {
                "label": row["label"],
                "stage": row["stage"],
                "module": row["module"],
                "clients": row.get("clients"),
                "enabled": enabled,
                "menu_order": row.get("menu_order"),
                "output_subdir": row.get("output_subdir"),
                "description": row.get("description"),
            },
        )

    def report_sequence_refs(self, code: str) -> List[str]:
        code_l = code.strip().lower()
        return [
            sid
            for sid, seq in self.registry.load_sequences().items()
            if code_l in (seq.get("reports") or [])
        ]

    # ----- stages -----

    def list_stages_config(self) -> List[Dict[str, Any]]:
        self.registry.refresh()
        meta = self.registry.report_stages_meta()
        reports = self.registry.all_reports()
        out = []
        for key, cfg in meta.items():
            nk = normalize_stage_key(key)
            count = sum(
                1 for m in reports.values() if normalize_stage_key(m.get("stage", "")) == nk
            )
            pkg = self.registry.stage_package_path(nk)
            out.append(
                {
                    "key": nk,
                    "label": cfg.get("label") or f"Stage: {nk}",
                    "order": cfg.get("order"),
                    "clients": cfg.get("clients"),
                    "enabled": bool(cfg.get("enabled", True)),
                    "package_path": pkg,
                    "report_count": count,
                    "package_exists": bool(pkg and (_PROJECT_ROOT / pkg).is_dir()),
                }
            )
        out.sort(key=lambda x: (int(x.get("order") or 999), x["key"]))
        return out

    def upsert_stage(self, key: str, body: Dict[str, Any], *, create: bool) -> Dict[str, Any]:
        stage_key = normalize_stage_key(key)
        if not stage_key or not re.match(r"^[a-z][a-z0-9_]{1,63}$", stage_key):
            raise ValueError("Invalid stage key")
        self._guard_busy("report.yaml")
        doc = config_io.load_yaml_file("report.yaml")
        stages = doc.setdefault("report_stages", {})
        existing = {normalize_stage_key(k): k for k in stages}
        if create and stage_key in existing:
            raise ValueError(f"Stage already exists: {stage_key}")
        if not create and stage_key not in existing:
            raise KeyError(f"Unknown stage: {stage_key}")

        package = body.get("package_path") or STAGE_PATHS.get(stage_key) or f"report_script/{stage_key}"
        package = str(package).replace("\\", "/").strip().strip("/")
        if not package.startswith("report_script/"):
            raise ValueError("Stage package_path must be under report_script/")
        if ".." in package:
            raise ValueError("Unsafe package path")
        pkg_path = _PROJECT_ROOT / package
        if create:
            pkg_path.mkdir(parents=True, exist_ok=True)
            init = pkg_path / "__init__.py"
            if not init.exists():
                init.write_text('"""Report stage package."""\n', encoding="utf-8")
        elif not pkg_path.is_dir():
            raise ValueError(f"Package path does not exist: {package}")

        entry = {
            "label": str(body.get("label") or f"Stage: {stage_key}"),
            "order": int(body.get("order") or 50),
            "enabled": bool(body.get("enabled", True)),
        }
        if body.get("clients"):
            entry["clients"] = [str(c).upper() for c in body["clients"]]

        before = config_io.read_raw("report.yaml")
        # replace under normalized key
        if stage_key in existing and existing[stage_key] != stage_key:
            stages.pop(existing[stage_key], None)
        stages[stage_key] = entry
        self._commit(
            "report.yaml",
            doc,
            action="create_stage" if create else "update_stage",
            summary=f"{'Added' if create else 'Updated'} stage {stage_key}",
            before=before,
            header="# Report registry — maps CLI choices to scripts / output folders.\n",
        )
        return next(s for s in self.list_stages_config() if s["key"] == stage_key)

    # ----- sequences -----

    def list_sequences_config(self) -> List[Dict[str, Any]]:
        self.registry.refresh()
        out = []
        for sid, meta in sorted(self.registry.load_sequences().items()):
            out.append(
                {
                    "id": sid,
                    "label": meta.get("label") or sid,
                    "clients": meta.get("clients") or [],
                    "geos": meta.get("geos") or [],
                    "reports": meta.get("reports") or [],
                    "enabled": bool(meta.get("enabled", True)),
                }
            )
        return out

    def validate_sequence_payload(self, body: Dict[str, Any]) -> List[str]:
        errors: List[str] = []
        clients = [str(c).upper() for c in (body.get("clients") or [])]
        geos = [str(g).upper() for g in (body.get("geos") or [])]
        raw_reports = [str(r).strip() for r in (body.get("reports") or []) if str(r).strip()]
        if not body.get("label") and not body.get("id"):
            errors.append("Sequence name/label is required")
        if not clients:
            errors.append("At least one client is required")
        if not geos:
            errors.append("At least one geography is required")
        if not raw_reports:
            errors.append("At least one report is required")

        reports: List[str] = []
        for r in raw_reports:
            key = self.registry.resolve_report_code(r)
            if key is None:
                errors.append(f'Report "{r}" does not exist')
            else:
                reports.append(key)
        if len(reports) != len(set(reports)):
            errors.append("Duplicate reports in sequence")

        known_clients = self._raw_clients()
        all_reports = self.registry.all_reports()
        for c in clients:
            if c not in known_clients:
                errors.append(f'Client "{c}" does not exist')
            else:
                allowed = {g.upper() for g in known_clients[c].get("geographies", [])}
                # also check geography.yaml enabled
                geo_rows = {g["country_code"]: g for g in self.list_geographies(c)}
                for g in geos:
                    if g not in allowed and g not in geo_rows:
                        errors.append(f'Geography "{g}" is not configured for client "{c}"')
                    elif g in geo_rows and not geo_rows[g].get("enabled", True):
                        errors.append(f'Geography "{g}" is disabled for client "{c}"')
        for r in reports:
            meta = all_reports[r]
            if not meta.get("enabled", True):
                errors.append(f'Report "{r}" is disabled')
            if clients and not self.registry.matches_clients(meta, clients):
                errors.append(f'Report "{r}" is not available for selected clients')
        return errors

    def upsert_sequence(self, seq_id: str, body: Dict[str, Any], *, create: bool) -> Dict[str, Any]:
        sid = slugify_sequence_id(seq_id or body.get("label") or "sequence")
        errors = self.validate_sequence_payload(body)
        if errors:
            raise ValueError("; ".join(errors))
        self._guard_busy("run_sequences.yaml")
        sequences = self.registry.load_sequences()
        if create and sid in sequences:
            raise ValueError(f"Sequence already exists: {sid}")
        if not create and sid not in sequences:
            raise KeyError(f"Unknown sequence: {sid}")

        canonical_reports: List[str] = []
        for r in body.get("reports") or []:
            key = self.registry.resolve_report_code(str(r))
            if key and key not in canonical_reports:
                canonical_reports.append(key)

        entry = {
            "label": str(body.get("label") or sid),
            "clients": [str(c).upper() for c in body.get("clients") or []],
            "geos": [str(g).upper() for g in body.get("geos") or []],
            "reports": canonical_reports,
            "enabled": bool(body.get("enabled", True)),
        }
        before = config_io.read_raw("run_sequences.yaml") if (_PROJECT_ROOT / "config_manager" / "run_sequences.yaml").exists() else ""
        sequences[sid] = entry
        backup = config_io.backup_file("run_sequences.yaml") if before else None
        self.registry.save_sequences(sequences)
        after = config_io.read_raw("run_sequences.yaml")
        config_io.append_history(
            file="run_sequences.yaml",
            action="create_sequence" if create else "update_sequence",
            summary=f"{'Added' if create else 'Updated'} sequence {sid}",
            backup=str(backup.name) if backup else None,
            diff=config_io.simple_diff(before, after) if before else None,
        )
        self.reload()
        return next(s for s in self.list_sequences_config() if s["id"] == sid)

    def delete_sequence(self, seq_id: str) -> Dict[str, Any]:
        sid = slugify_sequence_id(seq_id)
        self._guard_busy("run_sequences.yaml")
        sequences = self.registry.load_sequences()
        if sid not in sequences:
            raise KeyError(f"Unknown sequence: {sid}")
        before = config_io.read_raw("run_sequences.yaml")
        backup = config_io.backup_file("run_sequences.yaml")
        del sequences[sid]
        self.registry.save_sequences(sequences)
        after = config_io.read_raw("run_sequences.yaml")
        config_io.append_history(
            file="run_sequences.yaml",
            action="delete_sequence",
            summary=f"Deleted sequence {sid}",
            backup=str(backup.name),
            diff=config_io.simple_diff(before, after),
        )
        self.reload()
        return {"id": sid, "deleted": True}

    def duplicate_sequence(self, seq_id: str, new_id: Optional[str] = None) -> Dict[str, Any]:
        src = next((s for s in self.list_sequences_config() if s["id"] == seq_id), None)
        if src is None:
            raise KeyError(f"Unknown sequence: {seq_id}")
        nid = slugify_sequence_id(new_id or f"{src['id']}_copy")
        return self.upsert_sequence(
            nid,
            {
                "label": f"{src['label']} (copy)",
                "clients": src["clients"],
                "geos": src["geos"],
                "reports": src["reports"],
                "enabled": src.get("enabled", True),
            },
            create=True,
        )

    # ----- files / history -----

    def list_files(self) -> List[Dict[str, Any]]:
        return [config_io.file_meta(n) for n in sorted(config_io.EDITABLE_FILES)]

    def get_file(self, name: str) -> Dict[str, Any]:
        meta = config_io.file_meta(name)
        meta["content"] = config_io.read_raw(name)
        return meta

    def save_file(self, name: str, content: str) -> Dict[str, Any]:
        self._guard_busy(name)
        try:
            data = config_io.parse_yaml_text(content)
        except Exception as exc:
            raise ValueError(f"YAML parse error: {exc}") from exc
        # light schema checks
        if name == "client.yaml" and "clients" not in data:
            raise ValueError("client.yaml must contain 'clients'")
        if name == "geography.yaml" and "geographies" not in data:
            raise ValueError("geography.yaml must contain 'geographies'")
        if name == "report.yaml" and "reports" not in data:
            raise ValueError("report.yaml must contain 'reports'")
        if name == "run_sequences.yaml" and "sequences" not in data:
            raise ValueError("run_sequences.yaml must contain 'sequences'")

        before = config_io.read_raw(name)
        backup = config_io.backup_file(name)
        config_io.atomic_write_text(name, content if content.endswith("\n") else content + "\n")
        # reload + revalidate
        self.reload()
        validation = self.validate_all()
        if not validation["ok"]:
            # rollback
            Path(_PROJECT_ROOT / "config_manager" / name).write_text(before, encoding="utf-8")
            self.reload()
            msgs = [e["message"] for e in validation["errors"][:8]]
            raise ValueError("Validation failed after save — restored previous file. " + "; ".join(msgs))

        after = config_io.read_raw(name)
        entry = config_io.append_history(
            file=name,
            action="save_file",
            summary=f"Saved {name}",
            backup=str(backup.name),
            diff=config_io.simple_diff(before, after),
        )
        return {"file": config_io.file_meta(name), "history_id": entry["id"], "version": self.version()}

    def history(self, limit: int = 100) -> List[Dict[str, Any]]:
        return config_io.list_history(limit=limit)

    def history_entry(self, entry_id: str) -> Dict[str, Any]:
        row = config_io.get_history(entry_id)
        if row is None:
            raise KeyError(entry_id)
        return row

    def restore_history(self, entry_id: str) -> Dict[str, Any]:
        row = self.history_entry(entry_id)
        backup_name = row.get("backup")
        if not backup_name:
            raise ValueError("No backup attached to this history entry")
        backup_path = _PROJECT_ROOT / "runtime" / "config_backups" / Path(backup_name).name
        if not backup_path.is_file():
            raise FileNotFoundError(str(backup_path))
        name = row["file"]
        self._guard_busy(name)
        before = config_io.read_raw(name)
        safety = config_io.backup_file(name)
        text = backup_path.read_text(encoding="utf-8")
        config_io.atomic_write_text(name, text)
        self.reload()
        validation = self.validate_all()
        if not validation["ok"]:
            Path(_PROJECT_ROOT / "config_manager" / name).write_text(before, encoding="utf-8")
            self.reload()
            raise ValueError("Restore failed validation — previous file restored")
        after = config_io.read_raw(name)
        entry = config_io.append_history(
            file=name,
            action="restore",
            summary=f"Restored {name} from {backup_name}",
            backup=str(safety.name),
            diff=config_io.simple_diff(before, after),
        )
        return {"restored": name, "history_id": entry["id"], "version": self.version()}

    # ----- environment (.env local only) -----

    def environment_status(self) -> Dict[str, Any]:
        snap = self.env.snapshot()
        # classify
        for var in snap.get("variables", []):
            if var.get("secret"):
                var["category_ui"] = "secret"
            elif var.get("path_like"):
                key = var["key"]
                var["category_ui"] = "file" if key.endswith("_PATH") else "path"
            else:
                var["category_ui"] = "configuration"
        snap["dotenv_found"] = _ENV_PATH.is_file()
        snap["python_ok"] = True
        snap["repo_ok"] = _PROJECT_ROOT.is_dir()
        snap["version"] = self.version()
        # never include values
        return snap

    def update_env_path(self, key: str, value: str) -> Dict[str, Any]:
        key = key.strip()
        if not _ENV_KEY_RE.match(key):
            raise ValueError("Invalid env key")
        # refuse secrets
        if re.search(r"(PASSWORD|SECRET|TOKEN|CONNECTION_STRING|ACCOUNT_KEY|_KEY$)", key, re.I):
            raise ValueError("Secret keys cannot be set via this API")
        if not (key.endswith("_ROOT") or key.endswith("_PATH") or key.endswith("_DIR") or key in {"INVENTORY_BASE", "SANITY_DATA_ROOT", "PINCODE_DATA_DIR"}):
            raise ValueError("Only path-like keys can be updated from the UI")
        value = value.strip().strip('"').strip("'")
        if not value:
            raise ValueError("Path value required")
        path = Path(value)
        accessible = path.exists()
        _ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
        if not _ENV_PATH.exists():
            _ENV_PATH.write_text("", encoding="utf-8")
        set_key(str(_ENV_PATH), key, value, quote_mode="auto")
        # reload dotenv for this process
        from dotenv import load_dotenv

        load_dotenv(_ENV_PATH, override=True)
        self.reload()
        return {
            "key": key,
            "set": True,
            "accessible": accessible,
            "path_exists": accessible,
            # do not echo absolute path to callers that might sync remotely — local UI may show from form
        }

    # ----- internals -----

    def _raw_clients(self) -> Dict[str, Dict[str, Any]]:
        doc = config_io.load_yaml_file("client.yaml")
        raw = doc.get("clients") or {}
        return {str(k).upper(): dict(v) for k, v in raw.items() if isinstance(v, dict)}

    def _flat_geographies(self) -> List[Dict[str, Any]]:
        doc = config_io.load_yaml_file("geography.yaml")
        raw = doc.get("geographies") or {}
        rows = []
        for client, geos in raw.items():
            if not isinstance(geos, dict):
                continue
            for code, cfg in geos.items():
                if not isinstance(cfg, dict):
                    continue
                rows.append(
                    {
                        "client": str(client).upper(),
                        "country_code": str(cfg.get("country_code") or code).upper(),
                        "cogs_sheet_name": cfg.get("cogs_sheet_name"),
                        "country_currency": cfg.get("country_currency"),
                        "orders_sales_channel": cfg.get("orders_sales_channel"),
                        "enabled": bool(cfg.get("enabled", True)),
                    }
                )
        rows.sort(key=lambda r: (r["client"], r["country_code"]))
        return rows

    def _guard_busy(self, file: str) -> None:
        busy = self.pipeline_busy()
        if busy and file in {"report.yaml", "run_sequences.yaml", "client.yaml", "geography.yaml"}:
            # warn-level: allow but callers can surface; we only block report.yaml mid-run if desired
            # Spec: show warning — implement soft warn via exception subclass optional.
            # Soft allow with flag stored on thread? Simpler: raise RuntimeError with code PIPELINE_BUSY_WARN
            # For safety on report.yaml during active run, raise.
            if file == "report.yaml":
                raise RuntimeError(
                    f"Pipeline run {busy} is active. Changing report.yaml may cause inconsistent execution."
                )

    def _commit(
        self,
        name: str,
        doc: Dict[str, Any],
        *,
        action: str,
        summary: str,
        before: str,
        header: str = "",
    ) -> None:
        backup = config_io.backup_file(name)
        config_io.atomic_write_yaml(name, doc, header=header)
        self.reload()
        validation = self.validate_all()
        # Only hard-fail rollback on ERROR (not warnings)
        if validation["errors"]:
            Path(_PROJECT_ROOT / "config_manager" / name).write_text(before, encoding="utf-8")
            self.reload()
            raise ValueError(
                "Validation failed — changes rolled back. "
                + "; ".join(e["message"] for e in validation["errors"][:6])
            )
        after = config_io.read_raw(name)
        config_io.append_history(
            file=name,
            action=action,
            summary=summary,
            backup=str(backup.name),
            diff=config_io.simple_diff(before, after),
        )


def _reload_other_services() -> None:
    """Refresh in-process config facades used by other API routers."""
    import importlib

    for mod_name in (
        "backend.api.clients",
        "backend.api.geographies",
        "backend.api.reports",
        "backend.api.stages",
        "backend.api.sequences",
        "backend.api.registry",
        "backend.api.system",
        "backend.api.explore",
        "backend.services.run_service",
    ):
        try:
            mod = importlib.import_module(mod_name)
        except Exception:
            continue
        for attr in ("_service", "_diagnostics", "_environment", "_validation", "run_service"):
            svc = getattr(mod, attr, None)
            if svc is None:
                continue
            if hasattr(svc, "refresh"):
                try:
                    svc.refresh()
                except Exception:
                    pass
            if hasattr(svc, "registry") and hasattr(svc.registry, "refresh"):
                try:
                    svc.registry.refresh()
                except Exception:
                    pass
            if hasattr(svc, "run_manager"):
                pass
            if hasattr(svc, "validator") and hasattr(svc.validator, "registry"):
                try:
                    svc.validator.registry.refresh()
                except Exception:
                    pass


config_management = ConfigManagementService()
