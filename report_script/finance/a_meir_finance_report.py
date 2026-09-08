"""
ESH MEIR Finance — Closing Stock Analyzer + Inventory Reconciles.

Ports report_script/finance/a_MEIR_Finance.ipynb without changing processing /
cleaning / ageing / save-location conventions.

User selects the MEIR **report month** (e.g. Nov-2025). Source files are then
resolved as:

  Flipkart / EasyEcom : {report}/India_Platform_{last-day-report}.xlsx
  Walmart             : {next}/USA_Platform_{last-day-report}.xlsx
  3G                  : {next}/3G_WH_Database_{last-day-report}.xlsx
  Shipcube            : {next}/Inventory-Database_{01-next}.xlsx
                        (Date column forced to last-day-report)
  Updike              : {next}/Updike_WH_Database_{last-day-report}.xlsx
  Amazon US + CA      : {next}/Inventory-Database_{01-next}.xlsx
  Amazon other geos   : {report}/Inventory-Database_{last-day-report}.xlsx

Outputs (under ESH inventory root):
  Output_Database/Inventory Reconciles/{next_year}/{next}/Inventory Reconciles_{01-next}.xlsx
  Output_Database/Closing Stock Analysis/Closing Stock Analyzer-{report}.xlsx

Run:
  python report_script/finance/a_meir_finance_report.py
  python report_script/finance/a_meir_finance_report.py --month Nov --year 2025
  # or via run_pipeline.py → Stage: finance → MEIR Finance
"""
from __future__ import annotations

import argparse
import calendar
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from pipeline_engine.interactive import env_or_none, safe_input, stdin_is_interactive
from dateutil.relativedelta import relativedelta

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config_manager import layouts
from config_manager import paths as cfg_paths


# ---------------------------------------------------------------------------
# Report period + path resolution
# ---------------------------------------------------------------------------

MONTH_ALIASES = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}


@dataclass(frozen=True)
class MeirPeriod:
    """Calendar context for one MEIR closing month."""

    report_month: date          # first day of report month
    next_month: date            # first day of following month
    report_label: str           # e.g. Nov-2025
    next_label: str             # e.g. Dec-2025
    last_day_report: date       # e.g. 30-Nov-2025
    first_day_next: date        # e.g. 01-Dec-2025
    last_day_report_str: str    # 30-Nov-2025
    first_day_next_str: str     # 01-Dec-2025

    @property
    def report_year(self) -> int:
        return self.report_month.year

    @property
    def next_year(self) -> int:
        return self.next_month.year


def parse_report_month(month: str, year: int) -> date:
    key = str(month).strip().lower()
    if key.isdigit():
        m = int(key)
    else:
        # allow "Nov", "Nov-2025", "November"
        key = key.split("-")[0].split("/")[0]
        if key not in MONTH_ALIASES:
            raise ValueError(f"Unknown month {month!r}. Use e.g. Nov or 11.")
        m = MONTH_ALIASES[key]
    if not 1 <= m <= 12:
        raise ValueError(f"Month must be 1-12, got {m}")
    return date(int(year), m, 1)


def build_period(report_month: date) -> MeirPeriod:
    next_m = report_month + relativedelta(months=1)
    last_day = date(
        report_month.year,
        report_month.month,
        calendar.monthrange(report_month.year, report_month.month)[1],
    )
    first_next = next_m
    return MeirPeriod(
        report_month=report_month,
        next_month=next_m,
        report_label=report_month.strftime("%b-%Y"),
        next_label=next_m.strftime("%b-%Y"),
        last_day_report=last_day,
        first_day_next=first_next,
        last_day_report_str=last_day.strftime("%d-%b-%Y"),
        first_day_next_str=first_next.strftime("%d-%b-%Y"),
    )


def inventory_root() -> Path:
    return cfg_paths.esh_inventory_root()


def resolve_source_paths(period: MeirPeriod, inv: Path) -> dict:
    """
    Build absolute source paths for the selected MEIR report month.

    Folder / filename rules follow the Nov-2025 convention provided by ops.
    Each channel may list fallback filenames when the preferred date is absent.
    """
    r_year, r_label = period.report_year, period.report_label
    n_year, n_label = period.next_year, period.next_label
    d_last = period.last_day_report_str
    d_first = period.first_day_next_str

    india_dir = (
        inv / "india" / "output" / "India Platform temp files" / str(r_year) / r_label
    )
    walmart_dir = (
        inv / "us" / "output" / "USA Platform temp files" / str(n_year) / n_label
    )
    three_g_dir = inv / "Output_Database" / "USA" / "3G" / str(n_year) / n_label
    updike_dir = inv / "Output_Database" / "USA" / "Updike" / str(n_year) / n_label
    supply_next_dir = (
        inv / "Output_Database" / "Overall" / "Supply_chain_inventory_as_of"
        / str(n_year) / n_label
    )
    supply_report_dir = (
        inv / "Output_Database" / "Overall" / "Supply_chain_inventory_as_of"
        / str(r_year) / r_label
    )

    def pick(label: str, candidates: list) -> Path:
        for path in candidates:
            if path.is_file():
                if path != candidates[0]:
                    print(f"  [{label}] preferred missing — using {path.name}")
                return path
        return candidates[0]  # preferred (may be missing; caller validates)

    # Flipkart / EasyEcom: same report-month folder, month-end file
    india_file = pick(
        "flipkart/easyecom",
        [
            india_dir / f"India_Platform_{d_last}.xlsx",
            india_dir / f"India_Platform_{d_first}.xlsx",
        ],
    )
    # Preferred: last day of report month in next-month folder (ops rule).
    # Fallback: 01-next (often how USA platform dumps are named).
    walmart_file = pick(
        "walmart",
        [
            walmart_dir / f"USA_Platform_{d_last}.xlsx",
            walmart_dir / f"USA_Platform_{d_first}.xlsx",
        ],
    )
    three_g_file = pick(
        "3g",
        [
            three_g_dir / f"3G_WH_Database_{d_last}.xlsx",
            three_g_dir / f"3G_WH_Database_{d_first}.xlsx",
        ],
    )
    updike_file = pick(
        "updike",
        [
            updike_dir / f"Updike_WH_Database_{d_last}.xlsx",
            updike_dir / f"Updike_WH_Database_{d_first}.xlsx",
        ],
    )
    supply_next = pick(
        "supply_next",
        [
            supply_next_dir / f"Inventory-Database_{d_first}.xlsx",
            supply_next_dir / f"Inventory-Database_{d_last}.xlsx",
        ],
    )
    supply_report = pick(
        "amazon_other",
        [
            supply_report_dir / f"Inventory-Database_{d_last}.xlsx",
            supply_report_dir / f"Inventory-Database_{d_first}.xlsx",
        ],
    )
    container_file = inv / "IMS_new_Dashboard_files" / "Container_Data.xlsx"

    return {
        "india_platform": india_file,
        "walmart": walmart_file,
        "three_g": three_g_file,
        "updike": updike_file,
        "shipcube": supply_next,
        "amazon_us_ca": supply_next,
        "amazon_other": supply_report,
        "container": container_file,
    }


CHANNEL_LABELS = {
    "india_platform": "Flipkart / EasyEcom",
    "walmart": "Walmart",
    "three_g": "3G",
    "updike": "Updike",
    "shipcube": "Shipcube",
    "amazon_us_ca": "Amazon US / CA",
    "amazon_other": "Amazon other geos",
    "container": "Container Data",
}


def print_period_plan(period: MeirPeriod, paths: dict) -> None:
    print("\n" + "=" * 70)
    print(f"MEIR report month : {period.report_label}")
    print(f"Next-month folder : {period.next_label}")
    print(f"Last day report   : {period.last_day_report_str}")
    print(f"First day next    : {period.first_day_next_str}")
    print("-" * 70)
    print("Files selected for this run:")
    for key, path in paths.items():
        path = Path(path)
        label = CHANNEL_LABELS.get(key, key)
        exists = "OK" if path.is_file() else "MISSING"
        print(f"  [{exists:<7}] {label}")
        print(f"            file : {path.name}")
        print(f"            path : {path}")
    print("=" * 70)


def prompt_report_month(
    default_month: Optional[str] = None,
    default_year: Optional[int] = None,
) -> MeirPeriod:
    """Month/year picker — interactive on CLI TTY; previous month when non-interactive."""
    prev = datetime.now() - relativedelta(months=1)
    dm = default_month or prev.strftime("%b")
    dy = default_year or prev.year

    env_rm = env_or_none("MEIR_REPORT_MONTH")
    if env_rm:
        print(f"MEIR Closing Stock — MEIR_REPORT_MONTH={env_rm}")
        raw = env_rm.replace("/", "-")
        if "-" in raw:
            parts = raw.split("-")
            if parts[0].isdigit() and len(parts[0]) == 4:
                year, month = int(parts[0]), parts[1]
            else:
                month, year = parts[0], int(parts[1])
            return build_period(parse_report_month(month, int(year)))
        return build_period(parse_report_month(raw, int(dy)))

    if not stdin_is_interactive():
        print(
            f"MEIR Closing Stock — non-interactive: using previous month {dm}-{dy} "
            "(set MEIR_REPORT_MONTH=Nov-2025 or pass month=/year= to override)"
        )
        return build_period(parse_report_month(dm, int(dy)))

    print("\nMEIR Closing Stock — select report month")
    raw_m = safe_input(f"Month [{dm}]: ", default=dm)
    raw_y = safe_input(f"Year  [{dy}]: ", default=str(dy))
    return build_period(parse_report_month(raw_m, int(raw_y)))


# ---------------------------------------------------------------------------
# Ageing helpers (same logic as notebook)
# ---------------------------------------------------------------------------

def calculate_0_31_days(row):
    total_inventory = row["Total Inventory X India"]
    current_month_minus_1 = row["current_month_minus_1"]

    if total_inventory == 0 or current_month_minus_1 == 0:
        return 0
    elif total_inventory == current_month_minus_1:
        return current_month_minus_1
    elif total_inventory < current_month_minus_1:
        return total_inventory
    return current_month_minus_1


def calculate_31_60_days(row):
    total_inventory = row["Total Inventory X India"]
    current_month_minus_2 = row.get("current_month_minus_2", 0)
    zero_31_days = row.get("0-31 Days", 0)

    if total_inventory == 0:
        return 0
    elif total_inventory != 0 and current_month_minus_2 == 0:
        return 0
    elif total_inventory != 0 and current_month_minus_2 != 0 and total_inventory - zero_31_days == 0:
        return 0
    elif (
        total_inventory != 0
        and current_month_minus_2 != 0
        and current_month_minus_2 > total_inventory - zero_31_days
    ):
        return total_inventory - zero_31_days
    return current_month_minus_2


def calculate_61_90_days(row):
    total_inventory = row["Total Inventory X India"]
    current_month_minus_3 = row.get("current_month_minus_3", 0)
    zero_to_31_days = row.get("0-31 Days", 0)
    thirty_to_60_days = row.get("31-60 Days", 0)

    if total_inventory == 0:
        return 0
    elif current_month_minus_3 == 0:
        return 0
    elif total_inventory - (zero_to_31_days + thirty_to_60_days) == 0:
        return 0
    elif current_month_minus_3 > total_inventory - (zero_to_31_days + thirty_to_60_days):
        return total_inventory - (zero_to_31_days + thirty_to_60_days)
    return current_month_minus_3


def calculate_91_120_days(row):
    total_inventory = row["Total Inventory X India"]
    current_month_minus_4 = row.get("current_month_minus_4", 0)
    zero_to_31_days = row.get("0-31 Days", 0)
    thirty_to_60_days = row.get("31-60 Days", 0)
    sixty_to_90_days = row.get("61-90 Days", 0)

    if total_inventory == 0:
        return 0
    elif current_month_minus_4 == 0:
        return 0
    elif total_inventory - (zero_to_31_days + thirty_to_60_days + sixty_to_90_days) == 0:
        return 0
    elif current_month_minus_4 > total_inventory - (
        zero_to_31_days + thirty_to_60_days + sixty_to_90_days
    ):
        return total_inventory - (
            zero_to_31_days + thirty_to_60_days + sixty_to_90_days
        )
    return current_month_minus_4


def calculate_120_plus_days(row):
    total_inventory = row["Total Inventory X India"]
    zero_to_31_days = row.get("0-31 Days", 0)
    thirty_to_60_days = row.get("31-60 Days", 0)
    sixty_to_90_days = row.get("61-90 Days", 0)
    ninety_to_120_days = row.get("91-120 Days", 0)

    prior = [zero_to_31_days, thirty_to_60_days, sixty_to_90_days, ninety_to_120_days]
    if sum(prior) == 0 and total_inventory == 0:
        return 0
    elif sum(prior) == 0 and total_inventory != 0:
        return total_inventory
    elif sum(prior) != 0 and total_inventory != 0:
        return total_inventory - (
            zero_to_31_days + thirty_to_60_days + sixty_to_90_days + ninety_to_120_days
        )
    return total_inventory


PIVOT_COUNTRY_COLS = [
    "Date",
    "SKU",
    "3G",
    "Updike",
    "Shipcube-East",
    "Shipcube-West",
    "Walmart",
    "USA",
    "Canada",
    "Germany",
    "UAE",
    "UK",
    "Easy Ecom",
    "Flipkart",
    "India",
]

SKU_VALUE_COLS = [
    "3G",
    "Updike",
    "Walmart",
    "Shipcube-East",
    "Shipcube-West",
    "USA",
    "Canada",
    "Germany",
    "UAE",
    "UK",
    "Easy Ecom",
    "Flipkart",
    "India",
]


def _ensure_columns(df: pd.DataFrame, cols: Sequence[str], fill=0) -> pd.DataFrame:
    out = df.copy()
    for c in cols:
        if c not in out.columns:
            out[c] = fill
    return out


def _require_file(path: Path, label: str) -> Path:
    if not path.is_file():
        raise FileNotFoundError(f"[{label}] Missing source file:\n  {path}")
    print(f"  Reading [{label}] → {path.name}")
    return path


# ---------------------------------------------------------------------------
# Main pipeline (notebook logic)
# ---------------------------------------------------------------------------

def run_meir(period: MeirPeriod, *, dry_run_paths: bool = False) -> pd.DataFrame:
    inv = inventory_root()
    paths = resolve_source_paths(period, inv)
    print_period_plan(period, paths)

    if dry_run_paths:
        print("Dry-run only — skipping load/transform.")
        return pd.DataFrame()

    missing = [k for k, p in paths.items() if k != "container" and not Path(p).is_file()]
    if missing:
        raise FileNotFoundError(
            "Missing required MEIR source file(s): "
            + ", ".join(missing)
            + "\nCheck the paths printed above."
        )

    cols = ["Date", "Platform", "SKU", "On_Hand"]

    # ----- India: Flipkart + Easy Ecom -----
    print("\nLoading India platform (Flipkart / Easy Ecom)...")
    india_path = _require_file(Path(paths["india_platform"]), "india")
    flipkart = pd.read_excel(india_path, sheet_name="Flipkart")
    easyecom = pd.read_excel(india_path, sheet_name="Easy Ecomm")
    india_others = pd.concat([flipkart[cols], easyecom[cols]])
    india_others.reset_index(drop=True, inplace=True)

    # ----- Walmart -----
    print("Loading Walmart...")
    Walmart = pd.read_excel(
        _require_file(Path(paths["walmart"]), "walmart"),
        sheet_name="walmart_invntory",
    )

    # ----- 3G -----
    print("Loading 3G...")
    three_G = pd.read_excel(
        _require_file(Path(paths["three_g"]), "3g"),
        sheet_name="3G-Inventory",
    )
    three_G = three_G.loc[:, ["SKU", "3G On Hand", "Date", "Box / Case"]]
    three_G["Platform"] = "3G"
    three_G.reset_index(drop=True, inplace=True)
    three_G["On_Hand"] = three_G["3G On Hand"] * three_G["Box / Case"]

    # ----- Shipcube -----
    print("Loading Shipcube...")
    shipcube = pd.read_excel(
        _require_file(Path(paths["shipcube"]), "shipcube"),
        sheet_name="Inventory_S-D",
    )
    shipcube = shipcube.loc[:, ["SKU", "Shipcube-East", "Shipcube-West"]]
    shipcube_melted = pd.melt(
        shipcube,
        id_vars=["SKU"],
        value_vars=["Shipcube-East", "Shipcube-West"],
        var_name="Platform",
        value_name="On_Hand",
    )
    shipcube_melted.reset_index(drop=True, inplace=True)
    shipcube_melted["SKU"] = np.where(
        shipcube_melted["SKU"] == "32OZ Soup Bowl Lid Set of 300",
        "CBFL32OZ300",
        shipcube_melted["SKU"],
    )
    shipcube_melted["SKU"] = np.where(
        shipcube_melted["SKU"] == "32OZ",
        "CBFL32OZ300",
        shipcube_melted["SKU"],
    )
    # Notebook forced Date to report-month last day
    shipcube_melted["Date"] = period.last_day_report_str

    # ----- Updike -----
    print("Loading Updike...")
    updike = pd.read_excel(
        _require_file(Path(paths["updike"]), "updike"),
        sheet_name="Updk-Inveto",
    )
    updike = updike.loc[:, ["SKU", "Updike On Hand", "Date", "Box / Case"]]
    updike["Platform"] = "Updike"
    updike["On_Hand"] = updike["Updike On Hand"] * updike["Box / Case"]
    updike.reset_index(drop=True, inplace=True)

    usa_others = pd.concat([Walmart[cols], three_G[cols], updike[cols]])
    usa_others.reset_index(drop=True, inplace=True)
    usa_others = usa_others.drop_duplicates()

    # ----- Amazon US / CA -----
    print("Loading Amazon US / CA...")
    usa = pd.read_excel(_require_file(Path(paths["amazon_us_ca"]), "amazon_us_ca"))
    country_1 = ["USA", "Canada"]
    usa = usa[usa["Country"].isin(country_1)]
    usa = usa.loc[:, ["SKU", "Country", "afn-warehouse-quantity", "Date"]]
    usa.rename(columns={"afn-warehouse-quantity": "On_Hand"}, inplace=True)
    usa.reset_index(drop=True, inplace=True)

    # ----- Amazon other geos -----
    print("Loading Amazon other geos...")
    amz_other = pd.read_excel(_require_file(Path(paths["amazon_other"]), "amazon_other"))
    country_2 = ["USA", "Canada"]
    amz_other = amz_other[~amz_other["Country"].isin(country_2)]
    amz_other = amz_other.loc[:, ["SKU", "Country", "afn-warehouse-quantity", "Date"]]
    amz_other.rename(columns={"afn-warehouse-quantity": "On_Hand"}, inplace=True)
    amz_other.reset_index(drop=True, inplace=True)

    Amazon_overall = pd.merge(
        usa, amz_other, on=["SKU", "Country", "On_Hand", "Date"], how="outer"
    )

    # ----- Collate + pivot -----
    print("Collating MEIR dataframe...")
    MEIR_dataframe = pd.concat(
        [india_others, usa_others, shipcube_melted, Amazon_overall]
    )
    MEIR_dataframe["Country"] = np.where(
        MEIR_dataframe["Country"].isnull(),
        MEIR_dataframe["Platform"],
        MEIR_dataframe["Country"],
    )

    MEIR_dataframe = pd.pivot_table(
        MEIR_dataframe,
        index=["Date", "SKU"],
        columns="Country",
        values="On_Hand",
        aggfunc="sum",
    ).reset_index()
    MEIR_dataframe = MEIR_dataframe.fillna(0)
    MEIR_dataframe = MEIR_dataframe.drop(
        MEIR_dataframe[MEIR_dataframe.SKU == "0"].index
    )
    MEIR_dataframe = _ensure_columns(MEIR_dataframe, PIVOT_COUNTRY_COLS, fill=0)
    MEIR_dataframe = MEIR_dataframe.loc[:, list(PIVOT_COUNTRY_COLS)]

    # ----- Save Inventory Reconciles (next-month folder) -----
    reconciles_dir = (
        inv
        / "Output_Database"
        / "Inventory Reconciles"
        / str(period.next_year)
        / period.next_label
    )
    reconciles_dir.mkdir(parents=True, exist_ok=True)
    reconciles_name = f"Inventory Reconciles_{period.first_day_next_str}.xlsx"
    reconciles_path = reconciles_dir / reconciles_name
    MEIR_dataframe.to_excel(reconciles_path, index=False)
    print(f"Saved Inventory Reconciles → {reconciles_path}")

    # ----- SKU-level pivot (drop Date) -----
    MEIR_dataframe = pd.pivot_table(
        MEIR_dataframe,
        index="SKU",
        values=list(SKU_VALUE_COLS),
        aggfunc="sum",
    ).reset_index()

    # ----- Container ageing buckets relative to report month -----
    print("Loading container data...")
    colums_to_read = ["SKU", "QTY in Box", "Month_Year", "Status"]
    container = pd.read_excel(
        _require_file(Path(paths["container"]), "container"),
        sheet_name="Container SKU",
        usecols=colums_to_read,
    )
    container["Month_Year"] = container["Month_Year"].apply(
        lambda x: pd.to_datetime(x).strftime("%b-%Y")
        if pd.to_datetime(x, errors="coerce") is not pd.NaT
        else None
    )
    container = container.drop(container[container.Status != "Reached"].index)

    current_month_minus_1 = period.report_label
    current_month_minus_2 = (
        period.report_month - relativedelta(months=1)
    ).strftime("%b-%Y")
    current_month_minus_3 = (
        period.report_month - relativedelta(months=2)
    ).strftime("%b-%Y")
    current_month_minus_4 = (
        period.report_month - relativedelta(months=3)
    ).strftime("%b-%Y")

    def calculate_ageing(month_year):
        if month_year == current_month_minus_1:
            return "current_month_minus_1"
        elif month_year == current_month_minus_2:
            return "current_month_minus_2"
        elif month_year == current_month_minus_3:
            return "current_month_minus_3"
        elif month_year == current_month_minus_4:
            return "current_month_minus_4"
        else:
            return "Outside range"

    container["Ageing"] = container["Month_Year"].apply(calculate_ageing)
    container = container.drop(container[container.Ageing == "Outside range"].index)
    container_data = pd.pivot_table(
        container,
        index="SKU",
        columns="Ageing",
        values="QTY in Box",
        aggfunc="sum",
        fill_value=0,
    ).reset_index()

    MEIR_dataframe["Total Inventory X India"] = (
        MEIR_dataframe["3G"]
        + MEIR_dataframe["Updike"]
        + MEIR_dataframe["Walmart"]
        + MEIR_dataframe["USA"]
        + MEIR_dataframe["Canada"]
        + MEIR_dataframe["Germany"]
        + MEIR_dataframe["UAE"]
        + MEIR_dataframe["UK"]
        + MEIR_dataframe["Shipcube-East"]
        + MEIR_dataframe["Shipcube-West"]
    )

    MEIR_dataframe = pd.merge(MEIR_dataframe, container_data, on="SKU", how="left")
    MEIR_dataframe = MEIR_dataframe.fillna(0)

    if "current_month_minus_1" not in MEIR_dataframe.columns:
        MEIR_dataframe["current_month_minus_1"] = 0

    MEIR_dataframe["0-31 Days"] = MEIR_dataframe.apply(calculate_0_31_days, axis=1)
    MEIR_dataframe["31-60 Days"] = MEIR_dataframe.apply(calculate_31_60_days, axis=1)
    MEIR_dataframe["61-90 Days"] = MEIR_dataframe.apply(calculate_61_90_days, axis=1)
    MEIR_dataframe["91-120 Days"] = MEIR_dataframe.apply(calculate_91_120_days, axis=1)
    MEIR_dataframe["120+ Days"] = MEIR_dataframe.apply(calculate_120_plus_days, axis=1)

    columns_to_drop = [
        "current_month_minus_1",
        "current_month_minus_2",
        "current_month_minus_3",
        "current_month_minus_4",
    ]
    existing_columns_to_drop = [
        c for c in columns_to_drop if c in MEIR_dataframe.columns
    ]
    if existing_columns_to_drop:
        MEIR_dataframe.drop(columns=existing_columns_to_drop, inplace=True)

    col_position = MEIR_dataframe.columns.get_loc("Total Inventory X India") + 1
    MEIR_dataframe.insert(col_position, "", None)

    closing_dir = inv / "Output_Database" / "Closing Stock Analysis"
    closing_dir.mkdir(parents=True, exist_ok=True)
    closing_path = closing_dir / f"Closing Stock Analyzer-{period.report_label}.xlsx"
    MEIR_dataframe.to_excel(closing_path, index=False)
    print(f"MEIR_dataframe has been saved at location for {period.report_label}")
    print(f"  → {closing_path}")
    print(f"  rows: {len(MEIR_dataframe):,}")

    return MEIR_dataframe


# ---------------------------------------------------------------------------
# CLI / pipeline entry
# ---------------------------------------------------------------------------

def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="ESH MEIR Finance Closing Stock Analyzer")
    p.add_argument("--month", default=None, help="Report month (e.g. Nov, 11, November)")
    p.add_argument("--year", type=int, default=None, help="Report year (e.g. 2025)")
    p.add_argument(
        "--report-month",
        default=None,
        help="Shortcut Mon-YYYY (e.g. Nov-2025). Overrides --month/--year.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print resolved source paths; do not load/save.",
    )
    return p.parse_args(argv)


def resolve_period_from_args(args: argparse.Namespace) -> MeirPeriod:
    if args.report_month:
        raw = str(args.report_month).strip()
        # Nov-2025 or 2025-11
        if "-" in raw:
            parts = raw.replace("/", "-").split("-")
            if parts[0].isdigit() and len(parts[0]) == 4:
                year, month = int(parts[0]), parts[1]
            else:
                month, year = parts[0], int(parts[1])
            return build_period(parse_report_month(month, int(year)))
        raise ValueError("--report-month must look like Nov-2025")

    if args.month and args.year:
        return build_period(parse_report_month(args.month, args.year))

    return prompt_report_month(
        default_month=args.month,
        default_year=args.year,
    )


def main(argv: Optional[Sequence[str]] = None) -> pd.DataFrame:
    args = parse_args(argv)
    period = resolve_period_from_args(args)
    return run_meir(period, dry_run_paths=args.dry_run)


def run(
    *,
    client: str = "ESH",
    geos: Optional[Sequence[str]] = None,
    month: Optional[str] = None,
    year: Optional[int] = None,
    report_month: Optional[str] = None,
    dry_run: bool = False,
    **_kwargs,
) -> pd.DataFrame:
    """Pipeline CLI entrypoint."""
    del geos
    print(f"MEIR Finance report (client={client})")
    print(f"Inventory root: {inventory_root()}")

    argv = []
    if report_month:
        argv.extend(["--report-month", str(report_month)])
    else:
        if month:
            argv.extend(["--month", str(month)])
        if year:
            argv.extend(["--year", str(year)])
    if dry_run:
        argv.append("--dry-run")

    # If launched from pipeline with no month, prompt (CLI) or default (portal)
    if not report_month and not month:
        period = prompt_report_month(default_year=year)
        return run_meir(period, dry_run_paths=dry_run)

    return main(argv)


from config_manager.report_helpers import print_script_completed

if __name__ == "__main__":
    main()
    print_script_completed('a_meir_finance_report')
