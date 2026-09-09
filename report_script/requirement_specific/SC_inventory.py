"""
ESH Inventory Supply Chain (instock) — USA platforms + Amazon sanity snapshots.

Covers:
  - Client: ESH — Shipbob, Walmart, Shipcube/Tradefull, AWD, 3G, Updike
  - Amazon manage_fba + reserved from sanity_data/ESH for US, CA, DE, AE, UK, IN
  - USA platform temp xlsx: us/output/USA Platform temp files/{YYYY}/{Mon}/USA_Platform_{T-1}.xlsx
  - SKU clean via ESH-Item_master / esh_sku_cleaning; paths from .env

Returns in-memory frames (USA_Platform, manage_fba/reserved by geo); not a full Azure export.

Run:
    python report_script/requirement_specific/SC_inventory.py
    python report_script/requirement_specific/SC_inventory.py --client ESH
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Sequence, Tuple

import numpy as np
import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config_manager import layouts
from config_manager import paths as cfg_paths
from config_manager.esh_sku_cleaning import (
    clean_sku_column,
    clean_warehouse_sku_column,
    mapping_from_convertor_helper,
)
from config_manager.report_helpers import coalesce_snake_columns
from config_manager.report_helpers import print_script_completed

ESH_ITEM_MASTER_SHEET = "ESH-Item_master"
HELPER_COLS = ["sku", "on_1", "on_2", "on_3", "on_4", "on_5"]
CONVERTOR_ATTR_COLS = [
    "sku",
    "material",
    "product_category",
    "channel",
    "product_sub_category",
    "product_type",
    "units_per_set",
    "box_case",
]


def _snake_df(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize headers to snake_case (BOM-safe; coalesce duplicate names)."""
    return coalesce_snake_columns(df)


def _ensure_box_case(df: pd.DataFrame) -> pd.DataFrame:
    """Alias case_pack_qty → box_case when item-master / WH sheets use the former."""
    out = df
    if "box_case" not in out.columns and "case_pack_qty" in out.columns:
        out = out.rename(columns={"case_pack_qty": "box_case"})
    return out


def _load_esh_item_master() -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    """
    Load ESH item master from ESH_COGS_PATH sheet ``ESH-Item_master``.

    Returns convertor_main, convertor_helper (sku+on_*), convertor (attrs), sku_mapping.
    All frames use snake_case columns.
    """
    path = layouts.cogs_path("ESH")
    convertor_main = _ensure_box_case(_snake_df(pd.read_excel(path, sheet_name=ESH_ITEM_MASTER_SHEET)))

    missing_helper = [c for c in HELPER_COLS if c not in convertor_main.columns]
    if missing_helper:
        raise KeyError(
            f"ESH-Item_master missing columns {missing_helper} in {path} "
            f"(have: {list(convertor_main.columns)[:20]}…)"
        )

    convertor_helper = convertor_main.loc[:, HELPER_COLS]
    convertor_helper = convertor_helper[convertor_helper["sku"] != 0]

    attr_cols = [c for c in CONVERTOR_ATTR_COLS if c in convertor_main.columns]
    convertor = convertor_main.loc[:, attr_cols].copy()
    if "main_wac" in convertor.columns:
        convertor["main_wac"] = convertor["main_wac"].fillna(1)
    if "box_case" in convertor.columns:
        convertor["box_case"] = convertor["box_case"].fillna(1)

    sku_mapping = mapping_from_convertor_helper(convertor_helper)
    print(f"[ESH] Item master loaded from {path.name} / {ESH_ITEM_MASTER_SHEET}")
    return convertor_main, convertor_helper, convertor, sku_mapping


def _wh_database_path(inv: Path, brand: str, datestr: str) -> Path:
    """
    ``Output_Database/USA/{3G|Updike}/{YYYY}/{Mon-YYYY}/{brand}_WH_Database_{datestr}.xlsx``
    """
    year = datetime.now().strftime("%Y")
    month_folder = datetime.now().strftime("%b-%Y")
    folder_name = "3G" if brand == "3G" else "Updike"
    file_name = f"{brand}_WH_Database_{datestr}.xlsx"
    path = inv / "Output_Database" / "USA" / folder_name / year / month_folder / file_name
    if path.is_file():
        return path
    parent = inv / "Output_Database" / "USA" / folder_name / year
    if parent.is_dir():
        wanted = month_folder.lower()
        for child in parent.iterdir():
            if child.is_dir() and child.name.lower() == wanted:
                candidate = child / file_name
                if candidate.is_file():
                    return candidate
    raise FileNotFoundError(f"Missing warehouse DB: {path}")


def _sanity_geo_parquet(sanity_esh: Path, report: str, geo: str, suffix: str) -> Path:
    path = sanity_esh / report / f"{geo}_{suffix}.parquet"
    if not path.is_file():
        raise FileNotFoundError(f"Missing sanity parquet: {path}")
    return path


def _latest_snapshot(df: pd.DataFrame, *, label: str) -> pd.DataFrame:
    today = pd.Timestamp.today().strftime("%Y-%m-%d")
    yesterday = (pd.Timestamp.today() - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    if "date" not in df.columns:
        raise KeyError(f"[{label}] expected date column (have: {list(df.columns)[:12]})")
    dates = df["date"].astype(str)
    if (dates == today).any():
        selected = today
    elif (dates == yesterday).any():
        selected = yesterday
    else:
        selected = dates.max()
        print(f"[{label}] WARN: no today/yesterday — using latest date {selected}")
    out = df.loc[dates == selected].copy()
    print(f"[{label}] Selected Date: {selected} | Rows: {len(out):,}")
    return out


def run(*, client: str = "ESH", geos: Optional[Sequence[str]] = None, **_kwargs):
    """Pipeline entrypoint: ESH-only inventory supply-chain / instock build."""
    _ = geos
    if str(client).strip().upper() != "ESH":
        print(f"[skip] Inventory Supply Chain is ESH-only (got {client})")
        return None
    return _build_inventory_supply_chain()


def _build_inventory_supply_chain():
    inv = cfg_paths.esh_inventory_root()
    sanity_esh = cfg_paths.sanity_data_root() / "ESH"

    datestr_1 = (pd.to_datetime("today") - timedelta(1)).strftime("%d-%b-%Y")
    date_col = pd.to_datetime("today").strftime("%Y-%m-%d")
    _ = date_col

    _, convertor_helper, convertor, sku_mapping = _load_esh_item_master()

    # --- Source files under ESH_DATA_ROOT (all snake_case headers) ---
    walmart = _snake_df(pd.read_excel(inv / "us/input/walmart/walmart_inventory/Inventory.xlsx"))
    tradefull = _snake_df(pd.read_excel(inv / "us/input/tradefull/InventoryReport/tradefull.xlsx"))
    _ = tradefull

    ThreeG_invnto = _ensure_box_case(
        _snake_df(
            pd.read_excel(
                _wh_database_path(inv, "3G", datestr_1),
                sheet_name="3G-Inventory",
            )
        )
    )
    if "box_case" in ThreeG_invnto.columns:
        ThreeG_invnto["box_case"] = ThreeG_invnto["box_case"].fillna(1)

    updike_invnto = _ensure_box_case(
        _snake_df(
            pd.read_excel(
                _wh_database_path(inv, "Updike", datestr_1),
                sheet_name="Updk-Inveto",
            )
        )
    )

    awd_invnto = _snake_df(
        pd.read_csv(
            inv / "us/input/amazon/awd_inventory_report/AWD-inventory-report.csv",
            encoding="latin1",
            skiprows=3,
        )
    )

    shipbob = _snake_df(pd.read_csv(inv / "us/input/shipbob/inventory_status/inventory_status.csv"))
    shipbob = shipbob[~shipbob["sku"].astype(str).str.contains("sample", case=False, na=False)]
    skus_to_remove = [
        "BTP3P300P08CASE6",
        "BTP3P300P12CASE4",
        "BTP3P300P4CASE6",
        "BTP3P300P12",
        "BTP3P300P12AMZ",
        "BTP3P300P24",
        "BTP3P300P24AMZ",
        "BTP3P300P36",
        "BTP3P300P36AMZ",
    ]
    shipbob = shipbob[~shipbob["sku"].isin(skus_to_remove)]

    Easy_inventory = _snake_df(
        pd.read_csv(inv / "india/input/easy_ecom/inventory/easy_inventory.csv")
    )
    Flip_invet = _snake_df(
        pd.read_excel(
            inv / "india/input/flipkart/my_listing/flipkart_inventory.xls",
            engine="xlrd",
        )
    )
    Amala_inventory = _snake_df(
        pd.read_csv(inv / "india/input/amala_earth/inventory/amalaearth_inventory.csv")
    )
    _ = (Easy_inventory, Flip_invet, Amala_inventory)

    item = _snake_df(pd.read_excel(inv / "dashboard_essential_files/ShipID.xlsx"))
    _ = item

    # --- Shipbob / Shipcube ---
    shipbob = shipbob.loc[:, ["name", "sku", "on_hand", "allocated", "warehouse"]]
    shipbob = shipbob.rename(
        columns={
            "allocated": "reserved",
            "warehouse": "fulfillment_center",
        }
    )
    shipbob["sellable"] = shipbob["on_hand"] - shipbob["reserved"]
    shipbob["sku"] = np.where(
        shipbob["sku"] == "32OZ Soup Bowl Lid Set of 300",
        "CBFL32OZ300",
        shipbob["sku"],
    )
    shipbob = shipbob.astype(
        {"sellable": "float", "on_hand": "float", "reserved": "float"}
    )

    shipbob["sku"] = shipbob.apply(
        lambda row: (
            str(row["sku"]) + "WL"
            if "(Walmart)" in str(row["name"]) and "WL" not in str(row["sku"])
            else row["sku"]
        ),
        axis=1,
    )
    shipbob["sku"] = shipbob["sku"].replace(
        {
            "BTP3P300P04": "BTP3P300P4",
            "BTP3P300P08": "BTP3P300P8",
            "BTP3P300P12NEW": "BTP3P300P12",
        }
    )
    shipbob = clean_warehouse_sku_column(
        shipbob, sku_column="sku", sku_mapping=sku_mapping
    )

    shipbob = shipbob.drop(shipbob[shipbob["fulfillment_center"].isnull()].index)
    shipbob["location"] = np.where(
        shipbob["fulfillment_center"] == "ShipCube", "East", "West"
    )
    Shipbob_inventory = (
        pd.pivot_table(
            shipbob,
            index=["sku", "location"],
            values=["on_hand", "reserved", "sellable"],
            aggfunc="sum",
        )
        .reset_index()
    )
    Shipbob_inventory["date"] = datestr_1
    Shipbob_inventory["platform"] = np.where(
        Shipbob_inventory.location == "East", "Shipcube-East", "Shipcube-West"
    )
    Shipbob_inventory = pd.merge(Shipbob_inventory, convertor, on="sku", how="left")

    trade_cols = [
        "sku",
        "location",
        "on_hand",
        "reserved",
        "sellable",
        "date",
        "platform",
        "material",
        "product_category",
        "product_sub_category",
        "product_type",
        "units_per_set",
        "box_case",
        "main_wac",
    ]
    trade_cols = [c for c in trade_cols if c in Shipbob_inventory.columns]
    trade = Shipbob_inventory.loc[
        Shipbob_inventory["location"] == "West", trade_cols
    ].copy()
    trade["date"] = datestr_1
    trade["platform"] = "Shipcube-West"

    # --- Walmart ---
    walmart = walmart.rename(
        columns={"available_to_sell": "sellable", "reservations": "reserved"}
    )
    walmart = clean_warehouse_sku_column(
        walmart, sku_column="sku", sku_mapping=sku_mapping
    )
    walmart["on_hand"] = walmart["available_units"] + walmart["reserved_units"]
    walmart = (
        pd.pivot_table(
            walmart,
            index=["sku"],
            values=["on_hand", "available_units", "reserved_units", "inbound_units"],
            aggfunc="sum",
        )
        .reset_index()
    )
    walmart["date"] = datestr_1
    walmart["platform"] = "Walmart"
    walmart_invnto = walmart.loc[
        :,
        [
            "date",
            "sku",
            "on_hand",
            "available_units",
            "reserved_units",
            "inbound_units",
            "platform",
        ],
    ]
    walmart_invnto = pd.merge(walmart_invnto, convertor, on="sku", how="left")
    walmart_invnto = walmart_invnto.rename(
        columns={
            "available_units": "sellable",
            "reserved_units": "reserved",
            "inbound_units": "total_incoming",
        }
    )

    # --- AWD (Amazon-style SKU clean, same as common sanity) ---
    awd_invnto = awd_invnto.loc[
        :, ["sku", "available_in_awd_units", "reserved_in_awd_units"]
    ].copy()
    awd_invnto["platform"] = "AWD-Units"
    awd_invnto = clean_sku_column(
        awd_invnto, sku_column="sku", sku_mapping=sku_mapping, drop_missing=True
    )
    awd_invnto["sellable"] = (
        awd_invnto["available_in_awd_units"] + awd_invnto["reserved_in_awd_units"]
    )

    # --- Save USA platform temp workbook ---
    current_month_year = datetime.now().strftime("%b-%Y")
    year = datetime.now().strftime("%Y")
    out_dir = inv / "us" / "output" / "USA Platform temp files" / year / current_month_year
    out_dir.mkdir(parents=True, exist_ok=True)
    file_path = out_dir / f"USA_Platform_{datestr_1}.xlsx"
    with pd.ExcelWriter(file_path) as writer:
        Shipbob_inventory.to_excel(writer, sheet_name="shipbob_inventory", index=False)
        walmart_invnto.to_excel(writer, sheet_name="walmart_invntory", index=False)
        trade.to_excel(writer, sheet_name="Shipcube-West", index=False)
        awd_invnto.to_excel(writer, sheet_name="AWD_Inventory", index=False)
    print(f"[ESH] Wrote USA platform temp: {file_path}")

    # --- 3G / Updike stock slices ---
    ThreeG_stock = ThreeG_invnto.loc[
        :, ["sku", "3g_on_hand", "3g_committed", "3g_fulfillable", "date", "box_case"]
    ].copy()
    ThreeG_stock["sellable"] = (
        ThreeG_stock["3g_fulfillable"] * ThreeG_stock["box_case"]
    )
    ThreeG_stock = ThreeG_stock.rename(
        columns={"3g_committed": "reserved", "3g_on_hand": "on_hand"}
    )
    ThreeG_stock["platform"] = "3G"

    Updike_stock = updike_invnto.loc[
        :,
        [
            "sku",
            "updike_on_hand",
            "updike_comitted",
            "updike_sellable",
            "date",
            "box_case",
        ],
    ].copy()
    Updike_stock = Updike_stock.astype(
        {"box_case": "float", "updike_sellable": "float"}
    )
    Updike_stock["sellable"] = (
        Updike_stock["updike_sellable"] * Updike_stock["box_case"]
    )
    Updike_stock = Updike_stock.rename(
        columns={"updike_comitted": "reserved", "updike_on_hand": "on_hand"}
    )
    Updike_stock["platform"] = "Updike"

    Shipbob_east = Shipbob_inventory.loc[Shipbob_inventory["location"] == "East"]
    USA_Platform = pd.concat(
        [Shipbob_east, trade, walmart_invnto, ThreeG_stock, Updike_stock, awd_invnto],
        axis=0,
    )
    keep_cols = [
        "sku",
        "on_hand",
        "reserved",
        "sellable",
        "total_incoming",
        "date",
        "platform",
    ]
    USA_Platform = USA_Platform.loc[
        :, [c for c in keep_cols if c in USA_Platform.columns]
    ]
    num_cols = USA_Platform.select_dtypes(include="number").columns
    USA_Platform[num_cols] = USA_Platform[num_cols].fillna(0)

    # --- Amazon manage_fba + reserved from sanity_data (already SKU-cleaned) ---
    manage_by_geo = {}
    reserved_by_geo = {}
    for geo, label in [
        ("US", "USA"),
        ("CA", "CA"),
        ("DE", "DE"),
        ("AE", "AE"),
        ("UK", "UK"),
        ("IN", "India"),
    ]:
        manage_by_geo[geo] = _latest_snapshot(
            _snake_df(
                pd.read_parquet(
                    _sanity_geo_parquet(
                        sanity_esh, "manage_fba", geo, "manage_fba_inventory"
                    )
                )
            ),
            label=f"{label} manage_fba",
        )
        reserved_by_geo[geo] = _latest_snapshot(
            _snake_df(
                pd.read_parquet(
                    _sanity_geo_parquet(
                        sanity_esh, "reserved", geo, "reserved_inventory"
                    )
                )
            ),
            label=f"{label} reserved",
        )

    return {
        "convertor_helper": convertor_helper,
        "convertor": convertor,
        "USA_Platform": USA_Platform,
        "manage_fba": manage_by_geo,
        "reserved": reserved_by_geo,
        "usa_platform_xlsx": file_path,
    }


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="ESH Inventory Supply Chain (instock)")
    parser.add_argument("--client", default="ESH")
    args = parser.parse_args(argv)
    run(client=args.client)


if __name__ == "__main__":
    main()
    print_script_completed('SC_inventory')
