"""
Convert any JSON file to CSV.

Interactive script (same logic as original):
1) Ask user for JSON file path (or pass --json)
2) Flatten nested dicts/lists into a flat row dictionary
3) Ask user for CSV output path (or pass --csv / default beside JSON)

Run:
  python report_script/utility_codes/c_convert_json_to_csv.py
  python report_script/utility_codes/c_convert_json_to_csv.py --json data.json --csv out.csv
  # or via run_pipeline.py → Stage: utility_codes → Convert JSON to CSV
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config_manager import paths as cfg_paths  # noqa: F401  # loads .env


def _flatten_json(value: Any, parent_key: str = "", sep: str = "_") -> Dict[str, Any]:
    """
    Flatten JSON-like structures (dict/list) into a single-row flat dictionary.

    - dict: recursively expands keys
    - list of dicts: indexes each dict (key_{idx}_...)
    - list of primitives: joins primitives with '; '
    - primitives: kept as-is
    """
    items: Dict[str, Any] = {}

    if isinstance(value, dict):
        for k, v in value.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else str(k)
            items.update(_flatten_json(v, new_key, sep=sep))
        return items

    if isinstance(value, list):
        if all(isinstance(x, dict) for x in value):
            for idx, elem in enumerate(value):
                new_key = f"{parent_key}{sep}{idx}" if parent_key else str(idx)
                items.update(_flatten_json(elem, new_key, sep=sep))
        else:
            # list of primitives (or mixed) => stringify and join
            joined = "; ".join("" if x is None else str(x) for x in value)
            items[parent_key] = joined
        return items

    # primitive
    items[parent_key] = value
    return items


def json_to_csv(json_path: Union[str, Path], csv_path: Union[str, Path]) -> Path:
    json_path = Path(json_path).expanduser().resolve()
    if not json_path.is_file():
        raise FileNotFoundError(f"JSON file not found: {json_path}")

    # Read JSON
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Normalize to list of records
    if isinstance(data, list):
        records = data
    else:
        records = [data]

    flattened_rows: List[Dict[str, Any]] = []
    for record in records:
        if isinstance(record, dict):
            flattened_rows.append(_flatten_json(record))
        else:
            # If record is not a dict, store it under a generic key
            flattened_rows.append({"value": record})

    df = pd.DataFrame(flattened_rows)

    csv_path = Path(csv_path).expanduser().resolve()
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    return csv_path


def process_json_to_csv(
    *,
    json_path: Optional[Union[str, Path]] = None,
    csv_path: Optional[Union[str, Path]] = None,
    interactive: bool = True,
) -> Path:
    if json_path is None and interactive:
        print("JSON -> CSV Converter")
        print("---------------------")
        json_path = input("Enter JSON file location: ").strip().strip('"').strip("'")
    if not json_path:
        raise SystemExit("No JSON file path provided.")

    json_path_obj = Path(json_path).expanduser().resolve()
    default_csv = json_path_obj.with_suffix(".csv")

    if csv_path is None and interactive:
        out_path = input(
            f"Enter CSV save location (Enter for default: {default_csv}): "
        ).strip().strip('"').strip("'")
        csv_path = out_path or str(default_csv)
    elif csv_path is None:
        csv_path = str(default_csv)

    result = json_to_csv(json_path_obj, csv_path)
    print(f"CSV saved to: {result}")
    print("   Rows exported: (records)")
    return result


def run(*, client: str = "ESH", geos=None, **_kwargs) -> Path:
    """Pipeline entry — interactive prompts (client/geos unused)."""
    _ = (client, geos)
    return process_json_to_csv(interactive=True)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Convert JSON file to CSV")
    p.add_argument("--json", default="", help="Input JSON path")
    p.add_argument("--csv", default="", help="Output CSV path (default: beside JSON)")
    return p.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> Path:
    args = parse_args(argv)
    json_path = str(args.json).strip() or None
    csv_path = str(args.csv).strip() or None
    interactive = json_path is None
    return process_json_to_csv(
        json_path=json_path,
        csv_path=csv_path,
        interactive=interactive,
    )


from config_manager.report_helpers import print_script_completed

if __name__ == "__main__":
    main()
    print_script_completed('c_convert_json_to_csv')
