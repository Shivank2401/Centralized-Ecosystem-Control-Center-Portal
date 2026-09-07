"""Pipeline-ready KNC executive decomposition chart for UK, DE, and AE."""

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
except ImportError:  # support direct script execution
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


def _latest_csv(root: Path, tokens: Sequence[str]) -> Path | None:
    if not root.exists():
        return None
    lowered_tokens = [token.lower() for token in tokens]
    candidates = [
        candidate
        for candidate in root.rglob("*.csv")
        if all(token in candidate.name.lower() for token in lowered_tokens)
    ]
    return max(candidates, key=lambda item: item.stat().st_mtime) if candidates else None


def _business_report(
    geo: str,
    year: int,
    month_abbr: str,
    year_month: str,
    cogs: pd.DataFrame,
) -> pd.DataFrame:
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
    frame = pd.read_csv(source, low_memory=False)
    aliases = {
        "(child) asin": "ASIN",
        "page views – total": "Page_Views_Total",
        "page views - total": "Page_Views_Total",
        "page views - total ": "Page_Views_Total",
        "featured offer (buy box) percentage": "buy_box_percentage",
    }
    frame = frame.rename(columns={column: aliases.get(str(column).strip().lower(), column) for column in frame.columns})
    required = {"ASIN", "Page_Views_Total", "buy_box_percentage"}
    if not required.issubset(frame.columns):
        raise ValueError(f"{geo} business report missing columns: {sorted(required - set(frame.columns))}")
    if GEO_CONFIG[geo]["kinetica_filter"] and "Title" in frame:
        frame = frame[frame["Title"].astype(str).str.contains("kinetica", case=False, na=False)]
    helper_columns = [
        column
        for column in ("ASIN", "SKU", "Product Name", "Product Category")
        if column in cogs
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
    return grouped.drop(columns="weighted_buy_box")


def _orders(geo: str, year_month: str) -> pd.DataFrame:
    source = _latest_csv(resolve_geo_path(geo, "orders"), (geo, "orders"))
    if source is None:
        raise FileNotFoundError(f"{geo} overall orders CSV not found")
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
    frame = frame.rename(columns={column: aliases.get(str(column).strip().lower(), column) for column in frame.columns})
    if "Year-Month" not in frame and "purchase-date" in frame:
        frame["Year-Month"] = pd.to_datetime(frame["purchase-date"], errors="coerce").dt.strftime("%Y-%m")
    if "order-status" in frame:
        frame = frame[~frame["order-status"].astype(str).str.casefold().eq("cancelled")]
    frame = frame[frame["Year-Month"].astype(str).eq(year_month)].copy()
    for column in ("Quantity", "Total_Sales"):
        frame[column] = numeric(frame[column]) if column in frame else 0
    if "Order_ID" not in frame:
        frame["Order_ID"] = pd.RangeIndex(len(frame)).astype(str)
    return frame.groupby(["Year-Month", "SKU"], as_index=False).agg(
        Quantity=("Quantity", "sum"),
        Total_Sales=("Total_Sales", "sum"),
        Add_to_cart=("Order_ID", "nunique"),
    )


def _inventory(geo: str, cogs: pd.DataFrame) -> pd.DataFrame:
    root = resolve_geo_path(geo, "inventory")
    source = _latest_csv(root, ("manage", "fba")) or _latest_csv(root, ("inventory",))
    if source is None:
        raise FileNotFoundError(f"{geo} manage-FBA inventory CSV not found")
    frame = pd.read_csv(source, low_memory=False)
    frame = frame.rename(columns={column: str(column).strip().lower() for column in frame.columns})
    if GEO_CONFIG[geo]["kinetica_filter"] and "product-name" in frame:
        frame = frame[frame["product-name"].astype(str).str.contains("kinetica", case=False, na=False)]
    if "sku" not in frame or "afn-fulfillable-quantity" not in frame:
        raise ValueError(f"{geo} inventory missing sku/afn-fulfillable-quantity")
    mapping = build_sku_mapping(cogs)
    frame["SKU"] = frame["sku"].map(lambda value: clean_sku(value, mapping))
    frame["Available_Inventory"] = numeric(frame["afn-fulfillable-quantity"])
    return frame.groupby("SKU", as_index=False)["Available_Inventory"].sum()


def _discounting(
    geo: str,
    year: int,
    month_abbr: str,
    cogs: pd.DataFrame,
) -> pd.DataFrame:
    frame = _read_transactions(geo, year, month_abbr)
    mapping = build_sku_mapping(cogs)
    frame["SKU"] = frame["sku"].map(lambda value: clean_sku(value, mapping))
    frame["Discounting"] = numeric(frame["promotional rebates"])
    return frame.groupby("SKU", as_index=False)["Discounting"].sum()


def _proration_factor(year: int, month_number: int) -> float:
    month_days = calendar.monthrange(year, month_number)[1]
    yesterday = datetime.now().date() - timedelta(days=1)
    start = datetime(year, month_number, 1).date()
    end = datetime(year, month_number, month_days).date()
    if yesterday < start:
        return 0.0
    elapsed = (min(yesterday, end) - start).days + 1
    return month_days / elapsed if elapsed else 0.0


def _ledger(geo: str, year_month: str) -> pd.DataFrame:
    source = _latest_csv(resolve_geo_path(geo, "ledger"), ("ledger",))
    if source is None:
        return pd.DataFrame(columns=["SKU", "Year-Month"])
    frame = pd.read_csv(source, low_memory=False)
    aliases = {"sku": "SKU", "year-month": "Year-Month", "year_month": "Year-Month"}
    frame = frame.rename(columns={column: aliases.get(str(column).strip().lower(), column) for column in frame.columns})
    if not {"SKU", "Year-Month"}.issubset(frame.columns):
        return pd.DataFrame(columns=["SKU", "Year-Month"])
    parsed = pd.to_datetime(frame["Year-Month"], errors="coerce")
    frame["Year-Month"] = parsed.dt.strftime("%Y-%m").fillna(frame["Year-Month"].astype(str))
    return frame[frame["Year-Month"].eq(year_month)].copy()


def _build_geo_decomposition(
    geo: str,
    year: int,
    month_number: int,
    month_abbr: str,
    year_month: str,
) -> pd.DataFrame:
    cogs = read_cogs(geo)
    frame = _business_report(geo, year, month_abbr, year_month, cogs)
    frame = frame.merge(_orders(geo, year_month), on=["SKU", "Year-Month"], how="outer")
    frame = frame.merge(_inventory(geo, cogs), on="SKU", how="left")
    ad_metrics = read_bulk_metrics(geo, year, month_abbr, cogs, ("Clicks", "Units", "Impressions"))
    frame = frame.merge(ad_metrics, on="SKU", how="outer")
    frame = frame.merge(_discounting(geo, year, month_abbr, cogs), on="SKU", how="outer")
    frame["Year-Month"] = frame["Year-Month"].replace(0, pd.NA).fillna(year_month)

    rename = {
        "Page_Views_Total": "Total Glance Views",
        "Clicks": "Ads Glance Views",
        "Quantity": "Total Units Sold",
        "Units": "Ads Units Sold",
    }
    frame = frame.rename(columns=rename).fillna(0)
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
    factor = _proration_factor(year, month_number)
    for column in scalable:
        frame[column] = numeric(frame[column]) * factor if column in frame else 0
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
    frame = frame.merge(_ledger(geo, year_month), on=["SKU", "Year-Month"], how="left")
    frame["Days_In_Month"] = (
        (datetime.now().date() - timedelta(days=1)).day
        if year == datetime.now().year and month_number == datetime.now().month
        else calendar.monthrange(year, month_number)[1]
    )
    if "Days_In_Stock" in frame:
        frame["OSA_Inventory_Availabilty%"] = (
            numeric(frame["Days_In_Stock"]).div(frame["Days_In_Month"].replace(0, np.nan)).fillna(0) * 100
        )
    frame["country"] = GEO_CONFIG[geo]["country"]
    frame["platform"] = "Amazon"
    frame["client_id"] = "TH-1753144646395"
    return normalize_columns(frame)


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
    frames: dict[str, pd.DataFrame] = {}
    for geo in parse_geos(geos):
        try:
            frames[geo] = _build_geo_decomposition(
                geo, resolved_year, month_number, month_abbr, year_month
            )
            print(f"Built {geo} decomposition chart: {len(frames[geo]):,} rows")
        except (FileNotFoundError, OSError, ValueError, KeyError) as exc:
            print(f"WARNING: skipping {geo} decomposition chart: {exc}")
    combined = (
        save_geo_and_combined(
            frames,
            client=client,
            report_subdir="decomposition_chart",
            name_suffix="decomposition_chart",
            dedupe_subset=("sku", "year_month", "country", "client_id"),
        )
        if save_output
        else concat_geo_frames(frames, report_type="decomposition_chart")
    )
    if upload_azure is True and not combined.empty:
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
    combined = build_decomposition_chart_dataframe(
        client=client,
        geos=geos,
        year=year,
        month=month,
        save_output=save_output,
        upload_azure=False,
    )
    if save_output and not combined.empty:
        if resolve_azure_upload_choice(upload_azure, skip_azure=skip_azure):
            upload_finals_to_azure(combined, report_type="decomposition_chart")
        else:
            print("[KNC] Azure upload skipped. Local decomposition_chart masters kept.")
    return combined


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
    main()
