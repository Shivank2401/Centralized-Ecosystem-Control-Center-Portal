"""
ESH COGS export — Excel sheets -> Azure only.

Source workbook: ESH_COGS_PATH (.env) via layouts.cogs_path("ESH").

Azure (container app-helper):
  thrive-client-ecosoulhome/cogs/{country}_{channel}_cogs.{parquet,csv}

Local project copies are pulled separately via:
  report_script/supply_chain/d_download_cogs.py

Run:
  python report_script/want_to_update/esh_cogs.py
  python report_script/want_to_update/esh_cogs.py --geos UK,US
  # or via run_pipeline.py -> Stage: want_to_update -> ESH COGS
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config_manager import layouts
from config_manager.loader import get_client
from report_script.want_to_update import cogs_io

CLIENT = "ESH"
AZURE_BLOB_PREFIX = cogs_io.CLIENT_AZURE_PREFIX[CLIENT]

SELECT_COLUMNS = [
    "client_id",
    "country",
    "channel",
    "ASIN",
    "Product CoGS",
    "Product Name",
    "Amazon Selling Price",
    "Type",
    "SKU",
    "ON_1",
    "ON_2",
    "ON_3",
    "ON_4",
    "ON_5",
    "Material",
    "Product_Category",
    "Product_Sub_Category",
    "Product_Type",
]

# parquet stem vs Azure CSV stem (USA csv stays usa_amazon_cogs.csv).
SHEET_SPECS: List[Dict[str, str]] = [
    {"country": "UK", "sheet": "ESH-UK", "file_stem": "uk_amazon", "csv_stem": "uk_amazon"},
    {"country": "CA", "sheet": "ESH-CA", "file_stem": "ca_amazon", "csv_stem": "ca_amazon"},
    {"country": "US", "sheet": "ESH-USA", "file_stem": "us_amazon", "csv_stem": "usa_amazon"},
    {"country": "AE", "sheet": "ESH-UAE", "file_stem": "ae_amazon", "csv_stem": "ae_amazon"},
    {"country": "IN", "sheet": "ESH-IN", "file_stem": "in_amazon", "csv_stem": "in_amazon"},
    {"country": "DE", "sheet": "ESH-DE", "file_stem": "de_amazon", "csv_stem": "de_amazon"},
]


def _normalize_geos(geos: Optional[Sequence[str]]) -> Optional[set[str]]:
    if geos is None:
        return None
    cleaned = {str(g).strip().upper() for g in geos if str(g).strip()}
    return cleaned or None


def _selected_specs(geos: Optional[Sequence[str]]) -> List[Dict[str, str]]:
    wanted = _normalize_geos(geos)
    if wanted is None:
        return list(SHEET_SPECS)
    selected = [s for s in SHEET_SPECS if s["country"] in wanted]
    if not selected:
        raise ValueError(
            f"No ESH COGS sheets for geos={sorted(wanted)}. "
            f"Known: {[s['country'] for s in SHEET_SPECS]}"
        )
    return selected


def process_cogs(
    *,
    geos: Optional[Sequence[str]] = None,
    cogs_path: Optional[Path] = None,
) -> Dict[str, pd.DataFrame]:
    path = Path(cogs_path) if cogs_path is not None else layouts.cogs_path(CLIENT)
    if not path.exists():
        raise FileNotFoundError(f"ESH COGS workbook not found: {path}")

    client_id = get_client(CLIENT).client_id
    specs = _selected_specs(geos)
    print(f"\nESH COGS -> Azure <- {path}")
    print(f"  Geos: {[s['country'] for s in specs]}")

    tables: Dict[str, pd.DataFrame] = {}
    for spec in specs:
        df = cogs_io.load_sheet(
            path,
            spec["sheet"],
            country=spec["country"],
            channel="amazon",
            client_id=client_id,
            columns=SELECT_COLUMNS,
        )
        key = f"{spec['file_stem']}_cogs"
        tables[key] = df

        cogs_io.upload_to_azure_parquet(
            df, f"{AZURE_BLOB_PREFIX}/{spec['file_stem']}_cogs.parquet"
        )
        cogs_io.upload_to_azure_csv(
            df, f"{AZURE_BLOB_PREFIX}/{spec['csv_stem']}_cogs.csv"
        )

    print(f"\nESH COGS Azure upload done — {len(tables)} slice(s).")
    return tables


def run(
    *,
    client: str = CLIENT,
    geos: Optional[Sequence[str]] = None,
    **_kwargs,
) -> Dict[str, pd.DataFrame]:
    if str(client).upper() != CLIENT:
        raise ValueError(f"esh_cogs.run only supports client={CLIENT}, got {client!r}")
    return process_cogs(geos=geos)


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="ESH COGS -> Azure")
    p.add_argument("--geos", default="", help="Comma-separated geos, e.g. UK,US,DE")
    p.add_argument("--cogs-path", default="", help="Override ESH_COGS_PATH workbook")
    return p.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> Dict[str, pd.DataFrame]:
    args = _parse_args(argv)
    geos = [g.strip() for g in str(args.geos).split(",") if g.strip()] or None
    cogs = Path(args.cogs_path) if str(args.cogs_path).strip() else None
    return process_cogs(geos=geos, cogs_path=cogs)


from config_manager.report_helpers import print_script_completed

if __name__ == "__main__":
    main()
    print_script_completed('esh_cogs')
