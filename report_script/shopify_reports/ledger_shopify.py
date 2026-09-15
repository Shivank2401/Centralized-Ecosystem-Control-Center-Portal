"""
KNC Shopify inventory ledger (UK + IE) — Year archives → ledger masters.

Covers:
  - Client: KNC only (geos with channels.shopify in geography.yaml — UK, IE)
  - Inputs: CSVs under KNC_SHOPIFY_{GEO}_LEDGER_ROOT/Year/{2025,2026}/…
      e.g. Inventory ledger_Apr-2026.csv
      Plus optional root live drops:
      Month-end inventory snapshot- Current Month.csv / Last Month.csv
  - Pipeline: load → concat → normalize Shopify cols → knc_sku_cleaning(shopify) →
              Amazon-style date clean → daily ending_balance agg → merge existing
  - Outputs (same folder as Amazon ledger; separate filenames):
      sanity_data/KNC/ledger/{GEO}_shopify_ledger_inventory.parquet|.csv
    Never overwrites {GEO}_ledger_inventory.*

Run:
    python report_script/shopify_reports/ledger_shopify.py
    python report_script/shopify_reports/ledger_shopify.py --geos UK,IE
    python report_script/shopify_reports/ledger_shopify.py --client KNC --no-merge

Year / month filters: edit PROCESS_YEARS / PROCESS_MONTHS below (same pattern as inventory_shopify).
PROCESS_MONTHS = None means all month files under each year.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

import numpy as np
import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config_manager import knc_sku_cleaning, layouts, paths
from config_manager.report_helpers import (
    IGNORE_FILE_NAMES,
    IGNORE_FILE_PREFIXES,
    LoadStats,
    merge_append_dedupe,
    print_script_completed,
    print_script_failure,
)
from report_script.amazon_reports.new_sku_check import (
    check_final_dataframe_new_skus,
)
from report_script.amazon_reports.run_logs import ReportRunLog

# =============================================================================
# Run knobs
# =============================================================================

CLIENT = "KNC"  # CLI default; pipeline passes client= via run()
PROCESS_GEOS: Optional[List[str]] = None

VALID_YEARS = {"2025", "2026"}
PROCESS_YEARS: Optional[List[str]] = ["2025", "2026"]
PROCESS_MONTHS: Optional[List[str]] = None  # None = all months under each year

SAVE_OUTPUT = True
MERGE_WITH_EXISTING = True
APPLY_TRANSFORM = True
INCLUDE_ROOT_LIVE = True  # Current / Last Month CSVs next to Year/

PARQUET_NAME_SUFFIX = "shopify_ledger_inventory"
DEDUPE_SUBSET = ["client", "geography", "date", "sku"]

YEAR_FOLDER_NAME = "Year"

# Notebook keep-list (normalized names)
USE_COLS = [
    "Product variant sku",
    "Day",
    "Ending inventory units",
    "Days in inventory",
    "Days in stock",
    "Days out of stock",
]

SKU_ALIASES = {"product variant sku", "sku", "product sku"}

MONTH_MAP = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

OUTPUT_COLS = [
    "client",
    "client_id",
    "geography",
    "platform",
    "date",
    "sku",
    "ending_balance",
]


# =============================================================================
# Client configuration
# =============================================================================

@dataclass
class ShopifyLedgerGeoConfig:
    ledger_root_env: str
    currency: str


@dataclass
class ClientShopifyLedgerConfig:
    client_code: str
    client_id: str
    client_name: str
    layout: str
    geos: Dict[str, ShopifyLedgerGeoConfig] = field(default_factory=dict)


def _knc_shopify_ledger_config() -> ClientShopifyLedgerConfig:
    """Geos with channels.shopify from geography.yaml."""
    from config_manager.loader import load_geographies

    ident = layouts.client_identity("KNC")
    geos_cfg: Dict[str, ShopifyLedgerGeoConfig] = {}
    for code, geo in load_geographies("KNC").items():
        if not geo.has_channel("shopify"):
            continue
        geos_cfg[code] = ShopifyLedgerGeoConfig(
            ledger_root_env=f"KNC_SHOPIFY_{code}_LEDGER_ROOT",
            currency=geo.country_currency,
        )
    if not geos_cfg:
        raise ValueError(
            "No KNC geos with channels.shopify in geography.yaml "
            "(expected UK and/or IE)."
        )
    return ClientShopifyLedgerConfig(
        client_code=ident["client_code"],
        client_id=ident["client_id"],
        client_name=ident["client_name"],
        layout=ident["layout"],
        geos=geos_cfg,
    )


CLIENT_CONFIGS: Dict[str, Callable[[], ClientShopifyLedgerConfig]] = {
    "KNC": _knc_shopify_ledger_config,
}


def get_client_config(client: str) -> ClientShopifyLedgerConfig:
    key = str(client).strip().upper()
    if key not in CLIENT_CONFIGS:
        known = ", ".join(sorted(CLIENT_CONFIGS))
        raise ValueError(f"Unknown client '{client}'. Expected one of: {known}")
    return CLIENT_CONFIGS[key]()


def output_dir_for(client_code: str) -> Path:
    """Same folder as Amazon ledger; Shopify uses a different file suffix."""
    return paths.sanity_data_root() / client_code.upper() / "ledger"


# =============================================================================
# Paths / IO
# =============================================================================

def resolve_geo_targets(
    cfg: ClientShopifyLedgerConfig,
    geos: Optional[Sequence[str]] = None,
) -> List[Tuple[str, Path, ShopifyLedgerGeoConfig]]:
    wanted: Optional[Set[str]] = None
    if geos is not None:
        wanted = {str(g).strip().upper() for g in geos}

    shopify_codes = {c.upper() for c in cfg.geos}
    if wanted is not None:
        skipped = sorted(wanted - shopify_codes)
        if skipped:
            print(
                f"[SKIP] Non-Shopify geos (no channels.shopify / not in config): "
                f"{', '.join(skipped)}"
            )

    targets: List[Tuple[str, Path, ShopifyLedgerGeoConfig]] = []
    for code, geo_cfg in cfg.geos.items():
        if wanted is not None and code.upper() not in wanted:
            continue
        try:
            root = paths.knc_shopify_ledger_root(code)
        except EnvironmentError as exc:
            print(f"[WARN] [{cfg.client_code}] [{code}] {exc}")
            continue
        if root is None or not root.is_dir():
            print(
                f"[WARN] [{cfg.client_code}] Shopify ledger path missing for {code}: "
                f"{root} (set {geo_cfg.ledger_root_env} in .env)"
            )
            continue
        targets.append((code, root, geo_cfg))
    return sorted(targets, key=lambda t: t[0])


def year_bucket_root(ledger_root: Path) -> Path:
    """Resolve the Year/ parent that holds 2025, 2026, …"""
    root = ledger_root.resolve()
    if root.name.lower() == YEAR_FOLDER_NAME.lower():
        return root
    nested = root / YEAR_FOLDER_NAME
    if nested.is_dir():
        return nested
    return root


def is_ignored_ledger_file(path: Path) -> bool:
    lower = path.name.lower()
    if lower in IGNORE_FILE_NAMES:
        return True
    return any(lower.startswith(prefix) for prefix in IGNORE_FILE_PREFIXES)


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


def discover_year_folders(
    ledger_root: Path,
    years: Optional[Sequence[str]] = None,
) -> List[Path]:
    year_root = year_bucket_root(ledger_root)
    allowed = set(VALID_YEARS)
    if years is not None:
        allowed &= {str(y).strip() for y in years}

    if not year_root.is_dir():
        return []

    return sorted(
        [p for p in year_root.iterdir() if p.is_dir() and p.name in allowed],
        key=lambda p: p.name,
    )


def discover_ledger_files(
    year_path: Path,
    months: Optional[Sequence[str]] = None,
) -> List[Path]:
    """All CSVs under a year folder (flat or nested Mon-YYYY)."""
    if not year_path.is_dir():
        return []

    wanted = _month_filter_tokens(months)
    files: List[Path] = []
    for path in year_path.rglob("*"):
        if not path.is_file() or path.suffix.lower() != ".csv":
            continue
        if is_ignored_ledger_file(path):
            continue
        if wanted is not None:
            rel_parts = {part.lower() for part in path.relative_to(year_path).parts[:-1]}
            name_l = path.name.lower()
            if not ((rel_parts & wanted) or any(tok in name_l for tok in wanted)):
                continue
        files.append(path)
    return sorted(files, key=lambda p: p.as_posix().lower())


def discover_root_live_files(ledger_root: Path) -> List[Path]:
    """Current / Last Month snapshots sitting next to Year/."""
    root = ledger_root.resolve()
    if root.name.lower() == YEAR_FOLDER_NAME.lower():
        root = root.parent
    if not root.is_dir():
        return []
    files: List[Path] = []
    for path in root.iterdir():
        if not path.is_file() or path.suffix.lower() != ".csv":
            continue
        if is_ignored_ledger_file(path):
            continue
        name_l = path.name.lower()
        if "month-end inventory snapshot" in name_l or "current month" in name_l or "last month" in name_l:
            files.append(path)
    return sorted(files, key=lambda p: p.as_posix().lower())


def _hydrate_onedrive_file(file_path: Path) -> None:
    with open(file_path, "rb") as handle:
        handle.read(1)


def _looks_like_shopify_ledger(columns: Sequence[str]) -> bool:
    norms = {str(c).strip().lower().replace("\ufeff", "") for c in columns}
    has_sku = bool(norms & SKU_ALIASES) or "product variant sku" in norms
    has_day = "day" in norms
    has_units = "ending inventory units" in norms
    # Amazon ledger exports land here occasionally — reject them
    amazonish = {"msku", "fnsku", "disposition", "starting warehouse balance"} & norms
    return has_sku and has_day and has_units and not amazonish


def normalize_shopify_ledger_columns(df: pd.DataFrame) -> pd.DataFrame:
    col_map: Dict[str, str] = {}
    for col in df.columns:
        normalized = str(col).strip().lower().replace("\ufeff", "")
        if normalized in SKU_ALIASES:
            col_map[col] = "Product variant sku"
        elif normalized == "day":
            col_map[col] = "Day"
        elif normalized == "ending inventory units":
            col_map[col] = "Ending inventory units"
        elif normalized == "days in inventory":
            col_map[col] = "Days in inventory"
        elif normalized == "days in stock":
            col_map[col] = "Days in stock"
        elif normalized == "days out of stock":
            col_map[col] = "Days out of stock"
    return df.rename(columns=col_map)


def read_ledger_csv(file_path: Path) -> pd.DataFrame:
    _hydrate_onedrive_file(file_path)
    try:
        raw = pd.read_csv(file_path, dtype=str, low_memory=False)
    except UnicodeDecodeError:
        raw = pd.read_csv(file_path, dtype=str, low_memory=False, encoding="latin1")

    raw.columns = [str(c).strip().replace("\ufeff", "") for c in raw.columns]
    if not _looks_like_shopify_ledger(raw.columns):
        raise ValueError(
            "Not a Shopify ledger export (expected Day + Product variant SKU + "
            f"Ending inventory units). Columns sample: {list(raw.columns)[:8]}"
        )

    raw = normalize_shopify_ledger_columns(raw)
    available = [c for c in USE_COLS if c in raw.columns]
    missing_core = [
        c
        for c in ("Product variant sku", "Day", "Ending inventory units")
        if c not in available
    ]
    if missing_core:
        raise KeyError(f"Missing core columns in {file_path.name}: {missing_core}")
    return raw.loc[:, available].copy()


# =============================================================================
# Date cleaning (Amazon ledger_report style + ISO Shopify Day)
# =============================================================================

def apply_ledger_date_cleaning(ledger_df: pd.DataFrame) -> pd.DataFrame:
    """
    DATE CLEANING aligned with amazon_reports/ledger_report.py.

    Shopify Day is usually ISO YYYY-MM-DD — parse those directly.
    Ambiguous DD/MM or MM/DD strings use the same intentional day/month swap
    as Amazon ledger_report.apply_ledger_date_cleaning.
    """
    ledger_df = ledger_df.copy()
    if "Date" not in ledger_df.columns:
        if "Day" in ledger_df.columns:
            ledger_df["Date"] = ledger_df["Day"]
        else:
            raise KeyError("Expected Date or Day column for date cleaning")

    raw = ledger_df["Date"].astype(str).str.strip()
    iso_mask = raw.str.match(r"^\d{4}[-/.]")
    out = pd.Series(pd.NaT, index=ledger_df.index, dtype="datetime64[ns]")

    if iso_mask.any():
        out.loc[iso_mask] = pd.to_datetime(raw.loc[iso_mask], errors="coerce")

    other = ~iso_mask & raw.notna() & (raw != "") & (raw.str.lower() != "nan")
    if other.any():
        sub = ledger_df.loc[other].copy()
        date_parts = sub["Date"].astype(str).str.split(r"[/-]", expand=True)
        sub["day"] = date_parts[0]
        sub["month"] = date_parts[1]
        sub["year"] = date_parts[2]

        sub["month"] = (
            sub["month"].astype(str).str.strip().str.lower().replace(MONTH_MAP)
        )
        sub["day"] = pd.to_numeric(sub["day"], errors="coerce")
        sub["month"] = pd.to_numeric(sub["month"], errors="coerce")
        sub["year"] = pd.to_numeric(sub["year"], errors="coerce")
        sub["year"] = np.where(sub["year"] < 100, sub["year"] + 2000, sub["year"])

        swap_mask = sub["day"] > 12
        sub.loc[swap_mask, ["month", "day"]] = sub.loc[
            swap_mask, ["day", "month"]
        ].values

        # Intentional Amazon notebook mapping: month=day, day=month
        sub["date"] = pd.to_datetime(
            {
                "year": sub["year"],
                "month": sub["day"],
                "day": sub["month"],
            },
            errors="coerce",
        )
        out.loc[other] = sub["date"]

    ledger_df["date"] = out
    return ledger_df


# =============================================================================
# Transform
# =============================================================================

def transform_geography_frame(
    geo_df: pd.DataFrame,
    cfg: ClientShopifyLedgerConfig,
    geography_code: str,
) -> pd.DataFrame:
    if geo_df.empty:
        return pd.DataFrame()

    print(
        f"\n>>> STEP: transform [{cfg.client_code}] {geography_code} "
        f"({len(geo_df):,} raw rows)"
    )

    work = normalize_shopify_ledger_columns(geo_df)
    work = work.rename(
        columns={
            "Product variant sku": "sku",
            "Day": "Date",
            "Ending inventory units": "ending_balance",
        }
    )
    if "sku" not in work.columns or "Date" not in work.columns:
        raise KeyError(
            f"[{geography_code}] expected sku + Date after rename; "
            f"got {list(work.columns)}"
        )

    work = knc_sku_cleaning.clean_sku_column(work, sku_column="sku", source="shopify")
    print(f"  After knc_sku_cleaning(source=shopify): {len(work):,} rows")

    work = apply_ledger_date_cleaning(work)
    work["ending_balance"] = pd.to_numeric(
        work.get("ending_balance", 0), errors="coerce"
    ).fillna(0)
    work = work.dropna(subset=["sku", "date"])

    ledger_daily = (
        work.groupby(["sku", "date"], as_index=False)["ending_balance"].sum()
    )
    ledger_daily["geography"] = geography_code
    ledger_daily["client"] = cfg.client_code
    ledger_daily["client_id"] = cfg.client_id
    ledger_daily["platform"] = "shopify"
    ledger_daily = ledger_daily.loc[:, OUTPUT_COLS]
    out = ledger_daily.drop_duplicates().reset_index(drop=True)
    print(f"  Result: {len(out):,} daily rows")
    return out


def transform_ledger(
    raw_df: pd.DataFrame,
    cfg: ClientShopifyLedgerConfig,
) -> pd.DataFrame:
    if raw_df.empty:
        return pd.DataFrame()

    frames: List[pd.DataFrame] = []
    for geography, geo_df in raw_df.groupby("geography", sort=True):
        code = str(geography).strip().upper()
        try:
            cleaned = transform_geography_frame(geo_df, cfg=cfg, geography_code=code)
            if not cleaned.empty:
                frames.append(cleaned)
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR transforming {code}: {exc}")

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True, sort=False)


def dedupe_ledger_frame(
    df: pd.DataFrame,
    subset: Sequence[str],
    *,
    label: str,
    keep: str = "last",
) -> pd.DataFrame:
    if df is None or df.empty:
        return df if df is not None else pd.DataFrame()
    present = [c for c in subset if c in df.columns]
    if len(present) != len(subset):
        missing = [c for c in subset if c not in df.columns]
        print(f"  [WARN] {label}: cannot dedupe — missing {missing}")
        return df
    before = len(df)
    out = df.drop_duplicates(subset=list(subset), keep=keep).reset_index(drop=True)
    print(f"  {label}: {before:,} -> {len(out):,} (drop_duplicates keep={keep})")
    return out


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
    print(f"\n>>> STEP: save per-geography Shopify ledger -> {output_dir}")
    for geography, geo_df in df.groupby("geography", sort=True):
        geo_name = str(geography).upper()
        parquet_path = output_dir / f"{geo_name}_{name_suffix}.parquet"
        csv_path = output_dir / f"{geo_name}_{name_suffix}.csv"
        geo_df.to_parquet(parquet_path, index=False)
        geo_df.to_csv(csv_path, index=False)
        saved.extend([parquet_path, csv_path])
        print(f"  [{geo_name}] {len(geo_df):,} rows -> {parquet_path.name}, {csv_path.name}")
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
    for file_path in discover_ledger_files(year_path, months=months):
        resolved = file_path.resolve()
        if resolved in processed_files:
            continue

        print(f"[{client}] [{geography_code}] [{year}] Reading {file_path.name}")
        try:
            df = read_ledger_csv(file_path)
            df = df.copy()
            df["geography"] = geography_code
            df["year"] = int(year) if str(year).isdigit() else year
            df["source_file"] = file_path.name
            df["source_path"] = str(resolved)
            frames.append(df)
            processed_files.add(resolved)
            stats.record_file_ok(geography_code, year, len(df))
        except Exception as exc:  # noqa: BLE001
            print(f"[{client}] [{geography_code}] [{year}] SKIP {file_path.name}: {exc}")
            failed_files.append(
                {
                    "path": str(resolved),
                    "geography": geography_code,
                    "year": year,
                    "error": str(exc),
                }
            )
            stats.record_file_failed(geography_code, year)
            processed_files.add(resolved)

    if frames:
        stats.record_month_folder(geography_code, year, year_path.name)
    return frames


def process_root_live_files(
    ledger_root: Path,
    geography_code: str,
    processed_files: Set[Path],
    failed_files: List[dict],
    stats: LoadStats,
    *,
    client_code: str = "",
) -> List[pd.DataFrame]:
    client = str(client_code).strip().upper() or "?"
    frames: List[pd.DataFrame] = []
    for file_path in discover_root_live_files(ledger_root):
        resolved = file_path.resolve()
        if resolved in processed_files:
            continue
        print(f"[{client}] [{geography_code}] [live] Reading {file_path.name}")
        try:
            df = read_ledger_csv(file_path)
            df = df.copy()
            df["geography"] = geography_code
            df["year"] = "live"
            df["source_file"] = file_path.name
            df["source_path"] = str(resolved)
            frames.append(df)
            processed_files.add(resolved)
            stats.record_file_ok(geography_code, "live", len(df))
        except Exception as exc:  # noqa: BLE001
            print(f"[{client}] [{geography_code}] [live] SKIP {file_path.name}: {exc}")
            failed_files.append(
                {
                    "path": str(resolved),
                    "geography": geography_code,
                    "year": "live",
                    "error": str(exc),
                }
            )
            stats.record_file_failed(geography_code, "live")
            processed_files.add(resolved)
    return frames


def build_ledger_dataframe(
    client: str = CLIENT,
    geos: Optional[Sequence[str]] = None,
    years: Optional[Sequence[str]] = None,
    months: Optional[Sequence[str]] = None,
    save_output: bool = SAVE_OUTPUT,
    apply_transform: bool = APPLY_TRANSFORM,
    merge_existing: bool = MERGE_WITH_EXISTING,
    include_root_live: bool = INCLUDE_ROOT_LIVE,
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
    print(f"ID     : {cfg.client_id}")
    print(f"Years  : {list(years)}")
    print(f"Months : {list(months) if months is not None else 'ALL'}")
    print(f"Geos   : {list(geos) if geos is not None else 'ALL (shopify channels)'}")
    print(f"Shopify geos configured: {', '.join(sorted(cfg.geos))}")
    print(f"Output : {out_dir}")
    print(f"Suffix : {PARQUET_NAME_SUFFIX}  (Amazon ledger_inventory NOT touched)")
    print(f"Merge  : {merge_existing}")
    print(f"Root live Current/Last Month: {include_root_live}")
    print("=" * 60)

    targets = resolve_geo_targets(cfg, geos)
    target_geos = [code for code, _root, _gcfg in targets]
    if not targets:
        print(
            "\n[SKIP] No Shopify ledger geos to process for this selection "
            f"(configured={sorted(cfg.geos)}, requested={list(geos) if geos else 'ALL'})."
        )
        return pd.DataFrame(), [], LoadStats()

    print(f"\n>>> STEP: run Shopify ledger for geos={target_geos} only")

    all_frames: List[pd.DataFrame] = []
    failed_files: List[dict] = []
    processed_files: Set[Path] = set()
    stats = LoadStats()
    run_log = ReportRunLog(cfg.client_code, "shopify_ledger")

    print("\n>>> STEP: load Year/{year} CSVs (+ optional root live)")
    for geo_code, ledger_root, geo_cfg in targets:
        stats.geographies.add(geo_code)
        year_root = year_bucket_root(ledger_root)
        print(f"  [{geo_code}] ledger_root={ledger_root}")
        print(f"  [{geo_code}] year_root={year_root}  env={geo_cfg.ledger_root_env}")

        if include_root_live:
            all_frames.extend(
                process_root_live_files(
                    ledger_root=ledger_root,
                    geography_code=geo_code,
                    processed_files=processed_files,
                    failed_files=failed_files,
                    stats=stats,
                    client_code=cfg.client_code,
                )
            )

        year_folders = discover_year_folders(ledger_root, years=years)
        if not year_folders:
            print(f"  [WARN] [{geo_code}] no Year folders for {list(years)} under {year_root}")
        for year_path in year_folders:
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

    raw_df = (
        pd.concat(all_frames, ignore_index=True, sort=False) if all_frames else pd.DataFrame()
    )
    print(f"\n>>> STEP: appended raw Shopify ledger shape: {raw_df.shape}")

    master_df = raw_df
    try:
        summary = stats.print_summary(
            title=f"{cfg.client_code} Shopify Ledger Load Summary"
        )
        run_log.append(summary)

        if failed_files:
            print("\nFailed / skipped files:")
            run_log.blank()
            run_log.append("Failed / skipped files:")
            for item in failed_files:
                line = f"  - {item['path']}: {item['error']}"
                print(line)
                run_log.append(line)

        if apply_transform and not raw_df.empty:
            print("\n>>> STEP: transform (SKU clean + date clean + daily agg)")
            new_df = transform_ledger(raw_df, cfg=cfg)
            print(f"Transformed new slice shape: {new_df.shape}")
        else:
            new_df = raw_df

        print("\n>>> STEP: dedupe new slice before append (keys=client,geography,date,sku)")
        new_df = dedupe_ledger_frame(
            new_df, DEDUPE_SUBSET, label="new slice", keep="last"
        )

        if merge_existing:
            print("\n>>> STEP: merge with existing parquet masters (run geos only)")
            frames = []
            print(f"Loading existing Shopify ledger for geos={target_geos} from: {out_dir}")
            for code in target_geos:
                path = out_dir / f"{code}_{PARQUET_NAME_SUFFIX}.parquet"
                if not path.is_file():
                    print(f"  [{code}] no existing {path.name}")
                    continue
                try:
                    df = pd.read_parquet(path)
                    print(f"  [{path.name}] {len(df):,} rows")
                    frames.append(df)
                except Exception as exc:  # noqa: BLE001
                    print(f"  [WARN] Could not read {path.name}: {exc}")
            existing_df = (
                pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()
            )
            if existing_df is not None and not existing_df.empty:
                print("\n>>> STEP: dedupe existing master before append")
                existing_df = dedupe_ledger_frame(
                    existing_df, DEDUPE_SUBSET, label="existing master", keep="last"
                )
            master_df = merge_append_dedupe(
                existing_df,
                new_df,
                subset=DEDUPE_SUBSET,
            )
            if "geography" in master_df.columns:
                master_df = master_df.loc[
                    master_df["geography"].astype(str).str.upper().isin(
                        {g.upper() for g in target_geos}
                    )
                ].reset_index(drop=True)
        else:
            master_df = new_df

        if not master_df.empty:
            print("\n>>> STEP: new SKU check vs Shopify COGS")
            check_final_dataframe_new_skus(
                master_df,
                client=cfg.client_code,
                label="shopify_ledger",
                channel="shopify",
                run_log=run_log,
            )

        if save_output and not master_df.empty:
            saved = save_geography_outputs(master_df, output_dir=out_dir)
            run_log.append(f"Saved {len(saved)} file(s) under {out_dir}")
        elif save_output:
            print("[WARN] Skip save - master empty")

        print("-" * 60)
        print(f"Done. Master shape: {master_df.shape}")
        return master_df, failed_files, stats
    finally:
        run_log.flush()


def run(
    client: str = CLIENT,
    geos: Optional[Sequence[str]] = None,
    years: Optional[Sequence[str]] = None,
    months: Optional[Sequence[str]] = None,
    save_output: bool = SAVE_OUTPUT,
    apply_transform: bool = APPLY_TRANSFORM,
    merge_existing: bool = MERGE_WITH_EXISTING,
    include_root_live: bool = INCLUDE_ROOT_LIVE,
    output_dir: Optional[Path] = None,
    **_kwargs,
) -> pd.DataFrame:
    master, _failed, _stats = build_ledger_dataframe(
        client=client,
        geos=geos,
        years=years,
        months=months,
        save_output=save_output,
        apply_transform=apply_transform,
        merge_existing=merge_existing,
        include_root_live=include_root_live,
        output_dir=output_dir,
    )
    return master


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="KNC Shopify ledger -> ledger masters"
    )
    parser.add_argument("--client", default=CLIENT, help="Client code (KNC)")
    parser.add_argument("--geos", default=None, help="Comma-separated geos, e.g. UK,IE")
    parser.add_argument(
        "--years",
        default=None,
        help="Optional override of PROCESS_YEARS (comma-separated). Omit to use script knobs.",
    )
    parser.add_argument("--no-merge", action="store_true", help="Do not merge existing parquet")
    parser.add_argument(
        "--no-root-live",
        action="store_true",
        help="Skip Month-end Current/Last Month CSVs at ledger root",
    )
    parser.add_argument("--no-save", action="store_true", help="Skip writing outputs")
    return parser.parse_args(argv)


if __name__ == "__main__":
    try:
        args = parse_args()
        geos = [g.strip().upper() for g in args.geos.split(",") if g.strip()] if args.geos else None
        years = [y.strip() for y in args.years.split(",") if y.strip()] if args.years else None
        run(
            client=args.client,
            geos=geos,
            years=years,
            months=None,
            save_output=not args.no_save,
            merge_existing=not args.no_merge,
            include_root_live=not args.no_root_live,
        )
        print_script_completed(
            "ledger_shopify",
            detail=(
                f"client={args.client} geos={geos or 'ALL'} "
                f"years={years or PROCESS_YEARS or sorted(VALID_YEARS)} "
                f"months={PROCESS_MONTHS or 'ALL'}"
            ),
        )
    except Exception as exc:  # noqa: BLE001
        print_script_failure(exc, script_hint="ledger_shopify")
        raise

