"""Filesystem explorers for sanity_data outputs, report logs, COGS, and pincode."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from config_manager import paths as path_mod
from pipeline_engine.registry import ConfigRegistry

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SAFE_SEG = re.compile(r"^[A-Za-z0-9._\-]+$")
_TEXT_EXT = {".log", ".txt", ".csv", ".json", ".md", ".yaml", ".yml"}
_TABLE_EXT = {".parquet", ".csv"}


class ExploreService:
    def __init__(self, registry: Optional[ConfigRegistry] = None) -> None:
        self.registry = registry or ConfigRegistry()

    # ----- roots -----

    def sanity_root(self) -> Path:
        return path_mod.sanity_data_root()

    def cogs_root(self) -> Path:
        return _PROJECT_ROOT / "cogs"

    def pincode_root(self) -> Path:
        try:
            return path_mod.pincode_data_dir()
        except Exception:
            return _PROJECT_ROOT / "pincode"

    def allowed_roots(self) -> Dict[str, Path]:
        return {
            "sanity": self.sanity_root(),
            "cogs": self.cogs_root(),
            "pincode": self.pincode_root(),
            "runtime_runs": _PROJECT_ROOT / "runtime" / "runs",
        }

    def resolve_rel(self, root_key: str, rel: str) -> Path:
        roots = self.allowed_roots()
        if root_key not in roots:
            raise ValueError(f"Unknown root: {root_key}")
        base = roots[root_key].resolve()
        parts = [p for p in Path(rel.replace("\\", "/")).parts if p not in ("", ".")]
        for part in parts:
            if part == ".." or not _SAFE_SEG.match(part):
                raise ValueError(f"Unsafe path segment: {part}")
        target = (base.joinpath(*parts)).resolve()
        if base != target and base not in target.parents:
            raise ValueError("Path escapes allowed root")
        return target

    # ----- outputs -----

    def list_output_clients(self) -> List[Dict[str, Any]]:
        root = self.sanity_root()
        clients_cfg = self.registry.clients(include_disabled=True)
        out: List[Dict[str, Any]] = []
        for code, cfg in clients_cfg.items():
            client_dir = root / code.upper()
            out.append(
                {
                    "code": code.upper(),
                    "name": cfg.name,
                    "path": str(client_dir),
                    "exists": client_dir.is_dir(),
                    "report_dirs": self._dir_names(client_dir) if client_dir.is_dir() else [],
                }
            )
        # Include orphan dirs under sanity_data not in yaml
        if root.is_dir():
            known = {c["code"] for c in out}
            for child in sorted(root.iterdir()):
                if child.is_dir() and child.name.upper() not in known and child.name.lower() != "item_master":
                    out.append(
                        {
                            "code": child.name.upper(),
                            "name": child.name,
                            "path": str(child),
                            "exists": True,
                            "report_dirs": self._dir_names(child),
                        }
                    )
        return out

    def list_report_outputs(
        self,
        *,
        client: Optional[str] = None,
        report: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """One row per report output folder with path link + file count."""
        reports = self.registry.all_reports()
        clients = [client.upper()] if client else [c.code for c in self.registry.clients(include_disabled=True).values()]
        rows: List[Dict[str, Any]] = []
        root = self.sanity_root()

        for code, meta in reports.items():
            if report and code != report.strip().lower():
                continue
            sub = meta.get("output_subdir")
            if not sub:
                continue
            for cli in clients:
                if not self.registry.matches_clients(meta, [cli]):
                    continue
                folder = root / cli.upper() / str(sub)
                files = self._list_files(folder, limit=200) if folder.is_dir() else []
                rows.append(
                    {
                        "client": cli.upper(),
                        "report": code,
                        "label": meta.get("label", code),
                        "output_subdir": sub,
                        "path": str(folder),
                        "rel": f"{cli.upper()}/{sub}",
                        "root": "sanity",
                        "exists": folder.is_dir(),
                        "file_count": len(files),
                        "files": files[:50],
                        "latest_modified": files[0]["modified"] if files else None,
                    }
                )
        rows.sort(key=lambda r: (r["client"], r["report"]))
        return rows

    def list_directory(self, root_key: str, rel: str = "") -> Dict[str, Any]:
        path = self.resolve_rel(root_key, rel) if rel else self.allowed_roots()[root_key].resolve()
        if not path.exists():
            return {
                "root": root_key,
                "rel": rel,
                "path": str(path),
                "exists": False,
                "directories": [],
                "files": [],
            }
        if not path.is_dir():
            raise ValueError("Not a directory")
        dirs = []
        files = []
        for child in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if not _SAFE_SEG.match(child.name):
                continue
            child_rel = "/".join(p for p in Path(rel).parts if p) 
            child_rel = f"{child_rel}/{child.name}".strip("/") if child_rel else child.name
            if child.is_dir():
                dirs.append({"name": child.name, "rel": child_rel, "path": str(child)})
            elif child.is_file():
                files.append(self._file_meta(child, child_rel))
        return {
            "root": root_key,
            "rel": rel,
            "path": str(path),
            "exists": True,
            "directories": dirs,
            "files": files,
        }

    # ----- logs (client + report scoped) -----

    def list_log_index(self, client: Optional[str] = None) -> List[Dict[str, Any]]:
        """sanity_data/{CLIENT}/logs/{report}/ — report-wise, client-specific."""
        root = self.sanity_root()
        clients = (
            [client.upper()]
            if client
            else [c.code for c in self.registry.clients(include_disabled=True).values()]
        )
        rows: List[Dict[str, Any]] = []
        for cli in clients:
            logs_root = root / cli / "logs"
            if not logs_root.is_dir():
                rows.append(
                    {
                        "client": cli,
                        "path": str(logs_root),
                        "exists": False,
                        "reports": [],
                    }
                )
                continue
            reports = []
            for child in sorted(logs_root.iterdir()):
                if not child.is_dir() or not _SAFE_SEG.match(child.name):
                    continue
                if child.name == "new_skus_vs_cogs":
                    # nested special folder
                    nested = []
                    for sub in sorted(child.iterdir()):
                        if sub.is_dir() and _SAFE_SEG.match(sub.name):
                            nested.append(self._log_report_entry(cli, f"new_skus_vs_cogs/{sub.name}", sub))
                    reports.extend(nested)
                    continue
                reports.append(self._log_report_entry(cli, child.name, child))
            rows.append(
                {
                    "client": cli,
                    "path": str(logs_root),
                    "exists": True,
                    "reports": reports,
                }
            )
        return rows

    def _log_report_entry(self, client: str, report_key: str, folder: Path) -> Dict[str, Any]:
        files = self._list_files(folder, limit=100, extensions={".log", ".txt", ".csv"})
        latest = next((f for f in files if f["name"] == "latest.log"), files[0] if files else None)
        return {
            "client": client,
            "report": report_key,
            "path": str(folder),
            "rel": f"{client}/logs/{report_key}",
            "root": "sanity",
            "file_count": len(files),
            "files": files,
            "latest": latest,
        }

    def read_log_text(
        self,
        *,
        client: str,
        report: str,
        filename: str = "latest.log",
        max_bytes: int = 512_000,
    ) -> Dict[str, Any]:
        safe_report = report.strip().replace("\\", "/").strip("/")
        for part in Path(safe_report).parts:
            if part == ".." or not _SAFE_SEG.match(part):
                raise ValueError("Invalid report path")
        if not _SAFE_SEG.match(filename) or "/" in filename or "\\" in filename:
            raise ValueError("Invalid filename")
        rel = f"{client.upper()}/logs/{safe_report}/{filename}"
        path = self.resolve_rel("sanity", rel)
        if not path.is_file():
            raise FileNotFoundError(str(path))
        size = path.stat().st_size
        raw = path.read_bytes()[:max_bytes]
        truncated = size > max_bytes
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("utf-8", errors="replace")
        return {
            "client": client.upper(),
            "report": safe_report,
            "filename": filename,
            "path": str(path),
            "rel": rel,
            "root": "sanity",
            "size_bytes": size,
            "truncated": truncated,
            "text": text,
        }

    # ----- file meta / preview -----

    def file_info(self, root_key: str, rel: str) -> Dict[str, Any]:
        path = self.resolve_rel(root_key, rel)
        if not path.is_file():
            raise FileNotFoundError(str(path))
        meta = self._file_meta(path, rel)
        meta["root"] = root_key
        meta["path"] = str(path)
        return meta

    def preview_file(self, root_key: str, rel: str, *, rows: int = 20) -> Dict[str, Any]:
        path = self.resolve_rel(root_key, rel)
        if not path.is_file():
            raise FileNotFoundError(str(path))
        meta = self._file_meta(path, rel)
        ext = path.suffix.lower()
        preview: Dict[str, Any] = {"columns": [], "rows": [], "note": None}
        if ext == ".parquet":
            try:
                import pyarrow.parquet as pq

                table = pq.read_table(path)
                preview["row_count"] = table.num_rows
                preview["columns"] = table.column_names
                head = table.slice(0, min(rows, table.num_rows)).to_pydict()
                # convert to list of row dicts
                keys = list(head.keys())
                n = len(next(iter(head.values()), []))
                preview["rows"] = [
                    {k: _jsonable(head[k][i]) for k in keys} for i in range(n)
                ]
            except Exception as exc:
                preview["note"] = f"Parquet preview unavailable: {exc}"
        elif ext == ".csv":
            try:
                import csv

                with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
                    reader = csv.DictReader(f)
                    preview["columns"] = list(reader.fieldnames or [])
                    for i, row in enumerate(reader):
                        if i >= rows:
                            break
                        preview["rows"].append(dict(row))
            except Exception as exc:
                preview["note"] = f"CSV preview unavailable: {exc}"
        elif ext in _TEXT_EXT:
            raw = path.read_text(encoding="utf-8", errors="replace")[:80_000]
            preview["note"] = "text"
            preview["text"] = raw
        else:
            preview["note"] = f"No preview for {ext or 'unknown'} files — use Download"
        return {"file": meta, "root": root_key, "rel": rel, "path": str(path), "preview": preview}

    def list_cogs(self, client: Optional[str] = None) -> Dict[str, Any]:
        root = self.cogs_root()
        rel = client.lower() if client else ""
        if client:
            return self.list_directory("cogs", client.lower())
        return {
            "root": "cogs",
            "path": str(root),
            "exists": root.is_dir(),
            "clients": self._dir_names(root) if root.is_dir() else [],
            "listing": self.list_directory("cogs", ""),
        }

    def list_pincode(self) -> Dict[str, Any]:
        return self.list_directory("pincode", "")

    # ----- helpers -----

    def _dir_names(self, path: Path) -> List[str]:
        if not path.is_dir():
            return []
        return sorted(
            p.name for p in path.iterdir() if p.is_dir() and _SAFE_SEG.match(p.name)
        )

    def _list_files(
        self,
        folder: Path,
        *,
        limit: int = 200,
        extensions: Optional[set] = None,
    ) -> List[Dict[str, Any]]:
        if not folder.is_dir():
            return []
        files = []
        for child in folder.iterdir():
            if not child.is_file() or not _SAFE_SEG.match(child.name):
                continue
            if extensions and child.suffix.lower() not in extensions:
                continue
            files.append(self._file_meta(child, child.name))
        files.sort(key=lambda f: f.get("modified") or "", reverse=True)
        return files[:limit]

    def _file_meta(self, path: Path, rel: str) -> Dict[str, Any]:
        st = path.stat()
        modified = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat()
        geo = None
        name = path.name
        # Heuristic: US_manage_fba_inventory.parquet
        m = re.match(r"^([A-Z]{2})_", name)
        if m:
            geo = m.group(1)
        return {
            "name": name,
            "rel": rel.replace("\\", "/"),
            "ext": path.suffix.lower(),
            "size_bytes": st.st_size,
            "modified": modified,
            "geo": geo,
            "kind": _kind_for(path.suffix.lower()),
        }


def _kind_for(ext: str) -> str:
    if ext == ".parquet":
        return "parquet"
    if ext == ".csv":
        return "csv"
    if ext in {".log", ".txt"}:
        return "log"
    if ext in {".xlsx", ".xls"}:
        return "excel"
    return "file"


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)
