"""Load and query YAML configuration (clients, geos, reports, sequences)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import yaml

from config_manager.loader import (
    ClientConfig,
    GeographyConfig,
    get_client,
    load_clients,
    load_geographies,
    load_reports,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
SEQUENCES_PATH = _PROJECT_ROOT / "config_manager" / "run_sequences.yaml"

GEO_OPTIONS: List[Tuple[str, str]] = [
    ("US", "US"),
    ("CA", "CA"),
    ("DE", "DE"),
    ("UK", "UK"),
    ("IN", "IN"),
    ("AE", "AE"),
]

STAGE_PATHS: Dict[str, str] = {
    "common": "report_script/common_sanity_report",
    "helper_files_nd_saving": "report_script/helper_files_nd_saving",
    "retail": "report_script/retail",
    "finance": "report_script/finance",
    "requirement_specific": "report_script/requirement_specific",
    "want_to_update": "report_script/want_to_update",
    "utility_codes": "report_script/utility_codes",
    "atros": "report_script/atros_code",
    "item_master": "report_script/item_master",
}


def normalize_stage_key(stage: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(stage).strip().lower()).strip("_")


def slugify_sequence_id(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    return slug or "sequence"


class ConfigRegistry:
    """Read-only façade over config_manager YAML + sequences."""

    def __init__(self) -> None:
        self._reports_raw: Dict[str, Any] = {}
        self.refresh()

    def refresh(self) -> None:
        self._reports_raw = load_reports()

    def clients(self, *, include_disabled: bool = False) -> Dict[str, ClientConfig]:
        if not include_disabled:
            return load_clients()
        path = _PROJECT_ROOT / "config_manager" / "client.yaml"
        with path.open(encoding="utf-8") as f:
            raw_doc = yaml.safe_load(f) or {}
        raw = raw_doc.get("clients", {})
        out: Dict[str, ClientConfig] = {}
        for code, cfg in raw.items():
            out[code.upper()] = ClientConfig(
                code=code.upper(),
                name=cfg["name"],
                client_id=str(cfg["client_id"]),
                enabled=bool(cfg.get("enabled", True)),
                data_root_env=cfg["data_root_env"],
                cogs_path_env=cfg["cogs_path_env"],
                package=cfg.get("package", ""),
                layout=cfg.get("layout", ""),
                geographies=[g.upper() for g in cfg.get("geographies", [])],
            )
        return out

    def get_client(self, code: str) -> ClientConfig:
        return get_client(code)

    def geographies(self, client: str) -> Dict[str, GeographyConfig]:
        return load_geographies(client)

    def all_geo_codes(self) -> List[str]:
        return [code for code, _ in GEO_OPTIONS]

    def reports_config(self) -> Dict[str, Any]:
        return self._reports_raw

    def report_stages_meta(self) -> Dict[str, dict]:
        return dict(self._reports_raw.get("report_stages") or {})

    def all_reports(self) -> Dict[str, dict]:
        return dict(self._reports_raw.get("reports") or {})

    def client_scope(self, meta: dict) -> Optional[List[str]]:
        raw = meta.get("clients")
        if not raw:
            return None
        return [str(c).strip().upper() for c in raw]

    def matches_clients(self, meta: dict, selected_clients: Sequence[str]) -> bool:
        scope = self.client_scope(meta)
        if scope is None:
            return True
        selected = {c.upper() for c in selected_clients}
        return bool(selected & set(scope))

    def enabled_reports(
        self, selected_clients: Optional[Sequence[str]] = None
    ) -> Dict[str, dict]:
        out: Dict[str, dict] = {}
        for code, cfg in self.all_reports().items():
            if not cfg.get("enabled", True):
                continue
            if selected_clients is not None and not self.matches_clients(cfg, selected_clients):
                continue
            out[code] = cfg
        return out

    def report_label(self, code: str) -> str:
        meta = self.all_reports().get(code) or {}
        return str(meta.get("label", code))

    def stage_menu_options(
        self, selected_clients: Optional[Sequence[str]] = None
    ) -> List[Tuple[str, str]]:
        stages_meta = self.report_stages_meta()
        reports = self.enabled_reports(selected_clients)
        used_stages = {
            normalize_stage_key(meta.get("stage", "common")) for meta in reports.values()
        }
        ordered: List[Tuple[int, str, str]] = []
        for key, meta in stages_meta.items():
            norm_key = normalize_stage_key(key)
            if norm_key not in used_stages:
                continue
            if selected_clients is not None and not self.matches_clients(meta, selected_clients):
                continue
            ordered.append(
                (int(meta.get("order", 999)), norm_key, str(meta.get("label", f"Stage: {norm_key}")))
            )
        known = {k for _, k, _ in ordered}
        for stage_key in sorted(used_stages):
            if stage_key not in known:
                ordered.append((999, stage_key, f"Stage: {stage_key}"))
        ordered.sort(key=lambda item: (item[0], item[1]))
        return [(key, label) for _, key, label in ordered]

    def reports_for_stage(
        self, stage_key: str, selected_clients: Optional[Sequence[str]] = None
    ) -> List[Tuple[str, str]]:
        stage_norm = normalize_stage_key(stage_key)
        items: List[Tuple[int, str, str]] = []
        for code, meta in self.enabled_reports(selected_clients).items():
            if normalize_stage_key(meta.get("stage", "common")) != stage_norm:
                continue
            items.append((int(meta.get("menu_order", 999)), code, str(meta.get("label", code))))
        items.sort(key=lambda item: (item[0], item[2].lower()))
        return [(code, label) for _, code, label in items]

    def stage_package_path(self, stage_key: str) -> Optional[str]:
        key = normalize_stage_key(stage_key)
        return STAGE_PATHS.get(key) or f"report_script/{key}"

    def load_sequences(self) -> Dict[str, dict]:
        if not SEQUENCES_PATH.exists():
            return {}
        try:
            with SEQUENCES_PATH.open(encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception:
            return {}
        raw = data.get("sequences") or {}
        if not isinstance(raw, dict):
            return {}
        return {str(k): dict(v) for k, v in raw.items() if isinstance(v, dict)}

    def save_sequences(self, sequences: Dict[str, dict]) -> Path:
        payload = {"sequences": sequences}
        SEQUENCES_PATH.parent.mkdir(parents=True, exist_ok=True)
        with SEQUENCES_PATH.open("w", encoding="utf-8") as f:
            f.write(
                "# Saved pipeline run sequences for run_pipeline.py\n"
                "# Edited via interactive: Create / manage sequences\n\n"
            )
            yaml.safe_dump(payload, f, sort_keys=False, allow_unicode=True)
        return SEQUENCES_PATH

    def get_sequence(self, sequence_id: str) -> Optional[dict]:
        sequences = self.load_sequences()
        seq_id = slugify_sequence_id(sequence_id)
        return sequences.get(sequence_id) or sequences.get(seq_id)

    def normalize_selection(
        self, clients: Sequence[str], geos: Sequence[str]
    ) -> Tuple[List[str], List[str]]:
        clients_map = self.clients()
        client_list = [c.strip().upper() for c in clients]
        if len(client_list) == 1 and client_list[0] == "ALL":
            client_list = list(clients_map.keys())
        all_geos = self.all_geo_codes()
        geo_list = [g.strip().upper() for g in geos]
        if len(geo_list) == 1 and geo_list[0] == "ALL":
            geo_list = all_geos
        return client_list, geo_list
