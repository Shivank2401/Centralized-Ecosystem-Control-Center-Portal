"""
KNC executive decomposition chart (page views, buy box, ads, transactions).

Covers:
  - Client: KNC only (UK, DE, AE)
  - Inputs: Business Report, Bulk Operations metrics, transactions, inventory/ledger, COGS
  - Outputs: sanity_data/KNC/decomposition_chart/{GEO}_decomposition_chart.* + final_*
  - Optional Azure: sanity_data/decomposition_chart/Decomposition_Chart.parquet

AE applies Kinetica title/product filters where configured.

Style: step-by-step (notebook-like). Each geo prints >>> STEP so a crash
shows which block failed.

Run:
    python report_script/atros_code/decomposition_chart.py
    python report_script/atros_code/decomposition_chart.py --geos UK,AE --year 2026 --month aug
"""

from __future__ import annotations

import argparse
import calendar
from datetime import datetime, timedelta
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

try:
    from .atros_common import (
        CLIENT,
        GEO_CONFIG,
        build_sku_mapping,
        clean_sku,
        concat_geo_frames,
        find_period_file,
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
    from .pnl_report import _read_transactions
except ImportError:  # direct script execution
    from atros_common import (  # type: ignore
        CLIENT,
        GEO_CONFIG,
        build_sku_mapping,
        clean_sku,
        concat_geo_frames,
        find_period_file,
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
    from pnl_report import _read_transactions  # type: ignore


# =============================================================================
# Helpers
# =============================================================================

def latest_csv(root: Path, tokens: Sequence[str]) -> Path | None:
    """Newest *.csv under root whose filename contains all tokens."""
    if not root.exists():
        return None
    lowered = [token.lower() for token in tokens]
    matches = [
        path
        for path in root.rglob("*.csv")
        if all(token in path.name.lower() for token in lowered)
    ]
    if not matches:
        return None
    return max(matches, key=lambda path: path.stat().st_mtime)


_latest_csv = latest_csv  # back-compat


def proration_factor(year: int, month_number: int) -> float:
    """Scale MTD metrics up to a full-month estimate (same formula as before)."""
    month_days = calendar.monthrange(year, month_number)[1]
    yesterday = datetime.now().date() - timedelta(days=1)
    start = datetime(year, month_number, 1).date()
    end = datetime(year, month_number, month_days).date()
    if yesterday < start:
        return 0.0
    elapsed = (min(yesterday, end) - start).days + 1
    return month_days / elapsed if elapsed else 0.0


_proration_factor = proration_factor


# =============================================================================
# Step 1 — Business Report (page views + buy box → SKU level)
# =============================================================================

def build_business_report(
    geo: str,
    year: int,
    month_abbr: str,
    year_month: str,
    cogs: pd.DataFrame,
) -> pd.DataFrame:
    print(f"    [biz] finding business report for {geo} / {year}-{month_abbr}...")
    source = find_period_file(
        geo,
        "business_report",
        year,
        month_abbr,
        extensions=(".csv",),
        required_tokens=("business",),
    )
    if source is None:
        raise FileNotFoundError(f"{geo} business report CSV not found")
    print(f"    [biz] reading: {source}")

    frame = pd.read_csv(source, low_memory=False)
    aliases = {
        "(child) asin": "ASIN",
        "page views – total": "Page_Views_Total",
        "page views - total": "Page_Views_Total",
        "page views - total ": "Page_Views_Total",
        "featured offer (buy box) percentage": "buy_box_percentage",
    }
    frame = frame.rename(
        columns={col: aliases.get(str(col).strip().lower(), col) for col in frame.columns}
    )

    required = {"ASIN", "Page_Views_Total", "buy_box_percentage"}
    if not required.issubset(frame.columns):
        missing = sorted(required - set(frame.columns))
        raise ValueError(f"{geo} business report missing columns: {missing}")

    if GEO_CONFIG[geo]["kinetica_filter"] and "Title" in frame.columns:
        print("    [biz] AE filter: Title contains 'kinetica'")
        frame = frame[frame["Title"].astype(str).str.contains("kinetica", case=False, na=False)]

    helper_columns = [
        col for col in ("ASIN", "SKU", "Product Name", "Product Category") if col in cogs.columns
    ]
    helper = cogs[helper_columns].drop_duplicates("ASIN", keep="last")
    frame["ASIN"] = frame["ASIN"].astype(str).str.strip()
    helper["ASIN"] = helper["ASIN"].astype(str).str.strip()
    frame = frame.merge(helper, on="ASIN", how="left")

    frame["Page_Views_Total"] = numeric(frame["Page_Views_Total"])
    frame["buy_box_percentage"] = numeric(frame["buy_box_percentage"])
    frame["weighted_buy_box"] = frame["buy_box_percentage"] * frame["Page_Views_Total"]
    frame["Year-Month"] = year_month

    group_columns = ["SKU", "Year-Month", "Product Name", "Product Category"]
    grouped = frame.groupby(group_columns, as_index=False, dropna=False).agg(
        Page_Views_Total=("Page_Views_Total", "sum"),
        weighted_buy_box=("weighted_buy_box", "sum"),
    )
    grouped["buy_box_percentage"] = (
        grouped["weighted_buy_box"].div(grouped["Page_Views_Total"].replace(0, np.nan)).fillna(0)
    )
    out = grouped.drop(columns="weighted_buy_box")
    print(f"    [biz] rows: {len(out):,}")
    return out


_business_report = build_business_report


# =============================================================================
# Step 2 — Orders (qty, sales, add-to-cart)
# =============================================================================

def build_orders(geo: str, year_month: str) -> pd.DataFrame:
    print(f"    [orders] finding orders CSV for {geo}...")
    source = latest_csv(resolve_geo_path(geo, "orders"), (geo, "orders"))
    if source is None:
        raise FileNotFoundError(f"{geo} overall orders CSV not found")
    print(f"    [orders] reading: {source}")

    frame = pd.read_csv(source, low_memory=False)
    aliases = {
        "sku": "SKU",
        "quantity": "Quantity",
        "total_sales": "Total_Sales",
        "order_id": "Order_ID",
        "order_status": "order-status",
        "year_month": "Year-Month",
        "purchase_date": "purchase-date",
        "purchase-date": "purchase-date",
    }
    frame = frame.rename(
        columns={col: aliases.get(str(col).strip().lower(), col) for col in frame.columns}
    )

    if "Year-Month" not in frame.columns and "purchase-date" in frame.columns:
        frame["Year-Month"] = pd.to_datetime(
            frame["purchase-date"], errors="coerce"
        ).dt.strftime("%Y-%m")

    if "order-status" in frame.columns:
        cancelled = frame["order-status"].astype(str).str.casefold().eq("cancelled")
        frame = frame[~cancelled]

    frame = frame[frame["Year-Month"].astype(str).eq(year_month)].copy()

    for column in ("Quantity", "Total_Sales"):
        frame[column] = numeric(frame[column]) if column in frame.columns else 0

    if "Order_ID" not in frame.columns:
        frame["Order_ID"] = pd.RangeIndex(len(frame)).astype(str)

    out = frame.groupby(["Year-Month", "SKU"], as_index=False).agg(
        Quantity=("Quantity", "sum"),
        Total_Sales=("Total_Sales", "sum"),
        Add_to_cart=("Order_ID", "nunique"),
    )
    print(f"    [orders] rows: {len(out):,}")
    return out


_orders = build_orders


# =============================================================================
# Step 3 — Available inventory (manage FBA)
# =============================================================================

def build_inventory(geo: str, cogs: pd.DataFrame) -> pd.DataFrame:
    print(f"    [inv] finding manage-FBA inventory for {geo}...")
    root = resolve_geo_path(geo, "inventory")
    source = latest_csv(root, ("manage", "fba")) or latest_csv(root, ("inventory",))
    if source is None:
        raise FileNotFoundError(f"{geo} manage-FBA inventory CSV not found")
    print(f"    [inv] reading: {source}")

    frame = pd.read_csv(source, low_memory=False)
    frame = frame.rename(columns={col: str(col).strip().lower() for col in frame.columns})

    if GEO_CONFIG[geo]["kinetica_filter"] and "product-name" in frame.columns:
        print("    [inv] AE filter: product-name contains 'kinetica'")
        frame = frame[
            frame["product-name"].astype(str).str.contains("kinetica", case=False, na=False)
        ]

    if "sku" not in frame.columns or "afn-fulfillable-quantity" not in frame.columns:
        raise ValueError(f"{geo} inventory missing sku/afn-fulfillable-quantity")

    mapping = build_sku_mapping(cogs)
    frame["SKU"] = frame["sku"].map(lambda value: clean_sku(value, mapping))
    frame["Available_Inventory"] = numeric(frame["afn-fulfillable-quantity"])
    out = frame.groupby("SKU", as_index=False)["Available_Inventory"].sum()
    print(f"    [inv] rows: {len(out):,}")
    return out


_inventory = build_inventory


# =============================================================================
# Step 4 — Discounting from transactions (promotional rebates)
# =============================================================================

def build_discounting(geo: str, year: int, month_abbr: str, cogs: pd.DataFrame) -> pd.DataFrame:
    print(f"    [disc] reading transactions for discounting ({geo})...")
    frame = _read_transactions(geo, year, month_abbr)
    mapping = build_sku_mapping(cogs)
    frame["SKU"] = frame["sku"].map(lambda value: clean_sku(value, mapping))
    frame["Discounting"] = numeric(frame["promotional rebates"])
    out = frame.groupby("SKU", as_index=False)["Discounting"].sum()
    print(f"    [disc] rows: {len(out):,}")
    return out


_discounting = build_discounting


# =============================================================================
# Step 5 — Ledger (Days_In_Stock etc. if present)
# =============================================================================

def build_ledger(geo: str, year_month: str) -> pd.DataFrame:
    print(f"    [ledger] finding ledger for {geo} / {year_month}...")
    source = latest_csv(resolve_geo_path(geo, "ledger"), ("ledger",))
    if source is None:
        print("    [ledger] none found — empty frame")
        return pd.DataFrame(columns=["SKU", "Year-Month"])

    print(f"    [ledger] reading: {source}")
    frame = pd.read_csv(source, low_memory=False)
    aliases = {"sku": "SKU", "year-month": "Year-Month", "year_month": "Year-Month"}
    frame = frame.rename(
        columns={col: aliases.get(str(col).strip().lower(), col) for col in frame.columns}
    )

    if not {"SKU", "Year-Month"}.issubset(frame.columns):
        print("    [ledger] missing SKU / Year-Month — empty frame")
        return pd.DataFrame(columns=["SKU", "Year-Month"])

    parsed = pd.to_datetime(frame["Year-Month"], errors="coerce")
    frame["Year-Month"] = parsed.dt.strftime("%Y-%m").fillna(frame["Year-Month"].astype(str))
    out = frame[frame["Year-Month"].eq(year_month)].copy()
    print(f"    [ledger] rows: {len(out):,}")
    return out


_ledger = build_ledger


# =============================================================================
# Step 6 — full decomposition for one geo
# =============================================================================

def build_one_geo_decomposition(
    geo: str,
    year: int,
    month_number: int,
    month_abbr: str,
    year_month: str,
) -> pd.DataFrame:
    print(f"\n>>> STEP: KNC / {geo} / decomposition ({year_month})")

    print("    [decomp] reading COGS...")
    cogs = read_cogs(geo)

    frame = build_business_report(geo, year, month_abbr, year_month, cogs)
    frame = frame.merge(build_orders(geo, year_month), on=["SKU", "Year-Month"], how="outer")
    frame = frame.merge(build_inventory(geo, cogs), on="SKU", how="left")

    print("    [decomp] reading bulk Clicks / Units / Impressions...")
    ad_metrics = read_bulk_metrics(geo, year, month_abbr, cogs, ("Clicks", "Units", "Impressions"))
    frame = frame.merge(ad_metrics, on="SKU", how="outer")
    frame = frame.merge(build_discounting(geo, year, month_abbr, cogs), on="SKU", how="outer")
    frame["Year-Month"] = frame["Year-Month"].replace(0, pd.NA).fillna(year_month)

    # rename to report names
    rename = {
        "Page_Views_Total": "Total Glance Views",
        "Clicks": "Ads Glance Views",
        "Quantity": "Total Units Sold",
        "Units": "Ads Units Sold",
    }
    frame = frame.rename(columns=rename).fillna(0)

    # MTD → full-month proration
    scalable = [
        "Total Glance Views",
        "Add_to_cart",
        "Total Units Sold",
        "Total_Sales",
        "Ads Glance Views",
        "Ads Units Sold",
        "Impressions",
        "Discounting",
    ]
    factor = proration_factor(year, month_number)
    print(f"    [decomp] proration factor: {factor:.4f}")
    for column in scalable:
        frame[column] = numeric(frame[column]) * factor if column in frame.columns else 0

    # derived rates
    frame["Total Conversion Rate"] = (
        frame["Total Units Sold"].div(frame["Total Glance Views"].replace(0, np.nan)).fillna(0) * 100
    )
    frame["ASP"] = frame["Total_Sales"].div(frame["Total Units Sold"].replace(0, np.nan)).fillna(0)
    frame["Organic Views"] = frame["Total Glance Views"] - frame["Ads Glance Views"]
    frame["Ads Conversion Rate"] = (
        frame["Ads Units Sold"].div(frame["Ads Glance Views"].replace(0, np.nan)).fillna(0) * 100
    )
    frame["Ads Organic Ratio"] = (
        frame["Ads Units Sold"].div(frame["Total Units Sold"].replace(0, np.nan)).fillna(0) * 100
    )
    frame["Discounting%"] = (
        frame["Discounting"].div(frame["Total_Sales"].replace(0, np.nan)).fillna(0) * 100
    )
    frame["CTR%"] = (
        frame["Ads Glance Views"].div(frame["Impressions"].replace(0, np.nan)).fillna(0) * 100
    )

    # ledger + OSA
    frame = frame.merge(build_ledger(geo, year_month), on=["SKU", "Year-Month"], how="left")
    frame["Days_In_Month"] = (
        (datetime.now().date() - timedelta(days=1)).day
        if year == datetime.now().year and month_number == datetime.now().month
        else calendar.monthrange(year, month_number)[1]
    )
    if "Days_In_Stock" in frame.columns:
        frame["OSA_Inventory_Availabilty%"] = (
            numeric(frame["Days_In_Stock"]).div(frame["Days_In_Month"].replace(0, np.nan)).fillna(0) * 100
        )

    frame["country"] = GEO_CONFIG[geo]["country"]
    frame["platform"] = "Amazon"
    frame["client_id"] = "TH-1753144646395"

    frame = normalize_columns(frame)
    print(f"    [decomp] DONE {geo}: {len(frame):,} rows")
    return frame


_build_geo_decomposition = build_one_geo_decomposition


# =============================================================================
# Step 7 — all geos → save → optional Azure
# =============================================================================

def build_decomposition_chart_dataframe(
    *,
    client: str = CLIENT,
    geos: str | Sequence[str] | None = None,
    year: int | str | None = None,
    month: int | str | None = None,
    save_output: bool = True,
    upload_azure: bool | None = None,
) -> pd.DataFrame:
    if client.upper() != CLIENT:
        raise ValueError("decomposition_chart supports KNC only")

    resolved_year, month_number, month_abbr, year_month = resolve_year_month(year, month)
    print("=" * 60)
    print(f"CLIENT : {CLIENT}")
    print(f"PERIOD : {year_month}  (month folder = {month_abbr})")
    print("=" * 60)

    frames: dict[str, pd.DataFrame] = {}
    for geo in parse_geos(geos):
        try:
            frames[geo] = build_one_geo_decomposition(
                geo, resolved_year, month_number, month_abbr, year_month
            )
            print(f"Built {geo} decomposition chart: {len(frames[geo]):,} rows")
        except (FileNotFoundError, OSError, ValueError, KeyError) as exc:
            print(f"WARNING: skipping {geo} decomposition chart: {exc}")

    if save_output:
        print("\n>>> STEP: save geo + combined decomposition_chart masters")
        combined = save_geo_and_combined(
            frames,
            client=client,
            report_subdir="decomposition_chart",
            name_suffix="decomposition_chart",
            dedupe_subset=("sku", "year_month", "country", "client_id"),
        )
    else:
        combined = concat_geo_frames(frames, report_type="decomposition_chart")

    if upload_azure is True and not combined.empty:
        print("\n>>> STEP: Azure upload (decomposition_chart)")
        upload_finals_to_azure(combined, report_type="decomposition_chart")

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
    combined = build_decomposition_chart_dataframe(
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
            upload_finals_to_azure(combined, report_type="decomposition_chart")
        else:
            print("[KNC] Azure upload skipped. Local decomposition_chart masters kept.")

    print("-" * 60)
    print(f"Done. Combined decomposition rows: {len(combined):,}")
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
    print_script_completed("decomposition_chart")
