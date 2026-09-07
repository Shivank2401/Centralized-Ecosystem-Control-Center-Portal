"""
Kinetica (KNC) shared SKU cleaning + COGS alias mapping.

COGS source: local project slices `cogs/knc/{geo}_amazon_cogs.parquet|.csv`
(via `config_manager.cogs_local`).

    from config_manager.knc_sku_cleaning import (
        clean_sku_column,
        load_sku_mapping,
    )
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from config_manager import layouts
from config_manager.invalid_skus_store import get_invalid_skus

# ---------------------------------------------------------------------------
# COGS workbook (KNC sheets) — paths from .env / geography.yaml
# ---------------------------------------------------------------------------

def get_cogs_path() -> Path:
    return layouts.cogs_path("KNC")


def get_cogs_sheets() -> Dict[str, str]:
    return layouts.cogs_sheets_for("KNC")


def default_invalid_skus() -> set:
    """Load KNC invalid SKUs from config_manager/invalid_skus.json."""
    return get_invalid_skus("KNC")


def __getattr__(name: str):
    """Lazy COGS_PATH / KNC_COGS_SHEETS / INVALID_SKUS so import works before .env is set."""
    if name == "COGS_PATH":
        return get_cogs_path()
    if name == "KNC_COGS_SHEETS":
        return get_cogs_sheets()
    if name in {"DEFAULT_INVALID_SKUS", "INVALID_SKUS"}:
        return default_invalid_skus()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


_SKU_MAPPING_CACHE: Dict[Tuple[str, Tuple[str, ...]], Dict[str, str]] = {}

DEFAULT_SKU_NORMALIZATION = {
    "200855": "KCA-200855",
    "KINWHEYBANANA227KG": "KCA-200852",
    "WHEYBAN227PANEU": "KCA-200852",
    "KIN-201033": "KCA-201033",
}

SKU_NORMALIZATION = DEFAULT_SKU_NORMALIZATION

def _to_upper_map(mapping: Optional[Dict[str, str]]) -> Dict[str, str]:
    if not mapping:
        return {}
    return {str(k).strip().upper(): str(v).strip().upper() for k, v in mapping.items()}


def _to_snake(name: str) -> str:
    name = str(name).strip().lower()
    name = re.sub(r"[^a-z0-9]+", "_", name)
    name = re.sub(r"_+", "_", name)
    return name.strip("_")


def _clean_col(c: str) -> str:
    c = str(c).strip()
    c = c.replace("\ufeff", "")
    c = c.replace("ï»¿", "")
    return c.strip('"').strip("'")


def build_sku_mapping(convertor_helper: pd.DataFrame) -> Dict[str, str]:
    """
    Build alias -> master SKU mapping from helper DataFrame
    using columns: sku, on_1, on_2, on_3 (KNC uses ON_1 / ON_2 / ON_3 aliases).
    """
    sku_mapping: Dict[str, str] = {}
    for _, row in convertor_helper.iterrows():
        master_sku = str(row.get("sku", "")).strip().upper()
        if not master_sku or master_sku == "NAN":
            continue
        for col in ["on_1", "on_2", "on_3"]:
            alias = row.get(col)
            if pd.notna(alias) and str(alias).strip():
                sku_mapping[str(alias).strip().upper()] = master_sku
    return sku_mapping


def load_cogs_helper_frame(
    cogs_path: Path | str | None = None,
    sheet_names: Optional[Sequence[str]] = None,
    *,
    geos: Optional[Sequence[str]] = None,
    channel: str = "amazon",
) -> pd.DataFrame:
    """
    Load KNC COGS from local project slices:

      cogs/knc/{geo}_{channel}_cogs.parquet|.csv

    ``cogs_path`` is ignored (kept for call-site compatibility).
    """
    from config_manager import cogs_local

    _ = cogs_path
    needed = ["sku", "on_1", "on_2", "on_3"]
    return cogs_local.load_cogs_frames(
        "KNC",
        geos=geos,
        sheet_names=sheet_names,
        channel=channel,
        columns=needed,
    )


def load_sku_mapping(
    cogs_path: Path | str | None = None,
    sheet_names: Optional[Sequence[str]] = None,
    *,
    geos: Optional[Sequence[str]] = None,
    channel: str = "amazon",
    force_reload: bool = False,
) -> Dict[str, str]:
    """Load Kinetica local COGS slices → alias → master SKU (cached)."""
    from config_manager import cogs_local

    _ = cogs_path
    resolved = tuple(
        cogs_local.resolve_geos("KNC", geos=geos, sheet_names=sheet_names)
    )
    cache_key = (
        str(cogs_local.client_cogs_dir("KNC")),
        channel,
        resolved,
    )

    if not force_reload and cache_key in _SKU_MAPPING_CACHE:
        return _SKU_MAPPING_CACHE[cache_key]

    convertor_helper = load_cogs_helper_frame(
        sheet_names=sheet_names,
        geos=list(resolved) if resolved else geos,
        channel=channel,
    )

    if convertor_helper.empty:
        print("[WARN] No local KNC COGS rows loaded — SKU mapping empty")
        _SKU_MAPPING_CACHE[cache_key] = {}
        return {}

    mapping = build_sku_mapping(convertor_helper)
    print(
        f"SKU mapping aliases loaded: {len(mapping):,} "
        f"(from cogs/knc geos={list(resolved) or 'ALL'})"
    )
    _SKU_MAPPING_CACHE[cache_key] = mapping
    return mapping


def clear_sku_mapping_cache() -> None:
    _SKU_MAPPING_CACHE.clear()


def custom_split(value):
    """
    Normalize raw SKU-like values with enhanced cleaning rules.

    Rules:
    1) Remove amzn.gr
    2) Remove Parent / amz records
    3) Remove regions
    4) Remove trailing dashes
    5) Remove common trailing suffixes like -N, --N, -A, --X (single letter)
    6) Ensure clean final format
    """
    if not isinstance(value, str):
        return np.nan

    value = value.strip()
    if not value:
        return np.nan

    value_lower = value.lower()

    if "amzn.gr." in value_lower:
        value = value_lower.split("amzn.gr.")[-1].strip()
        value_lower = value.lower()

    if any(keyword in value_lower for keyword in ["parent", "amz"]):
        return np.nan

    regions = ["UAE", "UK", "CAN", "USA", "DE", "EU", "IN"]
    for region in regions:
        value = re.sub(rf"\b{region}\b", "", value, flags=re.IGNORECASE)

    value = value.strip()
    value = re.sub(r"-{1,2}$", "", value)
    value = re.sub(r"--[A-Za-z]$", "", value)
    value = re.sub(r"-[A-Za-z]$", "", value)
    value = re.sub(r"-{2,}", "-", value)
    value = re.sub(r"-+$", "", value)
    value = value.strip()

    return value.upper() if value else np.nan


def clean_sku_series(
    sku_series: pd.Series,
    sku_mapping: Optional[Dict[str, str]] = None,
    sku_normalization: Optional[Dict[str, str]] = None,
    invalid_skus: Optional[Iterable] = None,
    source: Optional[str] = None,
) -> pd.Series:
    """
    Clean SKU series.

    Order:
    1) drop invalid SKUs from invalid_skus.json (raw, before split/map)
    2) custom_split
    3) normalization map
    4) alias mapping
    5) trailing dash removal
    6) source-specific prefix logic (shopify / amazon_ae)
    7) re-check invalid SKUs after cleaning
    """
    series = sku_series.copy().astype(str).str.strip().str.upper()

    invalid = default_invalid_skus() if invalid_skus is None else invalid_skus
    invalid = {str(x).strip().upper() for x in invalid}

    # Drop known-bad SKUs before split / mapping (exact match on raw value)
    series = series.where(~series.isin(invalid), np.nan)

    series = series.apply(custom_split)
    series = series.where(series.notna(), np.nan)
    series = series.astype(str).str.strip().str.upper()

    normalization_map = _to_upper_map(
        DEFAULT_SKU_NORMALIZATION if sku_normalization is None else sku_normalization
    )
    mapping_map = _to_upper_map(sku_mapping)

    if normalization_map:
        series = series.replace(normalization_map)
    if mapping_map:
        series = series.replace(mapping_map)

    series = series.str.replace(r"-{1,2}$", "", regex=True).str.strip()

    # Shopify / AE amazon: digit extract + KCA- prefix (from knc_ageing.py)
    if source in {"shopify", "amazon_ae"}:
        digits = series.str.extract(r"(\d+)", expand=False)
        series = np.where(
            digits.notna(),
            "KCA-" + digits.astype(str).str.replace(r"\.0$", "", regex=True),
            series,
        )
        series = pd.Series(series, index=sku_series.index)
        if mapping_map:
            series = series.replace(mapping_map)

    series = series.replace({"NAN": np.nan, "NONE": np.nan, "": np.nan})

    # Re-check after split/normalize/map
    series = series.astype(str).str.strip().str.upper()
    series = series.where(~series.isin(invalid | {"NAN", "NONE", ""}), np.nan)
    return series


def clean_sku_column(
    df: pd.DataFrame,
    sku_column: str = "sku",
    sku_mapping: Optional[Dict[str, str]] = None,
    sku_normalization: Optional[Dict[str, str]] = None,
    invalid_skus: Optional[Iterable] = None,
    drop_missing: bool = True,
    source: Optional[str] = None,
) -> pd.DataFrame:
    """
    Clean SKU column. Values in invalid_skus.json (KNC) — raw or after split —
    become NaN; with drop_missing=True those rows are removed.
    """
    cleaned = df.copy()
    cleaned[sku_column] = clean_sku_series(
        cleaned[sku_column],
        sku_mapping=sku_mapping,
        sku_normalization=sku_normalization,
        invalid_skus=invalid_skus,
        source=source,
    )
    if drop_missing:
        cleaned = cleaned[cleaned[sku_column].notna()].copy()
    return cleaned
