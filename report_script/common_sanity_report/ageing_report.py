"""
Client-aware Amazon FBA Inventory Ageing combiner.

Covers:
  - Clients: ESH (US, CA, UK, DE, AE, IN) and KNC (UK, DE, AE)
  - Source: amazon fba_inventory / KNC fba Inventory year-month folders
  - SKU clean via esh_sku_cleaning / knc_sku_cleaning + COGS sheets
  - Outputs: sanity_data/{CLIENT}/ageing/{GEO}_ageing_inventory.parquet
  - Run log + new-SKU vs COGS under sanity_data/{CLIENT}/logs/

Adding a NEW client (no ETL changes needed):
  1. Add client + geos in client.yaml / geography.yaml / layouts.py
  2. Add one `_xxx_config()` below and register it in CLIENT_CONFIGS
  3. List the client on this report in report.yaml

Style: step-by-step prints (>>> STEP). ETL formulas unchanged.

Run:
    python report_script/common_sanity_report/ageing_report.py
    python report_script/common_sanity_report/ageing_report.py --client ESH
    python report_script/common_sanity_report/ageing_report.py --client KNC --geos UK,DE,AE
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

import numpy as np
import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config_manager.report_helpers import (
    IGNORE_FILE_NAMES,
    IGNORE_FILE_PREFIXES,
    LoadStats,
    coalesce_snake_columns,
    load_existing_parquet_outputs,
    merge_append_dedupe,
)
from config_manager import esh_sku_cleaning, knc_sku_cleaning, paths
from config_manager import layouts
from config_manager.report_helpers import print_script_completed
from report_script.common_sanity_report.new_sku_check import (
    check_final_dataframe_new_skus,
)
from report_script.common_sanity_report.run_logs import ReportRunLog


# =============================================================================
# Run knobs
# =============================================================================

CLIENT: str = "ESH" | "KNC"  # "ESH" | "KNC"
PROCESS_GEOS: Optional[List[str]] = None

VALID_YEARS = {"2023", "2024", "2025", "2026"}
PROCESS_YEARS: Optional[List[str]] = ["2023", "2024", "2025", "2026"]
PROCESS_MONTHS: Optional[List[str]] = None

SAVE_OUTPUT = True
APPLY_TRANSFORM = True
MERGE_WITH_EXISTING = True

PARQUET_NAME_SUFFIX = "ageing_inventory"
MAX_DOS_CAP = 365
DEDUPE_SUBSET = ["client", "geography", "date", "sku"]


# =============================================================================
# Shared column sets (ESH notebook + KNC calculated cols)
# =============================================================================

FINAL_COLUMNS = [
    "date",
    "sku",
    "sell_thru",
    "dos",  # calculated (KNC: DOS_2)
    "available",
    "fc_transfer",
    "days_of_supply",  # Amazon native
    "velocity_trend",
    "velocity_trend_status",
    "daily_velocity_t30",
    "daily_velocity_t60",
    "daily_velocity_t90",
    "inv_age_0_to_30_days",
    "inv_age_31_to_60_days",
    "inv_age_61_to_90_days",
    "inv_age_91_to_180_days",
    "inv_age_181_to_270_days",
    "inv_age_271_to_365_days",
    "inv_age_365_plus_days",
    "units_shipped_t7",
    "units_shipped_t30",
    "units_shipped_t60",
    "units_shipped_t90",
    "recommended_action",
    "estimated_cost_savings_of_recommended_actions",
    "estimated_storage_cost_next_month",
    "healthy_inventory_level",
    "quantity_to_be_charged_ais_181_210_days",
    "estimated_ais_181_210_days",
    "quantity_to_be_charged_ais_211_240_days",
    "estimated_ais_211_240_days",
    "quantity_to_be_charged_ais_241_270_days",
    "estimated_ais_241_270_days",
    "quantity_to_be_charged_ais_271_300_days",
    "estimated_ais_271_300_days",
    "quantity_to_be_charged_ais_301_330_days",
    "estimated_ais_301_330_days",
    "quantity_to_be_charged_ais_331_365_days",
    "estimated_ais_331_365_days",
    "estimated_ais_365_plus_days",
    "quantity_to_be_charged_ais_366_455_days",
    "estimated_ais_366_455_days",
    "quantity_to_be_charged_ais_456_plus_days",
    "estimated_ais_456_plus_days",
]

PIVOT_VALUES = [
    "healthy_inventory_level",
    "days_of_supply",
    "available",
    "fc_transfer",
    "inv_age_0_to_30_days",
    "inv_age_31_to_60_days",
    "inv_age_61_to_90_days",
    "inv_age_91_to_180_days",
    "inv_age_181_to_270_days",
    "inv_age_271_to_365_days",
    "inv_age_365_plus_days",
    "units_shipped_t7",
    "units_shipped_t30",
    "units_shipped_t60",
    "units_shipped_t90",
    "recommended_action",
    "estimated_cost_savings_of_recommended_actions",
    "estimated_storage_cost_next_month",
    "estimated_ais_365_plus_days",
    "quantity_to_be_charged_ais_181_210_days",
    "estimated_ais_181_210_days",
    "quantity_to_be_charged_ais_211_240_days",
    "estimated_ais_211_240_days",
    "quantity_to_be_charged_ais_241_270_days",
    "estimated_ais_241_270_days",
    "quantity_to_be_charged_ais_271_300_days",
    "estimated_ais_271_300_days",
    "quantity_to_be_charged_ais_301_330_days",
    "estimated_ais_301_330_days",
    "quantity_to_be_charged_ais_331_365_days",
    "estimated_ais_331_365_days",
    "quantity_to_be_charged_ais_366_455_days",
    "estimated_ais_366_455_days",
    "quantity_to_be_charged_ais_456_plus_days",
    "estimated_ais_456_plus_days",
]

# Short DE exports (2024/2025) use a reduced Amazon column set
AGEING_COLUMN_ALIASES: Dict[str, str] = {
    "reserved_fc_transfer": "fc_transfer",
    "afn_fc_transfer_quantity": "fc_transfer",
    "inventory_age_snapshot_date": "snapshot_date",
    "inv_age_181_to_330_days": "inv_age_181_to_270_days",
    "inv_age_331_to_365_days": "inv_age_271_to_365_days",
    "quantity_to_be_charged_ais_365_plus_days": "quantity_to_be_charged_ais_456_plus_days",
}


# =============================================================================
# Client configuration
#   New client = copy a builder + register in CLIENT_CONFIGS.
#   Fill geo_roots OR geo_folders + relative_ageing_path.
# =============================================================================

@dataclass
class ClientAgeingConfig:
    client_code: str
    client_id: str
    client_name: str
    base_path: Path
    layout: str
    geo_folders: Dict[str, str] = field(default_factory=dict)
    geo_roots: Dict[str, Path] = field(default_factory=dict)
    cogs_path: Path = field(default_factory=Path)
    cogs_sheets: Dict[str, str] = field(default_factory=dict)
    sku_backend: str = "esh"
    product_name_contains: Dict[str, str] = field(default_factory=dict)
    sku_source_by_geo: Dict[str, str] = field(default_factory=dict)
    relative_ageing_path: Path = field(
        default_factory=lambda: Path("input") / "amazon" / "fba_inventory"
    )


def _esh_config() -> ClientAgeingConfig:
    ident = layouts.client_identity("ESH")
    return ClientAgeingConfig(
        client_code=ident["client_code"],
        client_id=ident["client_id"],
        client_name=ident["client_name"],
        base_path=layouts.data_root("ESH"),
        layout=ident["layout"],
        geo_folders=dict(layouts.ESH_GEO_FOLDERS),
        cogs_path=layouts.cogs_path("ESH"),
        cogs_sheets=layouts.cogs_sheets_for("ESH"),
        sku_backend="esh",
    )


def _knc_config() -> ClientAgeingConfig:
    ident = layouts.client_identity("KNC")
    base = layouts.data_root("KNC")
    return ClientAgeingConfig(
        client_code=ident["client_code"],
        client_id=ident["client_id"],
        client_name=ident["client_name"],
        base_path=base,
        layout=ident["layout"],
        geo_roots=layouts.knc_geo_roots("ageing", base),
        cogs_path=layouts.cogs_path("KNC"),
        cogs_sheets=layouts.cogs_sheets_for("KNC"),
        sku_backend="knc",
        product_name_contains={"AE": "Kinetica"},
        sku_source_by_geo={"AE": "amazon_ae"},
    )


CLIENT_CONFIGS: Dict[str, Callable[[], ClientAgeingConfig]] = {
    "ESH": _esh_config,
    "KNC": _knc_config,
}


def get_client_config(client: str) -> ClientAgeingConfig:
    key = str(client).strip().upper()
    if key not in CLIENT_CONFIGS:
        known = ", ".join(sorted(CLIENT_CONFIGS))
        raise ValueError(f"Unknown client '{client}'. Expected one of: {known}")
    return CLIENT_CONFIGS[key]()


def output_dir_for(client_code: str) -> Path:
    return paths.sanity_data_root() / client_code.upper() / "ageing"


def geo_code_label(geography: str, cfg: ClientAgeingConfig) -> str:
    g = str(geography).strip()
    if g.upper() in {c.upper() for c in cfg.cogs_sheets}:
        for code in cfg.cogs_sheets:
            if code.upper() == g.upper():
                return code
    if cfg.layout == "esh":
        mapped = cfg.geo_folders.get(g.lower())
        if mapped:
            return mapped
    return g.upper()


# =============================================================================
# SKU / COGS
# =============================================================================

def load_client_sku_mapping(
    cfg: ClientAgeingConfig,
    geography_code: Optional[str] = None,
) -> dict:
    geos = [geography_code] if geography_code else list(cfg.cogs_sheets.keys())
    if cfg.sku_backend == "knc":
        return knc_sku_cleaning.load_sku_mapping(geos=geos)
    return esh_sku_cleaning.load_sku_mapping(geos=geos)


def clean_client_skus(
    df: pd.DataFrame,
    cfg: ClientAgeingConfig,
    geography_code: str,
    sku_mapping: Optional[dict] = None,
) -> pd.DataFrame:
    source = cfg.sku_source_by_geo.get(geography_code)
    if cfg.sku_backend == "knc":
        return knc_sku_cleaning.clean_sku_column(
            df, sku_column="sku", sku_mapping=sku_mapping, source=source
        )
    return esh_sku_cleaning.clean_sku_column(
        df, sku_column="sku", sku_mapping=sku_mapping
    )


# =============================================================================
# Discovery / IO
# =============================================================================

def resolve_geo_targets(
    cfg: ClientAgeingConfig,
    geos: Optional[Sequence[str]] = None,
) -> List[Tuple[str, Path]]:
    """Prefer geo_roots when set; else geo_folders + relative_ageing_path."""
    wanted: Optional[Set[str]] = None
    if geos is not None:
        wanted = {str(g).strip().upper() for g in geos}

    targets: List[Tuple[str, Path]] = []

    if cfg.geo_roots:
        for code, root in cfg.geo_roots.items():
            if wanted is not None and code.upper() not in wanted:
                continue
            if not root.is_dir():
                print(f"[WARN] [{cfg.client_code}] Ageing path missing: {root}")
                continue
            targets.append((code, root))
    else:
        for folder, code in cfg.geo_folders.items():
            if wanted is not None and code.upper() not in wanted:
                continue
            root = cfg.base_path / folder / cfg.relative_ageing_path
            if not root.is_dir():
                print(f"[WARN] [{cfg.client_code}] Ageing path missing: {root}")
                continue
            targets.append((code, root))

    return sorted(targets, key=lambda t: t[0])


def discover_year_folders(
    ageing_root: Path,
    years: Optional[Sequence[str]] = None,
) -> List[Path]:
    allowed = set(VALID_YEARS)
    if years is not None:
        allowed &= {str(y) for y in years}
    found: List[Path] = []
    for path in ageing_root.iterdir():
        if path.is_dir() and path.name in allowed:
            found.append(path)
    return sorted(found, key=lambda p: p.name)


def is_ignored_file(file_path: Path) -> bool:
    name = file_path.name
    lower = name.lower()
    if lower in IGNORE_FILE_NAMES:
        return True
    if any(name.startswith(prefix) for prefix in IGNORE_FILE_PREFIXES):
        return True
    if lower in {"fba_inventory.csv", "fba_inventory_aging.csv"}:
        return True
    return False


def _month_filter_tokens(months: Optional[Sequence[str]]) -> Optional[Set[str]]:
    if months is None:
        return None
    tokens: Set[str] = set()
    for raw in months:
        m = str(raw).strip()
        if not m:
            continue
        tokens.add(m.lower())
        if "-" in m:
            tokens.add(m.split("-", 1)[0].lower())
        for fmt in ("%b-%Y", "%b"):
            try:
                parsed = datetime.strptime(m, fmt)
                tokens.add(parsed.strftime("%b").lower())
            except ValueError:
                continue
    return tokens


def discover_ageing_files(
    year_path: Path,
    months: Optional[Sequence[str]] = None,
) -> List[Path]:
    if not year_path.is_dir():
        return []
    wanted = _month_filter_tokens(months)
    files: List[Path] = []
    for path in year_path.rglob("*"):
        if not path.is_file() or path.suffix.lower() != ".csv":
            continue
        if is_ignored_file(path):
            continue
        if wanted is not None:
            rel_parts = {part.lower() for part in path.relative_to(year_path).parts[:-1]}
            name_l = path.name.lower()
            name_hit = any(tok in name_l for tok in wanted)
            if not ((rel_parts & wanted) or name_hit):
                continue
        files.append(path)
    return sorted(files, key=lambda p: p.as_posix().lower())


def _hydrate_onedrive_file(file_path: Path) -> None:
    with open(file_path, "rb") as handle:
        handle.read(1)


def read_ageing_csv(file_path: Path, retries: int = 3) -> pd.DataFrame:
    last_error: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            _hydrate_onedrive_file(file_path)
            for encoding in ("utf-8-sig", "utf-8", "latin1"):
                try:
                    return pd.read_csv(file_path, encoding=encoding)
                except UnicodeDecodeError:
                    continue
            return pd.read_csv(file_path, encoding="latin1")
        except OSError as exc:
            last_error = exc
            if getattr(exc, "errno", None) != 22 and getattr(exc, "winerror", None) != 22:
                raise
            if attempt < retries:
                print(
                    f"  [WARN] OSError 22 reading {file_path.name} "
                    f"(OneDrive sync?) — retry {attempt}/{retries}"
                )
                time.sleep(1.5 * attempt)
                continue
            raise OSError(
                f"Cannot read {file_path} after {retries} attempts (Errno 22). "
                f"Original: {exc}"
            ) from exc
    raise RuntimeError(f"Failed to read {file_path}: {last_error}")


# =============================================================================
# Transform (ETL — do not change formulas when cleaning style)
# =============================================================================

def normalize_headers(df: pd.DataFrame) -> pd.DataFrame:
    """Unify Amazon ageing headers across full vs short (DE 2024/2025) exports."""
    out = coalesce_snake_columns(df)

    rename_map: Dict[str, str] = {}
    for src, dest in AGEING_COLUMN_ALIASES.items():
        if src in out.columns and dest not in out.columns:
            rename_map[src] = dest
        elif src in out.columns and dest in out.columns and src != dest:
            out[dest] = out[dest].combine_first(out[src])
            out = out.drop(columns=[src])
    if rename_map:
        out = out.rename(columns=rename_map)

    if "fc_transfer" not in out.columns and "afn_fc_transfer_quantity" in out.columns:
        out = out.rename(columns={"afn_fc_transfer_quantity": "fc_transfer"})
    return out


def ensure_snapshot_date(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "snapshot_date" not in out.columns:
        for alt in ("inventory_age_snapshot_date", "snapshotdate"):
            if alt in out.columns:
                out["snapshot_date"] = out[alt]
                break
    if "snapshot_date" not in out.columns:
        raise KeyError("Expected snapshot_date column in ageing file")
    out["date"] = (
        pd.to_datetime(out["snapshot_date"], errors="coerce", format="mixed")
        .dt.strftime("%Y-%m-%d")
        .where(lambda s: s.notna(), None)
    )
    return out


def add_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculated columns from knc_ageing.py / ESH ageing notebook:
      sell_thru, dos (DOS_2), daily_velocity_*, velocity_trend(_status)
    """
    out = df.copy()
    for col in ("units_shipped_t30", "units_shipped_t60", "units_shipped_t90", "available"):
        if col not in out.columns:
            out[col] = 0
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0)

    out["sell_thru"] = np.where(
        out["units_shipped_t90"] == 0,
        (out["units_shipped_t30"] / 30 + out["units_shipped_t60"] / 60) / 2,
        (
            out["units_shipped_t30"] / 30
            + out["units_shipped_t60"] / 60
            + out["units_shipped_t90"] / 90
        )
        / 3,
    )

    out["dos"] = np.where(
        out["sell_thru"] > 0,
        np.minimum(out["available"] / out["sell_thru"], MAX_DOS_CAP),
        np.where(out["available"] > 0, MAX_DOS_CAP, 0),
    )

    out["daily_velocity_t30"] = out["units_shipped_t30"] / 30
    out["daily_velocity_t60"] = out["units_shipped_t60"] / 60
    out["daily_velocity_t90"] = np.where(
        out["units_shipped_t90"] == 0,
        out["daily_velocity_t60"],
        out["units_shipped_t90"] / 90,
    )
    out["velocity_trend"] = np.where(
        out["daily_velocity_t90"] != 0,
        out["daily_velocity_t30"] / out["daily_velocity_t90"],
        0,
    )
    out["velocity_trend_status"] = np.where(
        out["velocity_trend"] > 1.2,
        "Accelerating demand (risk of stockout)",
        np.where(
            (out["velocity_trend"] > 0.8) & (out["velocity_trend"] < 1.2),
            "Stable demand",
            "Declining demand (lower restock priority)",
        ),
    )
    return out


def transform_geography_frame(
    geo_df: pd.DataFrame,
    cfg: ClientAgeingConfig,
    geography_code: str,
    sku_mapping: Optional[dict] = None,
) -> pd.DataFrame:
    if geo_df.empty:
        return pd.DataFrame()

    ageing = normalize_headers(geo_df)
    ageing = ensure_snapshot_date(ageing)

    needle = cfg.product_name_contains.get(geography_code)
    if needle:
        name_col = None
        for cand in ("product_name", "productname", "title"):
            if cand in ageing.columns:
                name_col = cand
                break
        if name_col:
            before = len(ageing)
            ageing = ageing[
                ageing[name_col].astype(str).str.contains(needle, case=False, na=False)
            ].copy()
            print(
                f"  [{geography_code}] product_name filter '{needle}': "
                f"{before:,} -> {len(ageing):,}"
            )

    if "sku" not in ageing.columns:
        raise KeyError(f"[{geography_code}] Expected sku column after header normalize")

    if sku_mapping is None:
        sku_mapping = load_client_sku_mapping(cfg, geography_code)

    ageing = clean_client_skus(ageing, cfg, geography_code, sku_mapping=sku_mapping)
    ageing = ageing.dropna(subset=["sku", "date"])

    for col in ["units_shipped_t30", "units_shipped_t60", "units_shipped_t90"]:
        if col not in ageing.columns:
            ageing[col] = 0
        ageing[col] = pd.to_numeric(ageing[col], errors="coerce").fillna(0)

    pivot_cols = list(dict.fromkeys(PIVOT_VALUES))
    for col in pivot_cols:
        if col not in ageing.columns:
            ageing[col] = 0

    agg: Dict[str, str] = {}
    for col in pivot_cols:
        if col == "recommended_action":
            agg[col] = "first"
        else:
            ageing[col] = pd.to_numeric(ageing[col], errors="coerce").fillna(0)
            agg[col] = "sum"

    ageing = (
        pd.pivot_table(
            ageing,
            index=["date", "sku"],
            values=list(agg.keys()),
            aggfunc=agg,
        )
        .reset_index()
    )

    ageing = add_metrics(ageing)
    ageing["geography"] = geography_code
    ageing["client"] = cfg.client_code
    ageing["client_id"] = cfg.client_id
    ageing["platform"] = "amazon"

    for col in FINAL_COLUMNS:
        if col not in ageing.columns:
            ageing[col] = 0

    ordered = ["client", "client_id", "geography", "platform"] + [
        c for c in FINAL_COLUMNS if c in ageing.columns
    ]
    return ageing.loc[:, ordered].drop_duplicates().reset_index(drop=True)


def transform_ageing(
    raw_df: pd.DataFrame,
    cfg: ClientAgeingConfig,
) -> pd.DataFrame:
    if raw_df.empty:
        return pd.DataFrame()

    frames: List[pd.DataFrame] = []
    for geography, geo_df in raw_df.groupby("geography", sort=True):
        code = geo_code_label(str(geography), cfg)
        print(f"\n>>> STEP: transform [{cfg.client_code}] {code} ({len(geo_df):,} raw rows)")
        try:
            sku_mapping = load_client_sku_mapping(cfg, code)
            cleaned = transform_geography_frame(
                geo_df, cfg=cfg, geography_code=code, sku_mapping=sku_mapping
            )
            print(f"  Result: {len(cleaned):,} pivoted rows")
            if not cleaned.empty:
                frames.append(cleaned)
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR transforming {code}: {exc}")

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True, sort=False)


def save_geography_outputs(
    df: pd.DataFrame,
    output_dir: Path,
    name_suffix: str = PARQUET_NAME_SUFFIX,
) -> List[Path]:
    if df.empty:
        print("[WARN] Nothing to save — DataFrame is empty")
        return []
    if "geography" not in df.columns:
        raise KeyError("Expected 'geography' column")

    output_dir.mkdir(parents=True, exist_ok=True)
    saved: List[Path] = []
    print(f"\n>>> STEP: save per-geography ageing → {output_dir}")
    for geography, geo_df in df.groupby("geography", sort=True):
        geo_name = str(geography).upper()
        parquet_path = output_dir / f"{geo_name}_{name_suffix}.parquet"
        geo_df.to_parquet(parquet_path, index=False)
        saved.append(parquet_path)
        print(f"  [{geo_name}] {len(geo_df):,} rows -> {parquet_path.name}")
    return saved


# =============================================================================
# Build pipeline
# =============================================================================

def process_year_folder(
    year_path: Path,
    geography_code: str,
    year: str,
    processed_files: Set[Path],
    failed_files: List[dict],
    stats: LoadStats,
    months: Optional[Sequence[str]] = None,
    *,
    client_code: str = "",
) -> List[pd.DataFrame]:
    client = str(client_code).strip().upper() or "?"
    frames: List[pd.DataFrame] = []
    for file_path in discover_ageing_files(year_path, months=months):
        resolved = file_path.resolve()
        if resolved in processed_files:
            continue
        print(f"[{client}] [{geography_code}] [{year}] Reading {file_path.name}")
        try:
            df = read_ageing_csv(file_path)
            df = normalize_headers(df)
            df = df.copy()
            df["geography"] = geography_code
            df["year"] = int(year) if str(year).isdigit() else year
            df["source_file"] = file_path.name
            df["source_path"] = str(resolved)
            frames.append(df)
            processed_files.add(resolved)
            stats.record_file_ok(geography_code, year, len(df))
        except Exception as exc:  # noqa: BLE001
            print(f"[{client}] [{geography_code}] [{year}] ERROR reading {file_path.name}: {exc}")
            failed_files.append(
                {
                    "path": str(resolved),
                    "geography": geography_code,
                    "year": year,
                    "error": str(exc),
                }
            )
            stats.record_file_failed(geography_code, year)

    if frames:
        stats.record_month_folder(geography_code, year, year_path.name)
    return frames


def build_ageing_dataframe(
    client: str = CLIENT,
    geos: Optional[Sequence[str]] = None,
    years: Optional[Sequence[str]] = None,
    months: Optional[Sequence[str]] = None,
    save_output: bool = SAVE_OUTPUT,
    apply_transform: bool = APPLY_TRANSFORM,
    merge_existing: bool = MERGE_WITH_EXISTING,
    output_dir: Optional[Path] = None,
) -> Tuple[pd.DataFrame, List[dict], LoadStats]:
    cfg = get_client_config(client)
    geos = PROCESS_GEOS if geos is None and PROCESS_GEOS is not None else geos
    years = PROCESS_YEARS if years is None and PROCESS_YEARS is not None else years
    months = PROCESS_MONTHS if months is None and PROCESS_MONTHS is not None else months
    if years is None:
        years = sorted(VALID_YEARS)

    out_dir = output_dir or output_dir_for(cfg.client_code)

    print("=" * 60)
    print(f"Client : {cfg.client_code} ({cfg.client_name})")
    print(f"Script : {Path(__file__).resolve()}")
    print(f"ID     : {cfg.client_id}")
    print(f"Base   : {cfg.base_path}")
    print(f"Years  : {list(years)}")
    print(f"Months : {list(months) if months is not None else 'ALL'}")
    print(f"Geos   : {list(geos) if geos is not None else 'ALL enabled'}")
    print(f"Output : {out_dir}")
    print(f"Merge  : {merge_existing}")
    print("=" * 60)

    all_frames: List[pd.DataFrame] = []
    failed_files: List[dict] = []
    processed_files: Set[Path] = set()
    stats = LoadStats()

    print("\n>>> STEP: load raw ageing files")
    for geo_code, ageing_root in resolve_geo_targets(cfg, geos):
        stats.geographies.add(geo_code)
        print(f"  geo root [{geo_code}]: {ageing_root}")
        for year_path in discover_year_folders(ageing_root, years=years):
            year = year_path.name
            stats.year_folders.add(f"{geo_code}/{year}")
            all_frames.extend(
                process_year_folder(
                    year_path=year_path,
                    geography_code=geo_code,
                    year=year,
                    processed_files=processed_files,
                    failed_files=failed_files,
                    stats=stats,
                    months=months,
                    client_code=cfg.client_code,
                )
            )

    new_df = (
        pd.concat(all_frames, ignore_index=True, sort=False) if all_frames else pd.DataFrame()
    )
    master_df = new_df
    run_log = ReportRunLog(cfg.client_code, "ageing")
    try:
        summary = stats.print_summary(
            title=f"{cfg.client_code} Ageing Inventory Load Summary"
        )
        run_log.append(summary)

        if failed_files:
            print("\nFailed files:")
            run_log.blank()
            run_log.append("Failed files:")
            for item in failed_files:
                line = f"  - {item['path']}: {item['error']}"
                print(line)
                run_log.append(line)

        if apply_transform and not new_df.empty:
            print("\n>>> STEP: transform (SKU clean + pivot + calculated metrics)")
            new_df = transform_ageing(new_df, cfg=cfg)
            print(f"Transformed new slice shape: {new_df.shape}")

        if merge_existing:
            print("\n>>> STEP: merge with existing parquet masters")
            existing_df = load_existing_parquet_outputs(
                out_dir, name_suffix=PARQUET_NAME_SUFFIX
            )
            master_df = merge_append_dedupe(
                existing_df,
                new_df,
                subset=DEDUPE_SUBSET,
            )
        else:
            master_df = new_df

        if not master_df.empty:
            print("\n>>> STEP: new SKU check")
            check_final_dataframe_new_skus(
                master_df,
                client=cfg.client_code,
                label="ageing",
                run_log=run_log,
            )

        if save_output and not master_df.empty:
            save_geography_outputs(master_df, output_dir=out_dir)
    finally:
        run_log.flush()

    print("-" * 60)
    print(f"Done. Master shape: {master_df.shape}")
    return master_df, failed_files, stats


# =============================================================================
# CLI / pipeline entry
# =============================================================================

def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Client-wise ageing inventory combiner")
    parser.add_argument("--client", default=CLIENT, choices=sorted(CLIENT_CONFIGS.keys()))
    parser.add_argument("--geos", default=None, help="Comma-separated geo codes")
    parser.add_argument("--years", default=None, help="Comma-separated years")
    parser.add_argument("--months", default=None, help="Comma-separated month tokens")
    parser.add_argument("--no-merge", action="store_true")
    parser.add_argument("--no-save", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> Tuple[pd.DataFrame, List[dict]]:
    args = parse_args(argv)
    geos = [g.strip() for g in args.geos.split(",")] if args.geos else None
    years = [y.strip() for y in args.years.split(",")] if args.years else None
    months = [m.strip() for m in args.months.split(",")] if args.months else None

    master_df, failed_files, _stats = build_ageing_dataframe(
        client=args.client,
        geos=geos,
        years=years,
        months=months,
        save_output=not args.no_save,
        merge_existing=not args.no_merge,
    )
    print(master_df.shape)
    print(master_df.head())
    print(master_df.columns.tolist())
    return master_df, failed_files


def run_main() -> Tuple[pd.DataFrame, List[dict]]:
    return main()


def run(
    *,
    client: str = CLIENT,
    geos: Optional[Sequence[str]] = None,
    years: Optional[Sequence[str]] = None,
    months: Optional[Sequence[str]] = None,
    **_kwargs,
) -> Tuple[pd.DataFrame, List[dict]]:
    """Pipeline CLI entrypoint: run(client='ESH', geos=['US','UK'])."""
    return main(
        layouts.cli_argv(
            client=client,
            geos=list(geos) if geos else None,
            years=list(years) if years else None,
            months=list(months) if months else None,
        )
    )


if __name__ == "__main__":
    master_ageing_df, failed_files = main()
    print_script_completed("ageing_report")
