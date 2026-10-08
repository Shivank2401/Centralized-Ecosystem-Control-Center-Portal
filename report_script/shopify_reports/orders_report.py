"""
KNC Shopify Orders combiner (UK + IE).

Covers:
  - Client: KNC only (geos UK, IE)
  - Inputs: Shopify sales CSVs from KNC_SHOPIFY_{GEO}_SALES_ROOT (.env)
  - Pipeline (per geo after append):
      1) select required columns
      2) drop blank purchase_hour
      3) qty/sales clean (keep signed refunds)
      4) datetime parse → year_month / purchase_date / time
      5) SKU clean+map; missing SKU → "Not defined" (not dropped)
      6) pivot → pincode → COGS merge; missing product_name → "Not defined"
      7) print new SKUs in orders but not in Shopify COGS
  - Market / vendor lists stay in geography.yaml (bookmark / sell_thru) —
    NOT applied as filters here
  - Outputs: sanity_data/KNC/orders/{GEO}_shopify_orders_database.parquet|.csv
    (separate from Amazon {GEO}_orders_database — never merged)
  - Same 3-month qty/sales checklist as Amazon orders
  - Refunds: Shopify often has total_sales < 0 with quantity == 0 — keep those rows

Adding another Shopify geo later:
  1. Add geo in geography.yaml / client.yaml
  2. Set KNC_SHOPIFY_{GEO}_SALES_ROOT in .env
  3. Currency comes from geography.yaml; markets/vendors optional (not used here)
  4. Place cogs/knc/{geo}_shopify_cogs.csv

Style: step-by-step prints (>>> STEP). ETL aligned to orders_report.ipynb.

Run:
    python report_script/shopify_reports/orders_report.py
    python report_script/shopify_reports/orders_report.py --geos UK,IE
    python report_script/shopify_reports/orders_report.py --client KNC --years 2026
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
from config_manager.orders_pincode import attach_shopify_city_state
from config_manager.report_helpers import (
    IGNORE_FILE_NAMES,
    IGNORE_FILE_PREFIXES,
    LoadStats,
    print_script_completed,
    print_script_failure,
)
from report_script.amazon_reports.orders_report import (
    merge_orders_with_existing,
    prefer_geography_column,
    print_orders_three_month_checklist,
    resolve_orders_duplicates,
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
VALID_YEARS = {"2023", "2024", "2025", "2026"}
PROCESS_YEARS: Optional[List[str]] = ["2024", "2025", "2026"]
PROCESS_MONTHS: Optional[List[str]] = None

SAVE_OUTPUT = True
MERGE_WITH_EXISTING = True
APPLY_TRANSFORM = True

PARQUET_NAME_SUFFIX = "shopify_orders_database"
MISSING_SKU_LABEL = "Not defined"
MISSING_PRODUCT_NAME_LABEL = "Not defined"

# Same schema as Amazon orders (platform = shopify) + product_name from COGS
OUTPUT_COLUMNS = [
    "client",
    "geography",
    "order_id",
    "purchase_date",
    "order_status",
    "sku",
    "quantity",
    "total_sales",
    "year_month",
    "purchase_hour",
    "purchase_time",
    "pincode_new",
    "city",
    "state",
    "aov",
    "platform",
    "currency",
    "product_name",
]

# Columns kept after append (step 2 — select required columns)
PROCESS_COLUMNS = [
    "order_id",
    "sku",
    "quantity",
    "total_sales",
    "purchase_hour",
    "order_status",
    "year_month",
    "pincode",
    "city",
    "state",
    "market",
    "sales-channel",
    "currency",
    "aov",
    "geography",
    "source_file",
    "source_path",
]

COLUMNS_TO_READ = [
    "Order checkout currency",
    "Order fulfillment status",
    "Month",
    "Day",
    "Hour",
    "Shipping postal code",
    "Shipping region",
    "Shipping city",
    "Product variant SKU",
    "Product vendor",
    "Order ID",
    "Total sales",
    "Average order value",
    "Quantity ordered",
    "Market",
]

RENAME_MAPPING = {
    "Product variant SKU": "sku",
    "Product Variant SKU": "sku",
    "Product Variant Sku": "sku",
    "Order checkout currency": "currency",
    "Order fulfillment status": "order_status",
    "Month": "year_month",
    "Day": "purchase_date",
    "Hour": "purchase_hour",
    "Shipping postal code": "pincode",
    "Shipping region": "state",
    "Shipping city": "city",
    "Product vendor": "sales-channel",
    "Order ID": "order_id",
    "Total sales": "total_sales",
    "Average order value": "aov",
    "Quantity ordered": "quantity",
    "Market": "market",
}


# =============================================================================
# Client configuration
# =============================================================================

@dataclass
class ShopifyGeoConfig:
    """Per-geo Shopify orders config.

    ``markets`` / ``vendors`` are loaded from geography.yaml as a bookmark only
    (also used by sell_thru). Orders ETL does **not** filter on them.
    """

    markets: List[str]
    vendors: List[str]
    currency: str
    sales_root_env: str


@dataclass
class ClientShopifyOrdersConfig:
    client_code: str
    client_id: str
    client_name: str
    layout: str
    geos: Dict[str, ShopifyGeoConfig] = field(default_factory=dict)


def _knc_shopify_config() -> ClientShopifyOrdersConfig:
    """Build Shopify geo config from geography.yaml → channels.shopify."""
    from config_manager.loader import load_geographies

    ident = layouts.client_identity("KNC")
    geos_cfg: Dict[str, ShopifyGeoConfig] = {}
    for code, geo in load_geographies("KNC").items():
        if not geo.has_channel("shopify"):
            continue
        ch = geo.channel("shopify")
        geos_cfg[code] = ShopifyGeoConfig(
            markets=list(ch.markets),
            vendors=list(ch.vendors),
            currency=geo.country_currency,
            sales_root_env=f"KNC_SHOPIFY_{code}_SALES_ROOT",
        )
    if not geos_cfg:
        raise ValueError(
            "No KNC geos with channels.shopify in geography.yaml "
            "(expected UK and/or IE)."
        )
    return ClientShopifyOrdersConfig(
        client_code=ident["client_code"],
        client_id=ident["client_id"],
        client_name=ident["client_name"],
        layout=ident["layout"],
        geos=geos_cfg,
    )


CLIENT_CONFIGS: Dict[str, Callable[[], ClientShopifyOrdersConfig]] = {
    "KNC": _knc_shopify_config,
}


def get_client_config(client: str) -> ClientShopifyOrdersConfig:
    key = str(client).strip().upper()
    if key not in CLIENT_CONFIGS:
        known = ", ".join(sorted(CLIENT_CONFIGS))
        raise ValueError(f"Unknown client '{client}'. Expected one of: {known}")
    return CLIENT_CONFIGS[key]()


def output_dir_for(client_code: str) -> Path:
    return paths.sanity_data_root() / client_code.upper() / "orders"


# ---------------------------------------------------------------------------
# File discovery / IO
# ---------------------------------------------------------------------------

def is_ignored_file(path: Path) -> bool:
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


def resolve_geo_targets(
    cfg: ClientShopifyOrdersConfig,
    geos: Optional[Sequence[str]] = None,
) -> List[Tuple[str, Path, ShopifyGeoConfig]]:
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

    targets: List[Tuple[str, Path, ShopifyGeoConfig]] = []
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
                f"[WARN] [{cfg.client_code}] Shopify path missing for {code}: "
                f"{root} (set {geo_cfg.sales_root_env} in .env)"
            )
            continue
        targets.append((code, root, geo_cfg))
    return sorted(targets, key=lambda t: t[0])


def _filter_df_to_geos(df: pd.DataFrame, geos: Sequence[str]) -> pd.DataFrame:
    """Keep only rows for the geos this run is processing."""
    if df is None or df.empty or "geography" not in df.columns:
        return df if df is not None else pd.DataFrame()
    wanted = {str(g).strip().upper() for g in geos}
    out = df.loc[df["geography"].astype(str).str.upper().isin(wanted)].copy()
    return out.reset_index(drop=True)


def load_existing_shopify_orders(
    output_dir: Path,
    geos: Sequence[str],
    name_suffix: str = PARQUET_NAME_SUFFIX,
) -> pd.DataFrame:
    """Load existing masters only for the geos in this run (not every geo file)."""
    if not output_dir.is_dir():
        print(f"[INFO] No existing output folder yet: {output_dir}")
        return pd.DataFrame()

    frames: List[pd.DataFrame] = []
    print(f"\nLoading existing Shopify orders for geos={list(geos)} from: {output_dir}")
    for code in sorted({str(g).strip().upper() for g in geos}):
        path = output_dir / f"{code}_{name_suffix}.parquet"
        if not path.is_file():
            print(f"  [{code}] no existing {path.name}")
            continue
        try:
            df = pd.read_parquet(path)
            print(f"  [{path.name}] {len(df):,} rows")
            frames.append(df)
        except Exception as exc:  # noqa: BLE001
            print(f"  [WARN] Could not read {path.name}: {exc}")

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True, sort=False)


def discover_year_folders(
    sales_root: Path,
    years: Optional[Sequence[str]] = None,
) -> List[Path]:
    """Return year dirs under root when present; else [sales_root] for flat dumps."""
    allowed = set(VALID_YEARS)
    if years is not None:
        allowed &= {str(y).strip() for y in years}

    year_dirs = [
        p
        for p in sales_root.iterdir()
        if p.is_dir() and p.name in allowed
    ]
    if year_dirs:
        return sorted(year_dirs, key=lambda p: p.name)

    # Flat layout (typical IE): treat the sales root itself as one bucket
    return [sales_root]


def discover_order_files(
    folder: Path,
    months: Optional[Sequence[str]] = None,
) -> List[Path]:
    wanted = _month_filter_tokens(months)
    files: List[Path] = []
    for path in folder.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() != ".csv":
            continue
        if is_ignored_file(path):
            continue
        if wanted is not None:
            rel_parts = {part.lower() for part in path.relative_to(folder).parts[:-1]}
            name_l = path.name.lower()
            if not ((rel_parts & wanted) or any(tok in name_l for tok in wanted)):
                continue
        files.append(path)
    return sorted(files, key=lambda p: p.as_posix().lower())


def _hydrate_onedrive_file(file_path: Path) -> None:
    with open(file_path, "rb") as handle:
        handle.read(1)


def read_shopify_order_file(file_path: Path) -> pd.DataFrame:
    _hydrate_onedrive_file(file_path)
    try:
        raw = pd.read_csv(file_path, dtype=str, low_memory=False)
    except UnicodeDecodeError:
        raw = pd.read_csv(file_path, dtype=str, low_memory=False, encoding="latin1")

    raw.columns = [str(c).strip().replace("\ufeff", "") for c in raw.columns]
    available = [c for c in COLUMNS_TO_READ if c in raw.columns]
    # Accept SKU header variants beyond COLUMNS_TO_READ
    for alt in ("Product Variant SKU", "Product Variant Sku"):
        if alt in raw.columns and alt not in available:
            available.append(alt)

    sku_present = any(
        c in raw.columns
        for c in ("Product variant SKU", "Product Variant SKU", "Product Variant Sku")
    )
    if not sku_present or "Order ID" not in raw.columns:
        raise ValueError(f"Missing required Shopify columns in {file_path.name}")

    out = raw.loc[:, available].copy()
    rename = {k: v for k, v in RENAME_MAPPING.items() if k in out.columns}
    out = out.rename(columns=rename)
    if "market" not in out.columns and "Market" in raw.columns:
        out["market"] = raw["Market"]
    return out


def load_shopify_cogs(geography_code: str) -> pd.DataFrame:
    """
    Load Shopify COGS from local cogs/knc/{geo}_shopify_cogs.*
    (channel forced to shopify; UK also listed under geography.yaml cogs_channels).
    """
    from config_manager import cogs_local

    code = str(geography_code).strip().upper()
    df = cogs_local.read_cogs_slice("KNC", code, channel="shopify")
    out = pd.DataFrame(
        {
            "sku": df["sku"].astype(str).str.strip().str.upper()
            if "sku" in df.columns
            else pd.Series(dtype=str),
            "asin": df["asin"].astype(str) if "asin" in df.columns else pd.Series(dtype=str),
            "product_category": (
                df["product_category"].astype(str)
                if "product_category" in df.columns
                else pd.Series(dtype=str)
            ),
            "product_name": (
                df["product_name"].astype(str)
                if "product_name" in df.columns
                else pd.Series(dtype=str)
            ),
        }
    )
    return out.drop_duplicates(subset=["sku"], keep="first")


def _is_blank_series(series: pd.Series) -> pd.Series:
    s = series.astype(str).str.strip()
    return (
        series.isna()
        | s.eq("")
        | s.str.lower().isin({"nan", "none", "nat", "null"})
    )


def _print_new_skus_vs_cogs(
    orders_df: pd.DataFrame,
    cogs_df: pd.DataFrame,
    *,
    client: str,
    geography_code: str,
) -> List[str]:
    """Print SKUs present in orders but missing from Shopify COGS (excl. Not defined)."""
    tag = f"[{client}] [{geography_code}]"
    if orders_df.empty or "sku" not in orders_df.columns:
        print(f"  {tag} new SKU check: no order rows")
        return []

    order_skus = {
        str(s).strip().upper()
        for s in orders_df["sku"].dropna().unique()
        if str(s).strip() and str(s).strip().lower() != MISSING_SKU_LABEL.lower()
    }
    cogs_skus = set()
    if not cogs_df.empty and "sku" in cogs_df.columns:
        cogs_skus = {
            str(s).strip().upper()
            for s in cogs_df["sku"].dropna().unique()
            if str(s).strip()
        }
    missing = sorted(order_skus - cogs_skus)
    if missing:
        print(f"  {tag} NEW SKUs in orders but not in COGS ({len(missing)}):")
        for sku in missing[:50]:
            print(f"    - {sku}")
        if len(missing) > 50:
            print(f"    ... +{len(missing) - 50} more")
    else:
        print(f"  {tag} No new SKUs - all order SKUs present in COGS")
    return missing


# ---------------------------------------------------------------------------
# Transform
# ---------------------------------------------------------------------------

def _parse_purchase_dt(series: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(series, utc=True, errors="coerce")
    try:
        return parsed.dt.tz_localize(None)
    except TypeError:
        return parsed.dt.tz_convert(None) if getattr(parsed.dt, "tz", None) else parsed


def transform_geography_shopify_orders(
    raw_df: pd.DataFrame,
    *,
    cfg: ClientShopifyOrdersConfig,
    geography_code: str,
    geo_cfg: ShopifyGeoConfig,
) -> pd.DataFrame:
    """
    Per-geo transform after all year files are appended:

      1. select required columns
      2. drop blank purchase_hour
      3. qty / signed total_sales clean
      4. datetime fields
      5. SKU clean+map; missing → Not defined
      6. pivot + pincode + COGS; missing product_name → Not defined
      7. print new SKUs vs COGS
    """
    if raw_df.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    code = geography_code.upper()
    df = raw_df.copy()

    # --- 1) Select required columns ---
    keep_cols = [c for c in PROCESS_COLUMNS if c in df.columns]
    missing_req = [c for c in ("sku", "order_id", "purchase_hour", "quantity", "total_sales") if c not in df.columns]
    if missing_req:
        raise ValueError(f"[{code}] missing required columns after append: {missing_req}")
    df = df.loc[:, keep_cols].copy()
    print(f"  [1] select columns: {len(keep_cols)} cols -> {len(df):,} rows")

    # --- 2) Drop blank purchase_hour ---
    before = len(df)
    df = df[~_is_blank_series(df["purchase_hour"])].copy()
    print(f"  [2] drop blank purchase_hour: {len(df):,} / {before:,}")
    if df.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    # Market / vendor lists are bookmarked in geography.yaml — not filtered here
    if geo_cfg.markets or geo_cfg.vendors:
        print(
            "  market/vendor filter: OFF "
            f"(yaml bookmark markets={list(geo_cfg.markets)} "
            f"vendors={list(geo_cfg.vendors)})"
        )

    # --- 3) Qty / signed sales ---
    df["quantity"] = (
        pd.to_numeric(df["quantity"], errors="coerce").fillna(0).round(0).astype(int)
    )
    df["total_sales"] = pd.to_numeric(df["total_sales"], errors="coerce").fillna(0.0)
    before = len(df)
    df = df[(df["quantity"] != 0) | (df["total_sales"] != 0)].copy()
    neg_sales = int((df["total_sales"] < 0).sum())
    print(
        f"  [3] keep qty!=0 or sales!=0: {len(df):,} / {before:,} "
        f"(negative total_sales rows={neg_sales:,})"
    )
    if df.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    # --- 4) Datetime from purchase_hour ---
    purchase_dt = _parse_purchase_dt(df["purchase_hour"])
    df = df.copy()
    df["_purchase_dt"] = purchase_dt
    before = len(df)
    df = df[df["_purchase_dt"].notna()].copy()
    print(f"  [4] parse purchase_hour datetime: {len(df):,} / {before:,}")
    if df.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    df["purchase_date"] = df["_purchase_dt"].dt.strftime("%Y-%m-%d")
    df["year_month"] = df["_purchase_dt"].dt.to_period("M").astype(str)
    df["year_month"] = df["year_month"].fillna("").astype(str)
    df["purchase_hour"] = df["_purchase_dt"].dt.hour
    df["purchase_time"] = df["_purchase_dt"].dt.strftime("%H:%M")
    df = df.drop(columns=["_purchase_dt"])

    # --- 5) SKU clean + map; fill missing with Not defined (do not drop) ---
    print("  [5] SKU clean via knc_sku_cleaning(source='shopify'); missing -> Not defined")
    df = knc_sku_cleaning.clean_sku_column(
        df,
        sku_column="sku",
        sku_mapping=None,
        drop_missing=False,
        source="shopify",
    )
    missing_sku = _is_blank_series(df["sku"])
    filled = int(missing_sku.sum())
    df.loc[missing_sku, "sku"] = MISSING_SKU_LABEL
    print(f"  [5] SKUs filled as '{MISSING_SKU_LABEL}': {filled:,}")

    if "order_id" in df.columns:
        df["order_id"] = (
            df["order_id"].fillna("").astype(str).replace({"nan": "", "None": "", "NONE": ""})
        )

    for col in ("pincode", "city"):
        if col not in df.columns:
            df[col] = None

    group_cols = [
        "order_id",
        "year_month",
        "purchase_date",
        "purchase_hour",
        "purchase_time",
        "order_status",
        "sku",
        "pincode",
        "city",
    ]
    for col in group_cols:
        if col not in df.columns:
            df[col] = "UNKNOWN"
    df[group_cols] = df[group_cols].fillna("UNKNOWN")

    pivoted = (df.pivot_table(index=group_cols,values=["quantity", "total_sales"],aggfunc="sum",).reset_index())
    print(f"  pivot rows: {len(pivoted):,}")

    pivoted = attach_shopify_city_state(code, pivoted)
    if "City" in pivoted.columns:
        pivoted = pivoted.rename(columns={"City": "city", "State": "state"})
    if "city" not in pivoted.columns:
        pivoted["city"] = None
    if "state" not in pivoted.columns:
        pivoted["state"] = None
    if "pincode_new" not in pivoted.columns:
        pivoted["pincode_new"] = pivoted.get("pincode")

    # --- 6) COGS merge; missing product_name → Not defined ---
    cogs = pd.DataFrame(columns=["sku", "product_name"])
    try:
        cogs = load_shopify_cogs(code)
        pivoted = pivoted.merge(cogs, on="sku", how="left")
        from config_manager import cogs_local

        cogs_path = cogs_local.resolve_cogs_slice_path("KNC", code, channel="shopify")
        print(f"  [6] COGS merge: {cogs_path.name} (channel=shopify)")
    except Exception as exc:  # noqa: BLE001
        print(f"  [6] [WARN] COGS merge skipped: {exc}")
        if "product_name" not in pivoted.columns:
            pivoted["product_name"] = pd.NA

    if "product_name" not in pivoted.columns:
        pivoted["product_name"] = pd.NA
    name_blank = _is_blank_series(pivoted["product_name"])
    pivoted.loc[name_blank, "product_name"] = MISSING_PRODUCT_NAME_LABEL
    # Explicit: unmatched / Not defined SKU → Not defined product name
    pivoted.loc[
        pivoted["sku"].astype(str).str.strip().str.lower() == MISSING_SKU_LABEL.lower(),
        "product_name",
    ] = MISSING_PRODUCT_NAME_LABEL
    print(
        f"  [6] product_name filled as '{MISSING_PRODUCT_NAME_LABEL}': "
        f"{int(name_blank.sum()):,}"
    )

    # --- 7) New SKUs in orders but not in COGS ---
    print("  [7] new SKU check (orders vs Shopify COGS)")
    _print_new_skus_vs_cogs(
        pivoted,
        cogs,
        client=cfg.client_code,
        geography_code=code,
    )

    aov_df = (
        pivoted.groupby("year_month", as_index=False)
        .agg(unique_orders=("order_id", "nunique"), month_sales=("total_sales", "sum"))
    )
    aov_df["aov"] = (
        aov_df["month_sales"] / aov_df["unique_orders"].replace(0, np.nan)
    ).round(2)
    pivoted = pivoted.merge(aov_df[["year_month", "aov"]], on="year_month", how="left")

    pivoted["client"] = cfg.client_code
    pivoted["geography"] = code
    pivoted["platform"] = "shopify"
    pivoted["currency"] = geo_cfg.currency

    pivoted["quantity"] = pd.to_numeric(pivoted["quantity"], errors="coerce").fillna(0)
    pivoted["total_sales"] = pd.to_numeric(pivoted["total_sales"], errors="coerce").fillna(0.0)
    pivoted = pivoted[
        (pivoted["quantity"] != 0) | (pivoted["total_sales"] != 0)
    ].copy()

    keep = [c for c in OUTPUT_COLUMNS if c in pivoted.columns]
    return pivoted.loc[:, keep].reset_index(drop=True)


def _filter_years_on_frame(
    df: pd.DataFrame,
    years: Optional[Sequence[str]],
) -> pd.DataFrame:
    """When files came from a flat folder, restrict by year_month year."""
    if df.empty or years is None or "year_month" not in df.columns:
        return df
    allowed = {str(y).strip() for y in years}
    ym = df["year_month"].astype(str)
    mask = ym.str.slice(0, 4).isin(allowed)
    return df.loc[mask].copy()


# ---------------------------------------------------------------------------
# Save / build / run
# ---------------------------------------------------------------------------

def save_geography_outputs(
    df: pd.DataFrame,
    output_dir: Path,
    name_suffix: str = PARQUET_NAME_SUFFIX,
) -> List[Path]:
    if df.empty:
        print("[WARN] Nothing to save - DataFrame is empty")
        return []
    df = prefer_geography_column(df)
    if "geography" not in df.columns:
        raise KeyError("Expected 'geography' column")

    output_dir.mkdir(parents=True, exist_ok=True)
    saved: List[Path] = []
    print(f"\n>>> STEP: save per-geography Shopify orders -> {output_dir}")
    for geography, geo_df in df.groupby("geography", sort=True):
        geo_name = str(geography).upper()
        parquet_path = output_dir / f"{geo_name}_{name_suffix}.parquet"
        csv_path = output_dir / f"{geo_name}_{name_suffix}.csv"
        geo_df.to_parquet(parquet_path, index=False)
        geo_df.to_csv(csv_path, index=False)
        saved.extend([parquet_path, csv_path])
        print(f"  [{geo_name}] {len(geo_df):,} rows -> {parquet_path.name}, {csv_path.name}")
    return saved


def build_shopify_orders_dataframe(
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
    print(f"Years  : {list(years)}")
    print(f"Months : {list(months) if months is not None else 'ALL'}")
    print(f"Geos   : {list(geos) if geos is not None else 'ALL (shopify channels)'}")
    print(f"Shopify geos configured: {', '.join(sorted(cfg.geos))}")
    print(f"Output : {out_dir}")
    print(f"Suffix : {PARQUET_NAME_SUFFIX}  (Amazon parquet NOT touched)")
    print(f"Merge  : {merge_existing}")
    print("=" * 60)

    targets = resolve_geo_targets(cfg, geos)
    target_geos = [code for code, _root, _gcfg in targets]
    if not targets:
        print(
            "\n[SKIP] No Shopify order geos to process for this selection "
            f"(configured={sorted(cfg.geos)}, requested={list(geos) if geos else 'ALL'})."
        )
        return pd.DataFrame(columns=OUTPUT_COLUMNS), [], LoadStats()

    print(f"\n>>> STEP: run Shopify orders for geos={target_geos} only")

    all_frames: List[pd.DataFrame] = []
    failed_files: List[dict] = []
    processed_files: Set[Path] = set()
    stats = LoadStats()

    print("\n>>> STEP: load raw Shopify order CSVs")
    for geo_code, sales_root, geo_cfg in targets:
        stats.geographies.add(geo_code)
        print(f"  geo root [{geo_code}]: {sales_root}")
        year_folders = discover_year_folders(sales_root, years=years)
        flat_mode = len(year_folders) == 1 and year_folders[0].resolve() == sales_root.resolve()

        for year_path in year_folders:
            year_label = year_path.name if not flat_mode else "flat"
            if not flat_mode:
                stats.year_folders.add(f"{geo_code}/{year_label}")
            for file_path in discover_order_files(year_path, months=months):
                resolved = file_path.resolve()
                if resolved in processed_files:
                    continue
                print(
                    f"[{cfg.client_code}] [{geo_code}] [{year_label}] "
                    f"Reading {file_path.name}"
                )
                try:
                    df = read_shopify_order_file(file_path)
                    if df.empty:
                        processed_files.add(resolved)
                        continue
                    df = df.copy()
                    df["geography"] = geo_code
                    df["source_file"] = file_path.name
                    df["source_path"] = str(resolved)
                    all_frames.append(df)
                    processed_files.add(resolved)
                    stats.record_file_ok(geo_code, year_label, len(df))
                except Exception as exc:  # noqa: BLE001
                    print(
                        f"[{cfg.client_code}] [{geo_code}] [{year_label}] "
                        f"ERROR reading {file_path.name}: {exc}"
                    )
                    failed_files.append(
                        {
                            "path": str(resolved),
                            "geography": geo_code,
                            "year": year_label,
                            "error": str(exc),
                        }
                    )
                    stats.record_file_failed(geo_code, year_label)
                    processed_files.add(resolved)

    raw_df = (
        pd.concat(all_frames, ignore_index=True, sort=False) if all_frames else pd.DataFrame()
    )
    master_df = raw_df
    run_log = ReportRunLog(cfg.client_code, "shopify_orders")
    try:
        summary = stats.print_summary(title=f"{cfg.client_code} Shopify Orders Load Summary")
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
            print(
                "\n>>> STEP: transform per geo "
                "(select cols -> drop blank hour -> SKU Not defined -> COGS -> new SKUs)"
            )
            frames: List[pd.DataFrame] = []
            for geography, geo_df in raw_df.groupby("geography", sort=True):
                code = str(geography).strip().upper()
                geo_cfg = cfg.geos[code]
                print(f"\n>>> STEP: transform [{cfg.client_code}] {code} ({len(geo_df):,} raw rows)")
                try:
                    cleaned = transform_geography_shopify_orders(
                        geo_df, cfg=cfg, geography_code=code, geo_cfg=geo_cfg
                    )
                    # Flat IE dumps: apply year filter on year_month
                    cleaned = _filter_years_on_frame(cleaned, years)
                    print(f"  Result: {len(cleaned):,} pivoted rows")
                    if not cleaned.empty:
                        frames.append(cleaned)
                except Exception as exc:  # noqa: BLE001
                    print(f"  ERROR transforming {code}: {exc}")
            new_df = (
                pd.concat(frames, ignore_index=True, sort=False)
                if frames
                else pd.DataFrame(columns=OUTPUT_COLUMNS)
            )
            print(f"Transformed new slice shape: {new_df.shape}")
            print("\n>>> STEP: resolve duplicate order items (status rules)")
            new_df = resolve_orders_duplicates(new_df)
        else:
            new_df = raw_df

        if merge_existing:
            print("\n>>> STEP: merge with existing Shopify parquet masters (run geos only)")
            existing_df = load_existing_shopify_orders(out_dir, target_geos)
            master_df = merge_orders_with_existing(existing_df, new_df)
            master_df = _filter_df_to_geos(master_df, target_geos)
        else:
            master_df = resolve_orders_duplicates(new_df) if apply_transform else new_df
            master_df = _filter_df_to_geos(master_df, target_geos)

        if not master_df.empty:
            print("\n>>> STEP: new SKU check vs Shopify COGS (exclude 'Not defined')")
            check_df = master_df[
                master_df["sku"].astype(str).str.strip().str.lower()
                != MISSING_SKU_LABEL.lower()
            ].copy()
            check_final_dataframe_new_skus(
                check_df,
                client=cfg.client_code,
                label="shopify_orders",
                channel="shopify",
                run_log=run_log,
            )

        if apply_transform and not master_df.empty:
            print("\n>>> STEP: 3-month qty/sales checklist")
            period_text = print_orders_three_month_checklist(master_df)
            run_log.blank()
            run_log.append(period_text)

        if save_output and not master_df.empty:
            save_geography_outputs(master_df, output_dir=out_dir)
    finally:
        run_log.flush()

    print("-" * 60)
    print(f"Done. Master shape: {master_df.shape}")
    return master_df, failed_files, stats


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="KNC Shopify orders combiner (UK + IE)")
    parser.add_argument("--client", default=CLIENT, choices=sorted(CLIENT_CONFIGS.keys()))
    parser.add_argument("--geos", default=None, help="Comma-separated geo codes (UK,IE)")
    parser.add_argument("--years", default=None, help="Comma-separated years")
    parser.add_argument("--months", default=None, help="Comma-separated month tokens")
    parser.add_argument("--no-merge", action="store_true")
    parser.add_argument("--no-save", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> None:
    try:
        args = parse_args(argv)
        geos = [g.strip().upper() for g in args.geos.split(",")] if args.geos else None
        years = [y.strip() for y in args.years.split(",")] if args.years else None
        months = [m.strip() for m in args.months.split(",")] if args.months else None
        build_shopify_orders_dataframe(
            client=args.client,
            geos=geos,
            years=years,
            months=months,
            save_output=not args.no_save,
            merge_existing=not args.no_merge,
        )
        print_script_completed(
            "shopify_orders_report",
            detail=f"geos={','.join(geos)}" if geos else "",
        )
    except Exception as exc:  # noqa: BLE001
        print_script_failure(exc, script_hint="shopify_orders")
        raise


def run(
    client: str = CLIENT,
    geos: Optional[Sequence[str]] = None,
    years: Optional[Sequence[str]] = None,
    months: Optional[Sequence[str]] = None,
    save_output: bool = SAVE_OUTPUT,
    apply_transform: bool = APPLY_TRANSFORM,
    merge_existing: bool = MERGE_WITH_EXISTING,
    **_kwargs,
) -> pd.DataFrame:
    """Pipeline entrypoint."""
    key = str(client).strip().upper()
    if key not in CLIENT_CONFIGS:
        print(
            f"[skip] shopify_orders supports {', '.join(sorted(CLIENT_CONFIGS))} "
            f"only (got client={client})"
        )
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    master, _failed, _stats = build_shopify_orders_dataframe(
        client=key,
        geos=geos,
        years=years,
        months=months,
        save_output=save_output,
        apply_transform=apply_transform,
        merge_existing=merge_existing,
    )
    # Success banner is printed by pipeline_engine.executor.import_and_run
    return master


if __name__ == "__main__":
    main()
