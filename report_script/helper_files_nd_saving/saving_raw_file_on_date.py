"""
Save raw inventory downloads into dated year/month archive folders.

Covers:
  - USA others : Shipbob, Walmart, Tradefull, AWD
  - India others: Easy ecom, Flipkart, Amala Earth
  - Amazon     : manage_fba_inventory + reserved_inventory (all geos)
  - Amazon     : fba_inventory (ageing) — US/CA T-1, DE/IN/UK/AE T

No cleaning / ETL — read source file as-is and write a dated CSV snapshot.

Run:
    python c_saving_raw_file_on_date.py
    python c_saving_raw_file_on_date.py "D:\\path\\to\\inventory"

Optional:
    set INVENTORY_BASE=C:\\path\\to\\inventory
    # or ESH_DATA_ROOT in .env
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

# ---------------------------------------------------------------------------
# Report registry — relative paths under the inventory root
# ---------------------------------------------------------------------------

@dataclass
class RawReport:
    """One raw source file to archive datewise."""

    name: str
    # Relative path to the daily download file (under inventory root)
    source_rel: Path
    # Relative folder that holds archives (year/month under this)
    archive_rel: Path
    # Output filename prefix, e.g. Shipbob_inventory -> Shipbob_inventory_01-Aug-2026.csv
    output_prefix: str
    # 0 = today, 1 = yesterday (matches legacy IMS date stamps)
    date_offset_days: int = 0
    # Reader: csv | excel
    file_type: str = "csv"
    encoding: Optional[str] = None
    skiprows: int = 0
    excel_engine: Optional[str] = None
    # Extra pandas read kwargs if needed later
    read_kwargs: Dict[str, Any] = field(default_factory=dict)
    # Archive layout under archive_rel:
    #   "mon-yyyy"  -> {archive_rel}/{YYYY}/{Mon-YYYY}/prefix_dd-Mon-YYYY.csv  (default)
    #   "yyyy/mon"  -> {archive_rel}/{YYYY}/{mon}/prefix_dd-Mon-YYYY.csv
    #                 (FBA ageing legacy: year + lowercase month abbr; folders use file_date)
    archive_style: str = "mon-yyyy"


# USA others — legacy used yesterday (T-1) stamps
USA_OTHER_REPORTS: List[RawReport] = [
    RawReport(
        name="Shipbob",
        source_rel=Path("us/input/shipbob/inventory_status/inventory_status.csv"),
        archive_rel=Path("us/input/shipbob/inventory_status"),
        output_prefix="Shipbob_inventory",
        date_offset_days=1,
        file_type="csv",
    ),
    RawReport(
        name="Walmart",
        source_rel=Path("us/input/walmart/walmart_inventory/Inventory.xlsx"),
        archive_rel=Path("us/input/walmart/walmart_inventory"),
        output_prefix="Walmart_Inventory",
        date_offset_days=1,
        file_type="excel",
    ),
    RawReport(
        name="Tradefull",
        source_rel=Path("us/input/tradefull/InventoryReport/tradefull.xlsx"),
        archive_rel=Path("us/input/tradefull/InventoryReport"),
        output_prefix="Tradfull_inventory",
        date_offset_days=1,
        file_type="excel",
    ),
    RawReport(
        name="AWD",
        source_rel=Path("us/input/amazon/awd_inventory_report/AWD-inventory-report.csv"),
        archive_rel=Path("us/input/amazon/awd_inventory_report"),
        output_prefix="AWD_inventory",
        date_offset_days=1,
        file_type="csv",
        encoding="latin1",
        skiprows=3,
    ),
]

# India others — legacy used today stamps
INDIA_OTHER_REPORTS: List[RawReport] = [
    RawReport(
        name="Flipkart",
        source_rel=Path("india/input/flipkart/my_listing/flipkart_inventory.xls"),
        archive_rel=Path("india/input/flipkart/my_listing"),
        output_prefix="Flipkart_inventory",
        date_offset_days=0,
        file_type="excel",
        excel_engine="xlrd",
    ),
    RawReport(
        name="Amala Earth",
        source_rel=Path("india/input/amala_earth/inventory/amalaearth_inventory.csv"),
        archive_rel=Path("india/input/amala_earth/inventory"),
        output_prefix="Amala_Inventory",
        date_offset_days=0,
        file_type="csv",
    ),
    RawReport(
        name="Easy ecom",
        source_rel=Path("india/input/easy_ecom/inventory/easy_inventory.csv"),
        archive_rel=Path("india/input/easy_ecom/inventory"),
        output_prefix="Easyecom_inventory",
        date_offset_days=0,
        file_type="csv",
    ),
]

# Amazon manage FBA + reserved (all geos)
AMAZON_GEOS: List[Dict[str, Any]] = [
    {"geo": "us", "manage_offset": 1, "reserved_offset": 1, "encoding": "latin1"},
    {"geo": "canada", "manage_offset": 1, "reserved_offset": 1, "encoding": "latin1"},
    {"geo": "germany", "manage_offset": 0, "reserved_offset": 0, "encoding": "utf-8"},
    {"geo": "uae", "manage_offset": 0, "reserved_offset": 0, "encoding": "utf-8"},
    {"geo": "uk", "manage_offset": 0, "reserved_offset": 0, "encoding": "utf-8"},
    {"geo": "india", "manage_offset": 0, "reserved_offset": 0, "encoding": "utf-8"},
]


def amazon_reports() -> List[RawReport]:
    reports: List[RawReport] = []
    for cfg in AMAZON_GEOS:
        geo = cfg["geo"]
        enc = cfg["encoding"]
        for report_name, offset_key in (
            ("manage_fba_inventory", "manage_offset"),
            ("reserved_inventory", "reserved_offset"),
        ):
            reports.append(
                RawReport(
                    name=f"{geo}/{report_name}",
                    source_rel=Path(geo)
                    / "input"
                    / "amazon"
                    / report_name
                    / f"{report_name}.csv",
                    archive_rel=Path(geo) / "input" / "amazon" / report_name,
                    output_prefix=report_name,
                    date_offset_days=int(cfg[offset_key]),
                    file_type="csv",
                    encoding=enc,
                )
            )
    return reports


# Amazon FBA inventory (ageing) — mirrors legacy save_fba_inventory():
#   archive under {geo}/input/amazon/fba_inventory/{YYYY}/{mon}/fba_inventory_{dd-Mon-YYYY}.csv
#   US/CA = T-1; DE/IN/UK/AE = T; Canada source filename differs.
FBA_INVENTORY_GEOS: List[Dict[str, Any]] = [
    {
        "geo": "us",
        "input_filename": "fba_inventory.csv",
        "date_offset_days": 1,
        "encoding": "latin1",
    },
    {
        "geo": "canada",
        "input_filename": "FBA_inventory_aging.csv",
        "date_offset_days": 1,
        "encoding": "latin1",
    },
    {
        "geo": "germany",
        "input_filename": "fba_inventory.csv",
        "date_offset_days": 0,
        "encoding": "utf-8",
    },
    {
        "geo": "india",
        "input_filename": "fba_inventory.csv",
        "date_offset_days": 0,
        "encoding": "utf-8",
    },
    {
        "geo": "uk",
        "input_filename": "fba_inventory.csv",
        "date_offset_days": 0,
        "encoding": "utf-8",
    },
    {
        "geo": "uae",
        "input_filename": "fba_inventory.csv",
        "date_offset_days": 0,
        "encoding": "utf-8",
    },
]


def fba_inventory_reports() -> List[RawReport]:
    reports: List[RawReport] = []
    for cfg in FBA_INVENTORY_GEOS:
        geo = cfg["geo"]
        filename = cfg["input_filename"]
        reports.append(
            RawReport(
                name=f"{geo}/fba_inventory",
                source_rel=Path(geo) / "input" / "amazon" / "fba_inventory" / filename,
                archive_rel=Path(geo) / "input" / "amazon" / "fba_inventory",
                output_prefix="fba_inventory",
                date_offset_days=int(cfg["date_offset_days"]),
                file_type="csv",
                encoding=cfg.get("encoding"),
                archive_style="yyyy/mon",
            )
        )
    return reports


ALL_REPORTS: List[RawReport] = (
    USA_OTHER_REPORTS
    + INDIA_OTHER_REPORTS
    + amazon_reports()
    + fba_inventory_reports()
)


# ---------------------------------------------------------------------------
# Inventory root detection (no hardcoded user path)
# ---------------------------------------------------------------------------

def _looks_like_inventory_root(path: Path) -> bool:
    if not path.is_dir():
        return False
    return (path / "us" / "input").is_dir() or (path / "canada" / "input").is_dir()


def detect_inventory_base(client: Optional[str] = None) -> Path:
    if client:
        from config_manager.loader import get_client

        candidate = get_client(client).data_root
        if _looks_like_inventory_root(candidate):
            return candidate.resolve()
        return candidate.resolve()

    env = os.environ.get("INVENTORY_BASE", "").strip().strip('"')
    if not env:
        env = os.environ.get("ESH_DATA_ROOT", "").strip().strip('"')
    if env:
        candidate = Path(env).expanduser().resolve()
        if _looks_like_inventory_root(candidate):
            return candidate
        raise FileNotFoundError(
            f"INVENTORY_BASE/ESH_DATA_ROOT is set but is not a valid inventory root:\n  {candidate}"
        )

    script_dir = Path(__file__).resolve().parent
    for parent in [script_dir, *script_dir.parents]:
        candidate = parent / "inventory"
        if _looks_like_inventory_root(candidate):
            return candidate.resolve()

    home = Path.home()
    search_roots = [
        home / "OneDrive - EcoSoul Home",
        home / "OneDrive",
        home,
    ]
    relative_tails = [
        Path("Central Repository") / "inventory",
        Path("Data analytics_Ecosoul - Central Repository") / "inventory",
        Path("inventory"),
    ]

    for root in search_roots:
        if not root.is_dir():
            continue
        for tail in relative_tails:
            candidate = root / tail
            if _looks_like_inventory_root(candidate):
                return candidate.resolve()
        try:
            for path in root.rglob("inventory"):
                if path.is_dir() and _looks_like_inventory_root(path):
                    return path.resolve()
        except (PermissionError, OSError):
            continue

    raise FileNotFoundError(
        "Could not locate inventory root.\n"
        "Set ESH_DATA_ROOT (or INVENTORY_BASE) in .env and re-run."
    )


# ---------------------------------------------------------------------------
# Read / save helpers
# ---------------------------------------------------------------------------

def date_stamp(offset_days: int) -> str:
    return (datetime.now() - timedelta(days=offset_days)).strftime("%d-%b-%Y")


def file_date_for(offset_days: int) -> datetime:
    return datetime.now() - timedelta(days=offset_days)


def read_raw_file(path: Path, report: RawReport) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(f"Source missing: {path}")

    try:
        with open(path, "rb") as handle:
            handle.read(1)
    except OSError:
        pass

    kwargs = dict(report.read_kwargs)

    if report.file_type == "csv":
        encodings: Tuple[str, ...]
        if report.encoding:
            encodings = (report.encoding, "utf-8", "latin1")
        else:
            encodings = ("utf-8", "latin1")

        last_error: Optional[Exception] = None
        for enc in encodings:
            try:
                return pd.read_csv(
                    path,
                    encoding=enc,
                    skiprows=report.skiprows,
                    **kwargs,
                )
            except Exception as exc:  # noqa: BLE001
                last_error = exc
        raise RuntimeError(f"Failed to read CSV {path}: {last_error}")

    if report.file_type == "excel":
        excel_kwargs: Dict[str, Any] = dict(kwargs)
        if report.excel_engine:
            excel_kwargs["engine"] = report.excel_engine
        if report.skiprows:
            excel_kwargs["skiprows"] = report.skiprows
        return pd.read_excel(path, **excel_kwargs)

    raise ValueError(f"Unsupported file_type for {report.name}: {report.file_type}")


def archive_dir(base: Path, report: RawReport, year: str, month_folder: str) -> Path:
    return base / report.archive_rel / year / month_folder


def resolve_archive_parts(
    report: RawReport,
    today: datetime,
) -> Tuple[str, str, str]:
    """
    Return (year, month_folder, stamp) for this report.

    - Default mon-yyyy: year/month from today; stamp from offset (existing behaviour).
    - yyyy/mon (FBA ageing): year/month/stamp all from file_date (offset).
    """
    if report.archive_style == "yyyy/mon":
        fd = file_date_for(report.date_offset_days)
        return (
            fd.strftime("%Y"),
            fd.strftime("%b").lower(),
            fd.strftime("%d-%b-%Y"),
        )
    return (
        today.strftime("%Y"),
        today.strftime("%b-%Y"),
        date_stamp(report.date_offset_days),
    )


def save_dated_csv(
    df: pd.DataFrame,
    dest_dir: Path,
    output_prefix: str,
    stamp: str,
) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    out_path = dest_dir / f"{output_prefix}_{stamp}.csv"
    df.to_csv(out_path, index=False)
    return out_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(
    inventory_base: Optional[Path] = None,
    reports: Optional[List[RawReport]] = None,
    client: Optional[str] = None,
    geos: Optional[List[str]] = None,
    **_kwargs,
) -> List[Path]:
    """Archive all configured raw reports into YYYY/Mon-YYYY (or FBA yyyy/mon) folders."""
    del geos  # reserved for future geo-filtered archives
    if inventory_base is None:
        inventory_base = detect_inventory_base(client=client or "ESH")
    base = inventory_base.resolve()
    today = datetime.now()
    jobs = reports if reports is not None else ALL_REPORTS

    print(f"Client         : {client or 'ESH'}")
    print(f"Inventory base : {base}")
    print(f"Run date       : {today.strftime('%Y-%m-%d')}")
    print(f"Reports        : {len(jobs)}")
    print("-" * 60)

    saved: List[Path] = []
    failed: List[Tuple[str, str]] = []

    for report in jobs:
        src = base / report.source_rel
        year, month_folder, stamp = resolve_archive_parts(report, today)
        dest = archive_dir(base, report, year, month_folder)
        try:
            df = read_raw_file(src, report)
            out = save_dated_csv(df, dest, report.output_prefix, stamp)
            saved.append(out)
            print(
                f"[OK]   {report.name:<28} rows={len(df):>7,}  "
                f"-> {year}/{month_folder}/{out.name}"
            )
        except Exception as exc:  # noqa: BLE001
            failed.append((report.name, str(exc)))
            print(f"[FAIL] {report.name:<28} {exc}")

    print("-" * 60)
    print(f"Saved : {len(saved)}")
    print(f"Failed: {len(failed)}")
    if failed:
        for name, err in failed:
            print(f"  - {name}: {err}")
        raise RuntimeError(
            f"{len(failed)} raw inventory file(s) failed to save. "
            "Check missing downloads / OneDrive sync."
        )
    return saved


def run_main(inventory_base: Optional[Path] = None) -> List[Path]:
    """Entrypoint used by main_ecosoul.py orchestrator."""
    return run(inventory_base=inventory_base)


if __name__ == "__main__":
    from config_manager.report_helpers import print_script_completed

    cli_base = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else None
    run_main(inventory_base=cli_base)
    print_script_completed("saving_raw_file_on_date")
