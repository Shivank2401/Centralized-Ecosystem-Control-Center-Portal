"""
Vector Datahive — Amazon inventory snapshot from sanity slices + COGS.

Covers:
  - Clients: ESH + KNC (geos via --geos / client.yaml)
  - Inputs: manage_fba, reserved, ledger, ageing, orders + cogs/{client}/{geo}_amazon_cogs
  - FC transfer: AE/IN from ageing.fc_transfer; else manage_fba (fallback reserved)
  - Outputs: sanity_data/{CLIENT}/vector_report/{geo}_{platform}_inventory_report.parquet|.csv

Run:
    python report_script/requirement_specific/vector_report.py
    python report_script/requirement_specific/vector_report.py --client ESH --geos US,AE,IN
    python report_script/requirement_specific/vector_report.py --client KNC --geos UK,DE,AE
"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from dateutil.relativedelta import relativedelta

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config_manager import cogs_local, layouts, paths as cfg_paths
from config_manager.loader import load_geographies
from config_manager.report_helpers import to_snake
from config_manager.report_helpers import print_script_completed
from report_script.common_sanity_report.new_sku_check import report_new_skus_vs_cogs

CLIENT = "ESH"
PROCESS_GEOS: Optional[List[str]] = None
SAVE_OUTPUT = True
MAX_WORKERS = 4

PARQUET_NAME_SUFFIX = "inventory_report"
OUTPUT_SUBDIR = "vector_report"

# Geos whose manage-FBA file has no afn_fc_transfer_quantity — use ageing.fc_transfer.
FC_TRANSFER_FROM_AGEING_GEOS = {"AE", "IN"}

PRODUCT_INFO_COLUMNS = [
    "client_id",
    "country",
    "channel",
    "asin",
    "product_category",
    "product_cogs",
    "product_name",
    "amazon_selling_price",
    "type",
    "sku",
]

MANAGE_DROP_COLS = [
    "afn_future_supply_buyable",
    "afn_inbound_shipped_quantity",
    "afn_inbound_working_quantity",
    "afn_researching_quantity",
    "afn_reserved_quantity",
]

AGEING_DROP_COLS = [
    "date",
    "available",
    "days_of_supply",
    "velocity_trend",
    "recommended_action",
    "healthy_inventory_level",
]

MERGE_KEYS_SNAPSHOT = ["client", "client_id", "geography", "platform", "date", "sku"]
MERGE_KEYS_SKU_GEO = ["client_id", "client", "geography", "platform", "sku"]
MERGE_KEYS_PRODUCT = ["client_id", "sku", "geography", "platform"]

# Blank / NaN → 0 before export
FILLNA_ZERO_COLS = [
    "previous_DIS",
    "previous_total_days",
    "last_month_instock",
    "previous_month_sold_quantity",
    "days_in_stock",
    "total_days",
    "instock_rate",
]

# Round to 2 decimals before export
ROUND_2_COLS = [
    "afn_fulfillable_quantity",
    "afn_inbound_receiving_quantity",
    "afn_reserved_future_supply",
    "afn_total_quantity",
    "afn_unsellable_quantity",
    "afn_warehouse_quantity",
    "reserved_customer_orders",
    "reserved_fc_processing",
    "afn_reserved_quantity",
    "previous_DIS",
    "previous_total_days",
    "previous_days_out_of_stock",
    "previous_avg_unit_sold_qty",
    "last_month_instock",
    "previous_month_sold_quantity",
    "MTQ_overstock",
    "MTQ_understock",
    "days_in_stock",
    "total_days",
    "days_out_of_stock",
    "instock_rate",
    "sell_thru",
    "dos",
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
    "estimated_cost_savings_of_recommended_actions",
    "estimated_storage_cost_next_month",
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
    "afn_fc_transfer_quantity",
    "total_sellable",
    "wh_stock_value",
    "sellable_stock_value",
    "sale_lost",
    "previous_sale_lost",
]

@dataclass(frozen=True)
class VectorConfig:
    client_code: str
    client_id: str
    client_name: str
    geos: List[str]
    sanity_root: Path
    output_dir: Path


def _client_geos(client: str) -> List[str]:
    return [str(g).upper() for g in load_geographies(client)]


def get_vector_config(
    client: str,
    geos: Optional[Sequence[str]] = None,
) -> VectorConfig:
    ident = layouts.client_identity(client)
    code = ident["client_code"]
    allowed = _client_geos(code)
    if geos:
        wanted = [str(g).strip().upper() for g in geos if str(g).strip()]
        selected = [g for g in wanted if g in allowed]
        skipped = [g for g in wanted if g not in allowed]
        if skipped:
            print(f"[WARN] [{code}] geos not in client.yaml, skipped: {skipped}")
        if not selected:
            raise ValueError(
                f"No matching geos for {code}. Requested {wanted}, allowed {allowed}."
            )
    else:
        selected = list(allowed)

    sanity = cfg_paths.sanity_data_root() / code.upper()
    return VectorConfig(
        client_code=code,
        client_id=ident["client_id"],
        client_name=ident["client_name"],
        geos=selected,
        sanity_root=sanity,
        output_dir=sanity / OUTPUT_SUBDIR,
    )


def _geo_parquet(root: Path, folder: str, geo: str, suffix: str) -> Path:
    return root / folder / f"{geo.upper()}_{suffix}.parquet"


def _as_date_str(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce", utc=True).dt.tz_localize(None).dt.strftime(
        "%Y-%m-%d"
    )


def select_snapshot_date(
    df: pd.DataFrame,
    *,
    today: str,
    yesterday: str,
    label: str,
    client: str,
    geo: str,
    quiet: bool = False,
) -> Tuple[pd.DataFrame, str, str]:
    """Return filtered frame, selected date, and reason."""
    if df.empty or "date" not in df.columns:
        if not quiet:
            print(f"[{client}] [{geo}] [CHECK] {label}: empty / no date column")
        return df, "", "empty"

    dates = _as_date_str(df["date"])
    out = df.copy()
    out["date"] = dates

    if (dates == today).any():
        selected = today
        reason = "today"
    elif (dates == yesterday).any():
        selected = yesterday
        reason = "yesterday"
    else:
        valid = dates.dropna()
        selected = str(valid.max()) if not valid.empty else ""
        reason = "latest available"

    filtered = out[out["date"] == selected].copy() if selected else out.iloc[0:0].copy()
    if not quiet:
        print(
            f"[{client}] [{geo}] [CHECK] {label} snapshot date={selected or 'NONE'} "
            f"({reason}) rows={len(filtered):,}"
        )
    return filtered, selected, reason


def load_parquet_or_empty(
    path: Path,
    *,
    client: str,
    geo: str,
    label: str,
    quiet: bool = False,
) -> Tuple[pd.DataFrame, dict]:
    """Load parquet; return (df, meta) with rows / date range for checklist."""
    meta = {
        "label": label,
        "path": str(path),
        "file": path.name if path else "",
        "exists": False,
        "rows": 0,
        "date_min": "",
        "date_max": "",
    }
    if not path.is_file():
        if not quiet:
            print(f"[{client}] [{geo}] [CHECK] {label} MISSING -> {path}")
        return pd.DataFrame(), meta

    df = pd.read_parquet(path)
    meta["exists"] = True
    meta["rows"] = len(df)
    if "date" in df.columns and not df.empty:
        dates = _as_date_str(df["date"]).dropna()
        if not dates.empty:
            meta["date_min"] = str(dates.min())
            meta["date_max"] = str(dates.max())
    if not quiet:
        print(
            f"[{client}] [{geo}] [CHECK] {label} loaded {len(df):,} rows <- {path.name}"
            + (
                f" | file dates {meta['date_min']}..{meta['date_max']}"
                if meta["date_min"]
                else ""
            )
        )
    return df, meta


def load_product_info(client: str, geo: str, *, quiet: bool = False) -> pd.DataFrame:
    try:
        path = cogs_local.resolve_cogs_slice_path(client, geo, channel="amazon")
    except FileNotFoundError as exc:
        if not quiet:
            print(f"[{client}] [{geo}] [CHECK] COGS MISSING -> {exc}")
        return pd.DataFrame()

    if path.suffix.lower() == ".parquet":
        raw = pd.read_parquet(path)
    else:
        raw = pd.read_csv(path)
    raw = raw.copy()
    raw.rename(
        columns=lambda x: to_snake(str(x).strip().replace("\ufeff", "").strip('"').strip("'")),
        inplace=True,
    )

    keep = [c for c in PRODUCT_INFO_COLUMNS if c in raw.columns]
    missing = [c for c in PRODUCT_INFO_COLUMNS if c not in raw.columns]
    if missing and not quiet:
        print(f"[{client}] [{geo}] [CHECK] COGS missing columns {missing} (using {keep})")
    info = raw.loc[:, keep].copy()
    rename = {}
    if "country" in info.columns:
        rename["country"] = "geography"
    if "channel" in info.columns:
        rename["channel"] = "platform"
    info = info.rename(columns=rename)
    if "geography" in info.columns:
        info["geography"] = info["geography"].astype(str).str.upper()
    if "platform" in info.columns:
        info["platform"] = info["platform"].astype(str).str.lower()
    if not quiet:
        print(
            f"[{client}] [{geo}] [CHECK] product_info rows={len(info):,} "
            f"cols={list(info.columns)} <- {path.name}"
        )
    return info


def build_ledger_days_summary(
    ledger: pd.DataFrame,
    *,
    client: str,
    geo: str,
    quiet: bool = False,
) -> pd.DataFrame:
    if ledger.empty:
        if not quiet:
            print(f"[{client}] [{geo}] [CHECK] ledger empty - instock summary skipped")
        return pd.DataFrame()

    out = ledger.copy()
    out["date"] = pd.to_datetime(out["date"], utc=True, errors="coerce").dt.tz_localize(None)
    out["year_month"] = out["date"].dt.to_period("M").astype(str)
    ending = pd.to_numeric(out.get("ending_balance", 0), errors="coerce").fillna(0)
    out["Instock"] = np.where(ending > 0, 1, 0)

    group_cols = [c for c in ["client", "geography", "year_month", "sku"] if c in out.columns]
    summary = (
        out.groupby(group_cols, dropna=False)
        .agg(days_in_stock=("Instock", "sum"), total_days=("date", "nunique"))
        .reset_index()
    )
    summary["days_out_of_stock"] = summary["total_days"] - summary["days_in_stock"]
    summary["instock_rate"] = (
        (summary["days_in_stock"] / summary["total_days"].replace(0, np.nan)) * 100
    ).round(2)
    if not quiet:
        print(
            f"[{client}] [{geo}] [CHECK] ledger days_summary rows={len(summary):,} "
            f"months={summary['year_month'].nunique() if not summary.empty else 0}"
        )
    return summary


def build_previous_month_thresholds(
    days_summary: pd.DataFrame,
    prev_orders: pd.DataFrame,
    previous_month: str,
    *,
    client: str,
    geo: str,
    quiet: bool = False,
) -> Tuple[pd.DataFrame, float]:
    """
    Build MTQ thresholds from previous-month ledger + previous-month orders only.
    Returns (thresholds_df, previous_month_orders_total_sales).
    """
    prev_ledger = (
        days_summary[days_summary["year_month"] == previous_month].copy()
        if not days_summary.empty and "year_month" in days_summary.columns
        else pd.DataFrame()
    )

    prev_sales = 0.0
    if not prev_orders.empty:
        if "total_sales" in prev_orders.columns:
            prev_sales = float(
                pd.to_numeric(prev_orders["total_sales"], errors="coerce").fillna(0).sum()
            )
        elif "quantity" in prev_orders.columns:
            prev_sales = float(
                pd.to_numeric(prev_orders["quantity"], errors="coerce").fillna(0).sum()
            )

    if not quiet:
        print(
            f"[{client}] [{geo}] [CHECK] previous-month ledger {previous_month} "
            f"rows={len(prev_ledger):,}"
        )
        print(
            f"[{client}] [{geo}] [CHECK] previous-month orders {previous_month} "
            f"rows={len(prev_orders):,} total_sales={prev_sales:,.2f}"
        )

    if prev_ledger.empty:
        if not quiet:
            print(
                f"[{client}] [{geo}] [CHECK] no previous-month ledger — "
                f"MTQ defaults will apply"
            )
        return pd.DataFrame(), prev_sales

    if prev_orders.empty or "quantity" not in prev_orders.columns:
        sold = pd.DataFrame(columns=["year_month", "sku", "quantity"])
    else:
        sold = (
            pd.pivot_table(
                prev_orders,
                index=["year_month", "sku"],
                values="quantity",
                aggfunc="sum",
            )
            .reset_index()
        )

    merged = pd.merge(
        prev_ledger,
        sold.loc[:, [c for c in ["year_month", "sku", "quantity"] if c in sold.columns]],
        on=[c for c in ["year_month", "sku"] if c in prev_ledger.columns and c in sold.columns]
        or ["sku"],
        how="left",
    ).fillna(0)

    qty = pd.to_numeric(merged.get("quantity", 0), errors="coerce").fillna(0)
    dis = pd.to_numeric(merged.get("days_in_stock", 0), errors="coerce").fillna(0)
    merged["avg_unit_sold_qty"] = np.where(dis > 0, (qty / dis).round(0), 0)
    merged["avg_unit_sold_qty"] = np.where(
        merged["avg_unit_sold_qty"] == 0, 1, merged["avg_unit_sold_qty"]
    )
    merged["MTQ_overstock"] = merged["avg_unit_sold_qty"] * 90
    merged["MTQ_understock"] = merged["avg_unit_sold_qty"] * 30
    merged = merged.rename(
        columns={
            "days_in_stock": "previous_DIS",
            "total_days": "previous_total_days",
            "days_out_of_stock": "previous_days_out_of_stock",
            "avg_unit_sold_qty": "previous_avg_unit_sold_qty",
            "instock_rate": "last_month_instock",
            "quantity": "previous_month_sold_quantity",
        }
    )
    if not quiet:
        print(
            f"[{client}] [{geo}] [CHECK] MTQ thresholds rows={len(merged):,} "
            f"avg_sold min/max="
            f"{merged['previous_avg_unit_sold_qty'].min():.0f}/"
            f"{merged['previous_avg_unit_sold_qty'].max():.0f}"
        )
    return merged, prev_sales


def apply_fc_transfer_qty(
    df: pd.DataFrame,
    *,
    client: str,
    geo: str,
    quiet: bool = False,
) -> pd.DataFrame:
    """AE/IN use ageing.fc_transfer; other geos use manage_fba.afn_fc_transfer_quantity."""
    out = df.copy()
    for col in ("afn_fc_transfer_quantity", "reserved_fc_transfers", "fc_transfer"):
        if col not in out.columns:
            out[col] = 0
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0)

    geo_u = str(geo).upper()
    if geo_u in FC_TRANSFER_FROM_AGEING_GEOS:
        source = out["fc_transfer"]
        rule = "ageing.fc_transfer (AE/IN)"
    else:
        source = out["afn_fc_transfer_quantity"]
        rule = "manage_fba.afn_fc_transfer_quantity"

    fallback_mask = source == 0
    out["fc_transfer_qty"] = np.where(
        fallback_mask, out["reserved_fc_transfers"], source
    )
    if not quiet:
        print(
            f"[{client}] [{geo}] [CHECK] fc_transfer_qty rule={rule} | "
            f"source_nonzero={(~fallback_mask).sum():,} | "
            f"fallback_to_reserved={int(fallback_mask.sum()):,}"
        )
    return out


def format_geo_skipped_checklist(*, client: str, geo: str, reason: str) -> str:
    lines = [
        "=" * 64,
        f"[{client}] [{geo}] CHECKLIST — SKIPPED",
        "=" * 64,
        f"   Reason: {reason}",
        "=" * 64,
    ]
    return "\n".join(lines)


def format_geo_error_checklist(*, client: str, geo: str, error: str) -> str:
    lines = [
        "=" * 64,
        f"[{client}] [{geo}] CHECKLIST — ERROR",
        "=" * 64,
        f"   {error}",
        "=" * 64,
    ]
    return "\n".join(lines)


def format_client_geo_index(
    *,
    client: str,
    client_name: str,
    configured_geos: Sequence[str],
    this_run_geos: Sequence[str],
) -> str:
    """Header block so the log clearly shows client + all geos for this run."""
    configured = [str(g).upper() for g in configured_geos]
    this_run = [str(g).upper() for g in this_run_geos]
    lines = [
        "=" * 72,
        f"CLIENT: {client} ({client_name})",
        f"Configured geos (client.yaml): {', '.join(configured) if configured else '(none)'}",
        f"This run geos               : {', '.join(this_run) if this_run else '(none)'}",
        f"Not in this run             : "
        + (
            ", ".join(g for g in configured if g not in set(this_run))
            if any(g not in set(this_run) for g in configured)
            else "(none — all configured geos included)"
        ),
        "=" * 72,
        "Geo checklist index (in order below):",
    ]
    for geo in configured:
        if geo in this_run:
            lines.append(f"  - [{client}] [{geo}]  → processed in this run")
        else:
            lines.append(f"  - [{client}] [{geo}]  → SKIPPED (not selected for this run)")
    for geo in this_run:
        if geo not in set(configured):
            lines.append(f"  - [{client}] [{geo}]  → processed (not listed in client.yaml)")
    lines.append("-" * 72)
    return "\n".join(lines)


def format_client_run_summary(
    *,
    client: str,
    geo_rows: dict[str, int],
    geo_status: dict[str, str],
    geos_order: Sequence[str],
) -> str:
    lines = [
        "=" * 72,
        f"[{client}] CLIENT SUMMARY — all geos",
        "=" * 72,
        f"{'GEO':<8} {'STATUS':<12} {'OUTPUT_ROWS':>12}",
        "-" * 36,
    ]
    for geo in geos_order:
        status = geo_status.get(geo, "unknown")
        rows = geo_rows.get(geo, 0)
        lines.append(f"{geo:<8} {status:<12} {rows:>12,}")
    ok = sum(1 for g in geos_order if geo_status.get(g) == "ok")
    total_rows = sum(geo_rows.get(g, 0) for g in geos_order)
    lines.append("-" * 36)
    lines.append(
        f"geos_ok={ok}/{len(geos_order)} | combined_output_rows={total_rows:,}"
    )
    lines.append("=" * 72)
    return "\n".join(lines)


def format_geo_checklist(
    *,
    client: str,
    geo: str,
    file_metas: list,
    snapshot: dict,
    previous_month: str,
    prev_orders_rows: int,
    prev_orders_sales: float,
    stock_status: dict,
    new_skus: list,
    final_rows: int,
) -> str:
    """Client/geo checklist summary (printed after all geos finish)."""
    lines: list[str] = []
    lines.append(f"{'=' * 64}")
    lines.append(f"[{client}] [{geo}] CHECKLIST")
    lines.append(f"{'=' * 64}")

    lines.append("1) Files read + date range in file + snapshot used")
    for meta in file_metas:
        if not meta.get("exists"):
            lines.append(
                f"   - {meta['label']}: MISSING ({meta.get('file') or meta.get('path')})"
            )
            continue
        date_span = (
            f"{meta['date_min']} .. {meta['date_max']}"
            if meta.get("date_min")
            else "n/a"
        )
        snap = snapshot.get(meta["label"], {})
        snap_txt = ""
        if snap:
            snap_txt = (
                f" | snapshot={snap.get('date') or 'NONE'} ({snap.get('reason', '')}) "
                f"rows={snap.get('rows', 0):,}"
            )
        lines.append(
            f"   - {meta['label']}: {meta['file']} | rows={meta['rows']:,} "
            f"| file_dates={date_span}{snap_txt}"
        )

    lines.append(
        f"2) Previous-month orders ({previous_month}): "
        f"rows={prev_orders_rows:,} | total_sales_sum={prev_orders_sales:,.2f}"
    )

    lines.append("3) Stock status counts")
    if stock_status:
        for status in ("Overstock", "Understock", "Healthy"):
            if status in stock_status:
                lines.append(f"   - {status}: {stock_status[status]:,}")
        for status, count in stock_status.items():
            if status not in {"Overstock", "Understock", "Healthy"}:
                lines.append(f"   - {status}: {count:,}")
    else:
        lines.append("   - (none)")

    lines.append(
        f"4) New SKUs (final dataframe vs this geo COGS sheet): {len(new_skus):,}"
    )
    if new_skus:
        preview = new_skus[:25]
        lines.append(f"   - sample: {preview}")
        if len(new_skus) > 25:
            lines.append(f"   - ... +{len(new_skus) - 25} more")
    else:
        lines.append("   - none")

    lines.append(f"5) Final output rows: {final_rows:,}")
    lines.append(f"{'=' * 64}")
    return "\n".join(lines)


def process_geography(
    cfg: VectorConfig,
    geo: str,
    *,
    today: str,
    yesterday: str,
    current_month: str,
    previous_month: str,
) -> Tuple[pd.DataFrame, str]:
    client = cfg.client_code
    quiet = True  # mid-step noise off; one structured checklist at end

    manage, meta_manage = load_parquet_or_empty(
        _geo_parquet(cfg.sanity_root, "manage_fba", geo, "manage_fba_inventory"),
        client=client,
        geo=geo,
        label="manage_fba",
        quiet=quiet,
    )
    reserved, meta_reserved = load_parquet_or_empty(
        _geo_parquet(cfg.sanity_root, "reserved", geo, "reserved_inventory"),
        client=client,
        geo=geo,
        label="reserved",
        quiet=quiet,
    )
    ledger, meta_ledger = load_parquet_or_empty(
        _geo_parquet(cfg.sanity_root, "ledger", geo, "ledger_inventory"),
        client=client,
        geo=geo,
        label="ledger",
        quiet=quiet,
    )
    ageing, meta_ageing = load_parquet_or_empty(
        _geo_parquet(cfg.sanity_root, "ageing", geo, "ageing_inventory"),
        client=client,
        geo=geo,
        label="ageing",
        quiet=quiet,
    )
    orders, meta_orders = load_parquet_or_empty(
        _geo_parquet(cfg.sanity_root, "orders", geo, "orders_database"),
        client=client,
        geo=geo,
        label="orders",
        quiet=quiet,
    )
    product_info = load_product_info(client, geo, quiet=quiet)

    try:
        cogs_path = cogs_local.resolve_cogs_slice_path(client, geo, channel="amazon")
    except FileNotFoundError:
        cogs_path = None
    meta_cogs = {
        "label": "cogs",
        "path": str(cogs_path) if cogs_path else "",
        "file": cogs_path.name if cogs_path else f"{geo.lower()}_amazon_cogs",
        "exists": bool(cogs_path) and not product_info.empty,
        "rows": len(product_info),
        "date_min": "",
        "date_max": "",
    }
    file_metas = [
        meta_manage,
        meta_reserved,
        meta_ledger,
        meta_ageing,
        meta_orders,
        meta_cogs,
    ]

    if manage.empty:
        print(f"[{client}] [{geo}] skip — manage_fba is required and empty")
        checklist = format_geo_checklist(
            client=client,
            geo=geo,
            file_metas=file_metas,
            snapshot={},
            previous_month=previous_month,
            prev_orders_rows=0,
            prev_orders_sales=0.0,
            stock_status={},
            new_skus=[],
            final_rows=0,
        )
        return pd.DataFrame(), checklist

    manage, manage_date, manage_reason = select_snapshot_date(
        manage,
        today=today,
        yesterday=yesterday,
        label="manage_fba",
        client=client,
        geo=geo,
        quiet=quiet,
    )
    reserved, reserved_date, reserved_reason = select_snapshot_date(
        reserved,
        today=today,
        yesterday=yesterday,
        label="reserved",
        client=client,
        geo=geo,
        quiet=quiet,
    )
    ageing, ageing_date, ageing_reason = select_snapshot_date(
        ageing,
        today=today,
        yesterday=yesterday,
        label="ageing",
        client=client,
        geo=geo,
        quiet=quiet,
    )
    snapshot = {
        "manage_fba": {
            "date": manage_date,
            "reason": manage_reason,
            "rows": len(manage),
        },
        "reserved": {
            "date": reserved_date,
            "reason": reserved_reason,
            "rows": len(reserved),
        },
        "ageing": {
            "date": ageing_date,
            "reason": ageing_reason,
            "rows": len(ageing),
        },
    }

    days_summary = build_ledger_days_summary(
        ledger, client=client, geo=geo, quiet=quiet
    )
    del ledger  # raw ledger only needed for days_summary

    current_ledger = (
        days_summary[days_summary["year_month"] == current_month].copy()
        if not days_summary.empty
        else pd.DataFrame()
    )

    # Orders: previous month only (current-month orders never used in merges)
    prev_orders = pd.DataFrame()
    if not orders.empty:
        if "year_month" not in orders.columns and "date" in orders.columns:
            orders = orders.copy()
            orders["year_month"] = (
                pd.to_datetime(orders["date"], errors="coerce")
                .dt.to_period("M")
                .astype(str)
            )
        if "year_month" in orders.columns:
            prev_orders = orders[
                orders["year_month"].astype(str) == previous_month
            ].copy()
    del orders

    prev_thresholds, prev_orders_sales = build_previous_month_thresholds(
        days_summary,
        prev_orders,
        previous_month,
        client=client,
        geo=geo,
        quiet=quiet,
    )
    prev_orders_rows = len(prev_orders)
    del prev_orders
    del days_summary  # only current_ledger + prev_thresholds needed after this

    if not ageing.empty:
        ageing = ageing.drop(columns=[c for c in AGEING_DROP_COLS if c in ageing.columns])

    amazon = pd.merge(
        manage,
        reserved,
        on=[c for c in MERGE_KEYS_SNAPSHOT if c in manage.columns and c in reserved.columns],
        how="left",
    ).fillna(0)
    del manage
    del reserved
    amazon = amazon.drop(columns=[c for c in MANAGE_DROP_COLS if c in amazon.columns])

    if not prev_thresholds.empty:
        keep_prev = [
            c
            for c in [
                "sku",
                "previous_DIS",
                "previous_total_days",
                "previous_days_out_of_stock",
                "previous_avg_unit_sold_qty",
                "last_month_instock",
                "previous_month_sold_quantity",
                "MTQ_overstock",
                "MTQ_understock",
            ]
            if c in prev_thresholds.columns
        ]
        amazon = pd.merge(amazon, prev_thresholds.loc[:, keep_prev], on=["sku"], how="left")
    else:
        for col in (
            "previous_DIS",
            "previous_total_days",
            "previous_days_out_of_stock",
            "previous_avg_unit_sold_qty",
            "last_month_instock",
            "previous_month_sold_quantity",
            "MTQ_overstock",
            "MTQ_understock",
        ):
            if col not in amazon.columns:
                amazon[col] = 0
    del prev_thresholds

    if not current_ledger.empty:
        keep_cur = [
            c
            for c in ["sku", "days_in_stock", "total_days", "days_out_of_stock", "instock_rate"]
            if c in current_ledger.columns
        ]
        amazon = pd.merge(amazon, current_ledger.loc[:, keep_cur], on=["sku"], how="left")
    else:
        for col in ("days_in_stock", "total_days", "days_out_of_stock", "instock_rate"):
            if col not in amazon.columns:
                amazon[col] = 0
    del current_ledger

    if not ageing.empty:
        ageing_keys = [c for c in MERGE_KEYS_SKU_GEO if c in amazon.columns and c in ageing.columns]
        amazon = pd.merge(amazon, ageing, on=ageing_keys or ["sku"], how="left")
    del ageing

    if not product_info.empty:
        prod_keys = [
            c for c in MERGE_KEYS_PRODUCT if c in amazon.columns and c in product_info.columns
        ]
        amazon = pd.merge(amazon, product_info, on=prod_keys or ["sku"], how="left")
    del product_info

    amazon["product_cogs"] = pd.to_numeric(amazon.get("product_cogs", 0), errors="coerce").fillna(0)
    amazon["amazon_selling_price"] = pd.to_numeric(
        amazon.get("amazon_selling_price", 0), errors="coerce"
    ).fillna(0)
    for col in ("asin", "product_category", "product_name", "type"):
        if col not in amazon.columns:
            amazon[col] = "NAN"
        amazon[col] = amazon[col].fillna("NAN")

    amazon = amazon[amazon["product_name"] != "NAN"].copy()

    amazon = apply_fc_transfer_qty(amazon, client=client, geo=geo, quiet=quiet)

    amazon["afn_fulfillable_quantity"] = pd.to_numeric(
        amazon.get("afn_fulfillable_quantity", 0), errors="coerce"
    ).fillna(0)
    amazon["total_sellable"] = amazon["afn_fulfillable_quantity"] + amazon["fc_transfer_qty"]

    amazon["MTQ_overstock"] = pd.to_numeric(amazon["MTQ_overstock"], errors="coerce").fillna(0)
    amazon["MTQ_understock"] = pd.to_numeric(amazon["MTQ_understock"], errors="coerce").fillna(0)
    amazon["MTQ_overstock"] = np.where(amazon["MTQ_overstock"] == 0, 90, amazon["MTQ_overstock"])
    amazon["MTQ_understock"] = np.where(
        amazon["MTQ_understock"] == 0, 30, amazon["MTQ_understock"]
    )

    conditions = [
        amazon["total_sellable"] > amazon["MTQ_overstock"],
        amazon["total_sellable"] <= amazon["MTQ_understock"],
    ]
    amazon["stock_status"] = np.select(conditions, ["Overstock", "Understock"], default="Healthy")
    status_counts = amazon["stock_status"].value_counts().to_dict()

    for col in (
        "afn_warehouse_quantity",
        "afn_fulfillable_quantity",
        "afn_unsellable_quantity",
        "afn_inbound_receiving_quantity",
        "product_cogs",
        "amazon_selling_price",
        "days_out_of_stock",
        "previous_avg_unit_sold_qty",
        "previous_days_out_of_stock",
    ):
        if col not in amazon.columns:
            amazon[col] = 0
        amazon[col] = pd.to_numeric(amazon[col], errors="coerce").fillna(0)

    amazon["wh_stock_value"] = amazon["afn_warehouse_quantity"] * amazon["product_cogs"]
    amazon["sellable_stock_value"] = amazon["afn_fulfillable_quantity"] * amazon["product_cogs"]
    amazon["sale_lost"] = (
        amazon["days_out_of_stock"]
        * amazon["previous_avg_unit_sold_qty"]
        * amazon["amazon_selling_price"]
    )
    amazon["previous_sale_lost"] = (
        amazon["previous_days_out_of_stock"]
        * amazon["previous_avg_unit_sold_qty"]
        * amazon["amazon_selling_price"]
    )

    amazon = amazon.drop(
        columns=[
            c
            for c in (
                "amazon_selling_price",
                "afn_fc_transfer_quantity",
                "reserved_fc_transfers",
                "fc_transfer",
            )
            if c in amazon.columns
        ]
    )
    amazon = amazon.rename(
        columns={
            "fc_transfer_qty": "afn_fc_transfer_quantity",
            "reserved_qty": "afn_reserved_quantity",
        }
    )

    amazon["client"] = client
    amazon["client_id"] = cfg.client_id
    amazon["geography"] = geo.upper()
    if "platform" not in amazon.columns:
        amazon["platform"] = "amazon"

    amazon = finalize_output_frame(amazon, client=client, geo=geo, quiet=quiet)

    new_skus = report_new_skus_vs_cogs(
        amazon,
        client=client,
        geography_code=geo,
        label="vector_report",
        quiet=True,
    )

    checklist = format_geo_checklist(
        client=client,
        geo=geo,
        file_metas=file_metas,
        snapshot=snapshot,
        previous_month=previous_month,
        prev_orders_rows=prev_orders_rows,
        prev_orders_sales=prev_orders_sales,
        stock_status=status_counts,
        new_skus=new_skus,
        final_rows=len(amazon),
    )
    return amazon, checklist


def finalize_output_frame(
    df: pd.DataFrame,
    *,
    client: str = "",
    geo: str = "",
    quiet: bool = False,
) -> pd.DataFrame:
    """Fill blanks → round 2dp → snake_case all columns (pre-export)."""
    if df.empty:
        return df

    out = df.copy()
    tag = f"[{client}] [{geo}]" if client or geo else "[vector]"

    fill_cols = [c for c in FILLNA_ZERO_COLS if c in out.columns]
    for col in fill_cols:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0)

    round_cols = [c for c in ROUND_2_COLS if c in out.columns]
    missing_round = [c for c in ROUND_2_COLS if c not in out.columns]
    for col in round_cols:
        out[col] = pd.to_numeric(out[col], errors="coerce").round(2)

    before = list(out.columns)
    out.columns = [to_snake(c) for c in out.columns]
    # Deduplicate if snake_case collapses names
    seen: dict[str, int] = {}
    renamed: list[str] = []
    for c in out.columns:
        if c not in seen:
            seen[c] = 0
            renamed.append(c)
        else:
            seen[c] += 1
            renamed.append(f"{c}_{seen[c]}")
    out.columns = renamed
    changed = sum(1 for a, b in zip(before, out.columns) if to_snake(a) != a or a != b)
    if not quiet:
        print(f"{tag} [CHECK] fillna(0) applied to {len(fill_cols)} cols: {fill_cols}")
        print(f"{tag} [CHECK] round(2) applied to {len(round_cols)} cols")
        if missing_round:
            print(f"{tag} [CHECK] round(2) skipped missing cols: {missing_round}")
        print(
            f"{tag} [CHECK] snake_case columns ({changed} adjusted) -> {len(out.columns)} cols"
        )
    return out


def save_geography_outputs(df: pd.DataFrame, output_dir: Path) -> List[Path]:
    if df.empty:
        print("[WARN] Nothing to save — DataFrame is empty")
        return []
    output_dir.mkdir(parents=True, exist_ok=True)
    saved: List[Path] = []
    print(f"\nSaving Vector Datahive outputs → {output_dir}")
    for geography, geo_df in df.groupby("geography", sort=True):
        geo_name = str(geography).strip().lower()
        platforms = (
            geo_df["platform"].astype(str).str.strip().str.lower().unique().tolist()
            if "platform" in geo_df.columns
            else ["amazon"]
        )
        for platform in platforms or ["amazon"]:
            plat = platform or "amazon"
            slice_df = geo_df
            if "platform" in geo_df.columns and len(platforms) > 1:
                slice_df = geo_df[geo_df["platform"].astype(str).str.strip().str.lower() == plat]
            stem = f"{geo_name}_{plat}_{PARQUET_NAME_SUFFIX}"
            parquet_path = output_dir / f"{stem}.parquet"
            csv_path = output_dir / f"{stem}.csv"
            slice_df.to_parquet(parquet_path, index=False)
            slice_df.to_csv(csv_path, index=False)
            saved.extend([parquet_path, csv_path])
            print(
                f"  [{geo_name}/{plat}] {len(slice_df):,} rows -> "
                f"{parquet_path.name}, {csv_path.name}"
            )
    return saved


def build_vector_dataframe(
    *,
    client: str = CLIENT,
    geos: Optional[Sequence[str]] = None,
    save_output: bool = SAVE_OUTPUT,
    max_workers: int = MAX_WORKERS,
) -> pd.DataFrame:
    cfg = get_vector_config(client, geos)
    configured_geos = _client_geos(cfg.client_code)
    today = pd.Timestamp.today().strftime("%Y-%m-%d")
    yesterday = (pd.Timestamp.today() - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    now = datetime.now()
    current_month = now.strftime("%Y-%m")
    previous_month = (now - relativedelta(months=1)).strftime("%Y-%m")

    print("=" * 60)
    print(f"Client : {cfg.client_code} ({cfg.client_name})")
    print(f"ID     : {cfg.client_id}")
    print(f"Configured geos: {configured_geos}")
    print(f"This run geos  : {cfg.geos}")
    print(f"Today  : {today} | Yesterday: {yesterday}")
    print(f"Months : current={current_month} previous={previous_month}")
    print(f"Sanity : {cfg.sanity_root}")
    print(f"Output : {cfg.output_dir}")
    print(f"Threads: {min(max(1, max_workers), len(cfg.geos) or 1)}")
    print(
        f"FC rule: AE/IN use ageing.fc_transfer; "
        f"others use afn_fc_transfer_quantity; 0 → reserved_fc_transfers"
    )
    print("=" * 60)

    frames: List[pd.DataFrame] = []
    checklists: dict[str, str] = {}
    geo_rows: dict[str, int] = {}
    geo_status: dict[str, str] = {}
    workers = min(max(1, int(max_workers)), max(1, len(cfg.geos)))
    if workers == 1 or len(cfg.geos) == 1:
        for geo in cfg.geos:
            try:
                frame, checklist = process_geography(
                    cfg,
                    geo,
                    today=today,
                    yesterday=yesterday,
                    current_month=current_month,
                    previous_month=previous_month,
                )
                frames.append(frame)
                checklists[geo] = checklist
                rows = 0 if frame is None or frame.empty else len(frame)
                geo_rows[geo] = rows
                geo_status[geo] = "ok" if rows > 0 else "empty"
            except Exception as exc:  # noqa: BLE001
                print(f"[{cfg.client_code}] [{geo}] ERROR: {exc}")
                checklists[geo] = format_geo_error_checklist(
                    client=cfg.client_code, geo=geo, error=str(exc)
                )
                geo_rows[geo] = 0
                geo_status[geo] = "error"
    else:
        print(f"\nProcessing {len(cfg.geos)} geos on {workers} threads...")
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(
                    process_geography,
                    cfg,
                    geo,
                    today=today,
                    yesterday=yesterday,
                    current_month=current_month,
                    previous_month=previous_month,
                ): geo
                for geo in cfg.geos
            }
            for fut in as_completed(futures):
                geo = futures[fut]
                try:
                    frame, checklist = fut.result()
                    frames.append(frame)
                    checklists[geo] = checklist
                    rows = 0 if frame is None or frame.empty else len(frame)
                    geo_rows[geo] = rows
                    geo_status[geo] = "ok" if rows > 0 else "empty"
                except Exception as exc:  # noqa: BLE001
                    print(f"[{cfg.client_code}] [{geo}] ERROR: {exc}")
                    checklists[geo] = format_geo_error_checklist(
                        client=cfg.client_code, geo=geo, error=str(exc)
                    )
                    geo_rows[geo] = 0
                    geo_status[geo] = "error"

    # Geos configured for the client but not selected for this pipeline run
    for geo in configured_geos:
        if geo not in checklists:
            checklists[geo] = format_geo_skipped_checklist(
                client=cfg.client_code,
                geo=geo,
                reason="not selected for this run (pipeline geos filter)",
            )
            geo_rows[geo] = 0
            geo_status[geo] = "skipped"

    # Stable order: configured geos first, then any extras from this run
    geos_order: List[str] = list(configured_geos)
    for geo in cfg.geos:
        if geo not in geos_order:
            geos_order.append(geo)

    print(f"\n[{cfg.client_code}] ========== GEO CHECKLISTS (client-wise) ==========")
    from report_script.common_sanity_report.run_logs import ReportRunLog

    run_log = ReportRunLog(cfg.client_code, "vector")
    try:
        index_block = format_client_geo_index(
            client=cfg.client_code,
            client_name=cfg.client_name,
            configured_geos=configured_geos,
            this_run_geos=cfg.geos,
        )
        print(index_block)
        print()
        run_log.append(index_block)
        run_log.blank()

        for geo in geos_order:
            block = checklists.get(geo)
            if not block:
                continue
            print(block)
            print()
            run_log.append(block)
            run_log.blank()

        nonempty = [f for f in frames if f is not None and not f.empty]
        master = (
            pd.concat(nonempty, ignore_index=True, sort=False)
            if nonempty
            else pd.DataFrame()
        )
        summary = format_client_run_summary(
            client=cfg.client_code,
            geo_rows=geo_rows,
            geo_status=geo_status,
            geos_order=geos_order,
        )
        print(summary)
        run_log.append(summary)
        run_log.blank()
        run_log.append(
            f"[{cfg.client_code}] [CHECK] combined Vector Datahive "
            f"geos_ok={len(nonempty)}/{len(cfg.geos)} "
            f"(configured={len(configured_geos)}) rows={len(master):,}"
        )

        if save_output and not master.empty:
            save_geography_outputs(master, cfg.output_dir)
    finally:
        run_log.flush()

    return master


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Vector Datahive Amazon inventory snapshot")
    p.add_argument("--client", default=CLIENT, choices=["ESH", "KNC"])
    p.add_argument("--geos", default="", help="Comma-separated geos, e.g. US,AE,IN")
    p.add_argument("--workers", type=int, default=MAX_WORKERS)
    p.add_argument("--no-save", action="store_true")
    return p.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> pd.DataFrame:
    args = parse_args(argv)
    geos = [g.strip() for g in str(args.geos).split(",") if g.strip()] or None
    master = build_vector_dataframe(
        client=args.client,
        geos=geos,
        save_output=not args.no_save,
        max_workers=args.workers,
    )
    if not master.empty:
        print(master.shape)
        print(master.head())
        print(master.columns.tolist())
    return master


def run(
    *,
    client: str = CLIENT,
    geos: Optional[Sequence[str]] = None,
    save_output: bool = SAVE_OUTPUT,
    max_workers: int = MAX_WORKERS,
    **_kwargs,
) -> pd.DataFrame:
    """Pipeline CLI entrypoint: run(client='ESH', geos=['US','AE'])."""
    return build_vector_dataframe(
        client=client,
        geos=geos,
        save_output=save_output,
        max_workers=max_workers,
    )


if __name__ == "__main__":
    main()
    print_script_completed('vector_report')





