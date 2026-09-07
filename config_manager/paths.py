"""
Resolve filesystem paths from environment variables (no hardcoded user paths).

Each client declares data_root_env / cogs_path_env in client.yaml.
Copy .env.example -> .env and set values for your machine.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Project .env always wins over empty / stale shell env vars
load_dotenv(_PROJECT_ROOT / ".env", override=True)


def project_root() -> Path:
    return _PROJECT_ROOT


def env_path(var_name: str, *, required: bool = True) -> Optional[Path]:
    """Read a path from an env var. Returns None if missing and not required."""
    raw = os.getenv(var_name, "").strip().strip('"').strip("'")
    # Tolerate accidental Python raw-string literals pasted into .env (r"C:\...")
    if len(raw) >= 3 and raw[0] == "r" and raw[1] in {'"', "'"}:
        quote = raw[1]
        raw = raw[2:]
        if raw.endswith(quote):
            raw = raw[:-1]
        raw = raw.strip()
    if not raw:
        if required:
            raise EnvironmentError(
                f"Missing env var {var_name}. "
                f"Set it in {_PROJECT_ROOT / '.env'} (see .env.example)."
            )
        return None
    return Path(raw)


def sanity_data_root() -> Path:
    """Local processed/output root (relative to repo by default)."""
    override = env_path("SANITY_DATA_ROOT", required=False)
    if override is not None:
        return override
    return _PROJECT_ROOT / "sanity_data"


def esh_central_root() -> Path:
    """
    EcoSoul central repo root (parent of inventory).

    Prefer ESH_CENTRAL_ROOT; otherwise parent of ESH_DATA_ROOT.
    Used for siblings of inventory: retail/, logistics/, Task file/, etc.
    """
    override = env_path("ESH_CENTRAL_ROOT", required=False)
    if override is not None:
        return override
    return env_path("ESH_DATA_ROOT").parent  # type: ignore[union-attr]


def esh_inventory_root() -> Path:
    """Alias for ESH_DATA_ROOT (inventory tree with us/, canada/, …)."""
    return env_path("ESH_DATA_ROOT")  # type: ignore[return-value]


def esh_country_helper_path() -> Path:
    """Country_helper.xlsx under inventory dashboard essentials."""
    override = env_path("ESH_COUNTRY_HELPER_PATH", required=False)
    if override is not None:
        return override
    return esh_inventory_root() / "dashboard_essential_files" / "Country_helper.xlsx"


def esh_demand_instock_root() -> Optional[Path]:
    """Optional root for Demand_instock helper exports (outside inventory tree)."""
    return env_path("ESH_DEMAND_INSTOCK_ROOT", required=False)


def esh_revenue_root() -> Path:
    """
    EcoSoul revenue tree (sibling of inventory: revenue/{us,uk,...}/input/...).

    Prefer ESH_REVENUE_ROOT; otherwise {ESH_CENTRAL_ROOT}/revenue.
    """
    override = env_path("ESH_REVENUE_ROOT", required=False)
    if override is not None:
        return override
    return esh_central_root() / "revenue"


def esh_retail_root() -> Path:
    """
    EcoSoul retail tree (KeHE, Sprouts, item_master_data, dashboard exports).

    Prefer ESH_RETAIL_ROOT; otherwise {ESH_CENTRAL_ROOT}/retail.
    """
    override = env_path("ESH_RETAIL_ROOT", required=False)
    if override is not None:
        return override
    return esh_central_root() / "retail"


def esh_walmart_root() -> Path:
    """
    EcoSoul Walmart / Scintilla retail source folder
    (sku_helper.csv, eComm Inventory.xlsx, eComm_Sales.xlsx, …).

    Required: ESH_WALMART_ROOT in .env
    """
    path = env_path("ESH_WALMART_ROOT", required=False)
    if path is None:
        raise EnvironmentError(
            "Missing ESH_WALMART_ROOT in .env "
            "(Walmart retail folder with sku_helper.csv / eComm Inventory.xlsx / …)."
        )
    return path


def pincode_data_dir() -> Path:
    """
    Directory containing `{geo}_amazon_pincode.csv` files.

    Resolution order:
      1) PINCODE_DATA_DIR from .env
      2) {project_root}/pincode  (if that folder exists)
    """
    path = env_path("PINCODE_DATA_DIR", required=False)
    if path is not None:
        return path

    fallback = _PROJECT_ROOT / "pincode"
    if fallback.is_dir():
        return fallback

    raise EnvironmentError(
        "Missing PINCODE_DATA_DIR in .env (needed for city/state order reports). "
        f"Set PINCODE_DATA_DIR to your pincode CSV folder, or create {fallback}."
    )


def esh_pincode_xlsx_path() -> Path:
    """
    Master pincode.xlsx under ESH inventory dashboard essentials.

    Prefer ESH_PINCODE_PATH; otherwise
    {ESH_DATA_ROOT}/dashboard_essential_files/pincode.xlsx
    """
    override = env_path("ESH_PINCODE_PATH", required=False)
    if override is not None:
        return override
    return esh_inventory_root() / "dashboard_essential_files" / "pincode.xlsx"
