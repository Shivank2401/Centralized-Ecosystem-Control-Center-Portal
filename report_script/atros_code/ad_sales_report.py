"""
KNC advertising sales/spend report (Ad Sales, Ad Spend, Gross Sales, TACoS).

Covers:
  - Client: KNC only (UK, DE, AE)
  - Inputs: Bulk Operations ad Sales; P&L spend/revenue; orders gross sales; COGS
  - Outputs: sanity_data/KNC/ads/{GEO}_ads.parquet|.csv + final_ads.*
  - Optional Azure: sanity_data/ad_sales/final_ad_sales.parquet

Defaults year/month to current calendar month when omitted.

Style: step-by-step (notebook-like). Each geo prints >>> STEP so a crash
shows which block failed.

Run:
    python report_script/atros_code/ad_sales_report.py
    python report_script/atros_code/ad_sales_report.py --geos UK,DE --year 2026 --month aug
    python report_script/atros_code/ad_sales_report.py --upload-azure
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

import pandas as pd

try:
    from .atros_common import (
        CLIENT,
        GEO_CONFIG,
        concat_geo_frames,
        normalize_columns,
        numeric,
        parse_geos,
        read_bulk_metrics,
        read_cogs,
        resolve_azure_upload_choice,
        resolve_geo_path,
        resolve_year_month,
        save_geo_and_combined,
        upload_finals_to_azure,
    )
    from .pnl_report import _build_geo_pnl
except ImportError:  # direct script execution
    from atros_common import (  # type: ignore
        CLIENT,
        GEO_CONFIG,
        concat_geo_frames,
        normalize_columns,
        numeric,
        parse_geos,
        read_bulk_metrics,
        read_cogs,
        resolve_azure_upload_choice,
        resolve_geo_path,
        resolve_year_month,
        save_geo_and_combined,
        upload_finals_to_azure,
    )
    from pnl_report import _build_geo_pnl  # type: ignore


# =============================================================================
# Step 1 — find latest orders overall CSV for a geo
# =============================================================================

def find_orders_file(geo: str) -> Path | None:
    """Look under App Main Files / Orders / Kinetica for {geo}_orders_overall.csv."""
    print(f"    [orders] looking for {geo} orders file...")
    root = resolve_geo_path(geo, "orders")
    if not root.exists():
        print(f"    [orders] folder missing: {root}")
        return None

    wanted = {
        f"{geo}_orders_overall.csv".lower(),
        f"{geo.lower()}_orders_overall.csv".lower(),
    }
    matches = [
        path
        for path in root.rglob("*.csv")
        if path.name.lower() in wanted
    ]
    if not matches:
        print(f"    [orders] no matching csv under {root}")
        return None

    latest = max(matches, key=lambda path: path.stat().st_mtime)
    print(f"    [orders] using: {latest}")
    return latest


# =============================================================================
# Step 2 — Gross sales from orders (SKU x Year-Month)
# =============================================================================

def build_gross_sales(geo: str, year_month: str) -> pd.DataFrame:
    """
    Read orders → keep Year-Month → drop cancelled → sum Total_Gross_Sales by SKU.
    If file missing / columns missing → empty frame (same as before).
    """
    print(f"    [gross] building gross sales for {geo} / {year_month}")
    empty = pd.DataFrame(columns=["SKU", "Year-Month", "Total_Gross_Sales"])

    source = find_orders_file(geo)
    if source is None:
        return empty

    orders = pd.read_csv(source, low_memory=False)
    orders.columns = orders.columns.astype(str).str.strip()

    # normalize a few known headers (case-insensitive)
    rename = {
        "sku": "SKU",
        "year_month": "Year-Month",
        "total_sales": "Total_Gross_Sales",
        "purchase_date": "purchase-date",
        "purchase-date": "purchase-date",
        "order_status": "order-status",
        "order-status": "order-status",
    }
    orders = orders.rename(
        columns={col: rename.get(col.lower(), col) for col in orders.columns}
    )

    # Year-Month from purchase-date if needed
    if "Year-Month" not in orders.columns and "purchase-date" in orders.columns:
        orders["Year-Month"] = pd.to_datetime(
            orders["purchase-date"], errors="coerce"
        ).dt.strftime("%Y-%m")

    # drop cancelled
    if "order-status" in orders.columns:
        cancelled = orders["order-status"].astype(str).str.casefold().eq("cancelled")
        orders = orders[~cancelled]

    needed = {"SKU", "Year-Month", "Total_Gross_Sales"}
    if not needed.issubset(orders.columns):
        print(f"    [gross] missing columns: {needed - set(orders.columns)}")
        return empty

    orders = orders[orders["Year-Month"].astype(str).eq(year_month)].copy()
    orders["Total_Gross_Sales"] = numeric(orders["Total_Gross_Sales"])
    out = orders.groupby(["SKU", "Year-Month"], as_index=False)["Total_Gross_Sales"].sum()
    print(f"    [gross] rows after filter/group: {len(out):,}")
    return out


# =============================================================================
# Step 3 — one geo ads table
#   Ad_Sales  <- Bulk Operations
#   Ad_Spend + Total_Revenue <- P&L
#   Total_Gross_Sales <- orders
#   TACoS % = Ad_Spend / Total_Gross_Sales * 100
# =============================================================================

def build_one_geo_ads(geo: str, year: int, month_abbr: str, year_month: str) -> pd.DataFrame:
    print(f"\n>>> STEP: KNC / {geo} / ads ({year_month})")

    # --- COGS + Ad Sales from bulk ops ---
    print(f"    [ads] reading COGS + bulk Ad Sales...")
    cogs = read_cogs(geo)
    ad_sales = read_bulk_metrics(geo, year, month_abbr, cogs, ("Sales",))
    ad_sales = ad_sales.rename(columns={"Sales": "Ad_Sales"})
    ad_sales["Year-Month"] = year_month
    print(f"    [ads] bulk Ad_Sales rows: {len(ad_sales):,}")

    # --- Ad Spend + Revenue from P&L ---
    print(f"    [ads] reading P&L for spend/revenue...")
    pnl = _build_geo_pnl(geo, year, month_abbr, year_month)
    pnl_rename = {
        "sku": "SKU",
        "year_month": "Year-Month",
        "spend": "Ad_Spend",
        "total_sales_with_tax": "Total_Revenue",
    }
    keep = [col for col in pnl_rename if col in pnl.columns]
    pnl_slice = pnl[keep].rename(columns=pnl_rename)
    if "Ad_Spend" not in pnl_slice.columns:
        pnl_slice["Ad_Spend"] = 0
    if "Total_Revenue" not in pnl_slice.columns:
        pnl_slice["Total_Revenue"] = 0
    print(f"    [ads] P&L slice rows: {len(pnl_slice):,}")

    # --- merge everything ---
    print(f"    [ads] merging Ad_Sales + P&L + Gross Sales...")
    result = ad_sales.merge(pnl_slice, on=["SKU", "Year-Month"], how="outer")
    result = result.merge(build_gross_sales(geo, year_month), on=["SKU", "Year-Month"], how="outer")

    for col in ("Ad_Sales", "Ad_Spend", "Total_Revenue", "Total_Gross_Sales"):
        if col in result.columns:
            result[col] = numeric(result[col])
        else:
            result[col] = 0

    # drop all-zero rows
    all_zero = (
        (result["Ad_Sales"] == 0)
        & (result["Ad_Spend"] == 0)
        & (result["Total_Revenue"] == 0)
        & (result["Total_Gross_Sales"] == 0)
    )
    result = result[~all_zero].copy()

    # TACoS
    result["TACoS %"] = (
        result["Ad_Spend"].div(result["Total_Gross_Sales"].replace(0, float("nan"))).fillna(0) * 100
    )

    # meta columns
    result["country"] = GEO_CONFIG[geo]["country"]
    result["platform"] = "Amazon"
    result["channel"] = GEO_CONFIG[geo]["channel"]
    result["client_id"] = "TH-1753144646395"

    result = normalize_columns(result)
    print(f"    [ads] DONE {geo}: {len(result):,} rows")
    return result


# =============================================================================
# Step 4 — all geos → save local masters → optional Azure
# =============================================================================

def build_ad_sales_dataframe(
    *,
    client: str = CLIENT,
    geos: str | Sequence[str] | None = None,
    year: int | str | None = None,
    month: int | str | None = None,
    save_output: bool = True,
    upload_azure: bool | None = None,
) -> pd.DataFrame:
    if client.upper() != CLIENT:
        raise ValueError("ad_sales_report supports KNC only")

    resolved_year, _, month_abbr, year_month = resolve_year_month(year, month)
    print("=" * 60)
    print(f"CLIENT : {CLIENT}")
    print(f"PERIOD : {year_month}  (month folder = {month_abbr})")
    print("=" * 60)

    frames: dict[str, pd.DataFrame] = {}
    for geo in parse_geos(geos):
        try:
            frames[geo] = build_one_geo_ads(geo, resolved_year, month_abbr, year_month)
            print(f"Built {geo} ads report: {len(frames[geo]):,} rows")
        except (FileNotFoundError, OSError, ValueError, KeyError) as exc:
            # same skip behaviour as before — missing downloads should not kill other geos
            print(f"WARNING: skipping {geo} ads report: {exc}")

    if save_output:
        print("\n>>> STEP: save geo + combined ads masters")
        combined = save_geo_and_combined(
            frames,
            client=client,
            report_subdir="ads",
            name_suffix="ads",
            dedupe_subset=("sku", "year_month", "country", "client_id"),
        )
    else:
        combined = concat_geo_frames(frames, report_type="ads")

    if upload_azure is True and not combined.empty:
        print("\n>>> STEP: Azure upload (ads)")
        upload_finals_to_azure(combined, report_type="ads")

    return combined


def run(
    *,
    client: str = CLIENT,
    geos: str | Sequence[str] | None = None,
    year: int | str | None = None,
    month: int | str | None = None,
    save_output: bool = True,
    upload_azure: bool | None = None,
    skip_azure: bool = False,
    **_: object,
) -> pd.DataFrame:
    """Portal / pipeline entry."""
    combined = build_ad_sales_dataframe(
        client=client,
        geos=geos,
        year=year,
        month=month,
        save_output=save_output,
        upload_azure=False,
    )

    if save_output and not combined.empty:
        print("\n>>> STEP: Azure upload decision")
        if resolve_azure_upload_choice(upload_azure, skip_azure=skip_azure):
            upload_finals_to_azure(combined, report_type="ads")
        else:
            print("[KNC] Azure upload skipped. Local ads masters kept.")

    print("-" * 60)
    print(f"Done. Combined ads rows: {len(combined):,}")
    return combined


# =============================================================================
# CLI
# =============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", default=CLIENT)
    parser.add_argument("--geos", default="UK,DE,AE")
    parser.add_argument("--year", type=int)
    parser.add_argument("--month")
    parser.add_argument("--upload-azure", action="store_true")
    parser.add_argument("--skip-azure", action="store_true")
    parser.add_argument("--no-save", action="store_true")
    args = parser.parse_args()

    choice: bool | None = None
    if args.upload_azure:
        choice = True
    elif args.skip_azure:
        choice = False

    run(
        client=args.client,
        geos=args.geos,
        year=args.year,
        month=args.month,
        save_output=not args.no_save,
        upload_azure=choice,
        skip_azure=args.skip_azure,
    )


if __name__ == "__main__":
    from config_manager.report_helpers import print_script_completed

    main()
    print_script_completed("ad_sales_report")
