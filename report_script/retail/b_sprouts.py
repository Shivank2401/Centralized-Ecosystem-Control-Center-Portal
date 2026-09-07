"""
ESH Sprouts retail combiner (chain store, inventory, inventory at risk).

Ports the notebook/script into the pipeline:
  - processing logic preserved
  - paths from .env via config_manager.paths.esh_retail_root()
  - CLI entrypoint: run(client='ESH')

Outputs (under ESH retail root):
  Retail-Dashboard_Files/Sprouts-All.xlsx
  us/output/Sprouts/Sprouts Database Files/Sprouts-All_filestypes_{datestr}.xlsx

Azure CSV append (CONTAINER_NAME_ESH / sanity_data/retail/):
  sprout_chain_store.csv
  sprout_inventory.csv
  sprouts_risk.csv

Run:
  python report_script/retail/b_sprouts.py
  python report_script/retail/b_sprouts.py --skip-azure
  # or via run_pipeline.py → Stage: retail → Sprouts
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Sequence

import numpy as np
import pandas as pd
from dateutil.relativedelta import relativedelta

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config_manager import paths as cfg_paths
from report_script.retail import drop_duplicates_appended
from report_script.retail.azure_csv_sync import sync_datasets_to_azure_csv

# Azure blob paths (container = CONTAINER_NAME_ESH)
SPROUTS_AZURE_BLOBS = {
    "Sprouts_Chain_Store": "sanity_data/retail/sprout_chain_store.csv",
    "Sprouts_inventory": "sanity_data/retail/sprout_inventory.csv",
    "Sprouts_risk": "sanity_data/retail/sprouts_risk.csv",
}


def _walk_files(folder: Path) -> List[Path]:
    files: List[Path] = []
    for root, _dirs, names in os.walk(folder):
        for name in names:
            files.append(Path(root) / name)
    return files


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
    upc_helper["UPC"] = pd.to_numeric(upc_helper["UPC"], errors="coerce")
    return upc_helper


def _month_from_filename(name: str) -> str:
    parts = name.split("_")
    return parts[len(parts) - 1].split(".")[0]


def main(*, skip_azure: bool = False) -> dict:
    """Sprouts processing body (paths from .env; logic unchanged)."""
    retail = cfg_paths.esh_retail_root()
    sprouts = retail / "us/input/distributors/Sprouts"
    archive_year = datetime.now().strftime("%Y")

    datestr = pd.to_datetime("today").strftime("%d-%b-%Y")
    datestr_1 = (pd.to_datetime("today") - timedelta(1)).strftime("%d-%b-%Y")
    datestr_month_C = pd.to_datetime("today").strftime("%b-%Y")
    previous_month_date = datetime.now() - relativedelta(months=1)
    datestr_month_L = previous_month_date.strftime("%b-%Y")
    datestr_month = (pd.to_datetime("today") - timedelta(1)).strftime("%b-%Y")
    print(datestr)
    print(datestr_1)
    print(datestr_month_C)
    print(datestr_month_L)

    upc_helper = _load_upc_helper(retail)

    # --- Chain Store: Item Qty ---
    chain_root = sprouts / "Chain Store"
    qty_archive = chain_root / f"item_quantity(in_eaches)/{archive_year}"
    qty_archive.mkdir(parents=True, exist_ok=True)
    Chain_item_qty = pd.read_csv(chain_root / "Item_qty_eaches_MTD.csv")
    Chain_item_qty.to_csv(
        qty_archive / f"Item_qty_MTD_{datestr_month}.csv",
        index=False,
    )

    qty_files = _walk_files(chain_root / "item_quantity(in_eaches)")
    qty_frames = []
    for path in qty_files:
        frame = pd.read_csv(path)
        frame["File_Month"] = _month_from_filename(path.name)
        qty_frames.append(frame)
    chain_store_qty = pd.concat(qty_frames, ignore_index=True)
    chain_store_qty = drop_duplicates_appended(
        chain_store_qty, "Sprouts chain qty history"
    )
    chain_store_qty.rename(
        columns={
            "RetailerName": "Retailer",
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

    # --- Chain Store: List wholesale ---
    wholesale_archive = chain_root / f"item_list_wholesale/{archive_year}"
    wholesale_archive.mkdir(parents=True, exist_ok=True)
    list_wholesale = pd.read_csv(chain_root / "List_Wholesale_MTD.csv")
    list_wholesale.to_csv(
        wholesale_archive / f"List_Wholesale_MTD_{datestr_month}.csv",
        index=False,
    )

    wholesale_files = _walk_files(chain_root / "item_list_wholesale")
    wholesale_frames = []
    for path in wholesale_files:
        frame = pd.read_csv(path)
        frame["File_Month"] = _month_from_filename(path.name)
        wholesale_frames.append(frame)
    list_wholesale = pd.concat(wholesale_frames, ignore_index=True)
    list_wholesale = drop_duplicates_appended(
        list_wholesale, "Sprouts list wholesale history"
    )
    list_wholesale.rename(
        columns={
            "RetailerName": "Retailer",
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

    # --- Chain Store: Vendor cost ---
    vendor_archive = chain_root / f"vendor_cost/{archive_year}"
    vendor_archive.mkdir(parents=True, exist_ok=True)
    vendor_cost = pd.read_csv(chain_root / "Vendor_Cost_MTD.csv")
    vendor_cost.to_csv(
        vendor_archive / f"Vendor_Cost_MTD_{datestr_month}.csv",
        index=False,
    )

    vendor_files = _walk_files(chain_root / "vendor_cost")
    vendor_frames = []
    for path in vendor_files:
        frame = pd.read_csv(path)
        frame["File_Month"] = _month_from_filename(path.name)
        vendor_frames.append(frame)
    vendor_cost = pd.concat(vendor_frames, ignore_index=True)
    vendor_cost = drop_duplicates_appended(
        vendor_cost, "Sprouts vendor cost history"
    )
    vendor_cost.rename(
        columns={
            "RetailerName": "Retailer",
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

    # --- Collate chain store ---
    Sprouts_Chain_Store = (
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
    Sprouts_Chain_Store = pd.merge(Sprouts_Chain_Store, upc_helper, on="UPC", how="left")
    Sprouts_Chain_Store["Ordered_Case_Cost_(Vendor_Cost)"] = np.where(
        Sprouts_Chain_Store["Ordered (Quantity)"] == Sprouts_Chain_Store["Box_per_Case"],
        Sprouts_Chain_Store["Ordered (Vendor Cost)"],
        Sprouts_Chain_Store["Ordered (Vendor Cost)"]
        / (
            Sprouts_Chain_Store["Ordered (Quantity)"]
            / Sprouts_Chain_Store["Box_per_Case"]
        ),
    )
    Sprouts_Chain_Store["Ordered_Case_Cost_(List_Wholesale)"] = np.where(
        Sprouts_Chain_Store["Ordered (Quantity)"] == Sprouts_Chain_Store["Box_per_Case"],
        Sprouts_Chain_Store["Ordered (List Wholesale)"],
        Sprouts_Chain_Store["Ordered (List Wholesale)"]
        / (
            Sprouts_Chain_Store["Ordered (Quantity)"]
            / Sprouts_Chain_Store["Box_per_Case"]
        ),
    )
    Sprouts_Chain_Store["Markup"] = (
        Sprouts_Chain_Store["Ordered_Case_Cost_(List_Wholesale)"]
        - Sprouts_Chain_Store["Ordered_Case_Cost_(Vendor_Cost)"]
    ) / Sprouts_Chain_Store["Ordered_Case_Cost_(Vendor_Cost)"]

    # --- Inventory + inventory at risk ---
    inv_root = sprouts / "Inventory"
    stock_archive = inv_root / "inventory_stock_status"
    risk_archive = inv_root / "inventory_at_risk"
    stock_archive.mkdir(parents=True, exist_ok=True)
    risk_archive.mkdir(parents=True, exist_ok=True)

    Sprouts_inventory = pd.read_csv(inv_root / "Inventory Stock Status.csv")
    Sprouts_inventory["Downloaded_On"] = datestr
    # Filename convention preserved from original script (no underscore before month).
    Sprouts_inventory.to_csv(
        stock_archive / f"inventory_stock_status{datestr_month}.csv",
        index=False,
    )
    Sprouts_inventory = pd.merge(Sprouts_inventory, upc_helper, on="UPC", how="left")

    Sprouts_risk = pd.read_csv(inv_root / "Inventory at Risk.csv")
    Sprouts_risk["Downloaded_On"] = datestr
    Sprouts_risk.to_csv(
        risk_archive / f"inventory_at_risk_{datestr_month}.csv",
        index=False,
    )
    Sprouts_risk = pd.merge(Sprouts_risk, upc_helper, on="UPC", how="left")
    Sprouts_inventory = pd.merge(Sprouts_inventory, Sprouts_risk, how="outer")

    dashboard_path = retail / "Retail-Dashboard_Files/Sprouts-All.xlsx"
    backup_dir = retail / "us/output/Sprouts/Sprouts Database Files"
    dashboard_path.parent.mkdir(parents=True, exist_ok=True)
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"Sprouts-All_filestypes_{datestr}.xlsx"

    # Final sheet-level dedupe on the dashboard workbook (Azure-synced retail root)
    sheets = {
        "Sprout_Chain_Store": drop_duplicates_appended(
            Sprouts_Chain_Store, "sheet Sprout_Chain_Store"
        ),
        "SP-Inventory": drop_duplicates_appended(
            Sprouts_inventory, "sheet SP-Inventory"
        ),
        "SP-Risk_Inventory": drop_duplicates_appended(
            Sprouts_risk, "sheet SP-Risk_Inventory"
        ),
    }
    for out_path in (dashboard_path, backup_path):
        with pd.ExcelWriter(out_path) as writer:
            for sheet_name, frame in sheets.items():
                frame.to_excel(writer, sheet_name=sheet_name, index=False)

    print(f"Sprouts dashboard : {dashboard_path}")
    print(f"Sprouts backup    : {backup_path}")

    azure_frames = {
        "Sprouts_Chain_Store": sheets["Sprout_Chain_Store"],
        "Sprouts_inventory": sheets["SP-Inventory"],
        "Sprouts_risk": sheets["SP-Risk_Inventory"],
    }
    azure_results = sync_datasets_to_azure_csv(
        [
            (name, azure_frames[name], blob_path)
            for name, blob_path in SPROUTS_AZURE_BLOBS.items()
        ],
        skip_azure=skip_azure,
    )

    return {
        "chain_store": sheets["Sprout_Chain_Store"],
        "inventory": sheets["SP-Inventory"],
        "risk": sheets["SP-Risk_Inventory"],
        "dashboard_path": dashboard_path,
        "backup_path": backup_path,
        "azure": azure_results,
    }


def run(
    *,
    client: str = "ESH",
    geos: Optional[Sequence[str]] = None,
    skip_azure: bool = False,
    **_kwargs,
) -> dict:
    """Pipeline CLI entrypoint: run(client='ESH')."""
    del geos
    if str(client).upper() != "ESH":
        print(f"[skip] Sprouts retail script is ESH-only (got client={client})")
        return {}
    print(f"Sprouts retail report (client={client})")
    print(f"Retail root: {cfg_paths.esh_retail_root()}")
    return main(skip_azure=skip_azure)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ESH Sprouts retail combiner")
    parser.add_argument(
        "--skip-azure",
        action="store_true",
        help="Skip Azure CSV upload (local Excel only)",
    )
    args = parser.parse_args()
    run(skip_azure=args.skip_azure)