"""
KNC Shopify inventory (UK + IE) — Year archives + live drop → manage_fba masters.

Covers:
  - Client: KNC only (geos with channels.shopify in geography.yaml — UK, IE)
  - Inputs: dated CSVs under KNC_SHOPIFY_{GEO}_INVENTORY_ROOT/Year/{2025,2026}/…
      (all month folders; append like manage_fba_report) plus optional live drop
  - Archive (live drop): {ROOT}/Year/{YYYY}/{Mon-YYYY}/Shopify_inventory_{stamp}.csv
      stamp = T-1 for US/CA, else T (same rule as saving_raw_file_on_date)
  - Pipeline: load all files → concat → not-stocked filter → knc_sku_cleaning(shopify) →
              AFN rename → numeric qty → total → pivot → merge existing
  - Outputs (same folder as Amazon manage_fba; separate filenames):
      sanity_data/KNC/manage_fba/{GEO}_inventory_shopify.parquet|.csv
    Never overwrites {GEO}_manage_fba_inventory.*

Run:
    python report_script/shopify_reports/inventory_shopify.py
    python report_script/shopify_reports/inventory_shopify.py --geos UK,IE
    python report_script/shopify_reports/inventory_shopify.py --client KNC --no-merge

Year / month filters: edit PROCESS_YEARS / PROCESS_MONTHS below (same pattern as ageing_report).
PROCESS_MONTHS = None means all month folders under each year.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

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
    to_snake,
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
ARCHIVE_DATED = True

PARQUET_NAME_SUFFIX = "inventory_shopify"
DEDUPE_SUBSET = ["client", "geography", "date", "sku"]

LIVE_FILENAME = "inventory_shopify.csv"
YEAR_FOLDER_NAME = "Year"
_DATE_IN_NAME = re.compile(r"(\d{2}-[A-Za-z]{3}-\d{4})")

USE_COLS = [
    "SKU",
    "Location",
    "Incoming (not editable)",
    "Unavailable (not editable)",
    "Committed (not editable)",
    "Available (not editable)",
    "On hand (current)",
]

QTY_COLS_CLEAN = ["Incoming", "Unavailable", "Committed", "Available", "On hand"]

RENAME_TO_AFN = {
    "Incoming": "afn-inbound-receiving-quantity",
    "Available": "afn-fulfillable-quantity",
    "Unavailable": "afn-unsellable-quantity",
    "Committed": "afn-reserved-quantity",
    "On hand": "afn-warehouse-quantity",
}

AFN_QTY_HYPHEN = [
    "afn-inbound-receiving-quantity",
    "afn-fulfillable-quantity",
    "afn-unsellable-quantity",
    "afn-reserved-quantity",
    "afn-warehouse-quantity",
    "afn-total-quantity",
]

OUTPUT_FRONT = ["client", "client_id", "geography", "platform", "date", "sku"]


# =============================================================================
# Date stamp (US/CA → T-1, else T)
# =============================================================================

def inventory_as_of_date(geo: str, *, now: Optional[datetime] = None) -> datetime:
    """US/CA use yesterday; all other geos (UK, IE, …) use today."""
    base = now or datetime.now()
    if str(geo).strip().upper() in {"US", "CA"}:
        return base - timedelta(days=1)
    return base


def inventory_date_stamp(geo: str, *, now: Optional[datetime] = None) -> str:
    return inventory_as_of_date(geo, now=now).strftime("%d-%b-%Y")


# =============================================================================
# Client configuration
# =============================================================================

@dataclass
class ShopifyInventoryGeoConfig:
    inventory_root_env: str
    currency: str


@dataclass
class ClientShopifyInventoryConfig:
    client_code: str
    client_id: str
    client_name: str
    layout: str
    geos: Dict[str, ShopifyInventoryGeoConfig] = field(default_factory=dict)


def _knc_shopify_inventory_config() -> ClientShopifyInventoryConfig:
    """Geos with channels.shopify from geography.yaml."""
    from config_manager.loader import load_geographies

    ident = layouts.client_identity("KNC")
    geos_cfg: Dict[str, ShopifyInventoryGeoConfig] = {}
    for code, geo in load_geographies("KNC").items():
        if not geo.has_channel("shopify"):
            continue
        geos_cfg[code] = ShopifyInventoryGeoConfig(
            inventory_root_env=f"KNC_SHOPIFY_{code}_INVENTORY_ROOT",
            currency=geo.country_currency,
        )
    if not geos_cfg:
        raise ValueError(
            "No KNC geos with channels.shopify in geography.yaml "
            "(expected UK and/or IE)."
        )
    return ClientShopifyInventoryConfig(
        client_code=ident["client_code"],
        client_id=ident["client_id"],
        client_name=ident["client_name"],
        layout=ident["layout"],
        geos=geos_cfg,
    )


CLIENT_CONFIGS: Dict[str, Callable[[], ClientShopifyInventoryConfig]] = {
    "KNC": _knc_shopify_inventory_config,
}


def get_client_config(client: str) -> ClientShopifyInventoryConfig:
    key = str(client).strip().upper()
    if key not in CLIENT_CONFIGS:
        known = ", ".join(sorted(CLIENT_CONFIGS))
        raise ValueError(f"Unknown client '{client}'. Expected one of: {known}")
    return CLIENT_CONFIGS[key]()


def output_dir_for(client_code: str) -> Path:
    """Same folder as Amazon manage_fba; Shopify uses a different file suffix."""
    return paths.sanity_data_root() / client_code.upper() / "manage_fba"


# =============================================================================
# Paths / IO
# =============================================================================

def resolve_geo_targets(
    cfg: ClientShopifyInventoryConfig,
    geos: Optional[Sequence[str]] = None,
) -> List[Tuple[str, Path, ShopifyInventoryGeoConfig]]:
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

    targets: List[Tuple[str, Path, ShopifyInventoryGeoConfig]] = []
    for code, geo_cfg in cfg.geos.items():
        if wanted is not None and code.upper() not in wanted:
            continue
        try:
            root = paths.knc_shopify_inventory_root(code)
        except EnvironmentError as exc:
            print(f"[WARN] [{cfg.client_code}] [{code}] {exc}")
            continue
        if root is None or not root.is_dir():
            print(
                f"[WARN] [{cfg.client_code}] Shopify inventory path missing for {code}: "
                f"{root} (set {geo_cfg.inventory_root_env} in .env)"
            )
            continue
        targets.append((code, root, geo_cfg))
    return sorted(targets, key=lambda t: t[0])


def year_bucket_root(inventory_root: Path) -> Path:
    """
    Resolve the Year/ parent that holds 2025, 2026, …
    Env may point at …/inventory or …/inventory/Year.
    """
    root = inventory_root.resolve()
    if root.name.lower() == YEAR_FOLDER_NAME.lower():
        return root
    nested = root / YEAR_FOLDER_NAME
    if nested.is_dir():
        return nested
    return root


def live_inventory_path(inventory_root: Path) -> Path:
    """Live drop sits next to Year/ (or inside root if env already is Year)."""
    root = inventory_root.resolve()
    if root.name.lower() == YEAR_FOLDER_NAME.lower():
        return root.parent / LIVE_FILENAME
    return root / LIVE_FILENAME


def is_ignored_inventory_file(path: Path) -> bool:
    lower = path.name.lower()
    if lower == LIVE_FILENAME.lower():
        return True
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
    inventory_root: Path,
    years: Optional[Sequence[str]] = None,
) -> List[Path]:
    year_root = year_bucket_root(inventory_root)
    allowed = set(VALID_YEARS)
    if years is not None:
        allowed &= {str(y).strip() for y in years}

    if not year_root.is_dir():
        return []

    return sorted(
        [
            p
            for p in year_root.iterdir()
            if p.is_dir() and p.name in allowed
        ],
        key=lambda p: p.name,
    )


def discover_inventory_files(
    year_path: Path,
    months: Optional[Sequence[str]] = None,
) -> List[Path]:
    """All CSVs under a year folder (Mon-YYYY / apr / flat)."""
    if not year_path.is_dir():
        return []

    wanted = _month_filter_tokens(months)
    files: List[Path] = []
    for path in year_path.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() != ".csv":
            continue
        if is_ignored_inventory_file(path):
            continue
        if wanted is not None:
            rel_parts = {part.lower() for part in path.relative_to(year_path).parts[:-1]}
            name_l = path.name.lower()
            if not ((rel_parts & wanted) or any(tok in name_l for tok in wanted)):
                continue
        files.append(path)
    return sorted(files, key=lambda p: p.as_posix().lower())


def date_from_filename(path: Path) -> Optional[datetime]:
    match = _DATE_IN_NAME.search(path.stem)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%d-%b-%Y")
    except ValueError:
        return None


def _hydrate_onedrive_file(file_path: Path) -> None:
    with open(file_path, "rb") as handle:
        handle.read(1)


def read_inventory_csv(file_path: Path) -> pd.DataFrame:
    _hydrate_onedrive_file(file_path)
    try:
        raw = pd.read_csv(file_path, usecols=USE_COLS, dtype=str, low_memory=False)
    except ValueError:
        try:
            raw = pd.read_csv(file_path, dtype=str, low_memory=False)
        except UnicodeDecodeError:
            raw = pd.read_csv(file_path, dtype=str, low_memory=False, encoding="latin1")
        missing = [c for c in USE_COLS if c not in raw.columns]
        if missing:
            # Archived files may already have cleaned headers (no "(not editable)")
            cleaned_needed = ["SKU"] + QTY_COLS_CLEAN
            alt_missing = [c for c in cleaned_needed if c not in raw.columns]
            if alt_missing:
                raise KeyError(f"Missing columns in {file_path.name}: {missing}") from None
            raw = raw.loc[:, [c for c in cleaned_needed if c in raw.columns]]
            raw.columns = [str(c).strip().replace("\ufeff", "") for c in raw.columns]
            return raw
        raw = raw.loc[:, USE_COLS]
    except UnicodeDecodeError:
        raw = pd.read_csv(
            file_path, usecols=USE_COLS, dtype=str, low_memory=False, encoding="latin1"
        )

    raw.columns = [str(c).split("(")[0].strip().replace("\ufeff", "") for c in raw.columns]
    return raw


def archive_dated_raw(
    df: pd.DataFrame,
    inventory_root: Path,
    geo: str,
    *,
    now: Optional[datetime] = None,
) -> Path:
    """Save cleaned-header live drop under {ROOT}/Year/{YYYY}/{Mon-YYYY}/."""
    as_of = inventory_as_of_date(geo, now=now)
    stamp = as_of.strftime("%d-%b-%Y")
    year = as_of.strftime("%Y")
    mon_yyyy = as_of.strftime("%b-%Y")
    folder = year_bucket_root(inventory_root) / year / mon_yyyy
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"Shopify_inventory_{stamp}.csv"
    df.to_csv(out, index=False)
    return out


# =============================================================================
# Transform
# =============================================================================

def _extract_date_from_source(df: pd.DataFrame) -> pd.Series:
    """Parse dd-Mon-YYYY from source_file (same idea as manage_fba _extract_date)."""
    if "source_file" not in df.columns:
        raise KeyError("Expected source_file column for date extraction")
    date_raw = (
        df["source_file"]
        .astype(str)
        .str.extract(r"(\d{2}-[A-Za-z]{3}-\d{4})", expand=False)
    )
    return pd.to_datetime(date_raw, format="%d-%b-%Y", errors="coerce")


def transform_geography_shopify_inventory(
    raw: pd.DataFrame,
    *,
    cfg: ClientShopifyInventoryConfig,
    geography_code: str,
) -> pd.DataFrame:
    """
    Clean + pivot one geography slice of the appended raw frame.
    Date comes from source_file filename (Shopify_inventory_10-Sep-2026.csv).
    """
    print(
        f"\n>>> STEP: transform [{cfg.client_code}] {geography_code} "
        f"({len(raw):,} raw rows)"
    )

    needed = ["SKU"] + QTY_COLS_CLEAN
    missing = [c for c in needed if c not in raw.columns]
    if missing:
        raise KeyError(f"[{geography_code}] missing columns after header clean: {missing}")

    keep_meta = [c for c in ("source_file", "year", "month") if c in raw.columns]
    df = raw.loc[:, needed + keep_meta].copy()

    df["date"] = _extract_date_from_source(df)
    bad_dates = int(df["date"].isna().sum())
    if bad_dates:
        print(f"  [WARN] Dropping {bad_dates:,} rows with unparseable source_file date")
        df = df.loc[df["date"].notna()].copy()
    if df.empty:
        print("  Result: 0 pivoted rows (no dated rows)")
        return pd.DataFrame()

    # Drop rows where every qty cell is the Shopify "not stocked" sentinel
    not_stocked = df[QTY_COLS_CLEAN].apply(
        lambda row: all(str(x).strip().lower() == "not stocked" for x in row),
        axis=1,
    )
    before = len(df)
    df = df.loc[~not_stocked].copy()
    print(f"  Dropped 'not stocked' rows: {before - len(df):,} (kept {len(df):,})")

    df = df.rename(columns={"SKU": "sku"})
    df = knc_sku_cleaning.clean_sku_column(df, sku_column="sku", source="shopify")
    print(f"  After knc_sku_cleaning(source=shopify): {len(df):,} rows")

    df["platform"] = "shopify"
    df["geography"] = geography_code

    df = df.rename(columns=RENAME_TO_AFN)
    for col in AFN_QTY_HYPHEN:
        if col == "afn-total-quantity":
            continue
        if col not in df.columns:
            df[col] = 0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    df["afn-total-quantity"] = (
        df["afn-warehouse-quantity"] + df["afn-inbound-receiving-quantity"]
    )

    value_cols = [to_snake(c) for c in AFN_QTY_HYPHEN]
    work = df.copy()
    work.columns = [
        to_snake(c) if str(c).startswith("afn-") else c for c in work.columns
    ]

    pivoted = (
        pd.pivot_table(
            work,
            index=["sku", "platform", "geography", "date"],
            values=value_cols,
            aggfunc="sum",
        )
        .reset_index()
    )

    pivoted["client"] = cfg.client_code
    pivoted["client_id"] = cfg.client_id

    rest = [c for c in pivoted.columns if c not in OUTPUT_FRONT]
    out = pivoted.loc[:, OUTPUT_FRONT + rest]
    print(f"  Result: {len(out):,} pivoted rows")
    return out


def transform_shopify_inventory(
    raw_df: pd.DataFrame,
    cfg: ClientShopifyInventoryConfig,
) -> pd.DataFrame:
    """Transform appended raw (all geos) — same structure as transform_manage_fba."""
    if raw_df.empty:
        return pd.DataFrame()

    frames: List[pd.DataFrame] = []
    for geography, geo_df in raw_df.groupby("geography", sort=True):
        code = str(geography).strip().upper()
        try:
            cleaned = transform_geography_shopify_inventory(
                geo_df, cfg=cfg, geography_code=code
            )
            if not cleaned.empty:
                frames.append(cleaned)
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR transforming {code}: {exc}")

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True, sort=False)


def dedupe_inventory_frame(
    df: pd.DataFrame,
    subset: Sequence[str] = DEDUPE_SUBSET,
    *,
    label: str = "frame",
    keep: str = "last",
) -> pd.DataFrame:
    """
    Drop duplicate inventory keys within one frame.
    Same key set as manage_fba_report.DEDUPE_SUBSET:
      client, geography, date, sku
    """
    if df is None or df.empty:
        return pd.DataFrame() if df is None else df

    out = df.copy()
    if "date" in out.columns:
        out["date"] = pd.to_datetime(out["date"], errors="coerce")

    usable = [c for c in subset if c in out.columns]
    before = len(out)
    if usable:
        out = out.drop_duplicates(subset=usable, keep=keep).reset_index(drop=True)
    else:
        out = out.drop_duplicates(keep=keep).reset_index(drop=True)
    removed = before - len(out)
    print(
        f"  Dedupe [{label}] on {usable or 'all columns'}: "
        f"{before:,} -> {len(out):,} (removed {removed:,})"
    )
    return out


def save_geography_outputs(
    df: pd.DataFrame,
    output_dir: Path,
    name_suffix: str = PARQUET_NAME_SUFFIX,
) -> List[Path]:
    if df.empty:
        print("[WARN] Nothing to save - DataFrame is empty")
        return []
    if "geography" not in df.columns:
        raise KeyError("Expected 'geography' column")

    output_dir.mkdir(parents=True, exist_ok=True)
    saved: List[Path] = []
    print(f"\n>>> STEP: save per-geography Shopify inventory -> {output_dir}")
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
# Build pipeline (manage_fba-style: load all -> concat -> transform -> save)
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
    """Read every CSV under Year/{year}/… into frames (no ETL yet)."""
    client = str(client_code).strip().upper() or "?"
    frames: List[pd.DataFrame] = []
    for file_path in discover_inventory_files(year_path, months=months):
        resolved = file_path.resolve()
        if resolved in processed_files:
            continue

        parent = file_path.parent.name
        month_label = parent if parent != year else "files"

        print(f"[{client}] [{geography_code}] [{year}] [{month_label}] Reading {file_path.name}")
        try:
            df = read_inventory_csv(file_path)
            df = df.copy()
            df["geography"] = geography_code
            df["year"] = int(year) if str(year).isdigit() else year
            df["month"] = month_label
            df["source_file"] = file_path.name
            df["source_path"] = str(resolved)
            frames.append(df)
            processed_files.add(resolved)
            stats.record_file_ok(geography_code, year, len(df))
        except Exception as exc:  # noqa: BLE001
            print(
                f"[{client}] [{geography_code}] [{year}] [{month_label}] "
                f"ERROR reading {file_path.name}: {exc}"
            )
            failed_files.append(
                {
                    "path": str(resolved),
                    "geography": geography_code,
                    "year": year,
                    "month": month_label,
                    "error": str(exc),
                }
            )
            stats.record_file_failed(geography_code, year)
            processed_files.add(resolved)

    if frames:
        stats.record_month_folder(geography_code, year, year_path.name)
    return frames


def build_shopify_inventory_dataframe(
    client: str = CLIENT,
    geos: Optional[Sequence[str]] = None,
    years: Optional[Sequence[str]] = None,
    months: Optional[Sequence[str]] = None,
    save_output: bool = SAVE_OUTPUT,
    apply_transform: bool = APPLY_TRANSFORM,
    merge_existing: bool = MERGE_WITH_EXISTING,
    archive_dated: bool = ARCHIVE_DATED,
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
    print(f"Suffix : {PARQUET_NAME_SUFFIX}  (Amazon manage_fba_inventory NOT touched)")
    print(f"Merge  : {merge_existing}")
    print(f"Archive: {archive_dated}")
    print("=" * 60)

    targets = resolve_geo_targets(cfg, geos)
    target_geos = [code for code, _root, _gcfg in targets]
    if not targets:
        print(
            "\n[SKIP] No Shopify inventory geos to process for this selection "
            f"(configured={sorted(cfg.geos)}, requested={list(geos) if geos else 'ALL'})."
        )
        return pd.DataFrame(), [], LoadStats()

    print(f"\n>>> STEP: run Shopify inventory for geos={target_geos} only")

    all_frames: List[pd.DataFrame] = []
    failed_files: List[dict] = []
    processed_files: Set[Path] = set()
    stats = LoadStats()
    run_log = ReportRunLog(cfg.client_code, "shopify_inventory")

    print("\n>>> STEP: optional live archive, then load Year/{year}/all months CSVs")
    for geo_code, inv_root, geo_cfg in targets:
        stats.geographies.add(geo_code)
        year_root = year_bucket_root(inv_root)
        live = live_inventory_path(inv_root)
        stamp = inventory_date_stamp(geo_code)
        print(f"  [{geo_code}] inventory_root={inv_root}")
        print(f"  [{geo_code}] year_root={year_root}  env={geo_cfg.inventory_root_env}")
        print(f"  [{geo_code}] live={live}  archive_stamp={stamp}")

        if archive_dated and live.is_file():
            try:
                print(f"\n>>> STEP: [{cfg.client_code}] [{geo_code}] archive live -> Year/…")
                raw_live = read_inventory_csv(live)
                archived = archive_dated_raw(raw_live, inv_root, geo_code)
                print(f"  Wrote {archived}")
            except Exception as exc:  # noqa: BLE001
                print(f"  [WARN] archive failed [{geo_code}]: {exc}")
                failed_files.append(
                    {"path": str(live), "geography": geo_code, "error": f"archive: {exc}"}
                )
        elif archive_dated:
            print(f"  [WARN] [{geo_code}] live file missing (skip archive): {live}")

        year_folders = discover_year_folders(inv_root, years=years)
        if not year_folders:
            print(f"  [WARN] [{geo_code}] no Year folders for {list(years)} under {year_root}")
            continue

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
    print(f"\n>>> STEP: appended raw Shopify inventory shape: {raw_df.shape}")
    if not raw_df.empty and "source_file" in raw_df.columns:
        # Visibility: calendar year from filename (not Year/ folder name)
        _dates = (
            raw_df["source_file"]
            .astype(str)
            .str.extract(r"(\d{2}-[A-Za-z]{3}-\d{4})", expand=False)
        )
        _parsed = pd.to_datetime(_dates, format="%d-%b-%Y", errors="coerce")
        print("  Date coverage from filenames (rows by calendar year):")
        for geo_code, geo_df in raw_df.assign(_d=_parsed).groupby("geography", sort=True):
            years_counts = (
                geo_df["_d"].dt.year.value_counts(dropna=False).sort_index()
            )
            parts = ", ".join(
                f"{int(y) if pd.notna(y) else 'BAD'}={int(n):,}"
                for y, n in years_counts.items()
            )
            print(f"    [{geo_code}] {parts}")

    master_df = raw_df
    try:
        summary = stats.print_summary(
            title=f"{cfg.client_code} Shopify Inventory Load Summary"
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

        if apply_transform and not raw_df.empty:
            print("\n>>> STEP: transform (not-stocked filter + SKU clean + AFN rename + pivot)")
            new_df = transform_shopify_inventory(raw_df, cfg=cfg)
            print(f"Transformed new slice shape: {new_df.shape}")
        else:
            new_df = raw_df

        # Same intent as manage_fba_report transform drop_duplicates + DEDUPE_SUBSET merge:
        # 1) dedupe new slice on keys before append
        # 2) merge_append_dedupe(existing, new) — concat then drop_duplicates keep='last'
        print("\n>>> STEP: dedupe new slice before append (keys=client,geography,date,sku)")
        new_df = dedupe_inventory_frame(
            new_df, DEDUPE_SUBSET, label="new slice", keep="last"
        )

        if merge_existing:
            print("\n>>> STEP: merge with existing parquet masters (run geos only)")
            # Load only this run's geo masters (same idea as shopify orders)
            frames = []
            print(f"Loading existing Shopify inventory for geos={target_geos} from: {out_dir}")
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
                existing_df = dedupe_inventory_frame(
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
                label="shopify_inventory",
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
    archive_dated: bool = ARCHIVE_DATED,
    output_dir: Optional[Path] = None,
    **_kwargs,
) -> pd.DataFrame:
    master, _failed, _stats = build_shopify_inventory_dataframe(
        client=client,
        geos=geos,
        years=years,
        months=months,
        save_output=save_output,
        apply_transform=apply_transform,
        merge_existing=merge_existing,
        archive_dated=archive_dated,
        output_dir=output_dir,
    )
    return master


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="KNC Shopify inventory -> manage_fba masters")
    parser.add_argument("--client", default=CLIENT, help="Client code (KNC)")
    parser.add_argument("--geos", default=None, help="Comma-separated geos, e.g. UK,IE")
    parser.add_argument(
        "--years",
        default=None,
        help="Optional override of PROCESS_YEARS (comma-separated). Omit to use script knobs.",
    )
    parser.add_argument("--no-merge", action="store_true", help="Do not merge existing parquet")
    parser.add_argument("--no-archive", action="store_true", help="Skip dated raw archive")
    parser.add_argument("--no-save", action="store_true", help="Skip writing outputs")
    return parser.parse_args(argv)


if __name__ == "__main__":
    try:
        args = parse_args()
        geos = [g.strip().upper() for g in args.geos.split(",") if g.strip()] if args.geos else None
        years = [y.strip() for y in args.years.split(",") if y.strip()] if args.years else None
        # Months: edit PROCESS_MONTHS in the script knobs (None = all months). No CLI --months.
        run(
            client=args.client,
            geos=geos,
            years=years,
            months=None,
            save_output=not args.no_save,
            merge_existing=not args.no_merge,
            archive_dated=not args.no_archive,
        )
        print_script_completed(
            "inventory_shopify",
            detail=(
                f"client={args.client} geos={geos or 'ALL'} "
                f"years={years or PROCESS_YEARS or sorted(VALID_YEARS)} "
                f"months={PROCESS_MONTHS or 'ALL'}"
            ),
        )
    except Exception as exc:  # noqa: BLE001
        print_script_failure(exc, script_hint="inventory_shopify")
        raise
