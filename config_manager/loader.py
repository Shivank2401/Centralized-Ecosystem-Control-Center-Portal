"""
Load client / geography / report YAML configs and resolve env-based paths.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

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


def _as_str_list(value: Any) -> Tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        parts = [p.strip() for p in value.split(",")]
        return tuple(p for p in parts if p)
    if isinstance(value, (list, tuple)):
        return tuple(str(x).strip() for x in value if str(x).strip())
    return (str(value).strip(),) if str(value).strip() else ()


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
        """Legacy Excel workbook path (want_to_update upload only). Reports use cogs_local."""
        return paths.env_path(self.cogs_path_env)  # type: ignore[return-value]


@dataclass(frozen=True)
class ChannelConfig:
    """One sales/platform channel under a geography (amazon, shopify, …)."""

    name: str
    # Optional Excel sheet for want_to_update upload only (not used by report COGS reads)
    excel_sheet: str = ""
    # Amazon-style sales-channel filter
    orders_sales_channel: str = ""
    # Shopify Market + Product vendor filters
    markets: Tuple[str, ...] = ()
    vendors: Tuple[str, ...] = ()

    @property
    def cogs_stem(self) -> str:
        """Local file stem segment: always the channel name (uk_amazon_cogs, uk_shopify_cogs)."""
        return self.name.strip().lower()


@dataclass(frozen=True)
class GeographyConfig:
    """
    One geography for a client; may host multiple channels.

    Local COGS path for channel C:
      cogs/{client}/{geo}_{C}_cogs.parquet|.csv
    """

    client: str
    country_code: str
    country_currency: str
    enabled: bool = True
    default_channel: str = "amazon"
    channels: Dict[str, ChannelConfig] = field(default_factory=dict)

    def channel(self, name: Optional[str] = None) -> ChannelConfig:
        key = str(name or self.default_channel).strip().lower() or self.default_channel
        if key not in self.channels:
            known = ", ".join(sorted(self.channels)) or "(none)"
            raise KeyError(
                f"No channel '{key}' for {self.client}/{self.country_code}. Known: {known}"
            )
        return self.channels[key]

    def has_channel(self, name: str) -> bool:
        return str(name).strip().lower() in self.channels

    # --- Backward-compatible accessors (amazon reports / older UI) ---

    @property
    def cogs_channel(self) -> str:
        return self.default_channel

    @property
    def cogs_sheet_name(self) -> str:
        try:
            return self.channel(self.default_channel).excel_sheet
        except KeyError:
            if not self.channels:
                return ""
            return next(iter(self.channels.values())).excel_sheet

    @property
    def orders_sales_channel(self) -> str:
        """Default-channel Amazon sales-channel (or first channel that has one)."""
        try:
            ch = self.channel(self.default_channel)
            if ch.orders_sales_channel:
                return ch.orders_sales_channel
        except KeyError:
            pass
        for ch in self.channels.values():
            if ch.orders_sales_channel:
                return ch.orders_sales_channel
        return ""

    @property
    def cogs_channels(self) -> Dict[str, str]:
        """channel → excel_sheet (upload mapping only)."""
        return {k: v.excel_sheet for k, v in self.channels.items() if v.excel_sheet}


def _parse_channel(name: str, raw: Dict[str, Any]) -> ChannelConfig:
    orders = raw.get("orders_sales_channel") or ""
    if isinstance(orders, list):
        orders = ", ".join(str(x).strip() for x in orders if str(x).strip())
    return ChannelConfig(
        name=str(name).strip().lower(),
        excel_sheet=str(raw.get("excel_sheet") or raw.get("cogs_sheet_name") or "").strip(),
        orders_sales_channel=str(orders).strip(),
        markets=_as_str_list(raw.get("markets")),
        vendors=_as_str_list(raw.get("vendors")),
    )


def _legacy_channels_from_flat(cfg: Dict[str, Any]) -> Dict[str, ChannelConfig]:
    """Support old flat geography keys during transition."""
    channel = str(cfg.get("cogs_channel") or "amazon").strip().lower() or "amazon"
    sheet = str(cfg.get("cogs_sheet_name") or "").strip()
    orders = cfg.get("orders_sales_channel") or ""
    if isinstance(orders, list):
        orders = ", ".join(str(x).strip() for x in orders if str(x).strip())
    channels: Dict[str, ChannelConfig] = {
        channel: ChannelConfig(
            name=channel,
            excel_sheet=sheet,
            orders_sales_channel=str(orders).strip(),
        )
    }
    extra = cfg.get("cogs_channels") or {}
    if isinstance(extra, dict):
        for ch_name, excel in extra.items():
            key = str(ch_name).strip().lower()
            if not key:
                continue
            if key in channels:
                continue
            channels[key] = ChannelConfig(
                name=key,
                excel_sheet=str(excel).strip(),
            )
    return channels


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
        if not isinstance(cfg, dict):
            continue
        if not cfg.get("enabled", True):
            continue

        channels_raw = cfg.get("channels")
        channels: Dict[str, ChannelConfig] = {}
        if isinstance(channels_raw, dict) and channels_raw:
            for ch_name, ch_cfg in channels_raw.items():
                if not isinstance(ch_cfg, dict):
                    continue
                parsed = _parse_channel(str(ch_name), ch_cfg)
                channels[parsed.name] = parsed
        else:
            channels = _legacy_channels_from_flat(cfg)

        default_channel = str(cfg.get("default_channel") or "").strip().lower()
        if not default_channel:
            default_channel = (
                "amazon"
                if "amazon" in channels
                else (next(iter(channels)) if channels else "amazon")
            )
        if default_channel not in channels and channels:
            default_channel = next(iter(channels))

        out[code.upper()] = GeographyConfig(
            client=client,
            country_code=str(cfg.get("country_code", code)).upper(),
            country_currency=str(cfg["country_currency"]).strip(),
            enabled=bool(cfg.get("enabled", True)),
            default_channel=default_channel,
            channels=channels,
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
