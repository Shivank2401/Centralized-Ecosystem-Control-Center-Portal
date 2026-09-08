"""
Client-aware Amazon Orders combiner (ESH + KNC).

Shared pipeline:
  load year folders → filter sales-channel → SKU clean (esh/knc) →
  pivot → dates → city/state via orders_pincode → monthly AOV →
  new-SKU alert vs COGS → 3-month qty/sales checklist (client × geo).

Outputs (per client):
  sanity_data/{CLIENT}/orders/{GEO}_orders.parquet (+ .csv)

Run examples:
  python report_script/common_sanity_report/orders_report.py
  python report_script/common_sanity_report/orders_report.py --client ESH --geos US,UK
  python report_script/common_sanity_report/orders_report.py --client KNC --years 2026
"""

from __future__ import annotations

import argparse
import re
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

from config_manager import esh_sku_cleaning, knc_sku_cleaning, layouts, paths
from config_manager.loader import load_geographies
from config_manager.orders_pincode import attach_city_state_for_geo
from config_manager.report_helpers import (
    IGNORE_FILE_NAMES,
    IGNORE_FILE_PREFIXES,
    LoadStats,
    load_existing_parquet_outputs,
    print_script_completed,
)
from report_script.common_sanity_report.new_sku_check import (
    check_final_dataframe_new_skus,
)
from report_script.common_sanity_report.run_logs import (
    ReportRunLog,
)

# ---------------------------------------------------------------------------
# Run knobs
# ---------------------------------------------------------------------------

CLIENT: str = "ESH"
PROCESS_GEOS: Optional[List[str]] = None
VALID_YEARS = {"2023", "2024", "2025", "2026"}
PROCESS_YEARS: Optional[List[str]] = ["2023", "2024", "2025", "2026"]
PROCESS_MONTHS: Optional[List[str]] = None

SAVE_OUTPUT = True
MERGE_WITH_EXISTING = True
APPLY_TRANSFORM = True

PARQUET_NAME_SUFFIX = "orders_database"
# Status-aware dedupe uses order_id/sku/qty/sales + order_status (see _resolve_duplicate_order_items).

ORDER_COLUMNS = [
    "amazon-order-id",
    "order-status",
    "sales-channel",
    "sku",
    "purchase-date",
    "quantity",
    "item-price",
    "promotion-ids",
    "ship-city",
    "ship-postal-code",
]
OPTIONAL_COLUMNS = ["Source.Name", "product-name"]

RENAME_MAP = {
    "sku": "sku",
    "amazon-order-id": "order_id",
    "purchase-date": "purchase_date",
    "promotion-ids": "promotion_ids",
    "ship-city": "city",
    "ship-postal-code": "pincode",
    "order-status": "order_status",
    "product-name": "product_name",
}

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
    "country",
    "platform",
    "currency",
]

# Line-level ASHU export (before pivot) — keeps promotion_ids
ASHU_PREFERRED_COLUMNS = [
    "Source.Name",
    "order_id",
    "order_status",
    "sales-channel",
    "SKU",
    "purchase_date",
    "purchase_date_1",
    "year_month",
    "purchase_hour",
    "purchase_time",
    "quantity",
    "item-price",
    "total_sales",
    "promotion_ids",
    "city",
    "pincode",
    "client",
    "geography",
    "currency",
]
ASHU_FOLDER = "orders_ASHU"
ASHU_NAME_SUFFIX = "orders_ASHU"


# ---------------------------------------------------------------------------
# Client configuration
# ---------------------------------------------------------------------------

@dataclass
class ClientOrdersConfig:
    client_code: str
    client_id: str
    client_name: str
    layout: str  # "esh" | "knc"
    base_path: Path = field(default_factory=Path)
    geo_roots: Dict[str, Path] = field(default_factory=dict)
    cogs_path: Path = field(default_factory=Path)
    cogs_sheets: Dict[str, str] = field(default_factory=dict)
    sales_channels: Dict[str, str] = field(default_factory=dict)
    currencies: Dict[str, str] = field(default_factory=dict)
    sku_backend: str = "esh"
    product_name_contains: Dict[str, str] = field(default_factory=dict)
    sku_source_by_geo: Dict[str, str] = field(default_factory=dict)
    european_numeric_geos: Set[str] = field(default_factory=set)


def _geo_meta(client: str) -> Tuple[Dict[str, str], Dict[str, str]]:
    geos = load_geographies(client)
    channels = {code: g.orders_sales_channel for code, g in geos.items()}
    currencies = {code: g.country_currency for code, g in geos.items()}
    return channels, currencies


def _esh_config() -> ClientOrdersConfig:
    ident = layouts.client_identity("ESH")
    channels, currencies = _geo_meta("ESH")
    revenue_root = paths.esh_revenue_root()
    return ClientOrdersConfig(
        client_code=ident["client_code"],
        client_id=ident["client_id"],
        client_name=ident["client_name"],
        layout=ident["layout"],
        base_path=revenue_root,
        geo_roots=layouts.esh_orders_geo_roots(revenue_root),
        cogs_path=layouts.cogs_path("ESH"),
        cogs_sheets=layouts.cogs_sheets_for("ESH"),
        sales_channels=channels,
        currencies=currencies,
        sku_backend="esh",
    )


def _knc_config() -> ClientOrdersConfig:
    ident = layouts.client_identity("KNC")
    base = layouts.data_root("KNC")
    channels, currencies = _geo_meta("KNC")
    return ClientOrdersConfig(
        client_code=ident["client_code"],
        client_id=ident["client_id"],
        client_name=ident["client_name"],
        layout=ident["layout"],
        base_path=base,
        geo_roots=layouts.knc_geo_roots("orders", base),
        cogs_path=layouts.cogs_path("KNC"),
        cogs_sheets=layouts.cogs_sheets_for("KNC"),
        sales_channels=channels,
        currencies=currencies,
        sku_backend="knc",
        product_name_contains={"AE": "Kinetica"},
        sku_source_by_geo={"AE": "amazon_ae"},
        european_numeric_geos={"DE"},
    )


CLIENT_CONFIGS: Dict[str, Callable[[], ClientOrdersConfig]] = {
    "ESH": _esh_config,
    "KNC": _knc_config,
}


def get_client_config(client: str) -> ClientOrdersConfig:
    key = str(client).strip().upper()
    if key not in CLIENT_CONFIGS:
        raise ValueError(f"Unknown client '{client}'. Expected one of: {list(CLIENT_CONFIGS)}")
    return CLIENT_CONFIGS[key]()


def output_dir_for(client_code: str) -> Path:
    return paths.sanity_data_root() / client_code.upper() / "orders"


def ashu_output_dir_for(client_code: str) -> Path:
    """Line-level ASHU export folder (promotion_ids retained)."""
    return paths.sanity_data_root() / client_code.upper() / ASHU_FOLDER


# ---------------------------------------------------------------------------
# SKU / COGS
# ---------------------------------------------------------------------------

def load_client_sku_mapping(
    cfg: ClientOrdersConfig,
    geography_code: Optional[str] = None,
) -> dict:
    geos = (
        [geography_code]
        if geography_code
        else list(cfg.cogs_sheets.keys())
    )
    if cfg.sku_backend == "knc":
        return knc_sku_cleaning.load_sku_mapping(geos=geos)
    return esh_sku_cleaning.load_sku_mapping(geos=geos)


def clean_client_skus(
    df: pd.DataFrame,
    cfg: ClientOrdersConfig,
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


# ---------------------------------------------------------------------------
# File IO
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
    cfg: ClientOrdersConfig,
    geos: Optional[Sequence[str]] = None,
) -> List[Tuple[str, Path]]:
    wanted: Optional[Set[str]] = None
    if geos is not None:
        wanted = {str(g).strip().upper() for g in geos}

    targets: List[Tuple[str, Path]] = []
    for code, root in cfg.geo_roots.items():
        if wanted is not None and code.upper() not in wanted:
            continue
        if not root.is_dir():
            print(f"[WARN] [{cfg.client_code}] Orders path missing: {root}")
            continue
        targets.append((code, root))
    return sorted(targets, key=lambda t: t[0])


def discover_year_folders(
    orders_root: Path,
    years: Optional[Sequence[str]] = None,
) -> List[Path]:
    allowed = set(VALID_YEARS)
    if years is not None:
        allowed &= {str(y).strip() for y in years}
    found: List[Path] = []
    if not orders_root.is_dir():
        return found
    for path in orders_root.iterdir():
        if path.is_dir() and path.name in allowed:
            found.append(path)
    return sorted(found, key=lambda p: p.name)


def discover_order_files(
    year_path: Path,
    months: Optional[Sequence[str]] = None,
) -> List[Path]:
    wanted = _month_filter_tokens(months)
    files: List[Path] = []
    for path in year_path.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".txt", ".csv", ".xlsx", ".xls"}:
            continue
        if is_ignored_file(path):
            continue
        if wanted is not None:
            rel_parts = {part.lower() for part in path.relative_to(year_path).parts[:-1]}
            name_l = path.name.lower()
            if not ((rel_parts & wanted) or any(tok in name_l for tok in wanted)):
                continue
        files.append(path)
    return sorted(files, key=lambda p: p.as_posix().lower())


def _hydrate_onedrive_file(file_path: Path) -> None:
    with open(file_path, "rb") as handle:
        handle.read(1)


def read_order_file(file_path: Path) -> pd.DataFrame:
    _hydrate_onedrive_file(file_path)
    suffix = file_path.suffix.lower()
    wanted = ORDER_COLUMNS + OPTIONAL_COLUMNS

    if suffix in {".xlsx", ".xls"}:
        raw = pd.read_excel(file_path, dtype=str)
    elif suffix == ".txt":
        try:
            raw = pd.read_csv(file_path, sep="\t", encoding="utf-8", dtype=str)
        except UnicodeDecodeError:
            raw = pd.read_csv(file_path, sep="\t", encoding="latin1", dtype=str)
    else:
        try:
            raw = pd.read_csv(file_path, encoding="utf-8", dtype=str)
        except UnicodeDecodeError:
            raw = pd.read_csv(file_path, encoding="latin1", dtype=str)

    raw.columns = [str(c).strip().replace("\ufeff", "") for c in raw.columns]
    available = [c for c in wanted if c in raw.columns]
    if "sku" not in available or "amazon-order-id" not in available:
        raise ValueError(f"Missing required columns in {file_path.name}")
    out = raw.loc[:, available].copy()
    if "Source.Name" not in out.columns:
        out["Source.Name"] = file_path.name
    return out


def clean_european_number(value) -> Optional[float]:
    if pd.isna(value):
        return None
    s = str(value).strip()
    s = re.sub(r"[^0-9,.\-\s]", "", s)
    s = re.sub(r"([0-9])[, \-]([0-9]{2})$", r"\1.\2", s)
    if re.fullmatch(r"\d{3,}", s):
        s = s[:-2] + "." + s[-2:]
    s = re.sub(r"(?<=\.)[^0-9].*", "", s)
    try:
        return float(s)
    except ValueError:
        return None


def standardize_sales_channel(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.lower().str.capitalize()


# ---------------------------------------------------------------------------
# Transform
# ---------------------------------------------------------------------------

def _parse_purchase_dates(series: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(series, utc=True, errors="coerce")
    try:
        return parsed.dt.tz_localize(None)
    except TypeError:
        return parsed.dt.tz_convert(None) if getattr(parsed.dt, "tz", None) else parsed


def _build_ashu_frame(
    df: pd.DataFrame,
    *,
    cfg: ClientOrdersConfig,
    geography_code: str,
) -> pd.DataFrame:
    """
    Line-level orders frame exported before pivot (legacy *_orders_ASHU.csv).

    Keeps promotion_ids and other source columns that are dropped by the
    order_id/sku/pincode/city pivot used for the main orders dataset.
    """
    ashu = df.copy()
    purchase_dt = _parse_purchase_dates(ashu["purchase_date"])
    ashu["year_month"] = purchase_dt.dt.to_period("M").astype(str)
    ashu["purchase_hour"] = purchase_dt.dt.hour
    ashu["purchase_time"] = purchase_dt.dt.strftime("%H:%M")
    ashu["purchase_date_1"] = purchase_dt.dt.strftime("%d-%b-%Y")

    if "sku" in ashu.columns and "SKU" not in ashu.columns:
        ashu = ashu.rename(columns={"sku": "SKU"})

    ashu["client"] = cfg.client_code
    ashu["geography"] = geography_code
    ashu["currency"] = cfg.currencies.get(geography_code)

    keep = [c for c in ASHU_PREFERRED_COLUMNS if c in ashu.columns]
    extras = [c for c in ashu.columns if c not in keep and not str(c).startswith("__")]
    # Prefer stable ASHU schema; append any leftover useful cols except load helpers
    skip_extras = {"year", "month", "source_file", "source_path", "product_name", "product-name"}
    extras = [c for c in extras if c not in skip_extras]
    return ashu.loc[:, keep + extras].reset_index(drop=True)


def transform_geography_orders(
    raw_df: pd.DataFrame,
    *,
    cfg: ClientOrdersConfig,
    geography_code: str,
    sku_mapping: dict,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Returns:
      pivoted_df — main sanity orders output (no promotion_ids)
      ashu_df    — line-level export with promotion_ids (pre-pivot)
    """
    empty_ashu = pd.DataFrame(columns=ASHU_PREFERRED_COLUMNS)
    if raw_df.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS), empty_ashu

    df = raw_df.copy()

    channel = cfg.sales_channels.get(geography_code)
    if not channel:
        raise KeyError(f"No orders_sales_channel for {cfg.client_code}/{geography_code}")

    df["sales-channel"] = standardize_sales_channel(df["sales-channel"])
    before = len(df)
    channel_norm = str(channel).strip().lower().capitalize()
    df = df[df["sales-channel"] == channel_norm].copy()
    print(f"  sales-channel={channel_norm!r}: {len(df):,} / {before:,} rows")
    if df.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS), empty_ashu

    contains = cfg.product_name_contains.get(geography_code)
    if contains and "product-name" in df.columns:
        df = df[df["product-name"].astype(str).str.contains(contains, case=False, na=False)].copy()
        print(f"  product-name contains {contains!r}: {len(df):,} rows")
    if df.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS), empty_ashu

    if geography_code in cfg.european_numeric_geos:
        df["quantity"] = df["quantity"].apply(clean_european_number)
        df["item-price"] = df["item-price"].apply(clean_european_number)
    else:
        df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce")
        df["item-price"] = pd.to_numeric(df["item-price"], errors="coerce")

    df["quantity"] = df["quantity"].fillna(0).round(0)
    df["total_sales"] = df["item-price"].fillna(0).astype(float)

    rename = {k: v for k, v in RENAME_MAP.items() if k in df.columns}
    df = df.rename(columns=rename)

    df = clean_client_skus(df, cfg, geography_code, sku_mapping=sku_mapping)

    # --- ASHU export snapshot (line-level, includes promotion_ids) ---
    ashu_df = _build_ashu_frame(df, cfg=cfg, geography_code=geography_code)
    print(f"  ASHU line-level rows: {len(ashu_df):,}")

    group_cols = ["order_id", "purchase_date", "order_status", "sku", "pincode", "city"]
    for col in group_cols:
        if col not in df.columns:
            df[col] = "UNKNOWN"
    df[group_cols] = df[group_cols].fillna("UNKNOWN")

    pivoted = (
        df.pivot_table(
            index=group_cols,
            values=["quantity", "total_sales"],
            aggfunc="sum",
        )
        .reset_index()
    )

    purchase_dt = _parse_purchase_dates(pivoted["purchase_date"])
    pivoted["year_month"] = purchase_dt.dt.to_period("M").astype(str)
    pivoted["purchase_hour"] = purchase_dt.dt.hour
    pivoted["purchase_time"] = purchase_dt.dt.strftime("%H:%M")
    pivoted["purchase_date"] = purchase_dt.dt.strftime("%Y-%m-%d")

    pivoted = attach_city_state_for_geo(geography_code, pivoted)
    # Normalize City/State from pincode helper
    if "City" in pivoted.columns:
        pivoted = pivoted.rename(columns={"City": "city", "State": "state"})
    if "city" not in pivoted.columns:
        pivoted["city"] = None
    if "state" not in pivoted.columns:
        pivoted["state"] = None
    if "pincode_new" not in pivoted.columns:
        pivoted["pincode_new"] = pivoted.get("pincode")

    aov_df = (
        pivoted.groupby("year_month", as_index=False)
        .agg(unique_orders=("order_id", "nunique"), month_sales=("total_sales", "sum"))
    )
    aov_df["aov"] = (
        aov_df["month_sales"] / aov_df["unique_orders"].replace(0, np.nan)
    ).round(2)
    pivoted = pivoted.merge(aov_df[["year_month", "aov"]], on="year_month", how="left")

    pivoted["client"] = cfg.client_code
    pivoted["geography"] = geography_code
    pivoted["country"] = geography_code
    pivoted["platform"] = "amazon"
    pivoted["currency"] = cfg.currencies.get(geography_code)

    pivoted["quantity"] = pd.to_numeric(pivoted["quantity"], errors="coerce").fillna(0)
    pivoted["total_sales"] = pd.to_numeric(pivoted["total_sales"], errors="coerce").fillna(0.0)
    pivoted = pivoted[pivoted["quantity"] != 0].copy()

    # Drop leftover helper columns; keep stable output schema
    keep = [c for c in OUTPUT_COLUMNS if c in pivoted.columns]
    return pivoted.loc[:, keep].reset_index(drop=True), ashu_df


# ---------------------------------------------------------------------------
# Period summary / checklist
# ---------------------------------------------------------------------------
def _three_month_labels(as_of: Optional[pd.Timestamp] = None) -> Tuple[str, str, str]:
    """
    Return (current_month, previous_month, previous_2_month) as YYYY-MM.

    Uses yesterday as the reference day. On the first 2 calendar days of a
    month, "current" is still the prior month (same early-month rule as before).
    """
    today = as_of if as_of is not None else pd.Timestamp.today().normalize()
    ref = today - pd.Timedelta(days=1)
    if ref.day <= 2:
        current = (ref - pd.DateOffset(months=1)).to_period("M")
    else:
        current = ref.to_period("M")
    return str(current), str(current - 1), str(current - 2)


def _period_labels(as_of: Optional[pd.Timestamp] = None) -> Tuple[str, str, str]:
    """Legacy helper: (current_month, previous_month, current_year)."""
    m0, m1, _m2 = _three_month_labels(as_of)
    return m0, m1, m0[:4]


def _fmt_qty(value: float) -> str:
    return f"{int(round(value)):,}"


def _fmt_sales(value: float) -> str:
    return f"{value:,.2f}"


def print_orders_three_month_checklist(df: pd.DataFrame) -> str:
    """
    Print Orders period summary as a tabular checklist:

        Client- ESH          2026-09              2026-08              2026-07
        GEO            Qty        Sales     Qty        Sales     Qty        Sales
        AE              26       277.80     ...
    """
    if df is None or df.empty:
        msg = "\n[INFO] Empty orders frame - no Orders period summary"
        print(msg)
        return msg.strip()

    required = {"year_month", "quantity", "total_sales"}
    missing = required - set(df.columns)
    if missing:
        msg = f"\n[WARN] Missing columns for period summary: {sorted(missing)}"
        print(msg)
        return msg.strip()

    m0, m1, m2 = _three_month_labels()
    months = [m0, m1, m2]
    work = df.copy()
    work["quantity"] = pd.to_numeric(work["quantity"], errors="coerce").fillna(0)
    work["total_sales"] = pd.to_numeric(work["total_sales"], errors="coerce").fillna(0.0)
    work["year_month"] = work["year_month"].astype(str)
    if "client" not in work.columns:
        work["client"] = "ALL"
    if "geography" not in work.columns:
        work["geography"] = "ALL"

    geo_w, qty_w, sales_w = 12, 10, 14
    month_block_w = qty_w + 1 + sales_w
    sep = "-" * (geo_w + 2 + len(months) * (month_block_w + 2) - 2)

    def _month_pair(qty: float, sales: float) -> str:
        return f"{_fmt_qty(qty):>{qty_w}} {_fmt_sales(sales):>{sales_w}}"

    def _header_months() -> str:
        return "  ".join(f"{label:^{month_block_w}}" for label in months)

    def _subheader() -> str:
        pair = f"{'Qty':>{qty_w}} {'Sales':>{sales_w}}"
        return "  ".join(pair for _ in months)

    lines: List[str] = []
    lines.append("")
    lines.append("=" * len(sep))
    lines.append("Orders period summary  (current + previous 2 months)")
    lines.append("=" * len(sep))

    for client, c_df in work.groupby("client", sort=True):
        client_label = f"Client- {client}"
        lines.append(f"{client_label:<{geo_w}}  {_header_months()}")
        lines.append(f"{'GEO':<{geo_w}}  {_subheader()}")
        lines.append(sep)

        for geo, geo_df in c_df.groupby("geography", sort=True):
            ym = geo_df["year_month"]
            cells: List[str] = []
            for label in months:
                slice_df = geo_df.loc[ym == label]
                cells.append(
                    _month_pair(
                        float(slice_df["quantity"].sum()),
                        float(slice_df["total_sales"].sum()),
                    )
                )
            lines.append(f"{str(geo):<{geo_w}}  " + "  ".join(cells))

        # Client total row
        ym_all = c_df["year_month"]
        total_cells: List[str] = []
        for label in months:
            slice_df = c_df.loc[ym_all == label]
            total_cells.append(
                _month_pair(
                    float(slice_df["quantity"].sum()),
                    float(slice_df["total_sales"].sum()),
                )
            )
        lines.append(sep)
        lines.append(f"{'ALL':<{geo_w}}  " + "  ".join(total_cells))
        lines.append("")

    lines.append("=" * len(sep))
    text = "\n".join(lines).rstrip() + "\n"
    print(text)
    return text.strip()


def print_period_summary_tables(df: pd.DataFrame) -> str:
    """Print tabular Orders period summary (qty/sales by GEO x 3 months)."""
    return print_orders_three_month_checklist(df)


# ---------------------------------------------------------------------------
# Dedupe (status-aware) — used when appending into existing outputs
# ---------------------------------------------------------------------------

def _resolve_duplicate_order_items(df: pd.DataFrame) -> pd.DataFrame:
    """
    Resolve duplicates for line-items using key columns + order_status precedence.

    Duplicate key:
      - Base key: order_id, sku
      - Non-cancelled dedupe key: order_id, sku, quantity, total_sales

    Precedence rules:
      - If any cancelled/canceled row exists for the same (order_id, sku),
        keep cancelled and drop pending/shipped regardless of qty/total_sales
        (because cancelled rows commonly carry qty/sales = 0).
      - Otherwise, within the non-cancelled dedupe key group:
      - pending + shipped => keep only shipped
      - pending + cancelled => keep only cancelled
      - shipped + cancelled => keep only cancelled
      - if multiple rows have the same winning status, keep the first.
    """
    if df.empty:
        return df

    required = {"order_id", "sku", "quantity", "total_sales", "order_status"}
    missing = required - set(df.columns)
    if missing:
        # Fallback: keep old behavior if expected columns are missing.
        return df.drop_duplicates()

    out = df.copy()
    out["__orig_order"] = range(len(out))

    # Normalize base key columns.
    out["order_id"] = out["order_id"].astype(str).str.strip()
    out["sku"] = out["sku"].astype(str).str.strip()

    status_norm = out["order_status"].astype(str).str.strip().str.lower()
    out["__status_norm"] = status_norm

    # 1) Cancellation override: if cancelled exists for (order_id, sku), drop other statuses.
    cancel_mask = out["__status_norm"].isin(["cancelled", "canceled"])
    if cancel_mask.any():
        cancel_keys = out.loc[cancel_mask, ["order_id", "sku"]].drop_duplicates()
        cancel_key_set = set(map(tuple, cancel_keys.values.tolist()))
        keep_mask = cancel_mask | ~out[["order_id", "sku"]].apply(tuple, axis=1).isin(cancel_key_set)
        out = out.loc[keep_mask].copy()

    # Build stable grouping keys for numeric comparisons (for non-cancelled matching).
    out["__quantity_key"] = (
        pd.to_numeric(out["quantity"], errors="coerce").fillna(0).round(0).astype("int64")
    )
    out["__total_sales_key"] = (
        pd.to_numeric(out["total_sales"], errors="coerce").fillna(0).round(2)
    )

    key_cols = ["order_id", "sku", "__quantity_key", "__total_sales_key"]

    # Higher number = higher precedence.
    rank = (
        out["__status_norm"]
        .map(
            {
                "cancelled": 3,
                "canceled": 3,
                "shipped": 2,
                "pending": 1,
                "shipping": 2,  # common typo guard
            }
        )
        .fillna(0)
        .astype("int64")
    )
    out["__status_rank"] = rank

    # Sort so the highest precedence status is encountered first.
    # For ties within the same status, keep the first occurrence in the original order.
    out = out.sort_values(by=["__status_rank", "__orig_order"], ascending=[False, True])
    resolved = out.groupby(key_cols, as_index=False).first()

    resolved = resolved.drop(
        columns=[c for c in resolved.columns if c.startswith("__")], errors="ignore"
    )
    return resolved.drop_duplicates()


def resolve_orders_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    """Apply `_resolve_duplicate_order_items` per geography (and client when present)."""
    if df is None or df.empty:
        return pd.DataFrame() if df is None else df

    group_cols = [c for c in ("client", "geography") if c in df.columns]
    if not group_cols:
        before = len(df)
        out = _resolve_duplicate_order_items(df)
        print(f"  Orders dedupe (status rules): {before:,} -> {len(out):,} rows")
        return out.reset_index(drop=True)

    frames: List[pd.DataFrame] = []
    before = len(df)
    for _, geo_df in df.groupby(group_cols, sort=False, dropna=False):
        frames.append(_resolve_duplicate_order_items(geo_df))
    out = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()
    print(f"  Orders dedupe (status rules): {before:,} -> {len(out):,} rows")
    return out


def merge_orders_with_existing(
    existing_df: pd.DataFrame,
    new_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Append new orders onto existing parquet history, then apply status-aware
    duplicate resolution (`_resolve_duplicate_order_items`).

    Concat order is existing then new so same-status ties keep the first row
    (existing wins when statuses match).
    """
    frames = [df for df in (existing_df, new_df) if df is not None and not df.empty]
    if not frames:
        return pd.DataFrame()
    if len(frames) == 1:
        return resolve_orders_duplicates(frames[0])

    combined = pd.concat(frames, ignore_index=True, sort=False)
    print(
        f"\nMerging orders history: existing={len(existing_df):,} + new={len(new_df):,} "
        f"= {len(combined):,} before status-rule dedupe"
    )
    return resolve_orders_duplicates(combined)

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
    for file_path in discover_order_files(year_path, months=months):
        resolved = file_path.resolve()
        if resolved in processed_files:
            continue

        parent = file_path.parent.name
        month_label = parent if parent != year else "files"

        print(f"[{client}] [{geography_code}] [{year}] [{month_label}] Reading {file_path.name}")
        try:
            df = read_order_file(file_path)
            if df.empty:
                processed_files.add(resolved)
                continue
            df = df.copy()
            df["geography"] = geography_code
            df["year"] = int(year) if str(year).isdigit() else year
            df["month"] = month_label
            df["source_file"] = file_path.name
            df["source_path"] = str(resolved)
            frames.append(df)
            processed_files.add(resolved)
            stats.record_file_ok(geography_code, year, len(df))
            stats.record_month_folder(geography_code, year, month_label)
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

    return frames


def transform_orders(
    raw_df: pd.DataFrame,
    cfg: ClientOrdersConfig,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Per-geography transform after bulk load (same phase as manage_fba)."""
    if raw_df.empty:
        return (
            pd.DataFrame(columns=OUTPUT_COLUMNS),
            pd.DataFrame(columns=ASHU_PREFERRED_COLUMNS),
        )

    frames: List[pd.DataFrame] = []
    ashu_frames: List[pd.DataFrame] = []

    for geography, geo_df in raw_df.groupby("geography", sort=True):
        code = str(geography).strip().upper()
        print(f"\n=== Transform [{cfg.client_code}] {code} ({len(geo_df):,} raw rows) ===")
        try:
            sku_mapping = load_client_sku_mapping(cfg, code)
            print("FBA19D7Y7F67:", sku_mapping.get("FBA19D7Y7F67"))
            print("FBA18VLXSWJF:", sku_mapping.get("FBA18VLXSWJF"))
            
            cleaned, ashu_df = transform_geography_orders(
                geo_df, cfg=cfg, geography_code=code, sku_mapping=sku_mapping
            )
            print(f"  Result: {len(cleaned):,} pivoted rows")
            if not ashu_df.empty:
                ashu_frames.append(ashu_df)
            if not cleaned.empty:
                frames.append(cleaned)
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR transforming {code}: {exc}")

    ashu_all = (
        pd.concat(ashu_frames, ignore_index=True, sort=False)
        if ashu_frames
        else pd.DataFrame(columns=ASHU_PREFERRED_COLUMNS)
    )
    if not frames:
        return pd.DataFrame(columns=OUTPUT_COLUMNS), ashu_all
    return pd.concat(frames, ignore_index=True, sort=False), ashu_all


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
    print(f"\nSaving per-geography orders outputs to: {output_dir}")
    for geography, geo_df in df.groupby("geography", sort=True):
        geo_name = str(geography).upper()
        parquet_path = output_dir / f"{geo_name}_{name_suffix}.parquet"
        csv_path = output_dir / f"{geo_name}_{name_suffix}.csv"
        geo_df.to_parquet(parquet_path, index=False)
        geo_df.to_csv(csv_path, index=False)
        saved.extend([parquet_path, csv_path])
        print(f"  [{geo_name}] {len(geo_df):,} rows -> {parquet_path.name}, {csv_path.name}")
    return saved


def save_ashu_outputs(
    df: pd.DataFrame,
    output_dir: Path,
    name_suffix: str = ASHU_NAME_SUFFIX,
) -> List[Path]:
    """Write line-level ASHU CSVs (with promotion_ids) under Orders_Ashu/."""
    if df.empty:
        print("[WARN] Nothing to save for ASHU export — DataFrame is empty")
        return []
    if "geography" not in df.columns:
        raise KeyError("Expected 'geography' column on ASHU frame")

    output_dir.mkdir(parents=True, exist_ok=True)
    saved: List[Path] = []
    print(f"\nSaving ASHU line-level orders (promotion_ids) to: {output_dir}")
    for geography, geo_df in df.groupby("geography", sort=True):
        geo_name = str(geography).upper()
        csv_path = output_dir / f"{geo_name}_{name_suffix}.csv"
        geo_df.to_csv(csv_path, index=False)
        saved.append(csv_path)
        has_promo = "promotion_ids" in geo_df.columns
        print(
            f"  [{geo_name}] {len(geo_df):,} rows -> {csv_path.name}"
            f"{' (promotion_ids ✓)' if has_promo else ''}"
        )
    return saved


def build_orders_dataframe(
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

    for geo_code, orders_root in resolve_geo_targets(cfg, geos):
        stats.geographies.add(geo_code)
        for year_path in discover_year_folders(orders_root, years=years):
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
    master_df = raw_df
    ashu_df = pd.DataFrame(columns=ASHU_PREFERRED_COLUMNS)
    run_log = ReportRunLog(cfg.client_code, "orders")
    try:
        summary = stats.print_summary(title=f"{cfg.client_code} Orders Load Summary")
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
            print("\nApplying orders transform (channel filter + SKU clean + pincode + pivot)...")
            new_df, ashu_df = transform_orders(raw_df, cfg=cfg)
            print(f"Transformed new slice shape: {new_df.shape}")
            print(f"ASHU line-level shape: {ashu_df.shape}")
            print("\nResolving duplicate order items (cancelled override + status rules)...")
            new_df = resolve_orders_duplicates(new_df)
        else:
            new_df = raw_df

        if merge_existing:
            existing_df = load_existing_parquet_outputs(out_dir, name_suffix=PARQUET_NAME_SUFFIX)
            master_df = merge_orders_with_existing(existing_df, new_df)
        else:
            master_df = resolve_orders_duplicates(new_df) if apply_transform else new_df

        if not master_df.empty:
            check_final_dataframe_new_skus(
                master_df,
                client=cfg.client_code,
                label="orders",
                run_log=run_log,
            )

        if apply_transform and not master_df.empty:
            # Tabular period summary immediately before final export.
            period_text = print_period_summary_tables(master_df)
            run_log.blank()
            run_log.append(period_text)

        if save_output:
            if not master_df.empty:
                save_geography_outputs(master_df, output_dir=out_dir)
            if apply_transform and not ashu_df.empty:
                save_ashu_outputs(ashu_df, output_dir=ashu_output_dir_for(cfg.client_code))
    finally:
        run_log.flush()

    return master_df, failed_files, stats


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Client-wise Amazon orders combiner")
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

    master_df, failed_files, _stats = build_orders_dataframe(
        client=args.client,
        geos=geos,
        years=years,
        months=months,
        save_output=not args.no_save,
        merge_existing=not args.no_merge,
    )
    print(master_df.shape)
    if not master_df.empty:
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
    run_main()
    print_script_completed('orders_report')
