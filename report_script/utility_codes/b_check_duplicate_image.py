"""
Export unique image basenames from a folder to CSV.

Original behavior: list image files in a folder, strip extensions, dedupe/sort,
write a one-column CSV (`image_name`).

Run knobs (edit here) or CLI:
  FOLDER_PATH / --folder
  OUTPUT_CSV / --output

Run:
  python report_script/utility_codes/b_check_duplicate_image.py
  python report_script/utility_codes/b_check_duplicate_image.py --folder "D:/imgs" --output image_list.csv
  # or via run_pipeline.py → Stage: utility_codes → Export image names
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path
from typing import List, Optional, Sequence

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config_manager import paths as cfg_paths  # noqa: F401  # loads .env

# ---------------------------------------------------------------------------
# Run knobs (edit here, or override via CLI / env)
# ---------------------------------------------------------------------------

FOLDER_PATH = os.getenv(
    "UTILITY_IMAGE_FOLDER",
    r"C:\Users\Shivank Rajput\Downloads\Primary\Primary_converted",
).strip()
OUTPUT_CSV = os.getenv("UTILITY_IMAGE_OUTPUT", "image_list.csv").strip() or "image_list.csv"

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"}


def export_image_names(folder: str | Path, output_csv: str | Path = OUTPUT_CSV) -> Path:
    folder_path = Path(folder).expanduser().resolve()
    if not folder_path.is_dir():
        raise FileNotFoundError(f"Folder not found: {folder_path}")

    image_names: List[str] = []

    for filename in os.listdir(folder_path):
        file_path = folder_path / filename

        if file_path.is_file():
            name, ext = os.path.splitext(filename)
            if ext.lower() in IMAGE_EXTENSIONS:
                image_names.append(name)  # without extension

    # Optional: remove duplicates & sort
    image_names = sorted(set(image_names))

    out_path = Path(output_csv).expanduser()
    if not out_path.is_absolute():
        out_path = (Path.cwd() / out_path).resolve()
    else:
        out_path = out_path.resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Write to CSV
    with open(out_path, mode="w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["image_name"])  # header

        for name in image_names:
            writer.writerow([name])

    print(f"CSV created: {out_path}")
    print(f"Total unique image names: {len(image_names)}")
    return out_path


def run(*, client: str = "ESH", geos=None, **_kwargs) -> Path:
    """Pipeline entry — uses run knobs / env (client/geos unused)."""
    _ = (client, geos)
    return export_image_names(FOLDER_PATH, OUTPUT_CSV)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Export unique image basenames to CSV")
    p.add_argument("--folder", default="", help="Folder containing images")
    p.add_argument("--output", default="", help="Output CSV path (default: image_list.csv)")
    return p.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> Path:
    args = parse_args(argv)
    folder = str(args.folder).strip() or FOLDER_PATH
    output = str(args.output).strip() or OUTPUT_CSV
    if not folder:
        print("Enter image folder path:")
        folder = input("> ").strip().strip('"').strip("'")
    if not folder:
        raise SystemExit("No folder path provided.")
    return export_image_names(folder, output)


if __name__ == "__main__":
    main()
