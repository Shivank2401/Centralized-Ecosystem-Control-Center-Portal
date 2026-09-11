"""
Client filesystem layouts — relative paths under each client's data_root (.env).

Report scripts use these instead of hardcoded OneDrive absolute paths.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from config_manager.loader import get_client, load_geographies

# ESH: folder name under inventory root → geography code
ESH_GEO_FOLDERS: Dict[str, str] = {
    "canada": "CA",
    "us": "US",
    "uk": "UK",
    "germany": "DE",
    "uae": "AE",
    "india": "IN",
}

# KNC: report key → geo → path parts under KNC_DATA_ROOT
KNC_GEO_REL: Dict[str, Dict[str, Tuple[str, ...]]] = {
    "ledger": {
        "UK": ("Inventory", "ledger_report", "Year"),
        "DE": ("Germany", "Inventory", "ledger_report", "Year"),
        "AE": ("UAE", "Inventory", "ledger_report", "Year"),
    },
    "manage_fba": {
        "UK": ("Inventory", "manage fba"),
        "DE": ("Germany", "Inventory", "manage fba"),
        "AE": ("UAE", "Inventory", "manage fba"),
    },
    "reserved": {
        "UK": ("Inventory", "reserved"),
        "DE": ("Germany", "Inventory", "reserved"),
        "AE": ("UAE", "Inventory", "reserved"),
    },
    "ageing": {
        "UK": ("Inventory", "fba Inventory"),
        "DE": ("Germany", "Inventory", "fba Inventory"),
        "AE": ("UAE", "Inventory", "fba Inventory"),
    },
    "orders": {
        "UK": ("Orders",),
        "DE": ("Germany", "Orders"),
        "AE": ("UAE", "Orders"),
    },
}

# ESH: geography code → folder under revenue root
ESH_REVENUE_GEO_FOLDERS: Dict[str, str] = {
    "US": "us",
    "CA": "canada",
    "UK": "uk",
    "DE": "germany",
    "AE": "uae",
    "IN": "india",
}


def cogs_sheets_for(client: str, *, channel: Optional[str] = None) -> Dict[str, str]:
    """
    Geography → excel_sheet for upload mapping / SKU-mapping geo lists.

    When ``channel`` is set (e.g. ``amazon``), only geos that define that channel
    are returned — so KNC IE (shopify-only) is excluded from Amazon reports.
    """
    out: Dict[str, str] = {}
    for code, geo in load_geographies(client).items():
        if channel:
            if not geo.has_channel(channel):
                continue
            sheet = geo.channel(channel).excel_sheet
        else:
            sheet = geo.cogs_sheet_name
        if sheet:
            out[code] = sheet
    return out


def geos_with_channel(client: str, channel: str) -> List[str]:
    """Enabled geo codes that define the given channel in geography.yaml."""
    ch = str(channel).strip().lower()
    return [
        code
        for code, geo in load_geographies(client).items()
        if geo.has_channel(ch)
    ]


def cogs_channel_for(client: str, geography: str) -> str:
    """Default local COGS channel for a geo from geography.yaml."""
    geos = load_geographies(client)
    g = geos.get(str(geography).strip().upper())
    if g is None:
        return "amazon"
    return str(g.default_channel or "amazon").strip().lower() or "amazon"


def channel_config(client: str, geography: str, channel: str):
    """Return ChannelConfig for client/geo/channel."""
    geos = load_geographies(client)
    g = geos.get(str(geography).strip().upper())
    if g is None:
        raise KeyError(f"Unknown geography {client}/{geography}")
    return g.channel(channel)


def client_identity(client: str) -> Dict[str, str]:
    cfg = get_client(client)
    return {
        "client_code": cfg.code,
        "client_id": cfg.client_id,
        "client_name": cfg.name,
        "layout": cfg.layout,
    }


def data_root(client: str) -> Path:
    return get_client(client).data_root


def cogs_path(client: str) -> Path:
    return get_client(client).cogs_path


def knc_geo_roots(report: str, base: Path | None = None) -> Dict[str, Path]:
    """Absolute geo roots for a KNC report type."""
    root = base if base is not None else data_root("KNC")
    rel = KNC_GEO_REL.get(report)
    if not rel:
        raise KeyError(f"Unknown KNC report layout: {report}. Known: {list(KNC_GEO_REL)}")
    return {geo: root.joinpath(*parts) for geo, parts in rel.items()}


def esh_orders_geo_roots(base: Path | None = None) -> Dict[str, Path]:
    """
    Absolute geo roots for ESH Amazon orders under revenue/.

    Pattern: {revenue}/{folder}/input/amazon/orders
    """
    from config_manager import paths as cfg_paths

    root = base if base is not None else cfg_paths.esh_revenue_root()
    return {
        code: root / folder / "input" / "amazon" / "orders"
        for code, folder in ESH_REVENUE_GEO_FOLDERS.items()
    }


def cli_argv(
    *,
    client: str,
    geos: List[str] | None = None,
    years: List[str] | None = None,
    months: List[str] | None = None,
) -> List[str]:
    """Build argparse argv for common report scripts."""
    argv = ["--client", client.upper()]
    if geos:
        argv.extend(["--geos", ",".join(geos)])
    if years:
        argv.extend(["--years", ",".join(years)])
    if months:
        argv.extend(["--months", ",".join(months)])
    return argv
