"""
KNC Shopify Sell-Thru (UK + IE) — year CSVs under sales roots → sell_thru masters.

Covers:
  - Client: KNC only (geos with channels.shopify — UK, IE)
  - Inputs: nested under existing KNC_SHOPIFY_{GEO}_SALES_ROOT (no new env keys)
      UK: {sales}/Sell-thru/Sell-thru {YYYY}.csv
      IE: {sales}/Sell-thru/… or sibling …/ie/sell_thru/Sell-thru {YYYY}.csv
  - Pipeline (notebook-style): load year CSVs → vendor filter →
      knc_sku_cleaning(shopify) → date + sell_thru pivot → merge_append_dedupe
  - Outputs (standalone; NOT merged into Shopify orders):
      sanity_data/KNC/sell_thru/{GEO}_shopify_sell_thru.parquet|.csv

Run:
    python report_script/shopify_reports/sell_thru.py
    python report_script/shopify_reports/sell_thru.py --geos UK,IE
    python report_script/shopify_reports/sell_thru.py --client KNC --years 2025,2026 --no-merge

Year filter: edit PROCESS_YEARS below (matched from filename, e.g. Sell-thru 2026.csv).
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
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
)
from report_script.amazon_reports.new_sku_check import (
    check_final_dataframe_new_skus,
)
from report_script.amazon_reports.run_logs import ReportRunLog

# =============================================================================
# Run knobs
# =============================================================================

CLIENT = "KNC"
PROCESS_GEOS: Optional[List[str]] = None

VALID_YEARS = {"2024", "2025", "2026"}
PROCESS_YEARS: Optional[List[str]] = ["2024", "2025", "2026"]

SAVE_OUTPUT = True
MERGE_WITH_EXISTING = True
APPLY_TRANSFORM = True

PARQUET_NAME_SUFFIX = "shopify_sell_thru"
DEDUPE_SUBSET = ["client", "geography", "date", "sku"]

OUTPUT_COLS = [
    "client",
    "client_id",
    "geography",
    "platform",
    "date",
    "sku",
    "sell_thru",
]





_YEAR_IN_NAME = re.compile(r"(20\d{2})")

USE_COLS = [
    "Product variant SKU",
    "Product vendor",
    "Day",
    "Sell-through rate",
]

# Exact Product vendor lists (also match geography.yaml shopify vendors)
VENDOR_BY_GEO: Dict[str, Tuple[str, ...]] = {
    "UK": ("Kinetica - UK", "Kinetica Sports UK"),
    "IE": ("Kinetica - IE", "Kinetica Sports", "Kinetica Sports IE"),
}


# =============================================================================
# Client configuration
# =============================================================================

@dataclass
class ShopifySellThruGeoConfig:
    sales_root_env: str
    currency: str


@dataclass
class ClientShopifySellThruConfig:
    client_code: str
    client_id: str
    client_name: str
    layout: str
    geos: Dict[str, ShopifySellThruGeoConfig] = field(default_factory=dict)


def _knc_shopify_sell_thru_config() -> ClientShopifySellThruConfig:
    from config_manager.loader import load_geographies

    ident = layouts.client_identity("KNC")
    geos_cfg: Dict[str, ShopifySellThruGeoConfig] = {}
    for code, geo in load_geographies("KNC").items():
        if not geo.has_channel("shopify"):
            continue
        geos_cfg[code] = ShopifySellThruGeoConfig(
            sales_root_env=f"KNC_SHOPIFY_{code}_SALES_ROOT",
            currency=geo.country_currency,
        )
    if not geos_cfg:
        raise ValueError(
            "No KNC geos with channels.shopify in geography.yaml "
            "(expected UK and/or IE)."
        )
    return ClientShopifySellThruConfig(
        client_code=ident["client_code"],
        client_id=ident["client_id"],
        client_name=ident["client_name"],
        layout=ident["layout"],
        geos=geos_cfg,
    )


CLIENT_CONFIGS: Dict[str, Callable[[], ClientShopifySellThruConfig]] = {
    "KNC": _knc_shopify_sell_thru_config,
}


def get_client_config(client: str) -> ClientShopifySellThruConfig:
    key = str(client).strip().upper()
    if key not in CLIENT_CONFIGS:
        known = ", ".join(sorted(CLIENT_CONFIGS))
        raise ValueError(f"Unknown client '{client}'. Expected one of: {known}")
    return CLIENT_CONFIGS[key]()


def output_dir_for(client_code: str) -> Path:
    return paths.sanity_data_root() / client_code.upper() / "sell_thru"


# =============================================================================
# Paths / IO
# =============================================================================

def resolve_sell_thru_root(sales_root: Path) -> Optional[Path]:
    """
    Nest under the sales tree when possible; also accept IE sibling `sell_thru`.

    sales_root may be …/sales or …/sales/Year.
    """
    root = sales_root.resolve()
    sales_dir = root.parent if root.name.lower() == "year" else root
    candidates = [
        sales_dir / "Sell-thru",
        sales_dir / "Sell-Thru",
        sales_dir / "sell_thru",
        # IE historical layout: …/Shopify/ie/sell_thru next to sales/
        sales_dir.parent / "sell_thru",
        sales_dir.parent / "Sell-thru",
        sales_dir.parent / "Sell-Thru",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


def resolve_geo_targets(
    cfg: ClientShopifySellThruConfig,
    geos: Optional[Sequence[str]] = None,
) -> List[Tuple[str, Path, ShopifySellThruGeoConfig]]:
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

    targets: List[Tuple[str, Path, ShopifySellThruGeoConfig]] = []
    for code, geo_cfg in cfg.geos.items():
        if wanted is not None and code.upper() not in wanted:
            continue
        try:
            root = paths.knc_shopify_sales_root(code)
        except EnvironmentError as exc:
            print(f"[WARN] [{cfg.client_code}] [{code}] {exc}")
            continue
        if root is None or not root.is_dir():
            print(
                f"[WARN] [{cfg.client_code}] Shopify sales path missing for {code}: "
                f"{root} (set {geo_cfg.sales_root_env} in .env)"
            )
            continue
        targets.append((code, root, geo_cfg))
    return sorted(targets, key=lambda t: t[0])


def is_ignored_file(path: Path) -> bool:
    lower = path.name.lower()
    if lower in IGNORE_FILE_NAMES:
        return True
    return any(lower.startswith(prefix) for prefix in IGNORE_FILE_PREFIXES)


def year_from_filename(path: Path) -> Optional[str]:
    match = _YEAR_IN_NAME.search(path.stem)
    return match.group(1) if match else None


def discover_sell_thru_files(
    sell_thru_root: Path,
    years: Optional[Sequence[str]] = None,
) -> List[Path]:
    if not sell_thru_root.is_dir():
        return []
    allowed: Optional[Set[str]] = None
    if years is not None:
        allowed = {str(y).strip() for y in years}

    files: List[Path] = []
    for path in sell_thru_root.rglob("*.csv"):
        if not path.is_file() or is_ignored_file(path):
            continue
        year = year_from_filename(path)
        if allowed is not None:
            if year is None or year not in allowed:
                continue
        files.append(path)
    return sorted(files, key=lambda p: p.as_posix().lower())


def _hydrate_onedrive_file(file_path: Path) -> None:
    with open(file_path, "rb") as handle:
        handle.read(1)


def read_sell_thru_csv(file_path: Path) -> pd.DataFrame:
    _hydrate_onedrive_file(file_path)
    try:
        raw = pd.read_csv(file_path, dtype=str, low_memory=False)
    except UnicodeDecodeError:
        raw = pd.read_csv(file_path, dtype=str, low_memory=False, encoding="latin1")

    raw.columns = [str(c).strip().replace("\ufeff", "") for c in raw.columns]
    rename: Dict[str, str] = {}
    for col in raw.columns:
        norm = col.strip().lower()
        if norm in {"product variant sku", "product variant sku.", "sku"}:
            rename[col] = "Product variant SKU"
        elif norm == "product vendor":
            rename[col] = "Product vendor"
        elif norm == "day":
            rename[col] = "Day"
        elif norm in {"sell-through rate", "sell through rate", "sell_thru"}:
            rename[col] = "Sell-through rate"
    raw = raw.rename(columns=rename)
    missing = [c for c in USE_COLS if c not in raw.columns]
    if missing:
        raise KeyError(f"Missing columns in {file_path.name}: {missing}")
    return raw.loc[:, USE_COLS].copy()


# =============================================================================
# Transform (vendor filter + pivot early, then SKU/date clean)
# =============================================================================

def filter_raw_by_vendor(raw_df: pd.DataFrame) -> pd.DataFrame:
    """
    Keep rows whose Product vendor matches the geo allow-list:

      UK: Kinetica - UK, Kinetica Sports UK
      IE: Kinetica - IE, Kinetica Sports, Kinetica Sports IE
    """
    if raw_df.empty:
        return raw_df

    print("\n>>> STEP: filter Product vendor (exact lists per geography)")
    frames: List[pd.DataFrame] = []
    for geography, geo_df in raw_df.groupby("geography", sort=True):
        code = str(geography).strip().upper()
        allowed = VENDOR_BY_GEO.get(code)
        before = len(geo_df)
        if not allowed:
            print(f"  [{code}] no vendor list configured — keeping all {before:,} rows")
            frames.append(geo_df.copy())
            continue
        vendor = geo_df["Product vendor"].astype(str).str.strip()
        out = geo_df.loc[vendor.isin(allowed)].copy()
        print(
            f"  [{code}] vendors={list(allowed)}: {len(out):,} / {before:,} rows"
        )
        if not out.empty:
            frames.append(out)

    if not frames:
        return pd.DataFrame(columns=list(raw_df.columns))
    return pd.concat(frames, ignore_index=True, sort=False)


def pivot_sell_thru_rate(filtered_df: pd.DataFrame) -> pd.DataFrame:
    """
    Sum Sell-through rate on Day + Product variant SKU (per geography).

    Notebook-style pivot after vendor filter, before SKU cleaning.
    """
    if filtered_df.empty:
        return filtered_df

    print("\n>>> STEP: pivot sum(Sell-through rate) on Day + Product variant SKU")
    work = filtered_df.copy()
    work["Sell-through rate"] = pd.to_numeric(
        work["Sell-through rate"], errors="coerce"
    ).fillna(0.0)

    # geography stays in the index so UK/IE do not mix
    index_cols = ["Day", "Product variant SKU"]
    if "geography" in work.columns:
        index_cols = ["geography"] + index_cols

    pivoted = (
        pd.pivot_table(
            work,
            index=index_cols,
            values="Sell-through rate",
            aggfunc="sum",
        )
        .reset_index()
    )
    print(f"  pivoted shape: {pivoted.shape} (from {len(work):,} filtered rows)")
    return pivoted


def transform_geography_sell_thru(
    raw: pd.DataFrame,
    *,
    cfg: ClientShopifySellThruConfig,
    geography_code: str,
) -> pd.DataFrame:
    """Clean already vendor-filtered + pivoted slice → output schema."""
    if raw.empty:
        return pd.DataFrame(columns=OUTPUT_COLS)

    code = str(geography_code).strip().upper()
    print(
        f"\n>>> STEP: transform sell_thru [{cfg.client_code}] {code} "
        f"({len(raw):,} pivoted rows)"
    )

    work = raw.rename(
        columns={
            "Product variant SKU": "sku",
            "Sell-through rate": "sell_thru",
        }
    )
    before = len(work)
    work = work[work["sku"].notna() & (work["sku"].astype(str).str.strip() != "")].copy()
    print(f"  drop null sku: {len(work):,} / {before:,}")
    if work.empty:
        return pd.DataFrame(columns=OUTPUT_COLS)

    work = knc_sku_cleaning.clean_sku_column(work, sku_column="sku", source="shopify")
    print(f"  After knc_sku_cleaning(source=shopify): {len(work):,} rows")
    if work.empty:
        return pd.DataFrame(columns=OUTPUT_COLS)

    day = pd.to_datetime(work["Day"], utc=True, errors="coerce")
    try:
        day = day.dt.tz_localize(None)
    except TypeError:
        day = day.dt.tz_convert(None) if getattr(day.dt, "tz", None) else day
    work["date"] = pd.to_datetime(day, errors="coerce")
    work = work.dropna(subset=["date", "sku"])

    work["sell_thru"] = pd.to_numeric(work.get("sell_thru", 0), errors="coerce").fillna(0.0)

    # Already pivoted; re-sum in case SKU cleaning collapsed aliases
    daily = work.groupby(["sku", "date"], as_index=False)["sell_thru"].sum()
    daily["client"] = cfg.client_code
    daily["client_id"] = cfg.client_id
    daily["geography"] = code
    daily["platform"] = "shopify"
    out = daily.loc[:, OUTPUT_COLS].drop_duplicates().reset_index(drop=True)
    print(f"  Result: {len(out):,} daily sell_thru rows")
    return out


def transform_sell_thru(
    raw_df: pd.DataFrame,
    cfg: ClientShopifySellThruConfig,
) -> pd.DataFrame:
    if raw_df.empty:
        return pd.DataFrame(columns=OUTPUT_COLS)

    frames: List[pd.DataFrame] = []
    for geography, geo_df in raw_df.groupby("geography", sort=True):
        code = str(geography).strip().upper()
        try:
            cleaned = transform_geography_sell_thru(
                geo_df, cfg=cfg, geography_code=code
            )
            if not cleaned.empty:
                frames.append(cleaned)
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR transforming sell_thru {code}: {exc}")

    if not frames:
        return pd.DataFrame(columns=OUTPUT_COLS)
    return pd.concat(frames, ignore_index=True, sort=False)


def dedupe_sell_thru_frame(
    df: pd.DataFrame,
    subset: Sequence[str] = DEDUPE_SUBSET,
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
    print(f"\n>>> STEP: save per-geography Shopify sell_thru -> {output_dir}")
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

def build_sell_thru_dataframe(
    client: str = CLIENT,
    geos: Optional[Sequence[str]] = None,
    years: Optional[Sequence[str]] = None,
    save_output: bool = SAVE_OUTPUT,
    apply_transform: bool = APPLY_TRANSFORM,
    merge_existing: bool = MERGE_WITH_EXISTING,
    output_dir: Optional[Path] = None,
) -> Tuple[pd.DataFrame, List[dict], LoadStats]:
    cfg = get_client_config(client)
    geos = PROCESS_GEOS if geos is None and PROCESS_GEOS is not None else geos
    years = PROCESS_YEARS if years is None and PROCESS_YEARS is not None else years
    if years is None:
        years = sorted(VALID_YEARS)
    out_dir = output_dir or output_dir_for(cfg.client_code)

    print("=" * 60)
    print(f"Client : {cfg.client_code} ({cfg.client_name})")
    print(f"ID     : {cfg.client_id}")
    print(f"Years  : {list(years)}")
    print(f"Geos   : {list(geos) if geos is not None else 'ALL (shopify channels)'}")
    print(f"Shopify geos configured: {', '.join(sorted(cfg.geos))}")
    print(f"Output : {out_dir}")
    print(f"Suffix : {PARQUET_NAME_SUFFIX}  (standalone; orders NOT touched)")
    print(f"Merge  : {merge_existing}")
    print("=" * 60)

    targets = resolve_geo_targets(cfg, geos)
    target_geos = [code for code, _root, _gcfg in targets]
    if not targets:
        print(
            "\n[SKIP] No Shopify sell_thru geos to process for this selection "
            f"(configured={sorted(cfg.geos)}, requested={list(geos) if geos else 'ALL'})."
        )
        return pd.DataFrame(), [], LoadStats()

    print(f"\n>>> STEP: run Shopify sell_thru for geos={target_geos} only")

    all_frames: List[pd.DataFrame] = []
    failed_files: List[dict] = []
    processed_files: Set[Path] = set()
    stats = LoadStats()
    run_log = ReportRunLog(cfg.client_code, "shopify_sell_thru")

    print("\n>>> STEP: load Sell-thru CSVs nested under sales roots")
    for geo_code, sales_root, geo_cfg in targets:
        stats.geographies.add(geo_code)
        st_root = resolve_sell_thru_root(sales_root)
        print(f"  [{geo_code}] sales_root={sales_root}  env={geo_cfg.sales_root_env}")
        if st_root is None:
            print(
                f"  [WARN] [{geo_code}] Sell-thru folder not found near {sales_root} "
                f"(tried Sell-thru / sell_thru under sales and sibling)"
            )
            continue
        print(f"  [{geo_code}] sell_thru_root={st_root}")

        files = discover_sell_thru_files(st_root, years=years)
        if not files:
            print(
                f"  [WARN] [{geo_code}] no Sell-thru CSVs for years={list(years)}"
            )
            continue

        year_seen: Set[str] = set()
        for file_path in files:
            resolved = file_path.resolve()
            if resolved in processed_files:
                continue
            year = year_from_filename(file_path) or "?"
            year_seen.add(str(year))
            print(f"[{cfg.client_code}] [{geo_code}] [{year}] Reading {file_path.name}")
            try:
                df = read_sell_thru_csv(file_path)
                df = df.copy()
                df["geography"] = geo_code
                df["year"] = year
                df["source_file"] = file_path.name
                df["source_path"] = str(resolved)
                all_frames.append(df)
                processed_files.add(resolved)
                stats.record_file_ok(geo_code, year, len(df))
            except Exception as exc:  # noqa: BLE001
                print(
                    f"[{cfg.client_code}] [{geo_code}] [{year}] "
                    f"SKIP {file_path.name}: {exc}"
                )
                failed_files.append(
                    {
                        "path": str(resolved),
                        "geography": geo_code,
                        "year": year,
                        "error": str(exc),
                    }
                )
                stats.record_file_failed(geo_code, year)
                processed_files.add(resolved)

        for y in sorted(year_seen):
            stats.year_folders.add(f"{geo_code}/{y}")

    raw_df = (
        pd.concat(all_frames, ignore_index=True, sort=False) if all_frames else pd.DataFrame()
    )
    print(f"\n>>> STEP: appended raw Shopify sell_thru shape: {raw_df.shape}")

    # Early steps (before SKU clean / master schema): vendor filter → pivot
    if not raw_df.empty:
        raw_df = filter_raw_by_vendor(raw_df)
        print(f"  after vendor filter shape: {raw_df.shape}")
        raw_df = pivot_sell_thru_rate(raw_df)
        print(f"  after pivot shape: {raw_df.shape}")

    master_df = raw_df
    try:
        summary = stats.print_summary(
            title=f"{cfg.client_code} Shopify Sell-Thru Load Summary"
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
            print("\n>>> STEP: transform (SKU clean + date normalize)")
            new_df = transform_sell_thru(raw_df, cfg=cfg)
            print(f"Transformed new slice shape: {new_df.shape}")
        else:
            new_df = raw_df

        print("\n>>> STEP: dedupe new slice before append (keys=client,geography,date,sku)")
        new_df = dedupe_sell_thru_frame(
            new_df, DEDUPE_SUBSET, label="new slice", keep="last"
        )

        if merge_existing:
            print("\n>>> STEP: merge with existing parquet masters (run geos only)")
            frames = []
            print(f"Loading existing sell_thru for geos={target_geos} from: {out_dir}")
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
                existing_df = dedupe_sell_thru_frame(
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
                label="shopify_sell_thru",
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
    save_output: bool = SAVE_OUTPUT,
    apply_transform: bool = APPLY_TRANSFORM,
    merge_existing: bool = MERGE_WITH_EXISTING,
    output_dir: Optional[Path] = None,
    **_kwargs,
) -> pd.DataFrame:
    master, _failed, _stats = build_sell_thru_dataframe(
        client=client,
        geos=geos,
        years=years,
        save_output=save_output,
        apply_transform=apply_transform,
        merge_existing=merge_existing,
        output_dir=output_dir,
    )
    return master


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="KNC Shopify sell-thru -> sell_thru masters"
    )
    parser.add_argument("--client", default=CLIENT, help="Client code (KNC)")
    parser.add_argument("--geos", default=None, help="Comma-separated geos, e.g. UK,IE")
    parser.add_argument(
        "--years",
        default=None,
        help="Optional override of PROCESS_YEARS (comma-separated). Omit to use script knobs.",
    )
    parser.add_argument("--no-merge", action="store_true", help="Do not merge existing parquet")
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
            save_output=not args.no_save,
            merge_existing=not args.no_merge,
        )
        print_script_completed(
            "sell_thru",
            detail=(
                f"client={args.client} geos={geos or 'ALL'} "
                f"years={years or PROCESS_YEARS or sorted(VALID_YEARS)}"
            ),
        )
    except Exception as exc:  # noqa: BLE001
        print_script_failure(exc, script_hint="sell_thru")
        raise
