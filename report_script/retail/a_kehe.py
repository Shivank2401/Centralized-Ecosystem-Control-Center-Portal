"""
ESH KeHE retail combiner (aged inventory, chain store, k-solve, inventory).

Covers:
  - Client: ESH — paths via esh_retail_root() / us/input/distributors/kehe
  - Local Excel: Retail-Dashboard_Files/Kehe-All.xlsx + dated Kehe Database Files
  - Azure CSV append (CONTAINER_NAME_ESH / sanity_data/retail/):
      kehe_age_inventory, kehe_chain_store, kehe_ksolve_overall, kehe_inventory

Adding a NEW client (paths only — transforms are KeHE/ESH-specific today):
  1. Add client in client.yaml / layouts + retail root env
  2. Register in CLIENT_CONFIGS below
  3. Adapt distributor path layout if needed
  4. List the client on this report in report.yaml

Style: step-by-step prints (>>> STEP). ETL formulas unchanged.

Run:
    python report_script/retail/a_kehe.py
    python report_script/retail/a_kehe.py --skip-azure
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd
from dateutil.relativedelta import relativedelta

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config_manager import paths as cfg_paths
from config_manager.report_helpers import print_script_completed
from report_script.retail import drop_duplicates_appended
from report_script.retail.azure_csv_sync import sync_datasets_to_azure_csv

# Azure blob paths (container = CONTAINER_NAME_ESH)
KEHE_AZURE_BLOBS = {
    "kehe_aged": "sanity_data/retail/kehe_age_inventory.csv",
    "kehe_Chain_Store": "sanity_data/retail/kehe_chain_store.csv",
    "k_solve_overall": "sanity_data/retail/kehe_ksolve_overall.csv",
    "kehe_inventory": "sanity_data/retail/kehe_inventory.csv",
}


# =============================================================================
# Client configuration (ESH today — register more when layouts exist)
# =============================================================================

CLIENT = "ESH"


@dataclass(frozen=True)
class KeheClientConfig:
    client_code: str
    retail_root: Path


def _esh_config() -> KeheClientConfig:
    return KeheClientConfig(
        client_code="ESH",
        retail_root=cfg_paths.esh_retail_root(),
    )


CLIENT_CONFIGS: Dict[str, Callable[[], KeheClientConfig]] = {
    "ESH": _esh_config,
}


def get_client_config(client: str = CLIENT) -> KeheClientConfig:
    key = str(client).strip().upper()
    if key not in CLIENT_CONFIGS:
        known = ", ".join(sorted(CLIENT_CONFIGS))
        raise ValueError(f"KeHE retail supports {known} only (got '{client}')")
    return CLIENT_CONFIGS[key]()


def _walk_files(folder: Path) -> List[Path]:
    files: List[Path] = []
    for root, _dirs, names in os.walk(folder):
        for name in names:
            files.append(Path(root) / name)
    return files


def _money_to_int(value) -> int:
    return int(str(value).replace("$", "").replace(",", ""))


def _money_to_float(value):
    if isinstance(value, str):
        return float(value.replace("$", "").replace(",", ""))
    return value


def _load_upc_helper(retail: Path) -> pd.DataFrame:
    item_data = pd.read_excel(
        retail / "us/input/item_master_data/item_details_master_sheet.xlsx"
    )
    upc_helper = item_data.loc[
        :,
        [
            "sku",
            "Case_Pack_Qty",
            "GTIN_12_UPC",
            "Material",
            "Product_Category",
            "Product_Sub_Category",
            "Product_Type",
        ],
    ].copy()
    upc_helper.rename(
        columns={"GTIN_12_UPC": "UPC", "Case_Pack_Qty": "Box_per_Case"},
        inplace=True,
    )
    return upc_helper


def _normalize_retailer_col(df: pd.DataFrame) -> pd.DataFrame:
    if "RetailerName" in df.columns:
        df.rename(columns={"RetailerName": "Retailer"}, inplace=True)
    elif "RetailerAreaName1" in df.columns:
        df.rename(columns={"RetailerAreaName1": "Retailer"}, inplace=True)
    return df


def _month_from_filename(name: str, *, sep: str = "_") -> str:
    parts = name.split(sep)
    return parts[len(parts) - 1].split(".")[0]


def _aged_month_from_filename(name: str) -> str:
    # Original quirk: split on "_" but index by count of "-".
    return name.split("_")[len(name.split("-")) - 1].split(".")[0]


def main(*, skip_azure: bool = False, client: str = CLIENT) -> dict:
    """KeHE processing body (paths from .env; logic unchanged)."""
    cfg = get_client_config(client)
    retail = cfg.retail_root
    kehe = retail / "us/input/distributors/kehe"
    archive_year = datetime.now().strftime("%Y")

    print(f"\n>>> STEP: setup dates + UPC helper (client={cfg.client_code})")
    print(f"  retail root: {retail}")
    datestr = pd.to_datetime("today").strftime("%d-%b-%Y")
    datestr_month_C = pd.to_datetime("today").strftime("%b-%Y")
    previous_month_date = datetime.now() - relativedelta(months=1)
    datestr_month_L = previous_month_date.strftime("%b-%Y")
    datestr_1 = (pd.to_datetime("today") - timedelta(1)).strftime("%d-%b-%Y")
    datestr_month = (pd.to_datetime("today") - timedelta(1)).strftime("%b-%Y")
    print(datestr)
    print(datestr_month_C)
    print(datestr_month_L)
    print(datestr_1)

    upc_helper = _load_upc_helper(retail)

    print("\n>>> STEP: K-solve (invoices + history)")
    # --- K-solve (Invoices Updates) ---
    k_solve_overall = pd.read_excel(
        kehe / "kehe_invoices/Kehe Deductions.xlsx",
        sheet_name="Overall Level",
    )
    k_solve_overall.rename(columns={"Date": "Invoice_Date"}, inplace=True)

    current_year_files = _walk_files(kehe / "k_solve/Current_years")
    k_solve_2025 = pd.concat(
        [pd.read_csv(p) for p in current_year_files], ignore_index=True
    ).drop_duplicates()

    previous_year_files = _walk_files(kehe / "k_solve/Previous_years")
    k_solve_oj = pd.concat(
        [pd.read_excel(p) for p in previous_year_files], ignore_index=True
    ).drop_duplicates()

    k_solve_oj = pd.concat([k_solve_oj, k_solve_2025], axis=0)
    k_solve_oj = drop_duplicates_appended(k_solve_oj, "k_solve history")
    k_solve_export = kehe / "k_solve/ksolve_export.xlsx"
    k_solve_export.parent.mkdir(parents=True, exist_ok=True)
    k_solve_oj.to_excel(k_solve_export, index=False)

    k_solve = k_solve_oj.loc[
        :,
        [
            "Invoice #",
            "Date",
            "Remarks",
            "PO #",
            "Status",
            "Invoice Amt",
            "DC Name",
            "Check #",
            "Check Date",
            "Special Payee",
            "ESN",
        ],
    ].copy()
    k_solve["Invoice Amt"] = pd.to_numeric(k_solve["Invoice Amt"], errors="coerce").abs()
    k_solve_overall = pd.merge(k_solve, k_solve_overall, on="Invoice #", how="outer")
    k_solve_overall.rename(columns={"Invoice #": "Invoice"}, inplace=True)

    print("\n>>> STEP: aged inventory archive + history")
    # --- Aged inventory ---
    aged_src = kehe / "aged inventory/Aged Inventory by Brand.csv"
    aged_archive_dir = kehe / f"aged inventory/{archive_year}"
    aged_archive_dir.mkdir(parents=True, exist_ok=True)
    Aged = pd.read_csv(aged_src)
    Aged.to_csv(
        aged_archive_dir / f"Aged Inventory by Brand_{datestr_month}.csv",
        index=False,
    )

    aged_files = _walk_files(aged_archive_dir)
    aged_frames = []
    for path in aged_files:
        frame = pd.read_csv(path)
        frame["Year-Month"] = _aged_month_from_filename(path.name)
        aged_frames.append(frame)
    Kehe_aged = pd.concat(aged_frames, ignore_index=True)
    Kehe_aged = drop_duplicates_appended(Kehe_aged, "Kehe aged inventory history")
    Kehe_aged.rename(
        columns={
            "Year-Month": "Month",
            "Product": "Product Description",
            "ThirtyQty": "Inventory Qty <= 30 days",
            "ThirtyVendorCost": "Vendor Cost <= 30 days",
            "SixtyQty": "Inventory Qty 31 to <= 60 days",
            "SixtyVendorCost": "Vendor Cost 31 to <= 60 days",
            "NintyQty": "Inventory Qty 61 to <= 90 days",
            "NintyVendorCost": "Vendor Cost 61 to <= 90 days",
            "OneTwentyQty": "Inventory Qty 91 to <= 120 days",
            "OneTwentyVendorCost": "Vendor Cost 91 to <= 120 days",
            "ThreeSixtyFiveQty": "Inventory Qty 121 to <= 365 days",
            "ThreeSixtyFiveVendorCost": "Vendor Cost 121 to <= 365 days",
            "OverThreeSixtyFiveQty": "Inventory Qty >= 366 days",
            "OverThreeSixtyFiveVendorCost": "Vendor Cost >= 366 days",
            "TotalQty": "Total Inventory Qty",
            "TotalVendorCost": "Total Vendor Cost",
        },
        inplace=True,
    )
    Kehe_aged = Kehe_aged.loc[
        :,
        [
            "Month",
            "Brand",
            "DC",
            "Product Description",
            "UPC",
            "Inventory Qty <= 30 days",
            "Vendor Cost <= 30 days",
            "Inventory Qty 31 to <= 60 days",
            "Vendor Cost 31 to <= 60 days",
            "Inventory Qty 61 to <= 90 days",
            "Vendor Cost 61 to <= 90 days",
            "Inventory Qty 91 to <= 120 days",
            "Vendor Cost 91 to <= 120 days",
            "Inventory Qty 121 to <= 365 days",
            "Vendor Cost 121 to <= 365 days",
            "Inventory Qty >= 366 days",
            "Vendor Cost >= 366 days",
            "Total Inventory Qty",
            "Total Vendor Cost",
        ],
    ].copy()

    for col in [
        "Vendor Cost <= 30 days",
        "Vendor Cost 31 to <= 60 days",
        "Vendor Cost 61 to <= 90 days",
        "Vendor Cost 91 to <= 120 days",
        "Vendor Cost 121 to <= 365 days",
        "Vendor Cost >= 366 days",
        "Total Vendor Cost",
    ]:
        Kehe_aged[col] = Kehe_aged[col].apply(_money_to_int)

    Kehe_aged["Product Description"] = Kehe_aged["Product Description"].apply(
        lambda x: x.replace(".000000", "")
    )
    for col in [
        "Inventory Qty <= 30 days",
        "Inventory Qty 31 to <= 60 days",
        "Inventory Qty 61 to <= 90 days",
        "Total Inventory Qty",
    ]:
        Kehe_aged[col] = Kehe_aged[col].apply(lambda x: int(str(x).replace(",", "")))

    Kehe_aged = Kehe_aged.merge(upc_helper, on="UPC", how="left")

    print("\n>>> STEP: chain store — item qty (eaches)")
    # --- Chain Store: Item Qty (eaches) ---
    chain_root = kehe / "Chain"
    qty_archive = chain_root / f"item_quantity(in_eaches)/{archive_year}"
    qty_archive.mkdir(parents=True, exist_ok=True)
    chain_store_qty = pd.read_csv(chain_root / "Item_qty_eaches_MTD.csv")
    chain_store_qty.to_csv(
        qty_archive / f"Chains_Stores_Item_qty_MTD_{datestr_month}.csv",
        index=False,
    )

    qty_files = _walk_files(chain_root / "item_quantity(in_eaches)")
    qty_frames = []
    for path in qty_files:
        frame = pd.read_csv(path)
        frame["File_Month"] = _month_from_filename(path.name, sep="_")
        qty_frames.append(frame)
    chain_store_qty = pd.concat(qty_frames, ignore_index=True)
    chain_store_qty = drop_duplicates_appended(
        chain_store_qty, "Kehe chain qty history"
    )
    chain_store_qty = _normalize_retailer_col(chain_store_qty)
    chain_store_qty.rename(
        columns={
            "Store": "Retailer Area",
            "Item": "Product Description",
            "FillRate": "Fill Rate (Quantity)",
            "Ordered": "Ordered (Quantity)",
            "Shipped": "Shipped (Quantity)",
        },
        inplace=True,
    )
    chain_store_qty = chain_store_qty.loc[
        :,
        [
            "File_Month",
            "Retailer",
            "Retailer Area",
            "Product Description",
            "Fill Rate (Quantity)",
            "Ordered (Quantity)",
            "Shipped (Quantity)",
        ],
    ].copy()
    chain_store_qty["UPC"] = chain_store_qty["Product Description"].apply(
        lambda x: int(x.split("(")[1].replace(")", ""))
    )
    chain_store_qty["Product Description"] = chain_store_qty["Product Description"].apply(
        lambda x: x.split(" (")[0]
    )
    chain_store_qty["Fill Rate (Quantity)"] = (
        chain_store_qty["Fill Rate (Quantity)"].apply(
            lambda x: float(str(x).replace("%", ""))
        )
        / 100
    )
    chain_store_qty.Retailer = np.where(
        chain_store_qty.Retailer == "ARS",
        "GRISTEDES/D'AGOSTINOS",
        chain_store_qty.Retailer,
    )

    print("\n>>> STEP: chain store — list wholesale")
    # --- Chain Store: List wholesale ---
    wholesale_archive = chain_root / f"item_list_wholesale/{archive_year}"
    wholesale_archive.mkdir(parents=True, exist_ok=True)
    list_wholesale = pd.read_csv(chain_root / "List_Wholesale_MTD.csv")
    list_wholesale.to_csv(
        wholesale_archive / f"Chains_Stores_list_Wholesale_MTD_{datestr_month}.csv",
        index=False,
    )

    wholesale_files = _walk_files(chain_root / "item_list_wholesale")
    wholesale_frames = []
    for path in wholesale_files:
        frame = pd.read_csv(path)
        frame["File_Month"] = _month_from_filename(path.name, sep="_")
        wholesale_frames.append(frame)
    list_wholesale = pd.concat(wholesale_frames, ignore_index=True)
    list_wholesale = drop_duplicates_appended(
        list_wholesale, "Kehe list wholesale history"
    )
    list_wholesale = _normalize_retailer_col(list_wholesale)
    list_wholesale.rename(
        columns={
            "Store": "Retailer Area",
            "Item": "Product Description",
            "FillRate": "Fill Rate (List Wholesale)",
            "Ordered": "Ordered (List Wholesale)",
            "Shipped": "Shipped (List Wholesale)",
        },
        inplace=True,
    )
    list_wholesale = list_wholesale.loc[
        :,
        [
            "File_Month",
            "Retailer",
            "Retailer Area",
            "Product Description",
            "Fill Rate (List Wholesale)",
            "Ordered (List Wholesale)",
            "Shipped (List Wholesale)",
        ],
    ].copy()
    list_wholesale["UPC"] = list_wholesale["Product Description"].apply(
        lambda x: int(x.split("(")[1].replace(")", ""))
    )
    list_wholesale["Product Description"] = list_wholesale["Product Description"].apply(
        lambda x: x.split(" (")[0]
    )
    list_wholesale["Ordered (List Wholesale)"] = list_wholesale[
        "Ordered (List Wholesale)"
    ].apply(_money_to_float)
    list_wholesale["Shipped (List Wholesale)"] = list_wholesale[
        "Shipped (List Wholesale)"
    ].apply(_money_to_float)
    list_wholesale.Retailer = np.where(
        list_wholesale.Retailer == "ARS",
        "GRISTEDES/D'AGOSTINOS",
        list_wholesale.Retailer,
    )

    print("\n>>> STEP: chain store — vendor cost")
    # --- Chain Store: Vendor cost ---
    vendor_archive = chain_root / f"vendor_cost/{archive_year}"
    vendor_archive.mkdir(parents=True, exist_ok=True)
    vendor_cost = pd.read_csv(chain_root / "Vendor_Cost_MTD.csv")
    vendor_cost.to_csv(
        vendor_archive / f"Chains_Stores_Vendor_Cost_MTD_{datestr_month}.csv",
        index=False,
    )

    vendor_files = _walk_files(chain_root / "vendor_cost")
    vendor_frames = []
    for path in vendor_files:
        frame = pd.read_csv(path)
        frame["File_Month"] = _month_from_filename(path.name, sep="_")
        vendor_frames.append(frame)
    vendor_cost = pd.concat(vendor_frames, ignore_index=True)
    vendor_cost = drop_duplicates_appended(vendor_cost, "Kehe vendor cost history")
    vendor_cost = _normalize_retailer_col(vendor_cost)
    vendor_cost.rename(
        columns={
            "Store": "Retailer Area",
            "Item": "Product Description",
            "FillRate": "Fill Rate (Vendor Cost)",
            "Ordered": "Ordered (Vendor Cost)",
            "Shipped": "Shipped (Vendor Cost)",
        },
        inplace=True,
    )
    vendor_cost = vendor_cost.loc[
        :,
        [
            "File_Month",
            "Retailer",
            "Retailer Area",
            "Product Description",
            "Fill Rate (Vendor Cost)",
            "Ordered (Vendor Cost)",
            "Shipped (Vendor Cost)",
        ],
    ].copy()
    vendor_cost["UPC"] = vendor_cost["Product Description"].apply(
        lambda x: int(x.split("(")[1].replace(")", ""))
    )
    vendor_cost["Product Description"] = vendor_cost["Product Description"].apply(
        lambda x: x.split(" (")[0]
    )
    vendor_cost["Ordered (Vendor Cost)"] = vendor_cost["Ordered (Vendor Cost)"].apply(
        _money_to_float
    )
    vendor_cost["Shipped (Vendor Cost)"] = vendor_cost["Shipped (Vendor Cost)"].apply(
        _money_to_float
    )
    vendor_cost.Retailer = np.where(
        vendor_cost.Retailer == "ARS",
        "GRISTEDES/D'AGOSTINOS",
        vendor_cost.Retailer,
    )

    print("\n>>> STEP: collate chain store + case cost / markup")
    # --- Collate chain store ---
    Kehe_Chain_Store = (
        vendor_cost.merge(
            chain_store_qty,
            on=["File_Month", "Retailer", "Retailer Area", "Product Description", "UPC"],
            how="outer",
        )
        .merge(
            list_wholesale,
            on=["File_Month", "Retailer", "Retailer Area", "Product Description", "UPC"],
            how="outer",
        )
    )
    Kehe_Chain_Store = pd.merge(Kehe_Chain_Store, upc_helper, on="UPC", how="left")
    Kehe_Chain_Store["Ordered (Quantity)"] = pd.to_numeric(
        Kehe_Chain_Store["Ordered (Quantity)"], errors="coerce"
    )
    Kehe_Chain_Store["Box_per_Case"] = pd.to_numeric(
        Kehe_Chain_Store["Box_per_Case"], errors="coerce"
    )
    Kehe_Chain_Store["Ordered (Vendor Cost)"] = pd.to_numeric(
        Kehe_Chain_Store["Ordered (Vendor Cost)"], errors="coerce"
    )
    Kehe_Chain_Store["Ordered_Case_Cost_(Vendor_Cost)"] = np.where(
        Kehe_Chain_Store["Ordered (Quantity)"] == Kehe_Chain_Store["Box_per_Case"],
        Kehe_Chain_Store["Ordered (Vendor Cost)"],
        Kehe_Chain_Store["Ordered (Vendor Cost)"]
        / (Kehe_Chain_Store["Ordered (Quantity)"] / Kehe_Chain_Store["Box_per_Case"]),
    )
    Kehe_Chain_Store["Ordered_Case_Cost_(List_Wholesale)"] = np.where(
        Kehe_Chain_Store["Ordered (Quantity)"] == Kehe_Chain_Store["Box_per_Case"],
        Kehe_Chain_Store["Ordered (List Wholesale)"],
        Kehe_Chain_Store["Ordered (List Wholesale)"]
        / (Kehe_Chain_Store["Ordered (Quantity)"] / Kehe_Chain_Store["Box_per_Case"]),
    )
    Kehe_Chain_Store["Markup"] = (
        Kehe_Chain_Store["Ordered_Case_Cost_(List_Wholesale)"]
        - Kehe_Chain_Store["Ordered_Case_Cost_(Vendor_Cost)"]
    ) / Kehe_Chain_Store["Ordered_Case_Cost_(Vendor_Cost)"]

    print("\n>>> STEP: inventory + inventory at risk")
    # --- Inventory + inventory at risk ---
    inv_root = kehe / "Inventory"
    stock_archive = inv_root / "inventory_stock_status"
    risk_archive = inv_root / "inventory_at_risk"
    stock_archive.mkdir(parents=True, exist_ok=True)
    risk_archive.mkdir(parents=True, exist_ok=True)

    kehe_inventory = pd.read_csv(inv_root / "Inventory Stock Status.csv")
    kehe_inventory["Downloaded_On"] = datestr
    kehe_inventory.to_csv(
        stock_archive / f"inventory_stock_status_{datestr_month}.csv",
        index=False,
    )
    kehe_inventory = pd.merge(kehe_inventory, upc_helper, on="UPC", how="left")

    inventory_risk = pd.read_csv(inv_root / "Inventory at Risk.csv")
    inventory_risk["Downloaded_On"] = datestr
    inventory_risk.to_csv(
        risk_archive / f"inventory_at_risk_{datestr_month}.csv",
        index=False,
    )
    inventory_risk = pd.merge(inventory_risk, upc_helper, on="UPC", how="left")
    kehe_inventory = pd.merge(kehe_inventory, inventory_risk, how="outer")

    print("\n>>> STEP: save Kehe-All.xlsx (dashboard + backup)")
    dashboard_path = retail / "Retail-Dashboard_Files/Kehe-All.xlsx"
    backup_dir = retail / "us/output/Kehe/Kehe Database Files"
    dashboard_path.parent.mkdir(parents=True, exist_ok=True)
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"Kehe-All_filestypes_{datestr}.xlsx"

    # Final sheet-level dedupe on the dashboard workbook (Azure-synced retail root)
    sheets = {
        "Kehe-Age_Invento": drop_duplicates_appended(Kehe_aged, "sheet Kehe-Age_Invento"),
        "Kehe_Chain_Store": drop_duplicates_appended(
            Kehe_Chain_Store, "sheet Kehe_Chain_Store"
        ),
        "Kehe-Solve_overall": drop_duplicates_appended(
            k_solve_overall, "sheet Kehe-Solve_overall"
        ),
        "Kehe-Inventory": drop_duplicates_appended(
            kehe_inventory, "sheet Kehe-Inventory"
        ),
        "Kehe-Risk_Inventory": drop_duplicates_appended(
            inventory_risk, "sheet Kehe-Risk_Inventory"
        ),
    }
    for out_path in (dashboard_path, backup_path):
        with pd.ExcelWriter(out_path) as writer:
            for sheet_name, frame in sheets.items():
                frame.to_excel(writer, sheet_name=sheet_name, index=False)

    print(f"KeHE dashboard : {dashboard_path}")
    print(f"KeHE backup    : {backup_path}")

    print("\n>>> STEP: Azure CSV append (KeHE datasets)")
    azure_frames = {
        "kehe_aged": sheets["Kehe-Age_Invento"],
        "kehe_Chain_Store": sheets["Kehe_Chain_Store"],
        "k_solve_overall": sheets["Kehe-Solve_overall"],
        "kehe_inventory": sheets["Kehe-Inventory"],
    }
    azure_results = sync_datasets_to_azure_csv(
        [
            (name, azure_frames[name], blob_path)
            for name, blob_path in KEHE_AZURE_BLOBS.items()
        ],
        skip_azure=skip_azure,
    )

    print("\n>>> STEP: KeHE complete")
    return {
        "aged": sheets["Kehe-Age_Invento"],
        "chain_store": sheets["Kehe_Chain_Store"],
        "k_solve": sheets["Kehe-Solve_overall"],
        "inventory": sheets["Kehe-Inventory"],
        "risk": sheets["Kehe-Risk_Inventory"],
        "dashboard_path": dashboard_path,
        "backup_path": backup_path,
        "azure": azure_results,
    }


def run(
    *,
    client: str = CLIENT,
    geos: Optional[Sequence[str]] = None,
    skip_azure: bool = False,
    **_kwargs,
) -> dict:
    """Pipeline CLI entrypoint: run(client='ESH')."""
    del geos
    key = str(client).strip().upper()
    if key not in CLIENT_CONFIGS:
        print(f"[skip] KeHE retail supports {', '.join(sorted(CLIENT_CONFIGS))} only (got client={client})")
        return {}
    cfg = get_client_config(key)
    print(f"KeHE retail report (client={cfg.client_code})")
    print(f"Retail root: {cfg.retail_root}")
    return main(skip_azure=skip_azure, client=key)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ESH KeHE retail combiner")
    parser.add_argument(
        "--skip-azure",
        action="store_true",
        help="Skip Azure CSV upload (local Excel only)",
    )
    args = parser.parse_args()
    run(skip_azure=args.skip_azure)
    print_script_completed("a_kehe")