"""
EcoSoul (ESH) shared SKU cleaning + COGS alias mapping.

COGS source: local project slices `cogs/esh/{geo}_amazon_cogs.parquet|.csv`
(via `config_manager.cogs_local`).

Import from report scripts instead of redefining INVALID_SKUS / COGS loaders:

    from config_manager.esh_sku_cleaning import (
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
# COGS workbook (ESH sheets) — paths from .env / geography.yaml
# ---------------------------------------------------------------------------

def get_cogs_path() -> Path:
    return layouts.cogs_path("ESH")


def get_cogs_sheets() -> Dict[str, str]:
    return layouts.cogs_sheets_for("ESH")


def default_invalid_skus() -> set:
    """Load ESH invalid SKUs from config_manager/invalid_skus.json."""
    return get_invalid_skus("ESH")


def __getattr__(name: str):
    """Lazy COGS_PATH / ESH_COGS_SHEETS / COUNTRY_HELPER_FILE / INVALID_SKUS."""
    if name == "COGS_PATH":
        return get_cogs_path()
    if name == "ESH_COGS_SHEETS":
        return get_cogs_sheets()
    if name == "COUNTRY_HELPER_FILE":
        from config_manager import paths as cfg_paths

        return cfg_paths.esh_country_helper_path()
    if name in {"DEFAULT_INVALID_SKUS", "INVALID_SKUS"}:
        return default_invalid_skus()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


_SKU_MAPPING_CACHE: Dict[Tuple[str, Tuple[str, ...]], Dict[str, str]] = {}

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_SKU_NORMALIZATION = {
    "17-0HPU-PJMJ": "17 0HPU PJMJ",
    "17": "17 0HPU PJMJ",
    "UNEXPECTED_ITEM_FBA15KP0K5C5": "FBA15KP0K5C5",
    "PLP6RO100N": "PLP6RO100",
    "A-PLP10RO20": "PLP10RO20",
    "A": "PLP10RO20",
    "P9-5UO8-O0NF": "P9 5UO8 O0NF",
    "P9": "P9 5UO8 O0NF",
    "C0-QDB6-K3Y0": "C0 QDB6 K3Y0",
    "C0": "C0 QDB6 K3Y0",
    "C6-T58V-R7J8": "C6 T58V R7J8",
    "C6": "C6 T58V R7J8",
    "HP-X0Z9-88SI": "HP X0Z9 88SI",
    "HP": "HP X0Z9 88SI",
    "QN-ZU4B-IC2Z": "QN ZU4B IC2Z",
    "QN": "QN ZU4B IC2Z",
    "QS-VWOY-YRKJ": "QS VWOY YRKJ",
    "QS": "QS VWOY YRKJ",
    "RF-IZ6R-7TGG": "RF IZ6R 7TGG",
    "RF": "RF IZ6R 7TGG",
    "9H": "9H-NFLE-BXIK",
    "9H-NFLE-BXIK": "9H-NFLE-BXIK", 
    "AMZN.GR.V1.JB3GPERSEDSU0R_OC2TPNVP2FTK": "B08MTDXPJW",
    "V1.JB3GPERSEDSU0R_OC2TPNVP2FTK": "B08MTDXPJW",
    "PLP10SQ25-HLUJBDEIPYSBS4-9IJ-LN": "PLP10SQ25",
    "PLP10SQ50-J5OTRUN6OZMZYTXPXK-LN": "PLP10SQ50",
    "PLP8SQ20-SKZUZGPJBJI3RPMKXT8H-VG": "PLP8SQ20",
    "BCW-USA": "BCW",

    # Warehouse / supply-chain aliases (Updike / 3G notebooks)
    "BST16": "BSTL16",
    "BKDO": "BKDO17",
}

# Public aliases used by report scripts
SKU_NORMALIZATION = DEFAULT_SKU_NORMALIZATION


# ---------------------------------------------------------------------------
# Header helpers (local to COGS load)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Mapping builders / COGS loaders (cached)
# ---------------------------------------------------------------------------

def _pack_style_forms(sku: str) -> List[str]:
    """Return compact + dashed variants for BS/BF/BSF pack-size SKUs."""
    text = str(sku).strip().upper()
    m = re.match(r"^(.*?)[-]?(BSF|BS|BF)[-]?(\d+[A-Z]*)$", text)
    if not m or not m.group(1).rstrip("-"):
        return []
    base, style, qty = m.group(1).rstrip("-"), m.group(2), m.group(3)
    dashed = f"{base}-{style}-{qty}"
    compact = f"{base}{style}{qty}"
    return [dashed, compact]


def build_sku_mapping(convertor_helper: pd.DataFrame) -> Dict[str, str]:
    sku_mapping: Dict[str, str] = {}

    masters = {
        str(row.get("sku", "")).strip().upper()
        for _, row in convertor_helper.iterrows()
        if str(row.get("sku", "")).strip()
        and str(row.get("sku", "")).strip().upper() != "NAN"
    }

    for _, row in convertor_helper.iterrows():
        master_sku = str(row.get("sku", "")).strip().upper()
        if not master_sku or master_sku == "NAN":
            continue

        for col in ["on_1", "on_2", "on_3", "on_4", "on_5"]:
            alias = row.get(col)
            if pd.notna(alias) and str(alias).strip():
                sku_mapping[str(alias).strip().upper()] = master_sku

        # If master is compact (or dashed), link the other pack form — but never
        # overwrite when that form is already its own master SKU in COGS.
        for form in _pack_style_forms(master_sku):
            if form != master_sku and form not in masters:
                sku_mapping.setdefault(form, master_sku)

    return sku_mapping


def load_cogs_helper_frame(
    cogs_path: Path | str | None = None,
    sheet_names: Optional[Sequence[str]] = None,
    *,
    geos: Optional[Sequence[str]] = None,
    channel: Optional[str] = None,
) -> pd.DataFrame:
    """
    Load ESH COGS from local project slices:

      cogs/esh/{geo}_{channel}_cogs.parquet|.csv

    Channel defaults per geo from geography.yaml when ``channel`` is None.
    ``cogs_path`` is ignored (kept for call-site compatibility).
    """
    from config_manager import cogs_local

    _ = cogs_path  # legacy Excel path no longer used
    needed = ["sku", "on_1", "on_2", "on_3", "on_4", "on_5"]
    return cogs_local.load_cogs_frames(
        "ESH",
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
    channel: Optional[str] = None,
    force_reload: bool = False,
) -> Dict[str, str]:
    """
    Load ESH local COGS slices → alias → master SKU (cached).

    Result is cached in-process so report scripts don't re-read files.
    """
    from config_manager import cogs_local

    _ = cogs_path
    resolved = tuple(
        cogs_local.resolve_geos("ESH", geos=geos, sheet_names=sheet_names)
    )
    ch_key = channel if channel is not None else "per-geo"
    cache_key = (
        str(cogs_local.client_cogs_dir("ESH")),
        ch_key,
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
        print("[WARN] No local ESH COGS rows loaded — SKU mapping empty")
        _SKU_MAPPING_CACHE[cache_key] = {}
        return {}

    mapping = build_sku_mapping(convertor_helper)
    print(
        f"SKU mapping aliases loaded: {len(mapping):,} "
        f"(from cogs/esh geos={list(resolved) or 'ALL'} channel={ch_key})"
    )
    _SKU_MAPPING_CACHE[cache_key] = mapping
    return mapping


def clear_sku_mapping_cache() -> None:
    _SKU_MAPPING_CACHE.clear()


# ---------------------------------------------------------------------------
# Cleaning
# ---------------------------------------------------------------------------
def custom_split(value):
    if pd.isna(value):
        return np.nan

    value = str(value).strip()

    if not value:
        return np.nan
    
    if "AMZN.GR." in value:
        value = value.split("AMZN.GR.")[-1].strip()
    
     # =========================================================
    # SPECIAL RULE: N-PLP8RO20 -> PLP8RO20
    # =========================================================
    value = re.sub(r'^N-', '', value, flags=re.I)

    # =========================================================
    # 1. REMOVE TOKENS
    # =========================================================

    tokens = ['MERGE','NEW', 'USA','US', 'UK', 'UAE','IN',"CAN",'DE', "CND", 'GE', 'GEM', "BULK","RENEW", 'UK1','IT', 'VARIATION', 'DEN', 'UKT', 'STICKERLESS',
              'PARENT', 'CHILD',  'N', 'RL', 'MCF', 
    ]

    tokens_no_n = [token for token in tokens if token != 'N']

    token_pattern = '|'.join(tokens)
    token_pattern_no_n = '|'.join(tokens_no_n)

    # Remove tokens appearing after a hyphen
    # Example:
    # ABC-NEW   -> ABC
    # ABC-US    -> ABC
    # ABC-DE    -> ABC
    value = re.sub(rf'-(?:{token_pattern})\b','',value,flags=re.I)

    # Remove tokens appearing before a hyphen
    # Example:
    # US-ABC    -> ABC
    # UK-ABC    -> ABC
    # DE-ABC    -> ABC
    value = re.sub(rf'\b(?:{token_pattern_no_n})-(?=[A-Za-z0-9])','',value,flags=re.I)

    # Remove standalone tokens
    # Example:
    # ABC US DEF -> ABC  DEF
    # ABC-DE-XYZ -> ABC-XYZ
    value = re.sub(
        rf'(?:(?<=^)|(?<=[^A-Za-z0-9_]))'
        rf'(?:{token_pattern_no_n})'
        rf'(?=$|[^A-Za-z0-9_])',
        '',
        value,flags=re.I)

    value = value.strip()

    # =========================================================
    # 2. REMOVE DISALLOWED CHARACTERS
    # =========================================================

    allowed = set(
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789-")

    upper_value = value.upper()

    # CTB, PLB and PLVP SKUs are allowed to contain '.'
    if upper_value.startswith(("CTB", "PLB", "PLVP", "PLBVP")):
        allowed.add(".")

    # Allow +, &, ; if they exist
    if any(char in upper_value for char in ["+", "&", ";"]):
        allowed.update(["+", "&", ";"])

    # CBV and PLPB7 SKUs are allowed to contain '&'
    if upper_value.startswith(("CBV", "PLPB")):
        allowed.add("&")

    value = ''.join(char for char in value if char in allowed)

    # =========================================================
    # 3. CUSTOM CLEANING RULES
    # =========================================================

    # -NL -> NL
    value = re.sub(r'-NL\b', 'NL', value, flags=re.I)

    # -FBA -> NL
    value = re.sub(r'-FBA\b', '', value, flags=re.I)

    # -FBM -> NL
    value = re.sub(r'-FBM\b', '', value, flags=re.I)

    # Remove -OLD from the end
    value = re.sub(r'-OLD$', '', value, flags=re.I)

    # Remove -CAN from the end
    value = re.sub(r'-CAN$', '', value, flags=re.I)

    # =========================================================
    # 4. FINAL CLEANUP
    # =========================================================

    value = value.strip()

    return value if value else np.nan
##############################
# old splitter function
##############################
# def custom_split(x):

#     if not isinstance(x, str):
#         return np.nan

#     x = x.strip()
#     x_lower = x.lower()

#     # 🔹 Step 1 — Remove everything before 'amzn.gr.' if present
#     if 'amzn.gr.' in x_lower:
#         x = x_lower.split('amzn.gr.')[-1]
#         x_lower = x.lower()

#     x = x.strip()

#     # 🔹 Step 2 — Remove PARENT rows
#     if 'parent' in x_lower:
#         return np.nan

#     # 🔹 Step 3 — Remove AMZ rows
#     if 'amz' in x_lower:
#         return np.nan
#     # Preserve PLVP decimal SKUs with BS quantity suffix
#     if re.match(r'^(?:PLVP|PLBVP)\d+(?:\.\d+)?(?:RO|SQ)-[A-Z]+-\d+$', x, flags=re.IGNORECASE):
#         return x
    
#     # 🔹 Step 4 — REGION LOGIC (remove region suffixes) 
#     regions = [
#     'NEW', 'US', 'UK', 'UAE', 'GE', 'GEM',
#     'BULK', 'RENEW', 'UK1', 'IT', 'VARIATION',
#     'DEN', 'UKT', 'STICKERLESS',
#     'PARENT', 'CHILD', 'DE', 'N', 'RL', 'MCF',
#     'IN', 'CAN', 'CND', 'CA', 'NL', 'FBM',
#     'FBA', 'OLD', 'NLUKRE', 'I'
#     ]

#     # Check longer suffixes first so N doesn't match the N in CAN,
#     # I doesn't match the I in IN, etc.
#     regions = sorted(regions, key=len, reverse=True)

#     for region in regions:
#         pattern = rf'-?{re.escape(region)}$'
#         if re.search(pattern, x, flags=re.IGNORECASE):
#             base = re.sub(pattern,'',x,flags=re.IGNORECASE)
#             return base.strip()

#     # 🔹 Step 5 — PREFIX LOGIC (keep SKU until prefix)
#     prefixes = ['CBVP', 'CTB', 'PLVP', 'BEP', 'AV', 'MT', 'PLBVP', 'PLPB7']

#     for prefix in prefixes:
#         key = f"-{prefix}".lower()
#         if key in x_lower:
#             idx = x_lower.index(key)
#             return x[:idx + len(key)].strip()


#     # 🔹 Step 6 — Final split using common delimiters (- . / space)
#     x = re.split(r'[-/\s]', x)[0]

#     value = x.strip()

#     return value if value else np.nan

def clean_sku_series(
    sku_series: pd.Series,
    sku_mapping: Optional[Dict[str, str]] = None,
    sku_normalization: Optional[Dict[str, str]] = None,
    invalid_skus: Optional[Iterable] = None,
) -> pd.Series:

    # ---------------------------------------------------------
    # 1. Basic cleanup
    # ---------------------------------------------------------
    series = (
        sku_series
        .astype(str)
        .str.strip()
        .str.upper()
    )

    # ---------------------------------------------------------
    # 2. Invalid SKU list
    # ---------------------------------------------------------
    invalid = (
        default_invalid_skus()
        if invalid_skus is None
        else invalid_skus
    )

    invalid = {
        str(x).strip().upper()
        for x in invalid
    }

    # Drop known-bad SKUs before split
    series = series.where(
        ~series.isin(invalid),
        np.nan
    )

    # ---------------------------------------------------------
    # 3. Normalize COGS alias mapping
    # ---------------------------------------------------------
    if sku_mapping:
        sku_mapping = {
            str(k).strip().upper(): str(v).strip().upper()
            for k, v in sku_mapping.items()
        }

    # ---------------------------------------------------------
    # 4. SPECIAL AMAZON .MISSING SKU HANDLING
    #
    # Examples:
    #   FBA19D7Y7F67.MISSING1
    #   FBA19D7Y7F67.MISSSING1
    #   FBA19D7Y7F67.MISS
    #
    # become:
    #   FBA19D7Y7F67
    # ---------------------------------------------------------
    missing_cleaned = series.str.replace(
        r"\.MISSING\d*$",
        "",
        regex=True
    )

    missing_cleaned = missing_cleaned.str.replace(
        r"\.(?:MISSSING|MISS)\d*$",
        "",
        regex=True
    )

    # ---------------------------------------------------------
    # 5. Try COGS mapping using .MISSING-cleaned SKU
    # ---------------------------------------------------------
    if sku_mapping:

        # First try the SKU after removing .MISSING
        missing_mapped = missing_cleaned.replace(
            sku_mapping
        )

        missing_was_mapped = missing_cleaned.isin(
            sku_mapping.keys()
        )

        # Also try exact raw SKU against COGS aliases
        raw_mapped = series.replace(
            sku_mapping
        )

        raw_was_mapped = series.isin(
            sku_mapping.keys()
        )

        # Priority:
        # 1. .MISSING-cleaned alias
        # 2. Exact raw alias
        mapped_series = missing_mapped.where(
            missing_was_mapped,
            raw_mapped
        )

        mapped_found = (
            missing_was_mapped
            | raw_was_mapped
        )

    else:
        mapped_series = series.copy()

        mapped_found = pd.Series(
            False,
            index=series.index
        )

    # ---------------------------------------------------------
    # 6. Existing custom SKU cleaning
    # ---------------------------------------------------------
    cleaned = series.apply(custom_split)

    # ---------------------------------------------------------
    # 7. SKU normalization
    # ---------------------------------------------------------
    normalization_map = (
        DEFAULT_SKU_NORMALIZATION
        if sku_normalization is None
        else sku_normalization
    )

    normalization_map = {
        str(k).strip().upper(): str(v).strip().upper()
        for k, v in normalization_map.items()
    }

    if normalization_map:
        cleaned = cleaned.replace(
            normalization_map
        )

    # ---------------------------------------------------------
    # 8. Post-clean COGS mapping
    #
    # Needed for SKUs that do not match before custom_split()
    # but become valid aliases after custom_split().
    # ---------------------------------------------------------
    if sku_mapping:
        cleaned = cleaned.replace(
            sku_mapping
        )

    # ---------------------------------------------------------
    # 9. Final selection
    #
    # If the raw/.MISSING SKU matched COGS:
    #     use COGS master SKU
    #
    # Otherwise:
    #     use the normal cleaned SKU
    # ---------------------------------------------------------
    series = mapped_series.where(
        mapped_found,
        cleaned
    )

    # ---------------------------------------------------------
    # 10. Final cleanup
    # ---------------------------------------------------------
    series = (
        series
        .astype(str)
        .str.replace(
            r"-+$",
            "",
            regex=True
        )
        .str.strip()
        .str.upper()
        .replace({
            "NAN": np.nan,
            "NONE": np.nan,
            "": np.nan
        })
    )

    # ---------------------------------------------------------
    # 11. Re-check invalid SKUs
    # ---------------------------------------------------------
    series = series.where(
        ~series.isin(invalid),
        np.nan
    )

    return series



# def clean_sku_series(
#     sku_series: pd.Series,
#     sku_mapping: Optional[Dict[str, str]] = None,
#     sku_normalization: Optional[Dict[str, str]] = None,
#     invalid_skus: Optional[Iterable] = None,
# ) -> pd.Series:

#     series = sku_series.astype(str).str.strip().str.upper()

#     invalid = (
#         default_invalid_skus()
#         if invalid_skus is None
#         else invalid_skus
#     )

#     invalid = {
#         str(x).strip().upper()
#         for x in invalid
#     }

#     # Drop known-bad SKUs before split (exact match on raw value)
#     series = series.where(
#         ~series.isin(invalid),
#         np.nan
#     )

#     # ---------------------------------------------------------
#     # IMPORTANT:
#     # Normalize sku_mapping first and check the RAW SKU
#     # against COGS aliases BEFORE custom_split().
#     #
#     # Example:
#     # FBA18VLXSWJF.MISSING1
#     #       -> CBP875RO100
#     #
#     # This prevents custom_split() from removing "." and
#     # breaking the COGS alias match.
#     # ---------------------------------------------------------
#     if sku_mapping:
#         sku_mapping = {
#             str(k).strip().upper(): str(v).strip().upper()
#             for k, v in sku_mapping.items()
#         }

#         # Map exact raw COGS aliases
#         raw_mapped = series.replace(sku_mapping)

#         # Track which rows actually matched an alias
#         raw_was_mapped = series.isin(sku_mapping.keys())
#     else:
#         raw_mapped = series.copy()

#         raw_was_mapped = pd.Series(
#             False,
#             index=series.index
#         )

#     # ---------------------------------------------------------
#     # Existing custom SKU cleaning
#     # ---------------------------------------------------------
#     cleaned = series.apply(custom_split)

#     # ---------------------------------------------------------
#     # Existing SKU normalization
#     # ---------------------------------------------------------
#     normalization_map = (
#         DEFAULT_SKU_NORMALIZATION
#         if sku_normalization is None
#         else sku_normalization
#     )

#     normalization_map = {
#         str(k).strip().upper(): str(v).strip().upper()
#         for k, v in normalization_map.items()
#     }

#     if normalization_map:
#         cleaned = cleaned.replace(
#             normalization_map
#         )

#     # ---------------------------------------------------------
#     # Existing post-clean COGS mapping
#     #
#     # Needed for SKUs which do NOT match the raw alias but
#     # become a valid COGS alias after custom_split().
#     # ---------------------------------------------------------
#     if sku_mapping:
#         cleaned = cleaned.replace(
#             sku_mapping
#         )

#     # ---------------------------------------------------------
#     # Use exact raw COGS mapping when available.
#     # Otherwise use the normal cleaned SKU.
#     # ---------------------------------------------------------
#     series = raw_mapped.where(
#         raw_was_mapped,
#         cleaned
#     )

#     # ---------------------------------------------------------
#     # Final cleanup
#     # ---------------------------------------------------------
#     series = (
#         series.astype(str)
#         .str.replace(
#             r"-+$",
#             "",
#             regex=True
#         )
#         .str.strip()
#         .str.upper()
#         .replace({
#             "NAN": np.nan,
#             "NONE": np.nan,
#             "": np.nan
#         })
#     )

#     # Re-check after split/normalize/map
#     # e.g. junk that cleaned down to PLB5
#     series = series.where(
#         ~series.isin(invalid),
#         np.nan
#     )

#     return series




def clean_sku_column(
    df: pd.DataFrame,
    sku_column: str = "sku",
    sku_mapping: Optional[Dict[str, str]] = None,
    sku_normalization: Optional[Dict[str, str]] = None,
    invalid_skus: Optional[Iterable] = None,
    drop_missing: bool = True,
) -> pd.DataFrame:
    """
    Clean SKU column. Values in invalid_skus.json (ESH) — raw or after split —
    become NaN; with drop_missing=True those rows are removed.
    """
    cleaned = df.copy()
    before = len(cleaned)

    cleaned[sku_column] = clean_sku_series(
        cleaned[sku_column],
        sku_mapping=sku_mapping,
        sku_normalization=sku_normalization,
        invalid_skus=invalid_skus,
    )

    if drop_missing:
        cleaned = cleaned[cleaned[sku_column].notna()].copy()
        dropped = before - len(cleaned)
        if dropped:
            print(f"  Dropped {dropped:,} row(s) with missing/invalid SKUs")

    return cleaned


# ---------------------------------------------------------------------------
# Warehouse / supply-chain helpers (Updike, 3G, Country_helper)
# ---------------------------------------------------------------------------

def strip_case_suffix(value):
    """Remove CASE pack suffixes before SKU split (Updike / 3G notebooks)."""
    if pd.isna(value):
        return np.nan
    text = str(value)
    text = text.split("CASE")[0]
    text = re.sub(r"[-]?CASE.*$", "", text, flags=re.IGNORECASE)
    text = text.strip()
    return text if text else np.nan


def clean_warehouse_sku_series(
    sku_series: pd.Series,
    sku_mapping: Optional[Dict[str, str]] = None,
    *,
    strip_case: bool = True,
    take_first_token: bool = True,
) -> pd.Series:
    """
    Supply-chain SKU clean used by Updike / 3G notebooks:

    1) strip CASE suffixes
    2) custom_split
    3) optional first whitespace token
    4) normalization (incl. BST16/BKDO) + alias mapping
    """
    series = sku_series.copy()
    if strip_case:
        series = series.apply(strip_case_suffix)
    series = series.apply(custom_split)
    if take_first_token:
        series = series.apply(
            lambda x: str(x).split(" ")[0] if pd.notna(x) else np.nan
        )
    return clean_sku_series(series, sku_mapping=sku_mapping)


def clean_warehouse_sku_column(
    df: pd.DataFrame,
    sku_column: str = "SKU",
    sku_mapping: Optional[Dict[str, str]] = None,
    *,
    strip_case: bool = True,
    take_first_token: bool = True,
    drop_missing: bool = False,
) -> pd.DataFrame:
    out = df.copy()
    out[sku_column] = clean_warehouse_sku_series(
        out[sku_column],
        sku_mapping=sku_mapping,
        strip_case=strip_case,
        take_first_token=take_first_token,
    )
    if drop_missing:
        out = out[out[sku_column].notna()].copy()
    return out


def mapping_from_convertor_helper(convertor_helper: pd.DataFrame) -> Dict[str, str]:
    """Alias→master map from Country_helper / item-master ON_1..ON_5 frame."""
    df = convertor_helper.copy()
    rename = {}
    for c in df.columns:
        cl = str(c).strip().lower().replace(" ", "_")
        if cl == "sku":
            rename[c] = "sku"
        elif cl.startswith("on_"):
            rename[c] = cl
        elif cl.startswith("on") and any(ch.isdigit() for ch in cl):
            num = "".join(ch for ch in cl if ch.isdigit())
            rename[c] = f"on_{num}"
    out = df.rename(columns=rename)
    out.columns = [str(c).strip().lower() for c in out.columns]
    if "sku" not in out.columns:
        raise KeyError("convertor_helper needs SKU column")
    return build_sku_mapping(out)


def load_country_helper(
    path: Path | str | None = None,
    *,
    sheet_name: str = "Main",
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Load Country_helper.xlsx Main sheet.

    Returns:
      convertor_main, convertor_helper (SKU+ON_*), convertor (attributes + Main_WAC)
    """
    from config_manager import paths as cfg_paths

    helper_path = Path(path) if path is not None else cfg_paths.esh_country_helper_path()
    if not helper_path.is_file():
        raise FileNotFoundError(f"Country_helper missing: {helper_path}")

    convertor_main = pd.read_excel(helper_path, sheet_name=sheet_name)
    convertor_helper = convertor_main.loc[
        :, ["SKU", "ON_1", "ON_2", "ON_3", "ON_4", "ON_5"]
    ]
    convertor_helper = convertor_helper[convertor_helper["SKU"] != 0]

    convertor = convertor_main.loc[
        :,
        [
            "SKU",
            "Material",
            "Product_Category",
            "Product_Sub_Category",
            "Product_Type",
            "Units_Per_Set",
            "Box / Case",
            "Main_WAC",
        ],
    ]
    convertor["Main_WAC"] = convertor.Main_WAC.fillna(1)
    return convertor_main, convertor_helper, convertor

