"""Safe YAML read/write with backups, history, and atomic replace."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_DIR = _PROJECT_ROOT / "config_manager"
_BACKUP_DIR = _PROJECT_ROOT / "runtime" / "config_backups"
_HISTORY_PATH = _BACKUP_DIR / "history.jsonl"

EDITABLE_FILES = {
    "client.yaml",
    "geography.yaml",
    "report.yaml",
    "run_sequences.yaml",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def config_version() -> str:
    h = hashlib.sha256()
    for name in sorted(EDITABLE_FILES):
        path = _CONFIG_DIR / name
        if path.is_file():
            h.update(path.read_bytes())
    return h.hexdigest()[:12]


def load_yaml_file(name: str) -> Dict[str, Any]:
    if name not in EDITABLE_FILES:
        raise ValueError(f"File not editable: {name}")
    path = _CONFIG_DIR / name
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{name} root must be a mapping")
    return data


def dump_yaml(data: Dict[str, Any]) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def parse_yaml_text(text: str) -> Dict[str, Any]:
    data = yaml.safe_load(text)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError("YAML root must be a mapping")
    return data


def backup_file(name: str) -> Path:
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    src = _CONFIG_DIR / name
    if not src.is_file():
        raise FileNotFoundError(name)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = _BACKUP_DIR / f"{name}.{stamp}"
    dest.write_bytes(src.read_bytes())
    return dest


def append_history(
    *,
    file: str,
    action: str,
    summary: str,
    backup: Optional[str] = None,
    user: str = "local",
    diff: Optional[str] = None,
) -> Dict[str, Any]:
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "id": datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + f"_{file.replace('.', '_')}",
        "timestamp": utc_now(),
        "user": user,
        "file": file,
        "action": action,
        "summary": summary,
        "backup": backup,
        "diff": diff,
        "version_after": config_version(),
    }
    with _HISTORY_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def list_history(limit: int = 100) -> List[Dict[str, Any]]:
    if not _HISTORY_PATH.is_file():
        return []
    rows: List[Dict[str, Any]] = []
    with _HISTORY_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    rows.reverse()
    return rows[:limit]


def get_history(entry_id: str) -> Optional[Dict[str, Any]]:
    for row in list_history(limit=500):
        if row.get("id") == entry_id:
            return row
    return None


def atomic_write_yaml(name: str, data: Dict[str, Any], *, header: str = "") -> None:
    if name not in EDITABLE_FILES:
        raise ValueError(f"File not editable: {name}")
    path = _CONFIG_DIR / name
    text = (header + dump_yaml(data)) if header else dump_yaml(data)
    # Validate round-trip before replace
    parse_yaml_text(text)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{name}.", suffix=".tmp", dir=str(_CONFIG_DIR))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


def atomic_write_text(name: str, text: str) -> None:
    parse_yaml_text(text)  # must be valid YAML mapping
    atomic_write_yaml(name, parse_yaml_text(text))


def simple_diff(before: str, after: str) -> str:
    import difflib

    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile="before",
            tofile="after",
        )
    )


def read_raw(name: str) -> str:
    if name not in EDITABLE_FILES:
        raise ValueError(f"File not editable: {name}")
    return (_CONFIG_DIR / name).read_text(encoding="utf-8")


def file_meta(name: str) -> Dict[str, Any]:
    path = _CONFIG_DIR / name
    st = path.stat()
    valid = True
    error = None
    try:
        load_yaml_file(name)
    except Exception as exc:
        valid = False
        error = str(exc)
    return {
        "name": name,
        "path": str(path),
        "size_bytes": st.st_size,
        "modified": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
        "valid": valid,
        "error": error,
    }
