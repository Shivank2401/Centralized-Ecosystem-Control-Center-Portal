"""
Save raw inventory downloads into dated archive folders.

Covers:
  - ESH USA others : Shipbob, Walmart, Tradefull, AWD
  - ESH India others: Easy ecom, Flipkart, Amala Earth
  - ESH Amazon     : manage_fba_inventory + reserved_inventory (all geos)
  - ESH Amazon     : fba_inventory (ageing) — US/CA T-1, DE/IN/UK/AE T
  - KNC Amazon     : manage_fba + reserved + fba_Inventory (ageing) for UK, DE, AE

Style: plain step-by-step (like a Jupyter notebook). Each file has a STEP print
before read/save so a crash shows exactly which block failed.

Run:
    python report_script/helper_files_nd_saving/saving_raw_file_on_date.py
    python report_script/helper_files_nd_saving/saving_raw_file_on_date.py --client ESH
    python report_script/helper_files_nd_saving/saving_raw_file_on_date.py --client KNC
    python report_script/helper_files_nd_saving/saving_raw_file_on_date.py --client KNC --geos UK,AE
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# =============================================================================
# Dates (same idea as notebook: datestr_T / datestr_T1)
# =============================================================================

TODAY = datetime.now()
DATESTR_T = TODAY.strftime("%d-%b-%Y")                    # today
DATESTR_T1 = (TODAY - timedelta(days=1)).strftime("%d-%b-%Y")  # yesterday
YEAR = TODAY.strftime("%Y")                               # e.g. 2026
MON_YYYY = TODAY.strftime("%b-%Y")                        # e.g. Sep-2026
MON_LOWER = TODAY.strftime("%b").lower()                  # e.g. sep


# =============================================================================
# Tiny helpers (read / write only — no fancy registry)
# =============================================================================

def get_data_root(client: str) -> Path:
    """Client folder from .env (ESH_DATA_ROOT / KNC_DATA_ROOT)."""
    client = client.strip().upper()
    try:
        from config_manager.loader import get_client
        return get_client(client).data_root.resolve()
    except Exception:
        pass

    env_map = {
        "ESH": ["INVENTORY_BASE", "ESH_DATA_ROOT"],
        "KNC": ["KNC_DATA_ROOT"],
    }
    for key in env_map.get(client, []):
        val = os.environ.get(key, "").strip().strip('"')
        if val:
            return Path(val).expanduser().resolve()

    raise FileNotFoundError(
        f"Could not find data root for {client}. Set {client}_DATA_ROOT in .env."
    )


def geo_ok(geo: str, geos) -> bool:
    """True if this geo should run (None / empty / ALL = all geos)."""
    if not geos:
        return True
    wanted = {str(g).strip().upper() for g in geos if str(g).strip()}
    if not wanted or "ALL" in wanted:
        return True
    return geo.upper() in wanted


def read_file(path: Path, file_type: str = "csv", encoding=None, skiprows: int = 0, excel_engine=None):
    """Read csv or excel. Tries a second encoding if csv fails."""
    if not path.is_file():
        raise FileNotFoundError(f"Source missing: {path}")

    if file_type == "excel":
        kwargs = {}
        if excel_engine:
            kwargs["engine"] = excel_engine
        if skiprows:
            kwargs["skiprows"] = skiprows
        return pd.read_excel(path, **kwargs)

    # csv
    try_list = []
    if encoding:
        try_list.append(encoding)
    try_list.extend(["utf-8", "latin1"])

    last_err = None
    for enc in try_list:
        try:
            return pd.read_csv(path, encoding=enc, skiprows=skiprows)
        except Exception as err:
            last_err = err
    raise RuntimeError(f"Failed to read CSV {path}: {last_err}")


def save_dated(df: pd.DataFrame, folder: Path, filename: str) -> Path:
    """Create folder if needed, write csv, return path."""
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / filename
    df.to_csv(out, index=False)
    return out


def step_save(
    step_name: str,
    src: Path,
    dest_folder: Path,
    out_name: str,
    file_type: str = "csv",
    encoding=None,
    skiprows: int = 0,
    excel_engine=None,
) -> Path:
    """
    One notebook-style cell:
      print step → read → save → print ok
    If anything breaks, the traceback points here and step_name is already printed.
    """
    print(f"\n>>> STEP: {step_name}")
    print(f"    read : {src}")
    print(f"    write: {dest_folder / out_name}")

    df = read_file(src, file_type=file_type, encoding=encoding, skiprows=skiprows, excel_engine=excel_engine)
    out = save_dated(df, dest_folder, out_name)
    print(f"    OK   : {len(df):,} rows -> {out.name}")
    return out


# =============================================================================
# ESH — USA others (T-1 stamp, folder = YEAR / Mon-YYYY)
# =============================================================================

def save_esh_usa_others(base: Path, geos=None):
    if not geo_ok("US", geos):
        return []

    saved = []

    # Shipbob
    saved.append(step_save(
        "ESH / US / Shipbob",
        src=base / "us/input/shipbob/inventory_status/inventory_status.csv",
        dest_folder=base / "us/input/shipbob/inventory_status" / YEAR / MON_YYYY,
        out_name=f"Shipbob_inventory_{DATESTR_T1}.csv",
    ))

    # Walmart
    saved.append(step_save(
        "ESH / US / Walmart",
        src=base / "us/input/walmart/walmart_inventory/Inventory.xlsx",
        dest_folder=base / "us/input/walmart/walmart_inventory" / YEAR / MON_YYYY,
        out_name=f"Walmart_Inventory_{DATESTR_T1}.csv",
        file_type="excel",
    ))

    # Tradefull
    saved.append(step_save(
        "ESH / US / Tradefull",
        src=base / "us/input/tradefull/InventoryReport/tradefull.xlsx",
        dest_folder=base / "us/input/tradefull/InventoryReport" / YEAR / MON_YYYY,
        out_name=f"Tradfull_inventory_{DATESTR_T1}.csv",
        file_type="excel",
    ))

    # AWD
    saved.append(step_save(
        "ESH / US / AWD",
        src=base / "us/input/amazon/awd_inventory_report/AWD-inventory-report.csv",
        dest_folder=base / "us/input/amazon/awd_inventory_report" / YEAR / MON_YYYY,
        out_name=f"AWD_inventory_{DATESTR_T1}.csv",
        encoding="latin1",
        skiprows=3,
    ))

    return saved


# =============================================================================
# ESH — India others (T stamp)
# =============================================================================

def save_esh_india_others(base: Path, geos=None):
    if not geo_ok("IN", geos):
        return []

    saved = []

    saved.append(step_save(
        "ESH / IN / Flipkart",
        src=base / "india/input/flipkart/my_listing/flipkart_inventory.xls",
        dest_folder=base / "india/input/flipkart/my_listing" / YEAR / MON_YYYY,
        out_name=f"Flipkart_inventory_{DATESTR_T}.csv",
        file_type="excel",
        excel_engine="xlrd",
    ))

    saved.append(step_save(
        "ESH / IN / Amala Earth",
        src=base / "india/input/amala_earth/inventory/amalaearth_inventory.csv",
        dest_folder=base / "india/input/amala_earth/inventory" / YEAR / MON_YYYY,
        out_name=f"Amala_Inventory_{DATESTR_T}.csv",
    ))

    saved.append(step_save(
        "ESH / IN / Easy ecom",
        src=base / "india/input/easy_ecom/inventory/easy_inventory.csv",
        dest_folder=base / "india/input/easy_ecom/inventory" / YEAR / MON_YYYY,
        out_name=f"Easyecom_inventory_{DATESTR_T}.csv",
    ))

    return saved


# =============================================================================
# ESH — Amazon manage_fba + reserved
#   US/CA = T-1 + latin1 ; DE/AE/UK/IN = T + utf-8
# =============================================================================

def save_esh_amazon_manage_reserved(base: Path, geos=None):
    # (folder_name, geo_code, stamp, encoding)
    rows = [
        ("us", "US", DATESTR_T1, "latin1"),
        ("canada", "CA", DATESTR_T1, "latin1"),
        ("germany", "DE", DATESTR_T, "utf-8"),
        ("uae", "AE", DATESTR_T, "utf-8"),
        ("uk", "UK", DATESTR_T, "utf-8"),
        ("india", "IN", DATESTR_T, "utf-8"),
    ]

    saved = []
    for folder, code, stamp, enc in rows:
        if not geo_ok(code, geos):
            continue

        for report_name in ("manage_fba_inventory", "reserved_inventory"):
            src = base / folder / "input" / "amazon" / report_name / f"{report_name}.csv"
            dest = base / folder / "input" / "amazon" / report_name / YEAR / MON_YYYY
            saved.append(step_save(
                f"ESH / {code} / {report_name}",
                src=src,
                dest_folder=dest,
                out_name=f"{report_name}_{stamp}.csv",
                encoding=enc,
            ))
    return saved


# =============================================================================
# ESH — Amazon fba_inventory (ageing)
#   archive = YEAR / mon   (e.g. 2026/sep)
#   US/CA = T-1 ; others = T
# =============================================================================

def save_esh_fba_inventory(base: Path, geos=None):
    # (folder, geo, source_filename, stamp, encoding)
    rows = [
        ("us", "US", "fba_inventory.csv", DATESTR_T1, "latin1"),
        ("canada", "CA", "FBA_inventory_aging.csv", DATESTR_T1, "latin1"),
        ("germany", "DE", "fba_inventory.csv", DATESTR_T, "utf-8"),
        ("india", "IN", "fba_inventory.csv", DATESTR_T, "utf-8"),
        ("uk", "UK", "fba_inventory.csv", DATESTR_T, "utf-8"),
        ("uae", "AE", "fba_inventory.csv", DATESTR_T, "utf-8"),
    ]

    saved = []
    for folder, code, filename, stamp, enc in rows:
        if not geo_ok(code, geos):
            continue

        # month folder from the stamp date (T or T-1)
        file_dt = TODAY if stamp == DATESTR_T else (TODAY - timedelta(days=1))
        year = file_dt.strftime("%Y")
        mon = file_dt.strftime("%b").lower()

        src = base / folder / "input" / "amazon" / "fba_inventory" / filename
        dest = base / folder / "input" / "amazon" / "fba_inventory" / year / mon
        saved.append(step_save(
            f"ESH / {code} / fba_inventory",
            src=src,
            dest_folder=dest,
            out_name=f"fba_inventory_{stamp}.csv",
            encoding=enc,
        ))
    return saved


def run_esh(base: Path, geos=None):
    print("=" * 60)
    print("CLIENT: ESH")
    print(f"BASE  : {base}")
    print("=" * 60)

    saved = []
    saved += save_esh_usa_others(base, geos)
    saved += save_esh_india_others(base, geos)
    saved += save_esh_amazon_manage_reserved(base, geos)
    saved += save_esh_fba_inventory(base, geos)
    return saved


# =============================================================================
# KNC — Amazon manage_fba + reserved + fba_Inventory
#   UK : Inventory/...          archive YEAR/mon
#   DE : Germany/Inventory/...  archive YEAR only
#   AE : UAE/Inventory/...      archive YEAR only
#   stamp = today (T)
# =============================================================================

def run_knc(base: Path, geos=None):
    print("=" * 60)
    print("CLIENT: KNC")
    print(f"BASE  : {base}")
    print("=" * 60)

    saved = []

    # ---- UK (year / mon) ----------------------------------------------------
    if geo_ok("UK", geos):
        inv = base / "Inventory"

        # manage fba
        saved.append(step_save(
            "KNC / UK / manage_fba_inventory",
            src=inv / "manage_fba_inventory.csv",
            dest_folder=inv / "manage fba" / YEAR / MON_LOWER,
            out_name=f"manage_fba_inventory_{DATESTR_T}.csv",
        ))
        # reserved
        saved.append(step_save(
            "KNC / UK / reserved_inventory",
            src=inv / "reserved_inventory.csv",
            dest_folder=inv / "reserved" / YEAR / MON_LOWER,
            out_name=f"reserved_inventory_{DATESTR_T}.csv",
        ))
        # ageing
        saved.append(step_save(
            "KNC / UK / fba_Inventory",
            src=inv / "fba_Inventory.csv",
            dest_folder=inv / "fba Inventory" / YEAR / MON_LOWER,
            out_name=f"fba_Inventory_{DATESTR_T}.csv",
        ))

    # ---- DE (year only) -----------------------------------------------------
    if geo_ok("DE", geos):
        inv = base / "Germany" / "Inventory"

        saved.append(step_save(
            "KNC / DE / manage_fba_inventory",
            src=inv / "manage_fba_inventory.csv",
            dest_folder=inv / "manage fba" / YEAR,
            out_name=f"manage_fba_inventory_{DATESTR_T}.csv",
        ))
        saved.append(step_save(
            "KNC / DE / reserved_inventory",
            src=inv / "reserved_inventory.csv",
            dest_folder=inv / "reserved" / YEAR,
            out_name=f"reserved_inventory_{DATESTR_T}.csv",
        ))
        saved.append(step_save(
            "KNC / DE / fba_Inventory",
            src=inv / "fba_Inventory.csv",
            dest_folder=inv / "fba Inventory" / YEAR,
            out_name=f"fba_Inventory_{DATESTR_T}.csv",
        ))

    # ---- AE (year only) -----------------------------------------------------
    if geo_ok("AE", geos):
        inv = base / "UAE" / "Inventory"

        saved.append(step_save(
            "KNC / AE / manage_fba_inventory",
            src=inv / "manage_fba_inventory.csv",
            dest_folder=inv / "manage fba" / YEAR,
            out_name=f"manage_fba_inventory_{DATESTR_T}.csv",
        ))
        saved.append(step_save(
            "KNC / AE / reserved_inventory",
            src=inv / "reserved_inventory.csv",
            dest_folder=inv / "reserved" / YEAR,
            out_name=f"reserved_inventory_{DATESTR_T}.csv",
        ))
        saved.append(step_save(
            "KNC / AE / fba_Inventory",
            src=inv / "fba_Inventory.csv",
            dest_folder=inv / "fba Inventory" / YEAR,
            out_name=f"fba_Inventory_{DATESTR_T}.csv",
        ))

    return saved


# =============================================================================
# Entry points (portal / CLI) — same API as before
# =============================================================================

def run(client=None, geos=None, inventory_base=None, **_kwargs):
    """
    Pipeline / portal entry.
    client = ESH | KNC
    geos   = optional list like ["UK", "AE"]
    """
    client_code = str(client or "ESH").strip().upper()
    base = Path(inventory_base).resolve() if inventory_base else get_data_root(client_code)

    print(f"Run date : {TODAY.strftime('%Y-%m-%d')}")
    print(f"T stamp  : {DATESTR_T}")
    print(f"T-1 stamp: {DATESTR_T1}")
    if geos:
        print(f"Geos     : {list(geos)}")

    if client_code == "ESH":
        saved = run_esh(base, geos)
    elif client_code == "KNC":
        saved = run_knc(base, geos)
    else:
        raise ValueError(f"Unknown client '{client_code}'. Use ESH or KNC.")

    print("\n" + "-" * 60)
    print(f"Done. Saved {len(saved)} file(s).")
    return saved


def run_main(inventory_base=None, *, client="ESH", geos=None):
    return run(client=client, geos=geos, inventory_base=inventory_base)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Archive raw inventory files with date stamp.")
    parser.add_argument("inventory_base", nargs="?", default=None, help="Optional data-root override")
    parser.add_argument("--client", default="ESH", help="ESH or KNC")
    parser.add_argument("--geos", default=None, help="Comma-separated geos, e.g. UK,AE")
    return parser.parse_args(argv)


if __name__ == "__main__":
    from config_manager.report_helpers import print_script_completed

    args = parse_args()
    geos = [g.strip() for g in args.geos.split(",") if g.strip()] if args.geos else None
    base = Path(args.inventory_base).expanduser() if args.inventory_base else None
    run_main(inventory_base=base, client=args.client, geos=geos)
    print_script_completed("saving_raw_file_on_date", detail=f"client={args.client}")
