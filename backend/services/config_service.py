"""Config-facing service wrapping pipeline_engine.ConfigRegistry."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from pipeline_engine.discovery import ReportDiscovery
from pipeline_engine.registry import ConfigRegistry, normalize_stage_key


class ConfigService:
    def __init__(self) -> None:
        self.registry = ConfigRegistry()
        self.discovery = ReportDiscovery(self.registry)

    def refresh(self) -> None:
        self.registry.refresh()

    def list_clients(self) -> List[Dict[str, Any]]:
        return [
            {
                "code": code,
                "name": cfg.name,
                "client_id": cfg.client_id,
                "enabled": cfg.enabled,
                "data_root_env": cfg.data_root_env,
                "cogs_path_env": cfg.cogs_path_env,
                "geographies": cfg.geographies,
                "layout": cfg.layout,
            }
            for code, cfg in self.registry.clients(include_disabled=True).items()
        ]

    def get_client(self, code: str) -> Dict[str, Any]:
        cfg = self.registry.clients(include_disabled=True).get(code.upper())
        if cfg is None:
            raise KeyError(f"Unknown client: {code}")
        return {
            "code": cfg.code,
            "name": cfg.name,
            "client_id": cfg.client_id,
            "enabled": cfg.enabled,
            "data_root_env": cfg.data_root_env,
            "cogs_path_env": cfg.cogs_path_env,
            "geographies": cfg.geographies,
            "layout": cfg.layout,
            "package": cfg.package,
        }

    def list_geographies(self, client: str) -> List[Dict[str, Any]]:
        clients = self.registry.clients(include_disabled=True)
        if client.upper() not in clients:
            raise KeyError(f"Unknown client: {client}")
        geos = self.registry.geographies(client)
        return [
            {
                "client": g.client,
                "country_code": g.country_code,
                "country_currency": g.country_currency,
                "enabled": g.enabled,
                "default_channel": g.default_channel,
                "channels": {
                    name: {
                        "excel_sheet": ch.excel_sheet,
                        "orders_sales_channel": ch.orders_sales_channel,
                        "markets": list(ch.markets),
                        "vendors": list(ch.vendors),
                        "cogs_stem": f"{g.country_code.lower()}_{ch.name}_cogs",
                    }
                    for name, ch in g.channels.items()
                },
                # Backward-compatible flat fields for older UI
                "cogs_sheet_name": g.cogs_sheet_name,
                "cogs_channel": g.default_channel,
                "cogs_channels": g.cogs_channels,
                "orders_sales_channel": g.orders_sales_channel,
            }
            for g in geos.values()
        ]

    def list_stages(self, clients: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
        opts = self.registry.stage_menu_options(clients)
        meta = self.registry.report_stages_meta()
        out = []
        for key, label in opts:
            m = meta.get(key) or {}
            out.append(
                {
                    "key": key,
                    "label": label,
                    "order": m.get("order"),
                    "clients": m.get("clients"),
                    "package_path": self.registry.stage_package_path(key),
                }
            )
        return out

    def list_reports(
        self,
        *,
        clients: Optional[Sequence[str]] = None,
        stage: Optional[str] = None,
        enabled_only: bool = True,
    ) -> List[Dict[str, Any]]:
        summaries = self.discovery.discover_report_summaries()
        stage_norm = normalize_stage_key(stage) if stage else None
        out = []
        for item in summaries:
            if enabled_only and not item.get("enabled", True):
                continue
            if stage_norm and item.get("stage") != stage_norm:
                continue
            if clients is not None:
                if not self.registry.matches_clients({"clients": item.get("clients")}, clients):
                    continue
            out.append(item)
        return out

    def get_report(self, code: str) -> Optional[Dict[str, Any]]:
        code = code.strip().lower()
        for item in self.discovery.discover_report_summaries():
            if item["code"] == code:
                return item
        return None

    def list_sequences(self) -> List[Dict[str, Any]]:
        sequences = self.registry.load_sequences()
        return [
            {
                "id": seq_id,
                "label": meta.get("label") or seq_id,
                "clients": meta.get("clients") or [],
                "geos": meta.get("geos") or [],
                "reports": meta.get("reports") or [],
            }
            for seq_id, meta in sorted(sequences.items())
        ]

    def get_sequence(self, sequence_id: str) -> Optional[Dict[str, Any]]:
        meta = self.registry.get_sequence(sequence_id)
        if meta is None:
            return None
        return {
            "id": sequence_id,
            "label": meta.get("label") or sequence_id,
            "clients": meta.get("clients") or [],
            "geos": meta.get("geos") or [],
            "reports": meta.get("reports") or [],
        }
