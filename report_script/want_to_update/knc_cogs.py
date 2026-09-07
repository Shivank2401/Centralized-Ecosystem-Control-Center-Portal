"""
KNC COGS export — Excel sheets -> Azure only.

Source workbook: KNC_COGS_PATH (.env) via layouts.cogs_path("KNC").

Azure (container app-helper):
  thrive-client-kinetica/cogs/{country}_{channel}_cogs.{parquet,csv}

Sheets:
  Main         -> UK amazon
  Shopify      -> UK shopify (+ IE shopify, same sheet)
  Germany-COGS -> DE amazon
  KCA-AE       -> AE amazon

IE Shopify is included when UK is selected (or geos omitted).

Local project copies are pulled separately via:
  report_script/supply_chain/d_download_cogs.py

Run:
  python report_script/want_to_update/knc_cogs.py
  python report_script/want_to_update/knc_cogs.py --geos UK,DE
  # or via run_pipeline.py -> Stage: want_to_update -> KNC COGS
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

CLIENT = "KNC"
AZURE_BLOB_PREFIX = cogs_io.CLIENT_AZURE_PREFIX[CLIENT]

SELECT_COLUMNS = [
    "client_id",
    "country",
    "channel",
    "ASIN",
    "Product Category",
    "Product CoGS",
    "Product Name",
    "Amazon Selling Price",
    "Type",
    "SKU",
    "ON_1",
    "ON_2",
    "ON_3",
]

SHEET_SPECS: List[Dict[str, str]] = [
    {
        "country": "UK",
        "channel": "amazon",
        "sheet": "Main",
        "file_stem": "uk_amazon",
        "geo_gate": "UK",
    },
    {
        "country": "UK",
        "channel": "shopify",
        "sheet": "Shopify",
        "file_stem": "uk_shopify",
        "geo_gate": "UK",
    },
    {
        "country": "DE",
        "channel": "amazon",
        "sheet": "Germany-COGS",
        "file_stem": "de_amazon",
        "geo_gate": "DE",
    },
    {
        "country": "AE",
        "channel": "amazon",
        "sheet": "KCA-AE",
        "file_stem": "ae_amazon",
        "geo_gate": "AE",
    },
    {
        "country": "IE",
        "channel": "shopify",
        "sheet": "Shopify",
        "file_stem": "ie_shopify",
        "geo_gate": "UK",
    },
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
    selected = [
        s
        for s in SHEET_SPECS
        if s["geo_gate"] in wanted or s["country"] in wanted
    ]
    if not selected:
        raise ValueError(
            f"No KNC COGS sheets for geos={sorted(wanted)}. "
            f"Known gates: UK, DE, AE (IE via UK)."
        )
    return selected


def process_cogs(
    *,
    geos: Optional[Sequence[str]] = None,
    cogs_path: Optional[Path] = None,
) -> Dict[str, pd.DataFrame]:
    path = Path(cogs_path) if cogs_path is not None else layouts.cogs_path(CLIENT)
    if not path.exists():
        raise FileNotFoundError(f"KNC COGS workbook not found: {path}")

    client_id = get_client(CLIENT).client_id
    specs = _selected_specs(geos)
    print(f"\nKNC COGS -> Azure <- {path}")
    print(
        "  Slices: "
        + ", ".join(f"{s['country']}/{s['channel']}" for s in specs)
    )

    tables: Dict[str, pd.DataFrame] = {}
    for spec in specs:
        df = cogs_io.load_sheet(
            path,
            spec["sheet"],
            country=spec["country"],
            channel=spec["channel"],
            client_id=client_id,
            columns=SELECT_COLUMNS,
        )
        key = f"{spec['file_stem']}_cogs"
        tables[key] = df

        stem = spec["file_stem"]
        cogs_io.upload_to_azure_parquet(
            df, f"{AZURE_BLOB_PREFIX}/{stem}_cogs.parquet"
        )
        cogs_io.upload_to_azure_csv(
            df, f"{AZURE_BLOB_PREFIX}/{stem}_cogs.csv"
        )

    print(f"\nKNC COGS Azure upload done — {len(tables)} slice(s).")
    return tables


def run(
    *,
    client: str = CLIENT,
    geos: Optional[Sequence[str]] = None,
    **_kwargs,
) -> Dict[str, pd.DataFrame]:
    if str(client).upper() != CLIENT:
        raise ValueError(f"knc_cogs.run only supports client={CLIENT}, got {client!r}")
    return process_cogs(geos=geos)


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="KNC COGS -> Azure")
    p.add_argument("--geos", default="", help="Comma-separated geos, e.g. UK,DE,AE")
    p.add_argument("--cogs-path", default="", help="Override KNC_COGS_PATH workbook")
    return p.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> Dict[str, pd.DataFrame]:
    args = _parse_args(argv)
    geos = [g.strip() for g in str(args.geos).split(",") if g.strip()] or None
    cogs = Path(args.cogs_path) if str(args.cogs_path).strip() else None
    return process_cogs(geos=geos, cogs_path=cogs)


if __name__ == "__main__":
    main()
