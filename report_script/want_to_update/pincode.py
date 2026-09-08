"""
Pincode master export — Excel (+ AE city map) -> local CSV + Azure.

Source workbook: ESH_PINCODE_PATH or
  {ESH_DATA_ROOT}/dashboard_essential_files/pincode.xlsx

Local output:
  {project_root}/pincode/{cc}_amazon_pincode.csv

Azure (container app-helper):
  pincode/{cc}_amazon_pincode.csv

Geos: US, CA, DE, UK, IN, AE, IE
AE is a hardcoded ship-city map (same as original notebook).
Pipeline run() always exports every geo (ignores selected client geos).
CLI `--geos` still filters when running the script directly.

Run:
  python report_script/want_to_update/pincode.py
  python report_script/want_to_update/pincode.py --geos UK,US --skip-azure
  # or via run_pipeline.py -> Stage: want_to_update -> Pincode
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

from config_manager import paths as cfg_paths
from report_script.want_to_update import cogs_io

AZURE_BLOB_PREFIX = "pincode"
PROJECTION_COLUMNS = ["Pincode", "City", "State", "Country"]

# geo -> excel sheet (None = hardcoded AE frame)
SHEET_SPECS: List[Dict[str, Optional[str]]] = [
    {"geo": "US", "sheet": "USA", "file": "us_amazon_pincode.csv"},
    {"geo": "CA", "sheet": "Canada", "file": "ca_amazon_pincode.csv"},
    {"geo": "DE", "sheet": "Germany", "file": "de_amazon_pincode.csv"},
    {"geo": "UK", "sheet": "UK", "file": "uk_amazon_pincode.csv"},
    {"geo": "IN", "sheet": "India", "file": "in_amazon_pincode.csv"},
    {"geo": "AE", "sheet": None, "file": "ae_amazon_pincode.csv"},
    {"geo": "IE", "sheet": "Ireland", "file": "ie_amazon_pincode.csv"},
]


def _ae_city_map() -> pd.DataFrame:
    """Hardcoded UAE / GCC ship-city -> City/State (from original notebook)."""
    data = {
        "ship-city": [
            "Dubai",
            "Abu Dhabi",
            "Sharjah",
            "Al Ain",
            "Ajman",
            "Ras Al Khaimah",
            "Fujairah",
            "Umm Al Quwain",
            "Kalba",
            "Madinat Zayed",
            "Khor Fakkan",
            "Dibba Al-Fujairah",
            "Ruwais",
            "Ghayathi",
            "Dhaid",
            "Jebel Ali",
            "Liwa Oasis",
            "Hatta",
            "Ar-Rams",
            "Dibba Al-Hisn",
            "Al Jazirah Al Hamra",
            "دبي",
            "رأس الخيمة",
            "أبوظبي",
            "عجمان",
            "العين",
            "الشارقة",
            "الفجيرة",
            "Not Available",
            "Muscat",
            "Kuwait",
            "Manama",
            "west riffa",
            "AlAnsab",
            "Al janabiyah",
            "Jeddah",
            "Diyar AlMuharraq",
            "Bowsher",
            "Al Seeb",
            "dubai",
            "Alkhoud",
            "Qurum",
            "Riyadh",
        ],
        "City": [
            "Dubai",
            "Abu Dhabi",
            "Sharjah",
            "Al Ain",
            "Ajman",
            "Ras Al Khaimah",
            "Fujairah",
            "Umm Al Quwain",
            "Kalba",
            "Madinat Zayed",
            "Khor Fakkan",
            "Dibba Al-Fujairah",
            "Ruwais",
            "Ghayathi",
            "Dhaid",
            "Jebel Ali",
            "Liwa Oasis",
            "Hatta",
            "Ar-Rams",
            "Dibba Al-Hisn",
            "Al Jazirah Al Hamra",
            "Dubai",
            "Ras Al Khaimah",
            "Abu Dhabi",
            "Ajman",
            "Al Ain",
            "Sharjah",
            "Fujairah",
            "Not Available",
            "Muscat",
            "Kuwait",
            "Manama",
            "West Riffa",
            "Muscat",
            "Janabiyah",
            "Jeddah",
            "Manama",
            "Muscat",
            "Dubai",
            "Dubai",
            "Al Garhoud",
            "Muscat",
            "Riyadh",
        ],
        "State": [
            "Dubai",
            "Abu Dhabi",
            "Sharjah",
            "Abu Dhabi",
            "Ajman",
            "Ras Al Khaimah",
            "Fujairah",
            "Umm al-Quwain",
            "Sharjah",
            "Abu Dhabi",
            "Sharjah",
            "Fujairah",
            "Abu Dhabi",
            "Abu Dhabi",
            "Sharjah",
            "Dubai",
            "Abu Dhabi",
            "Dubai",
            "Ras Al Khaimah",
            "Sharjah",
            "Ras Al Khaimah",
            "Dubai",
            "Ras Al Khaimah",
            "Abu Dhabi",
            "Ajman",
            "Abu Dhabi",
            "Sharjah",
            "Fujairah",
            "Not Available",
            "Oman",
            "Kuwait",
            "Ajman",
            "Bahrain",
            "Oman",
            "Bahrain",
            "Saudi Arabia",
            "Bahrain",
            "Oman",
            "Dubai",
            "Dubai",
            "Dubai",
            "Oman",
            "Abu Dhabi",
        ],
    }
    return pd.DataFrame(data)


def _normalize_geos(geos: Optional[Sequence[str]]) -> Optional[set[str]]:
    if geos is None:
        return None
    cleaned = {str(g).strip().upper() for g in geos if str(g).strip()}
    return cleaned or None


def _selected_specs(geos: Optional[Sequence[str]]) -> List[Dict[str, Optional[str]]]:
    wanted = _normalize_geos(geos)
    if wanted is None:
        return list(SHEET_SPECS)
    selected = [s for s in SHEET_SPECS if str(s["geo"]).upper() in wanted]
    if not selected:
        raise ValueError(
            f"No pincode sheets for geos={sorted(wanted)}. "
            f"Known: {[s['geo'] for s in SHEET_SPECS]}"
        )
    return selected


def _load_geo_frame(xlsx: Path, spec: Dict[str, Optional[str]]) -> pd.DataFrame:
    geo = str(spec["geo"]).upper()
    sheet = spec["sheet"]
    if sheet is None:
        df = _ae_city_map()
        print(f"  Built AE ship-city map: {len(df):,} rows")
        return df

    df = pd.read_excel(xlsx, sheet_name=sheet, usecols=PROJECTION_COLUMNS)
    if geo == "UK":
        df = df.assign(Pincode=df["Pincode"].astype(str).str.split(", ")).explode("Pincode")
    df = df.drop_duplicates(subset=["Pincode"])
    print(f"  Loaded {sheet!r} -> {geo}: {len(df):,} rows")
    return df


def local_pincode_dir() -> Path:
    """{project_root}/pincode/"""
    out = cfg_paths.project_root() / "pincode"
    out.mkdir(parents=True, exist_ok=True)
    return out


def save_local_pincode(df: pd.DataFrame, filename: str) -> Path:
    out = df.copy()
    object_cols = out.select_dtypes(include="object").columns
    out[object_cols] = out[object_cols].astype(str)
    path = local_pincode_dir() / filename
    out.to_csv(path, index=False)
    print(f"  Local save -> {path}")
    return path


def process_pincode(
    *,
    geos: Optional[Sequence[str]] = None,
    xlsx_path: Optional[Path] = None,
    save_local: bool = True,
    upload_azure: bool = True,
) -> Dict[str, pd.DataFrame]:
    path = Path(xlsx_path) if xlsx_path is not None else cfg_paths.esh_pincode_xlsx_path()
    specs = _selected_specs(geos)
    needs_xlsx = any(s["sheet"] is not None for s in specs)
    if needs_xlsx and not path.exists():
        raise FileNotFoundError(f"Pincode workbook not found: {path}")

    print(f"\nPincode <- {path if needs_xlsx else '(AE hardcoded only)'}")
    print(f"  Geos: {[s['geo'] for s in specs]}")

    tables: Dict[str, pd.DataFrame] = {}
    for spec in specs:
        geo = str(spec["geo"]).upper()
        filename = str(spec["file"])
        df = _load_geo_frame(path, spec)
        tables[geo] = df

        if save_local:
            save_local_pincode(df, filename)

        if upload_azure:
            cogs_io.upload_to_azure_csv(df, f"{AZURE_BLOB_PREFIX}/{filename}")

    print(f"\nPincode done - {len(tables)} slice(s).")
    return tables


def run(
    *,
    client: str = "ESH",
    geos: Optional[Sequence[str]] = None,
    save_local: bool = True,
    upload_azure: bool = True,
    **_kwargs,
) -> Dict[str, pd.DataFrame]:
    # Shared master export: always all geos (US/CA/DE/UK/IN/AE/IE),
    # ignoring pipeline client geography selection.
    _ = (client, geos)
    return process_pincode(
        geos=None,
        save_local=save_local,
        upload_azure=upload_azure,
    )


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Pincode master -> local CSV / Azure")
    p.add_argument("--geos", default="", help="Comma-separated geos, e.g. UK,US,AE")
    p.add_argument("--xlsx-path", default="", help="Override ESH_PINCODE_PATH workbook")
    p.add_argument("--skip-local", action="store_true")
    p.add_argument("--skip-azure", action="store_true")
    return p.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> Dict[str, pd.DataFrame]:
    args = _parse_args(argv)
    geos = [g.strip() for g in str(args.geos).split(",") if g.strip()] or None
    xlsx = Path(args.xlsx_path) if str(args.xlsx_path).strip() else None
    return process_pincode(
        geos=geos,
        xlsx_path=xlsx,
        save_local=not args.skip_local,
        upload_azure=not args.skip_azure,
    )


from config_manager.report_helpers import print_script_completed

if __name__ == "__main__":
    main()
    print_script_completed('pincode')
