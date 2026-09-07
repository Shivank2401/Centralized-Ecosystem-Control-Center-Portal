"""
Load client / geography / report YAML configs and resolve env-based paths.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import yaml

from config_manager import paths

_CONFIG_DIR = Path(__file__).resolve().parent


def _load_yaml(name: str) -> Dict[str, Any]:
    path = _CONFIG_DIR / name
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected mapping in {path}, got {type(data)}")
    return data


@dataclass(frozen=True)
class ClientConfig:
    code: str
    name: str
    client_id: str
    enabled: bool
    data_root_env: str
    cogs_path_env: str
    package: str
    layout: str
    geographies: List[str]

    @property
    def data_root(self) -> Path:
        return paths.env_path(self.data_root_env)  # type: ignore[return-value]

    @property
    def cogs_path(self) -> Path:
        return paths.env_path(self.cogs_path_env)  # type: ignore[return-value]


@dataclass(frozen=True)
class GeographyConfig:
    client: str
    country_code: str
    cogs_sheet_name: str
    country_currency: str
    orders_sales_channel: str
    enabled: bool = True


def load_clients() -> Dict[str, ClientConfig]:
    raw = _load_yaml("client.yaml").get("clients", {})
    out: Dict[str, ClientConfig] = {}
    for code, cfg in raw.items():
        if not cfg.get("enabled", True):
            continue
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


def load_geographies(client: str) -> Dict[str, GeographyConfig]:
    client = client.upper()
    raw = _load_yaml("geography.yaml").get("geographies", {}).get(client, {})
    out: Dict[str, GeographyConfig] = {}
    for code, cfg in raw.items():
        if not cfg.get("enabled", True):
            continue
        out[code.upper()] = GeographyConfig(
            client=client,
            country_code=cfg.get("country_code", code).upper(),
            cogs_sheet_name=cfg["cogs_sheet_name"],
            country_currency=cfg["country_currency"],
            orders_sales_channel=cfg["orders_sales_channel"],
            enabled=bool(cfg.get("enabled", True)),
        )
    return out


def load_reports() -> Dict[str, Any]:
    return _load_yaml("report.yaml")


def get_client(code: str) -> ClientConfig:
    clients = load_clients()
    key = code.upper()
    if key not in clients:
        raise KeyError(f"Unknown or disabled client: {code}. Known: {list(clients)}")
    return clients[key]


def resolve_geographies(client: str, selection: Sequence[str] | str) -> List[str]:
    """
    selection: 'ALL' / '7' style handled by CLI; here accepts list or 'ALL'.
    Returns enabled geo codes for the client.
    """
    geos = load_geographies(client)
    if isinstance(selection, str):
        if selection.upper() == "ALL":
            return list(geos.keys())
        selection = [g.strip().upper() for g in selection.split(",") if g.strip()]
    else:
        selection = [g.upper() for g in selection]

    unknown = [g for g in selection if g not in geos]
    if unknown:
        raise KeyError(
            f"Unknown geos for {client}: {unknown}. Allowed: {list(geos.keys())}"
        )
    return selection


def client_sanity_dir(client: str, report_subdir: str) -> Path:
    """sanity_data/{CLIENT}/{subdir}/"""
    return paths.sanity_data_root() / client.upper() / report_subdir
