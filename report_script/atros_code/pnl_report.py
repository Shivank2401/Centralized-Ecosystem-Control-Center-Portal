"""
KNC Amazon P&L (transactions + ad spend + COGS → CM1/CM2/CM3).

Covers:
  - Client: KNC only (UK, DE, AE)
  - Inputs: Settlement/transaction CSVs (DE translated), Bulk Operations Spend, COGS sheets
  - Outputs: sanity_data/KNC/pnl/{GEO}_pnl.parquet|.csv + final_pnl.*
  - Optional Azure: sanity_data/PNL/final_pnl.parquet

Preserves DE number/type translations from the legacy notebook.

Style: step-by-step (notebook-like). Each geo prints >>> STEP so a crash
shows which block failed.

Run:
    python report_script/atros_code/pnl_report.py
    python report_script/atros_code/pnl_report.py --geos UK,DE,AE --year 2026 --month aug
"""

from __future__ import annotations

import argparse
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
        resolve_year_month,
        save_geo_and_combined,
        upload_finals_to_azure,
    )
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
        resolve_year_month,
        save_geo_and_combined,
        upload_finals_to_azure,
    )


# =============================================================================
# DE translation tables (unchanged from legacy notebook)
# =============================================================================

DE_COLUMN_MAP = {
    "Datum/Uhrzeit": "date/time",
    "Typ": "type",
    "Bestellnummer": "order id",
    "SKU": "sku",
    "Beschreibung": "description",
    "Menge": "quantity",
    "Umsätze": "product sales",
    "Prodgertumsatzsteuer": "product sales tax",
    "Produktumsatzsteuer": "product sales tax",
    "Gutschrift für Versandkosten": "postage credits",
    "Steuer auf Versandgutschrift": "shipping credits tax",
    "Gutschrift für Geschenkverpackung": "gift wrap credits",
    "Steuer auf Geschenkverpackungsgutschriften": "giftwrap credits tax",
    "Rabatte aus Werbeaktionen": "promotional rebates",
    "Steuer auf Aktionsrabatte": "promotional rebates tax",
    "Einbehaltene Steuer auf Marketplace": "marketplace withheld tax",
    "Verkaufsgebühren": "selling fees",
    "Gebühren zu Versand durch Amazon": "fba fees",
    "Andere Transaktionsgebühren": "other transaction fees",
    "Andere": "other",
    "Gesamt": "total",
}

DE_TYPE_TRANSLATIONS = {
    "Bestellung": "Order",
    "Erstattung": "Refund",
    "Übertrag": "Transfer",
    "Versand durch Amazon Lagergebühr": "FBA Storage Fee",
    "Anpassung": "Adjustment",
    "Verbindlichkeit": "Liability",
    "Servicegebühr": "Service Fee",
    "Gebühren von Amazon": "Amazon Fees",
    "Bestellung_Wiedereinzug": "Order Reinstatement",
}

DE_DESCRIPTION_TRANSLATIONS = {
    "Sonstiges": "Miscellaneous",
    "FBA-Lagergebühr": "FBA Storage Fee",
    "Versand durch Amazon Gebühr für Entsorgung": "FBA Disposal Fee",
    "Versand durch Amazon Langzeitlagergebühr": "FBA Long-term Storage Fee",
    "Werbekosten": "Cost of Advertising",
    "Leistungsbasierte Coupon-Gebühr": "Performance-Based Coupon Fee",
    "Coupon-Teilnahmegebühr": "Coupon Participation Fee",
}

TRANSACTION_COLUMNS = [
    "date/time",
    "type",
    "order id",
    "sku",
    "description",
    "quantity",
    "product sales",
    "product sales tax",
    "postage credits",
    "shipping credits",
    "shipping credits tax",
    "gift wrap credits",
    "giftwrap credits tax",
    "promotional rebates",
    "promotional rebates tax",
    "marketplace withheld tax",
    "selling fees",
    "fba fees",
    "other transaction fees",
    "other",
    "total",
]


# =============================================================================
# Helpers
# =============================================================================

def german_number(value: object) -> float:
    """Convert German number text (1.234,56) to float."""
    if pd.isna(value) or value == "":
        return 0.0
    text = str(value).strip()
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(",", "")
    return pd.to_numeric(pd.Series([text]), errors="coerce").fillna(0).iloc[0]


# keep old private name in case anything still calls it
_german_number = german_number


# =============================================================================
# Step 1 — read transaction CSV for one geo / month
# =============================================================================

def read_transactions(geo: str, year: int, month_abbr: str) -> pd.DataFrame:
    print(f"    [txn] finding transaction CSV for {geo} / {year}-{month_abbr}...")
    source = find_period_file(
        geo,
        "transaction",
        year,
        month_abbr,
        extensions=(".csv",),
        required_tokens=("transaction",),
    )
    if source is None:
        raise FileNotFoundError(f"{geo} transaction CSV not found")
    print(f"    [txn] reading: {source}")

    skiprows = GEO_CONFIG[geo]["txn_skiprows"]
    frame = pd.read_csv(source, skiprows=skiprows, low_memory=False)
    frame.columns = frame.columns.astype(str).str.strip()

    # DE: translate headers / types / descriptions / number format
    if GEO_CONFIG[geo]["translate_de"]:
        print("    [txn] applying DE translations...")
        frame = frame.rename(columns=DE_COLUMN_MAP)
        frame.columns = frame.columns.astype(str).str.strip().str.lower()
        if "type" in frame.columns:
            frame["type"] = frame["type"].replace(DE_TYPE_TRANSLATIONS)
        if "description" in frame.columns:
            frame["description"] = frame["description"].replace(DE_DESCRIPTION_TRANSLATIONS)
        money_cols = set(DE_COLUMN_MAP.values()) - {
            "date/time", "type", "order id", "sku", "description", "quantity",
        }
        for column in money_cols:
            if column in frame.columns:
                frame[column] = frame[column].map(german_number)
    else:
        frame.columns = frame.columns.astype(str).str.strip().str.lower()

    # ensure all expected columns exist
    for column in TRANSACTION_COLUMNS:
        if column not in frame.columns:
            frame[column] = 0

    # AE: keep Kinetica rows only
    if geo == "AE":
        print("    [txn] AE filter: description contains 'kinetica'")
        frame = frame[
            frame["description"].astype(str).str.contains("kinetica", case=False, na=False)
        ].copy()

    print(f"    [txn] rows loaded: {len(frame):,}")
    return frame


_read_transactions = read_transactions  # back-compat alias


# =============================================================================
# Step 2 — derive line-level P&L metric columns on the transaction frame
# =============================================================================

def add_transaction_metrics(transaction: pd.DataFrame) -> pd.DataFrame:
    """Order / refund flags → sales, returns, fee buckets (same formulas as before)."""
    print("    [metrics] cleaning types + numeric columns...")
    transaction = transaction.copy()
    transaction["type"] = transaction["type"].fillna("").astype(str).str.strip()
    transaction["description"] = transaction["description"].fillna("").astype(str).str.strip()

    numeric_columns = [
        col for col in TRANSACTION_COLUMNS
        if col not in {"date/time", "type", "order id", "sku", "description"}
    ]
    for column in numeric_columns:
        transaction[column] = numeric(transaction[column])

    is_order = transaction["type"].str.casefold().eq("order")
    is_refund = transaction["type"].str.casefold().isin({"refund", "refund_retrocharge"})

    revenue_base = (
        transaction["product sales"]
        + transaction["postage credits"]
        + transaction["shipping credits"]
        + transaction["gift wrap credits"]
    )
    tax_base = (
        transaction["product sales tax"]
        + transaction["shipping credits tax"]
        + transaction["giftwrap credits tax"]
    )

    source_quantity = transaction["quantity"].copy()
    transaction["quantity"] = transaction["quantity"].where(is_order, 0)
    transaction["refund quantity"] = source_quantity.where(is_refund, 0)
    transaction["Total Units"] = transaction["quantity"] - transaction["refund quantity"]
    transaction["Total Sales"] = revenue_base.where(is_order, 0)
    transaction["Total Sales with tax"] = (revenue_base + tax_base).where(is_order, 0)
    transaction["Total_Return_Amount"] = revenue_base.where(is_refund, 0)
    transaction["Total Return with tax"] = (revenue_base + tax_base).where(is_refund, 0)
    transaction["Net Sales"] = transaction["Total Sales"] + transaction["Total_Return_Amount"]
    transaction["Net Sales with tax"] = (
        transaction["Total Sales with tax"] + transaction["Total Return with tax"]
    )

    type_lower = transaction["type"].str.casefold()
    description_lower = transaction["description"].str.casefold()

    transaction["Liquidations"] = transaction["other transaction fees"].where(
        type_lower.str.contains("liquidations"), 0
    ) + transaction["other"].where(
        type_lower.eq("fba inventory fee") & description_lower.str.contains("disposal fee"), 0
    )
    transaction["Deal Fee"] = transaction["other transaction fees"].where(
        type_lower.eq("lightning deal fee")
        | (type_lower.eq("service fee") & description_lower.str.contains("coupon redemption fee"))
        | description_lower.str.contains("lightning deal"),
        0,
    )
    transaction["FBA Reimbursement"] = (
        transaction["other"].where(
            type_lower.eq("adjustment")
            & (description_lower.str.contains("reimbursement") | description_lower.eq("other")),
            0,
        )
        + transaction["other transaction fees"].where(is_refund, 0)
    )
    transaction["Other marketing Expenses"] = transaction["other"].where(
        type_lower.eq("service fee") & description_lower.str.contains("subscription"), 0
    )
    storage_types = {"fba inventory fee", "fba storage fee"}
    transaction["Storage Fee"] = transaction["other"].where(
        type_lower.isin(storage_types) & description_lower.str.contains("storage fee"), 0
    )
    transaction["FBA Inventory Fee"] = transaction["other"].where(
        type_lower.eq("fba inventory fee") & description_lower.str.contains("reservation fee"), 0
    ) + transaction["other transaction fees"].where(is_order, 0)
    transaction["Ad Cost"] = transaction["other transaction fees"].where(
        type_lower.eq("service fee")
        & description_lower.isin({"cost of advertising", "advertising costs", "werbekosten"}),
        0,
    )
    return transaction


# =============================================================================
# Step 3 — CM1 / CM2 / CM3 (AE has special rules; UK/DE share the other branch)
# =============================================================================

def add_contribution_margins(pnl: pd.DataFrame, geo: str) -> pd.DataFrame:
    print(f"    [cm] computing CM1/CM2/CM3 for {geo}...")
    pnl = pnl.copy()

    if geo == "AE":
        pnl["CM1"] = np.where(
            (pnl["Net Sales"] > 0) | ((pnl["Net Sales"] == 0) & (pnl["Cogs"] >= 0)),
            pnl["Net Sales"] - pnl["Cogs"],
            pnl["Net Sales"] + pnl["Cogs"].abs(),
        )
        pnl["heads_CM2"] = (
            pnl["FBA Inventory Fee"] + pnl["FBA Reimbursement"] + pnl["Storage Fee"] + pnl["fba fees"]
        )
        pnl["CM2"] = np.select(
            [
                pnl["heads_CM2"] <= 0,
                (pnl["CM1"] >= 0) & (pnl["heads_CM2"] > 0),
                (pnl["CM1"] < 0) & (pnl["heads_CM2"] > 0),
            ],
            [pnl["CM1"] + pnl["heads_CM2"], pnl["CM1"] - pnl["heads_CM2"], pnl["CM1"] + pnl["heads_CM2"]],
            default=np.nan,
        )
        pnl["heads_CM3"] = (
            pnl["promotional rebates"] + pnl["Other marketing Expenses"] + pnl["selling fees"] - pnl["Spend"]
        )
        pnl["CM3"] = np.select(
            [
                pnl["heads_CM3"] <= 0,
                (pnl["CM2"] >= 0) & (pnl["heads_CM3"] > 0),
                (pnl["CM2"] < 0) & (pnl["heads_CM3"] > 0),
            ],
            [pnl["CM2"] + pnl["heads_CM3"], pnl["CM2"] - pnl["heads_CM3"], pnl["CM2"] + pnl["heads_CM3"]],
            default=np.nan,
        )
    else:
        # DE uses abs(Cogs); UK uses Cogs as-is
        if geo == "DE":
            pnl["CM1"] = pnl["Net Sales with tax"] - pnl["Cogs"].abs()
        else:
            pnl["CM1"] = pnl["Net Sales with tax"] - pnl["Cogs"]

        pnl["heads_CM2"] = pnl[
            ["Deal Fee", "FBA Inventory Fee", "Liquidations", "Storage Fee", "fba fees", "FBA Reimbursement"]
        ].sum(axis=1)
        pnl["CM2"] = pnl["CM1"] + pnl["heads_CM2"]
        pnl["heads_CM3"] = (
            pnl["Other marketing Expenses"]
            + pnl["promotional rebates"]
            + pnl["selling fees"]
            - pnl["Spend"]
            + pnl["marketplace withheld tax"]
        )
        pnl["CM3"] = pnl["CM2"] + pnl["heads_CM3"]

    return pnl


# =============================================================================
# Step 4 — full P&L for one geo
# =============================================================================

VALUE_COLUMNS = [
    "Ad Cost",
    "Deal Fee",
    "FBA Inventory Fee",
    "FBA Reimbursement",
    "Liquidations",
    "Net Sales",
    "Net Sales with tax",
    "Other marketing Expenses",
    "Storage Fee",
    "Total Return with tax",
    "Total Sales",
    "Total Sales with tax",
    "Total Units",
    "Total_Return_Amount",
    "fba fees",
    "promotional rebates",
    "quantity",
    "refund quantity",
    "selling fees",
    "marketplace withheld tax",
]


def build_one_geo_pnl(geo: str, year: int, month_abbr: str, year_month: str) -> pd.DataFrame:
    print(f"\n>>> STEP: KNC / {geo} / pnl ({year_month})")

    # --- COGS + SKU map ---
    print("    [pnl] reading COGS...")
    cogs = read_cogs(geo)
    mapping = build_sku_mapping(cogs)

    # --- transactions ---
    transaction = read_transactions(geo, year, month_abbr)
    transaction["SKU"] = transaction["sku"].map(lambda value: clean_sku(value, mapping))
    transaction = add_transaction_metrics(transaction)

    # --- group by SKU ---
    print("    [pnl] grouping by SKU...")
    pnl = transaction.groupby("SKU", as_index=False)[VALUE_COLUMNS].sum()

    # --- ad Spend from bulk ops ---
    print("    [pnl] reading bulk Ad Spend...")
    ads = read_bulk_metrics(geo, year, month_abbr, cogs, ("Spend",))
    pnl = pnl.merge(ads, on="SKU", how="outer").fillna(0)

    # --- COGS join ---
    print("    [pnl] joining Product CoGS...")
    cogs_columns = [col for col in ("SKU", "Product Category", "Product Name", "Product CoGS") if col in cogs.columns]
    cogs_frame = cogs[cogs_columns].copy()
    cogs_frame["SKU"] = cogs_frame["SKU"].map(lambda value: clean_sku(value, mapping))
    if "Product CoGS" not in cogs_frame.columns:
        cogs_frame["Product CoGS"] = 0
    cogs_frame["Product CoGS"] = numeric(cogs_frame["Product CoGS"])
    cogs_frame = cogs_frame.drop_duplicates("SKU", keep="last")
    pnl = pnl.merge(cogs_frame, on="SKU", how="left").fillna(0)
    pnl["Cogs"] = pnl["Product CoGS"] * pnl["Total Units"]

    # --- contribution margins ---
    pnl = add_contribution_margins(pnl, geo)

    # --- meta ---
    pnl["Year-Month"] = year_month
    pnl["Channel"] = GEO_CONFIG[geo]["channel"]
    pnl["platform"] = "Amazon"
    pnl["country"] = GEO_CONFIG[geo]["country"]
    pnl["client_id"] = "TH-1753144646395"

    pnl = normalize_columns(pnl)
    print(f"    [pnl] DONE {geo}: {len(pnl):,} rows")
    return pnl


# used by ad_sales_report.py — keep this name
_build_geo_pnl = build_one_geo_pnl


# =============================================================================
# Step 5 — all geos → save → optional Azure
# =============================================================================

def build_pnl_dataframe(
    *,
    client: str = CLIENT,
    geos: str | Sequence[str] | None = None,
    year: int | str | None = None,
    month: int | str | None = None,
    save_output: bool = True,
    upload_azure: bool | None = None,
) -> pd.DataFrame:
    if client.upper() != CLIENT:
        raise ValueError("pnl_report supports KNC only")

    resolved_year, _, month_abbr, year_month = resolve_year_month(year, month)
    print("=" * 60)
    print(f"CLIENT : {CLIENT}")
    print(f"PERIOD : {year_month}  (month folder = {month_abbr})")
    print("=" * 60)

    frames: dict[str, pd.DataFrame] = {}
    for geo in parse_geos(geos):
        try:
            frames[geo] = build_one_geo_pnl(geo, resolved_year, month_abbr, year_month)
            print(f"Built {geo} P&L: {len(frames[geo]):,} rows")
        except (FileNotFoundError, OSError, ValueError, KeyError) as exc:
            print(f"WARNING: skipping {geo} P&L: {exc}")

    if save_output:
        print("\n>>> STEP: save geo + combined pnl masters")
        combined = save_geo_and_combined(
            frames,
            client=client,
            report_subdir="pnl",
            name_suffix="pnl",
            dedupe_subset=("sku", "year_month", "channel", "client_id"),
        )
    else:
        combined = concat_geo_frames(frames, report_type="pnl")

    if upload_azure is True and not combined.empty:
        print("\n>>> STEP: Azure upload (pnl)")
        upload_finals_to_azure(combined, report_type="pnl")

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
    combined = build_pnl_dataframe(
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
            upload_finals_to_azure(combined, report_type="pnl")
        else:
            print("[KNC] Azure upload skipped. Local pnl masters kept.")

    print("-" * 60)
    print(f"Done. Combined pnl rows: {len(combined):,}")
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
    print_script_completed("pnl_report")
