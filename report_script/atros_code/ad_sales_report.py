"""Pipeline-ready KNC advertising sales/spend report for UK, DE, and AE."""

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
except ImportError:  # support direct script execution
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


def _orders_path(geo: str) -> Path | None:
    root = resolve_geo_path(geo, "orders")
    if not root.exists():
        return None
    names = [f"{geo}_orders_overall.csv", f"{geo.lower()}_orders_overall.csv"]
    candidates = [
        candidate
        for candidate in root.rglob("*.csv")
        if candidate.name.lower() in {name.lower() for name in names}
    ]
    return max(candidates, key=lambda item: item.stat().st_mtime) if candidates else None


def _gross_sales(geo: str, year_month: str) -> pd.DataFrame:
    source = _orders_path(geo)
    if source is None:
        return pd.DataFrame(columns=["SKU", "Year-Month", "Total_Gross_Sales"])
    orders = pd.read_csv(source, low_memory=False)
    orders.columns = orders.columns.astype(str).str.strip()
    rename = {
        "sku": "SKU",
        "year_month": "Year-Month",
        "total_sales": "Total_Gross_Sales",
        "purchase_date": "purchase-date",
        "purchase-date": "purchase-date",
        "order_status": "order-status",
        "order-status": "order-status",
    }
    orders = orders.rename(columns={column: rename.get(column.lower(), column) for column in orders.columns})
    if "Year-Month" not in orders and "purchase-date" in orders:
        orders["Year-Month"] = pd.to_datetime(orders["purchase-date"], errors="coerce").dt.strftime("%Y-%m")
    if "order-status" in orders:
        orders = orders[~orders["order-status"].astype(str).str.casefold().eq("cancelled")]
    required = {"SKU", "Year-Month", "Total_Gross_Sales"}
    if not required.issubset(orders.columns):
        return pd.DataFrame(columns=list(required))
    orders = orders[orders["Year-Month"].astype(str).eq(year_month)].copy()
    orders["Total_Gross_Sales"] = numeric(orders["Total_Gross_Sales"])
    return orders.groupby(["SKU", "Year-Month"], as_index=False)["Total_Gross_Sales"].sum()


def _build_geo_ads(geo: str, year: int, month_abbr: str, year_month: str) -> pd.DataFrame:
    cogs = read_cogs(geo)
    ad_sales = read_bulk_metrics(geo, year, month_abbr, cogs, ("Sales",))
    ad_sales = ad_sales.rename(columns={"Sales": "Ad_Sales"})
    ad_sales["Year-Month"] = year_month

    pnl = _build_geo_pnl(geo, year, month_abbr, year_month)
    pnl_columns = {
        "sku": "SKU",
        "year_month": "Year-Month",
        "spend": "Ad_Spend",
        "total_sales_with_tax": "Total_Revenue",
    }
    available = [column for column in pnl_columns if column in pnl]
    pnl_slice = pnl[available].rename(columns=pnl_columns)
    for column in ("Ad_Spend", "Total_Revenue"):
        if column not in pnl_slice:
            pnl_slice[column] = 0

    result = ad_sales.merge(pnl_slice, on=["SKU", "Year-Month"], how="outer")
    result = result.merge(_gross_sales(geo, year_month), on=["SKU", "Year-Month"], how="outer")
    for column in ("Ad_Sales", "Ad_Spend", "Total_Revenue", "Total_Gross_Sales"):
        result[column] = numeric(result[column]) if column in result else 0
    result = result[
        ~(
            (result["Ad_Sales"] == 0)
            & (result["Ad_Spend"] == 0)
            & (result["Total_Revenue"] == 0)
            & (result["Total_Gross_Sales"] == 0)
        )
    ].copy()
    result["TACoS %"] = (
        result["Ad_Spend"].div(result["Total_Gross_Sales"].replace(0, float("nan"))).fillna(0) * 100
    )
    result["country"] = GEO_CONFIG[geo]["country"]
    result["platform"] = "Amazon"
    result["channel"] = GEO_CONFIG[geo]["channel"]
    result["client_id"] = "TH-1753144646395"
    return normalize_columns(result)


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
    frames: dict[str, pd.DataFrame] = {}
    for geo in parse_geos(geos):
        try:
            frames[geo] = _build_geo_ads(geo, resolved_year, month_abbr, year_month)
            print(f"Built {geo} ads report: {len(frames[geo]):,} rows")
        except (FileNotFoundError, OSError, ValueError, KeyError) as exc:
            print(f"WARNING: skipping {geo} ads report: {exc}")
    combined = (
        save_geo_and_combined(
            frames,
            client=client,
            report_subdir="ads",
            name_suffix="ads",
            dedupe_subset=("sku", "year_month", "country", "client_id"),
        )
        if save_output
        else concat_geo_frames(frames, report_type="ads")
    )
    if upload_azure is True and not combined.empty:
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
    combined = build_ad_sales_dataframe(
        client=client,
        geos=geos,
        year=year,
        month=month,
        save_output=save_output,
        upload_azure=False,
    )
    if save_output and not combined.empty:
        if resolve_azure_upload_choice(upload_azure, skip_azure=skip_azure):
            upload_finals_to_azure(combined, report_type="ads")
        else:
            print("[KNC] Azure upload skipped. Local ads masters kept.")
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


from config_manager.report_helpers import print_script_completed

if __name__ == "__main__":
    main()
    print_script_completed('ad_sales_report')
