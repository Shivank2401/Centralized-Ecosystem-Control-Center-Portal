"""
Client-aware Amazon Reserved Inventory combiner.

Covers:
  - Clients: ESH (US, CA, UK, DE, AE, IN) and KNC (UK, DE, AE)
  - Source: reserved_inventory folders; coalesce header aliases; pivot reserved qty/FC cols
  - Outputs: sanity_data/{CLIENT}/reserved/{GEO}_reserved_inventory.parquet|.csv

Adding a NEW client (no ETL changes needed):
  1. Add client + geos in client.yaml / geography.yaml / layouts.py
  2. Add one `_xxx_config()` below and register it in CLIENT_CONFIGS
  3. List the client on this report in report.yaml

Style: step-by-step prints (>>> STEP). ETL formulas unchanged.

Run:
    python report_script/amazon_reports/reserved_report.py
    python report_script/amazon_reports/reserved_report.py --client ESH
    python report_script/amazon_reports/reserved_report.py --client KNC --geos UK,DE,AE
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
    SUPPORTED_EXTENSIONS,
    _clean_col,
    load_existing_parquet_outputs,
    merge_append_dedupe,
    to_snake,
)
from config_manager import esh_sku_cleaning, knc_sku_cleaning, paths
from config_manager import layouts
from config_manager.report_helpers import print_script_completed
from report_script.amazon_reports.new_sku_check import (
    check_final_dataframe_new_skus,
)
from report_script.amazon_reports.run_logs import ReportRunLog


# =============================================================================
# Run knobs
# =============================================================================

CLIENT = "ESH"  # CLI default; pipeline passes client= via run()
PROCESS_GEOS: Optional[List[str]] = None

VALID_YEARS = {"2023", "2024", "2025", "2026"}
PROCESS_YEARS: Optional[List[str]] = ["2026"]
PROCESS_MONTHS: Optional[List[str]] = None

SAVE_OUTPUT = True
APPLY_TRANSFORM = True
MERGE_WITH_EXISTING = True

PARQUET_NAME_SUFFIX = "reserved_inventory"
DEDUPE_SUBSET = ["client", "geography", "date", "sku"]

# Alternate headers seen in older / regional / KNC renamed reserved reports.
COLUMN_ALIASES: Dict[str, List[str]] = {
    "sku": ["SKU"],
    "reserved_qty": ["Amazon Reserved", "amazon_reserved"],
    "reserved_customerorders": ["Customer_reserved", "customer_reserved"],
    "reserved_fc-transfers": ["FC_Transfer", "fc_transfer", "fc-transfer"],
    "reserved_fc-processing": ["FC_Processing", "fc_processing"],
}

BASE_PIVOT_VALUES = [
    "reserved_qty",
    "reserved_customer_orders",
    "reserved_fc_processing",
]

FC_TRANSFERS_RAW = "reserved_fc-transfers"
FC_TRANSFERS_SNAKE = "reserved_fc_transfers"

# Markets that historically kept FC transfers longer (docs only — we keep for all).
KEEP_FC_TRANSFERS_ALWAYS = {"AE", "IN"}


# =============================================================================
# Client configuration
#   New client = copy a builder + register in CLIENT_CONFIGS.
#   Fill geo_roots (KNC-style) OR geo_folders + relative_inventory_path (ESH-style).
# =============================================================================

@dataclass
class ClientReservedConfig:
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
    relative_inventory_path: Path = field(
        default_factory=lambda: Path("input") / "amazon" / "reserved_inventory"
    )


def _esh_config() -> ClientReservedConfig:
    ident = layouts.client_identity("ESH")
    return ClientReservedConfig(
        client_code=ident["client_code"],
        client_id=ident["client_id"],
        client_name=ident["client_name"],
        base_path=layouts.data_root("ESH"),
        layout=ident["layout"],
        geo_folders=dict(layouts.ESH_GEO_FOLDERS),
        cogs_path=layouts.cogs_path("ESH"),
        cogs_sheets=layouts.cogs_sheets_for("ESH", channel="amazon"),
        sku_backend="esh",
    )


def _knc_config() -> ClientReservedConfig:
    ident = layouts.client_identity("KNC")
    base = layouts.data_root("KNC")
    return ClientReservedConfig(
        client_code=ident["client_code"],
        client_id=ident["client_id"],
        client_name=ident["client_name"],
        base_path=base,
        layout=ident["layout"],
        geo_roots=layouts.knc_geo_roots("reserved", base),
        cogs_path=layouts.cogs_path("KNC"),
        cogs_sheets=layouts.cogs_sheets_for("KNC", channel="amazon"),
        sku_backend="knc",
        product_name_contains={"AE": "Kinetica"},
        sku_source_by_geo={"AE": "amazon_ae"},
    )


CLIENT_CONFIGS: Dict[str, Callable[[], ClientReservedConfig]] = {
    "ESH": _esh_config,
    "KNC": _knc_config,
}


def get_client_config(client: str) -> ClientReservedConfig:
    key = str(client).strip().upper()
    if key not in CLIENT_CONFIGS:
        known = ", ".join(sorted(CLIENT_CONFIGS))
        raise ValueError(f"Unknown client '{client}'. Expected one of: {known}")
    return CLIENT_CONFIGS[key]()


def output_dir_for(client_code: str) -> Path:
    return paths.sanity_data_root() / client_code.upper() / "reserved"


def geo_code_label(geography: str, cfg: ClientReservedConfig) -> str:
    g = str(geography).strip()
    upper = g.upper()
    for code in cfg.cogs_sheets:
        if code.upper() == upper:
            return code
    if cfg.layout == "esh":
        mapped = cfg.geo_folders.get(g.lower())
        if mapped:
            return mapped
    return upper


# =============================================================================
# SKU / COGS
# =============================================================================

def load_client_sku_mapping(
    cfg: ClientReservedConfig,
    geography_code: Optional[str] = None,
) -> dict:
    geos = [geography_code] if geography_code else list(cfg.cogs_sheets.keys())
    if cfg.sku_backend == "knc":
        return knc_sku_cleaning.load_sku_mapping(geos=geos)
    return esh_sku_cleaning.load_sku_mapping(geos=geos)


def clean_client_skus(
    df: pd.DataFrame,
    cfg: ClientReservedConfig,
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
    cfg: ClientReservedConfig,
    geos: Optional[Sequence[str]] = None,
) -> List[Tuple[str, Path]]:
    """Prefer geo_roots when set; else geo_folders + relative_inventory_path."""
    wanted: Optional[Set[str]] = None
    if geos is not None:
        wanted = {str(g).strip().upper() for g in geos}

    targets: List[Tuple[str, Path]] = []

    if cfg.geo_roots:
        for code, root in cfg.geo_roots.items():
            if wanted is not None and code.upper() not in wanted:
                continue
            if not root.is_dir():
                print(f"[WARN] [{cfg.client_code}] Reserved path missing: {root}")
                continue
            targets.append((code, root))
    else:
        for folder, code in cfg.geo_folders.items():
            if wanted is not None and code.upper() not in wanted:
                continue
            root = cfg.base_path / folder / cfg.relative_inventory_path
            if not root.is_dir():
                print(f"[WARN] [{cfg.client_code}] Reserved path missing: {root}")
                continue
            targets.append((code, root))

    return sorted(targets, key=lambda t: t[0])


def discover_year_folders(
    inventory_root: Path,
    years: Optional[Sequence[str]] = None,
) -> List[Path]:
    allowed = set(VALID_YEARS)
    if years is not None:
        allowed &= {str(y) for y in years}
    found: List[Path] = []
    for path in inventory_root.iterdir():
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
    if lower in {"reserved_inventory.csv", "reserved.csv"}:
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


def discover_reserved_files(
    year_path: Path,
    months: Optional[Sequence[str]] = None,
) -> List[Path]:
    if not year_path.is_dir():
        return []

    wanted = _month_filter_tokens(months)
    files: List[Path] = []
    for path in year_path.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
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


def _read_csv_robust(file_path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(file_path, encoding="utf-8")
    except UnicodeDecodeError:
        return pd.read_csv(file_path, encoding="latin1")


def read_inventory_file(file_path: Path, retries: int = 3) -> pd.DataFrame:
    last_error: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            _hydrate_onedrive_file(file_path)
            suffix = file_path.suffix.lower()
            if suffix == ".csv":
                return _read_csv_robust(file_path)
            if suffix in {".xlsx", ".xls"}:
                return pd.read_excel(file_path)
            if suffix == ".ndjson":
                return pd.read_json(file_path, lines=True, encoding="utf-8")
            if suffix == ".json":
                return pd.read_json(file_path, encoding="utf-8")
            raise ValueError(f"Unsupported file extension: {suffix}")
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

def _normalize_headers(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [_clean_col(c) for c in out.columns]
    return out


def _extract_date(df: pd.DataFrame) -> pd.Series:
    source_col = None
    for candidate in ("source_file", "Source.Name", "source_name"):
        matches = [c for c in df.columns if str(c).strip().lower() == candidate.lower()]
        if matches:
            source_col = matches[0]
            break
    if source_col is None:
        for c in df.columns:
            if to_snake(_clean_col(c)) in {"source_file", "source_name"}:
                source_col = c
                break
    if source_col is None:
        raise KeyError("Expected source_file or Source.Name column for date extraction")

    date_raw = (
        df[source_col]
        .astype(str)
        .str.extract(r"(\d{2}-[A-Za-z]{3}-\d{4})", expand=False)
    )
    return pd.to_datetime(date_raw, format="%d-%b-%Y", errors="coerce").dt.strftime(
        "%Y-%m-%d"
    )


def _ensure_column(df: pd.DataFrame, name: str) -> None:
    if name not in df.columns:
        df[name] = np.nan


def coalesce_reserved_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Unify alternate reserved headers into canonical Amazon names."""
    out = df.copy()
    for target, alternates in COLUMN_ALIASES.items():
        _ensure_column(out, target)
        for alt in alternates:
            if alt not in out.columns:
                continue
            out[target] = np.where(out[target].isna(), out[alt], out[target])

    if "reserved_customerorders" in out.columns:
        out = out.rename(
            columns={"reserved_customerorders": "reserved_customer_orders"}
        )
    return out


def pivot_values_for() -> List[str]:
    cols = list(BASE_PIVOT_VALUES)
    if FC_TRANSFERS_SNAKE not in cols:
        if "reserved_customer_orders" in cols:
            idx = cols.index("reserved_customer_orders") + 1
            cols.insert(idx, FC_TRANSFERS_SNAKE)
        else:
            cols.append(FC_TRANSFERS_SNAKE)
    return cols


def transform_geography_frame(
    geo_df: pd.DataFrame,
    cfg: ClientReservedConfig,
    geography_code: str,
    sku_mapping: Optional[dict] = None,
) -> pd.DataFrame:
    if geo_df.empty:
        return pd.DataFrame()

    reserved_fba = _normalize_headers(geo_df)
    reserved_fba["date"] = _extract_date(reserved_fba)

    # Optional product-name filter (e.g. KNC AE → "Kinetica")
    needle = cfg.product_name_contains.get(geography_code)
    if needle:
        name_col = None
        for cand in ("product-name", "product_name", "Product Name"):
            matches = [
                c for c in reserved_fba.columns if str(c).strip().lower() == cand.lower()
            ]
            if matches:
                name_col = matches[0]
                break
        if name_col is None:
            for c in reserved_fba.columns:
                if to_snake(_clean_col(c)) == "product_name":
                    name_col = c
                    break
        if name_col:
            before = len(reserved_fba)
            reserved_fba = reserved_fba[
                reserved_fba[name_col]
                .astype(str)
                .str.contains(needle, case=False, na=False)
            ].copy()
            print(
                f"  [{geography_code}] product_name filter '{needle}': "
                f"{before:,} -> {len(reserved_fba):,}"
            )

    reserved_fba = coalesce_reserved_columns(reserved_fba)

    if FC_TRANSFERS_RAW not in reserved_fba.columns:
        reserved_fba[FC_TRANSFERS_RAW] = 0
        note = (
            "always-keep market"
            if geography_code in KEEP_FC_TRANSFERS_ALWAYS
            else "Jul+ schema / KNC rename"
        )
        print(f"  [{geography_code}] Note: {FC_TRANSFERS_RAW} missing ({note}) — filled with 0")
    else:
        reserved_fba[FC_TRANSFERS_RAW] = pd.to_numeric(
            reserved_fba[FC_TRANSFERS_RAW], errors="coerce"
        ).fillna(0)

    reserved_fba["geography"] = geography_code

    keep_raw = [
        "geography",
        "sku",
        "date",
        "reserved_qty",
        "reserved_customer_orders",
        FC_TRANSFERS_RAW,
        "reserved_fc-processing",
    ]
    for col in keep_raw:
        if col not in reserved_fba.columns:
            if col in {
                FC_TRANSFERS_RAW,
                "reserved_fc-processing",
                "reserved_qty",
                "reserved_customer_orders",
            }:
                reserved_fba[col] = 0
            elif col == "sku":
                reserved_fba[col] = np.nan
            else:
                raise KeyError(f"Missing columns for {geography_code}: {[col]}")

    reserved_fba = reserved_fba.loc[:, keep_raw]
    reserved_fba.columns = [
        c if c == "geography" else to_snake(c) for c in reserved_fba.columns
    ]

    for col in [
        "reserved_qty",
        "reserved_customer_orders",
        FC_TRANSFERS_SNAKE,
        "reserved_fc_processing",
    ]:
        if col in reserved_fba.columns:
            reserved_fba[col] = pd.to_numeric(reserved_fba[col], errors="coerce").fillna(0)

    reserved_fba["sku"] = reserved_fba["sku"].astype(str).str.replace(
        r"-{1,2}$", "", regex=True
    )

    if sku_mapping is None:
        sku_mapping = load_client_sku_mapping(cfg, geography_code)

    reserved_fba = clean_client_skus(
        reserved_fba, cfg, geography_code, sku_mapping=sku_mapping
    )
    reserved_fba = reserved_fba.dropna(subset=["sku"])
    reserved_fba = reserved_fba.drop_duplicates().reset_index(drop=True)

    value_cols = [c for c in pivot_values_for() if c in reserved_fba.columns]
    reserved_fba = (
        pd.pivot_table(
            reserved_fba,
            index=["geography", "date", "sku"],
            values=value_cols,
            aggfunc="sum",
        )
        .reset_index()
    )

    reserved_fba["client"] = cfg.client_code
    reserved_fba["client_id"] = cfg.client_id
    reserved_fba["platform"] = "amazon"

    front = ["client", "client_id", "geography", "platform", "date", "sku"]
    rest = [c for c in reserved_fba.columns if c not in front]
    return reserved_fba.loc[:, front + rest]


def transform_reserved(
    raw_df: pd.DataFrame,
    cfg: ClientReservedConfig,
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
    print(f"\n>>> STEP: save per-geography reserved → {output_dir}")
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
    for file_path in discover_reserved_files(year_path, months=months):
        resolved = file_path.resolve()
        if resolved in processed_files:
            continue

        parent = file_path.parent.name
        month_label = parent if parent != year else "files"

        print(f"[{client}] [{geography_code}] [{year}] [{month_label}] Reading {file_path.name}")
        try:
            df = read_inventory_file(file_path)
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

    if frames:
        stats.record_month_folder(geography_code, year, year_path.name)
    return frames


def build_reserved_dataframe(
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

    print("\n>>> STEP: load raw reserved files")
    for geo_code, inventory_root in resolve_geo_targets(cfg, geos):
        stats.geographies.add(geo_code)
        print(f"  geo root [{geo_code}]: {inventory_root}")
        for year_path in discover_year_folders(inventory_root, years=years):
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
    run_log = ReportRunLog(cfg.client_code, "reserved")
    try:
        summary = stats.print_summary(
            title=f"{cfg.client_code} Reserved Inventory Load Summary"
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
            print("\n>>> STEP: transform (coalesce + SKU clean + pivot)")
            new_df = transform_reserved(new_df, cfg=cfg)
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
                label="reserved",
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
    parser = argparse.ArgumentParser(description="Client-wise reserved inventory combiner")
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

    master_df, failed_files, _stats = build_reserved_dataframe(
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
    master_reserved_df, failed_files = main()
    print_script_completed("reserved_report")
