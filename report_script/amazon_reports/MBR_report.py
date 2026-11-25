"""
Client-aware Amazon Monthly Business Report (MBR) - SKU + material.

Covers:
  - Clients: ESH (US, CA, UK, DE, AE, IN) and KNC (UK, DE, AE) - amazon channel
  - Inputs (sanity_data): orders, inventory_database, ageing, ledger
    Optional: returns (ESH), ads CSV (single all-geo file; filter by country per geo)
  - Metrics from monthly_business_report.ipynb (orders x inventory/ageing x
    ledger instock x ads x returns x contribution / growth / ad alerts)
  - Material roll-up via local COGS (cogs_local + geography.yaml channel)
  - Outputs: sanity_data/{CLIENT}/mbr/{GEO}_amazon_mbr_sku.parquet|.csv
             sanity_data/{CLIENT}/mbr/{GEO}_amazon_mbr_material.parquet|.csv
  - Azure: CONTAINER_NAME_{ESH|KNC}/sanity_data/mbr_report_database/{same parquet}

Ads note (notebook):
  final_adsales_grosssales.csv holds ALL geos in one file (country = USA/CA/UK/...).
  Do NOT hardcode country == "USA" - filter to the current geo on each pass.

Does not re-read raw Amazon downloads - only merges sanity slices + ads CSV.

Adding a NEW client (like ageing_report):
  1. Add client + geos in client.yaml / geography.yaml / layouts.py
  2. Add one `_xxx_config()` below and register it in CLIENT_CONFIGS
  3. List the client on this report in report.yaml

Style: step-by-step prints (>>> STEP). Notebook ETL formulas preserved.

Run:
    python report_script/amazon_reports/MBR_report.py
    python report_script/amazon_reports/MBR_report.py --client ESH
    python report_script/amazon_reports/MBR_report.py --client KNC --geos UK,DE,AE
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

import numpy as np
import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config_manager import cogs_local, layouts, paths as cfg_paths
from config_manager.loader import load_geographies
from config_manager.report_helpers import print_script_completed
from report_script.amazon_reports.azure_parquet_upload import upload_parquets_to_azure
from report_script.amazon_reports.run_logs import ReportRunLog


# =============================================================================
# Run knobs
# =============================================================================

CLIENT = "ESH"  # CLI default; pipeline passes client= via run()
PROCESS_GEOS: Optional[List[str]] = None
PROCESS_YEARS: Optional[List[str]] = None  # e.g. ["2024","2025","2026"]; None = all
SAVE_OUTPUT = True
UPLOAD_TO_AZURE = True
BUILD_MATERIAL = True

SKU_PARQUET_SUFFIX = "amazon_mbr_sku"
MATERIAL_PARQUET_SUFFIX = "amazon_mbr_material"
OUTPUT_SUBDIR = "mbr"
AZURE_BLOB_FOLDER = "sanity_data/mbr_report_database"

# Notebook default (ESH Executive all-geo ads file). Override via ESH_MBR_ADS_PATH / MBR_ADS_PATH.
_DEFAULT_ESH_ADS_PATH = Path(
    r"C:\Users\Shivank Rajput\OneDrive - Incircle Ecoproducts Pvt Ltd"
    r"\Thrivebrands- Cental Repository\Client Database\Ecosoul"
    r"\Processed Files\Executive\final_adsales_grosssales.csv"
)

ORDERS_COLS = ["geography", "sku", "quantity", "total_sales", "year_month"]
INVENTORY_COLS = [
    "geography",
    "sku",
    "date",
    "afn_fulfillable_quantity",
    "afn_inbound_receiving_quantity",
    "afn_reserved_quantity",
    "afn_unsellable_quantity",
    "afn_warehouse_quantity",
    "reserved_customer_orders",
    "reserved_fc_processing",
    "afn_fc_transfer_quantity",
]
AGEING_METRIC_COLS = [
    "fc_transfer",
    "sell_thru",
    "inv_age_0_to_30_days",
    "inv_age_31_to_60_days",
    "inv_age_61_to_90_days",
    "inv_age_91_to_180_days",
    "inv_age_181_to_270_days",
    "inv_age_271_to_365_days",
    "inv_age_365_plus_days",
    "units_shipped_t7",
    "units_shipped_t30",
    "units_shipped_t60",
    "units_shipped_t90",
    "estimated_storage_cost_next_month",
]
LEDGER_COLS = ["sku", "date", "ending_balance"]
RETURN_COLS = ["year_month", "sku", "quantity"]
ADS_COLS = [
    "sku",
    "year_month",
    "ad_sales",
    "ad_spend",
    "total_gross_sales",
    "total_revenue",
]
COGS_COLS = [
    "sku",
    "material",
    "product_category",
    "product_sub_category",
    "product_type",
    "asin",
]

# Ads CSV country labels -> portal geo codes.
# File uses USA (not US); CA/UK/DE/AE/IN match portal codes.
ADS_COUNTRY_ALIASES: Dict[str, Set[str]] = {
    "US": {"USA", "US", "UNITED STATES"},
    "CA": {"CA", "CAN", "CANADA"},
    "UK": {"UK", "GB", "GBR", "UNITED KINGDOM"},
    "DE": {"DE", "DEU", "GERMANY"},
    "AE": {"AE", "ARE", "UAE", "UNITED ARAB EMIRATES"},
    "IN": {"IN", "IND", "INDIA"},
}


# =============================================================================
# Client configuration
#   New client = copy a builder + register in CLIENT_CONFIGS (ageing style).
# =============================================================================

@dataclass
class ClientMbrConfig:
    client_code: str
    client_id: str
    client_name: str
    sku_backend: str = "esh"
    ads_env_keys: Tuple[str, ...] = ("MBR_ADS_PATH",)
    default_ads_path: Optional[Path] = None
    include_returns: bool = True


def _esh_config() -> ClientMbrConfig:
    ident = layouts.client_identity("ESH")
    return ClientMbrConfig(
        client_code=ident["client_code"],
        client_id=ident["client_id"],
        client_name=ident["client_name"],
        sku_backend="esh",
        ads_env_keys=("ESH_MBR_ADS_PATH", "MBR_ADS_PATH"),
        default_ads_path=_DEFAULT_ESH_ADS_PATH,
        include_returns=True,
    )


def _knc_config() -> ClientMbrConfig:
    ident = layouts.client_identity("KNC")
    return ClientMbrConfig(
        client_code=ident["client_code"],
        client_id=ident["client_id"],
        client_name=ident["client_name"],
        sku_backend="knc",
        ads_env_keys=("KNC_MBR_ADS_PATH", "MBR_ADS_PATH"),
        default_ads_path=None,  # set KNC_MBR_ADS_PATH when a KNC all-geo ads file exists
        include_returns=False,
    )


CLIENT_CONFIGS: Dict[str, Callable[[], ClientMbrConfig]] = {
    "ESH": _esh_config,
    "KNC": _knc_config,
}


@dataclass
class MbrConfig:
    client_code: str
    client_id: str
    client_name: str
    geos: List[str]
    sku_backend: str
    sanity_root: Path
    output_dir: Path
    ads_env_keys: Tuple[str, ...] = field(default_factory=tuple)
    default_ads_path: Optional[Path] = None
    include_returns: bool = True


def _client_geos(client: str) -> List[str]:
    return layouts.geos_with_channel(client, "amazon") or [
        str(g).upper() for g in load_geographies(client)
    ]


def get_client_config(client: str) -> ClientMbrConfig:
    key = str(client).strip().upper()
    if key not in CLIENT_CONFIGS:
        known = ", ".join(sorted(CLIENT_CONFIGS))
        raise ValueError(f"Unknown client '{client}'. Expected one of: {known}")
    return CLIENT_CONFIGS[key]()


def get_mbr_config(
    client: str,
    geos: Optional[Sequence[str]] = None,
) -> MbrConfig:
    base = get_client_config(client)
    code = base.client_code
    allowed = _client_geos(code)

    if geos:
        wanted = [str(g).strip().upper() for g in geos if str(g).strip()]
        selected = [g for g in wanted if g in allowed]
        skipped = [g for g in wanted if g not in allowed]
        if skipped:
            print(f"[WARN] [{code}] geos not in amazon channel, skipped: {skipped}")
        if not selected:
            selected = allowed
    else:
        selected = allowed

    sanity = cfg_paths.sanity_data_root() / code
    return MbrConfig(
        client_code=code,
        client_id=base.client_id,
        client_name=base.client_name,
        geos=selected,
        sku_backend=base.sku_backend,
        sanity_root=sanity,
        output_dir=sanity / OUTPUT_SUBDIR,
        ads_env_keys=base.ads_env_keys,
        default_ads_path=base.default_ads_path,
        include_returns=base.include_returns,
    )


def known_clients() -> List[str]:
    return sorted(CLIENT_CONFIGS.keys())


def output_dir_for(client_code: str) -> Path:
    return cfg_paths.sanity_data_root() / str(client_code).upper() / OUTPUT_SUBDIR


# =============================================================================
# IO helpers
# =============================================================================

def _clean_env(value: str) -> str:
    return str(value or "").strip().strip('"').strip("'")


def _resolve_geo_parquet(root: Path, folder: str, geo: str, *suffixes: str) -> Path:
    """Prefer first existing `{GEO}_{suffix}.parquet` among candidates."""
    geo_u = geo.upper()
    for suffix in suffixes:
        path = root / folder / f"{geo_u}_{suffix}.parquet"
        if path.is_file():
            return path
    return root / folder / f"{geo_u}_{suffixes[0]}.parquet"


def load_parquet_or_empty(
    path: Path,
    *,
    client: str,
    geo: str,
    label: str,
    columns: Optional[Sequence[str]] = None,
) -> pd.DataFrame:
    if not path.is_file():
        print(f"[{client}] [{geo}] {label} MISSING -> {path}")
        return pd.DataFrame()
    wanted = list(columns) if columns else None
    if wanted:
        # Read available columns only (schemas differ slightly across geos)
        peek = pd.read_parquet(path, columns=None)
        keep = [c for c in wanted if c in peek.columns]
        missing = [c for c in wanted if c not in peek.columns]
        if missing:
            print(f"[{client}] [{geo}] {label} missing cols {missing} - filled later")
        df = peek.loc[:, keep].copy() if keep else pd.DataFrame()
        del peek
    else:
        df = pd.read_parquet(path)
    print(f"[{client}] [{geo}] {label} loaded {len(df):,} rows <- {path.name}")
    return df


def _normalize_year_month(series: pd.Series) -> pd.Series:
    """Coerce year_month to sortable YYYY-MM string."""
    s = series.copy()
    if pd.api.types.is_datetime64_any_dtype(s):
        return s.dt.to_period("M").astype(str)
    # period / object
    as_dt = pd.to_datetime(s.astype(str), errors="coerce")
    out = as_dt.dt.to_period("M").astype(str)
    # keep original non-null strings that already look like YYYY-MM
    mask = out.isna() & s.notna()
    if mask.any():
        out = out.where(~mask, s.astype(str).str.slice(0, 7))
    return out


def _filter_years(df: pd.DataFrame, years: Optional[Sequence[str]]) -> pd.DataFrame:
    if df.empty or not years or "year_month" not in df.columns:
        return df
    year_set = {str(y).strip() for y in years if str(y).strip()}
    ym = df["year_month"].astype(str)
    return df.loc[ym.str.slice(0, 4).isin(year_set)].copy()


def resolve_ads_path(cfg: MbrConfig) -> Optional[Path]:
    """Env override first, then client default_ads_path (ESH notebook Executive file)."""
    for key in cfg.ads_env_keys:
        raw = _clean_env(os.getenv(key, ""))
        if raw:
            path = Path(raw)
            if path.is_file():
                return path
            print(f"[WARN] [{cfg.client_code}] {key} set but file missing: {path}")
    if cfg.default_ads_path is not None and Path(cfg.default_ads_path).is_file():
        return Path(cfg.default_ads_path)
    if cfg.default_ads_path is not None:
        print(
            f"[WARN] [{cfg.client_code}] default ads path missing: {cfg.default_ads_path}"
        )
    return None


def load_ads_master(
    ads_path: Optional[Path],
    *,
    client: str,
    client_id: str = "",
) -> pd.DataFrame:
    """
    Load the single all-geo ads CSV once (notebook final_adsales_grosssales).

    Keep country so each geo can filter later - do NOT hardcode USA.
    """
    empty_cols = list(ADS_COLS) + ["country"]
    if ads_path is None:
        print(
            f"[{client}] ads SKIPPED "
            f"(set {' / '.join(cfg_paths_ads_hint(client))} or default path)"
        )
        return pd.DataFrame(columns=empty_cols)

    print(f"\n>>> STEP: load all-geo ads CSV <- {ads_path}")
    df = pd.read_csv(ads_path)
    df.columns = [str(c).strip().lower() for c in df.columns]

    if "client_id" in df.columns and client_id:
        before = len(df)
        df = df.loc[df["client_id"].astype(str).str.strip() == str(client_id)].copy()
        print(f"  client_id={client_id}: {before:,} -> {len(df):,} rows")

    if "platform" in df.columns:
        plat = df["platform"].astype(str).str.strip().str.lower()
        df = df.loc[plat.isin({"amazon", ""}) | plat.isna()].copy()

    keep = [c for c in (*ADS_COLS, "country") if c in df.columns]
    if "sku" not in keep or "year_month" not in keep:
        print(f"[{client}] ads missing sku/year_month - skipped")
        return pd.DataFrame(columns=empty_cols)

    out = df.loc[:, keep].copy()
    out["year_month"] = _normalize_year_month(out["year_month"])
    for col in ("ad_sales", "ad_spend", "total_gross_sales", "total_revenue"):
        if col not in out.columns:
            out[col] = 0.0
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)
    if "country" not in out.columns:
        out["country"] = ""
    else:
        out["country"] = out["country"].astype(str).str.strip().str.upper()

    countries = sorted(c for c in out["country"].dropna().unique() if c)
    print(
        f"[{client}] ads master loaded {len(out):,} rows | "
        f"countries={countries} <- {ads_path.name}"
    )
    return out


def cfg_paths_ads_hint(client: str) -> Tuple[str, ...]:
    key = str(client).strip().upper()
    if key in CLIENT_CONFIGS:
        return CLIENT_CONFIGS[key]().ads_env_keys
    return ("MBR_ADS_PATH",)


def ads_for_geo(
    ads_master: pd.DataFrame,
    *,
    client: str,
    geo: str,
) -> pd.DataFrame:
    """
    Slice the all-geo ads master for one geography.

    Notebook US used country == 'USA'; multi-geo uses ADS_COUNTRY_ALIASES
    (US->USA, CA->CA, ...). Never hardcode a single country for all geos.
    """
    if ads_master is None or ads_master.empty:
        return pd.DataFrame(columns=list(ADS_COLS))

    geo_u = geo.upper()
    aliases = ADS_COUNTRY_ALIASES.get(geo_u, {geo_u})
    work = ads_master
    if "country" in work.columns:
        country = work["country"].astype(str).str.strip().str.upper()
        work = work.loc[country.isin(aliases)].copy()
        if work.empty:
            print(
                f"[{client}] [{geo}] ads: no rows for country in {sorted(aliases)}"
            )
            return pd.DataFrame(columns=list(ADS_COLS))

    metric_cols = [
        c
        for c in ("ad_sales", "ad_spend", "total_gross_sales", "total_revenue")
        if c in work.columns
    ]
    out = (
        work.groupby(["sku", "year_month"], as_index=False)[metric_cols]
        .sum()
        if metric_cols
        else work.loc[:, ["sku", "year_month"]].drop_duplicates()
    )
    for col in ("ad_sales", "ad_spend", "total_gross_sales", "total_revenue"):
        if col not in out.columns:
            out[col] = 0.0
    print(
        f"[{client}] [{geo}] ads filtered country={sorted(aliases)} -> "
        f"{len(out):,} sku-months"
    )
    return out


# =============================================================================
# Build blocks (notebook cells)
# =============================================================================

def _orders_monthly(orders: pd.DataFrame) -> pd.DataFrame:
    if orders.empty:
        return pd.DataFrame(
            columns=["geography", "year_month", "sku", "quantity", "total_sales"]
        )
    df = orders.copy()
    df["year_month"] = _normalize_year_month(df["year_month"])
    for col in ("quantity", "total_sales"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    return (
        pd.pivot_table(
            df,
            index=["geography", "year_month", "sku"],
            values=["quantity", "total_sales"],
            aggfunc="sum",
        )
        .reset_index()
    )


def _inventory_ageing_monthly(
    inventory: pd.DataFrame,
    ageing: pd.DataFrame,
) -> pd.DataFrame:
    """Latest inventory+ageing snapshot per geography/sku/month (notebook cell 13-14)."""
    if inventory.empty:
        return pd.DataFrame()

    inv = inventory.copy()
    inv["date"] = pd.to_datetime(inv["date"], errors="coerce")
    inv = inv.dropna(subset=["date", "sku"])

    age = ageing.copy() if not ageing.empty else pd.DataFrame()
    if not age.empty:
        age["date"] = pd.to_datetime(age["date"], errors="coerce")
        merge_cols = ["geography", "sku", "date"]
        age_keep = [c for c in AGEING_METRIC_COLS if c in age.columns]
        age = age.loc[:, merge_cols + age_keep].drop_duplicates(
            subset=merge_cols, keep="last"
        )
        merged = pd.merge(inv, age, on=merge_cols, how="left")
    else:
        merged = inv.copy()

    for col in AGEING_METRIC_COLS:
        if col not in merged.columns:
            merged[col] = 0
        merged[col] = pd.to_numeric(merged[col], errors="coerce").fillna(0)

    # Prefer ageing fc_transfer; fall back to inventory afn_fc_transfer_quantity
    if "afn_fc_transfer_quantity" in merged.columns:
        merged["fc_transfer"] = np.where(
            merged["fc_transfer"].fillna(0).eq(0),
            pd.to_numeric(merged["afn_fc_transfer_quantity"], errors="coerce").fillna(0),
            merged["fc_transfer"],
        )

    merged = merged.sort_values(["geography", "sku", "date"])
    monthly = (
        merged.assign(year_month=merged["date"].dt.to_period("M"))
        .groupby(["geography", "sku", "year_month"], as_index=False)
        .tail(1)
        .reset_index(drop=True)
    )
    monthly["year_month"] = monthly["year_month"].astype(str)

    rename = {
        "afn_reserved_quantity": "amazon_reserved",
        "reserved_customer_orders": "customer_reserved",
        "reserved_fc_processing": "fc_processing",
    }
    monthly = monthly.rename(columns={k: v for k, v in rename.items() if k in monthly.columns})
    for alias in ("amazon_reserved", "customer_reserved", "fc_processing"):
        if alias not in monthly.columns:
            monthly[alias] = 0
        monthly[alias] = pd.to_numeric(monthly[alias], errors="coerce").fillna(0)

    drop_cols = [
        c
        for c in (
            "date",
            "client",
            "client_id",
            "platform",
            "afn_fc_transfer_quantity",
            "afn_unsellable_quantity",
            "afn_warehouse_quantity",
            "sell_thru",
        )
        if c in monthly.columns
    ]
    return monthly.drop(columns=drop_cols, errors="ignore")


def _ledger_instock(
    ledger: pd.DataFrame,
    ageing: pd.DataFrame,
) -> pd.DataFrame:
    """EIQ from ageing sell_thru x 30; instock days / rate (notebook cells 16-21)."""
    empty = pd.DataFrame(
        columns=[
            "year_month",
            "sku",
            "days_in_stock",
            "total_days",
            "days_out_of_stock",
            "instock_rate_percent",
        ]
    )
    if ledger.empty:
        return empty

    led = ledger.copy()
    led["date"] = pd.to_datetime(led["date"], errors="coerce")
    led = led.dropna(subset=["date", "sku"])
    led["ending_balance"] = pd.to_numeric(led["ending_balance"], errors="coerce").fillna(0)

    eiq = pd.DataFrame(columns=["sku", "date", "eiq"])
    if not ageing.empty and "sell_thru" in ageing.columns:
        eiq_df = ageing.loc[:, ["sku", "date", "sell_thru"]].copy()
        eiq_df["date"] = pd.to_datetime(eiq_df["date"], errors="coerce")
        eiq_df["sell_thru"] = pd.to_numeric(eiq_df["sell_thru"], errors="coerce")
        eiq_df = (
            pd.pivot_table(
                eiq_df,
                index=["sku", "date"],
                values=["sell_thru"],
                aggfunc="mean",
            )
            .reset_index()
        )
        eiq_df["eiq"] = eiq_df["sell_thru"] * 30
        eiq_df["eiq"] = np.where(eiq_df["eiq"] < 1, 10, eiq_df["eiq"])
        eiq = eiq_df.loc[:, ["sku", "date", "eiq"]]

    process = pd.merge(led, eiq, on=["sku", "date"], how="left")
    process["eiq"] = process["eiq"].fillna(10)
    process["instock"] = np.where(process["ending_balance"] > process["eiq"], 1, 0)
    process["year_month"] = process["date"].dt.to_period("M").astype(str)

    instock_days = (
        process.groupby(["year_month", "sku"])["instock"]
        .sum()
        .reset_index(name="days_in_stock")
    )
    total_days = (
        process.groupby(["year_month", "sku"])["date"]
        .nunique()
        .reset_index(name="total_days")
    )
    overall = pd.merge(instock_days, total_days, on=["year_month", "sku"])
    overall["days_out_of_stock"] = overall["total_days"] - overall["days_in_stock"]
    overall["instock_rate_percent"] = (
        overall["days_in_stock"] / overall["total_days"] * 100
    ).round(0)
    return overall


def _returns_monthly(returns: pd.DataFrame) -> pd.DataFrame:
    if returns.empty:
        return pd.DataFrame(columns=["year_month", "sku", "return_quantity"])
    df = returns.copy()
    df["year_month"] = _normalize_year_month(df["year_month"])
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").fillna(0)
    out = (
        pd.pivot_table(
            df,
            index=["year_month", "sku"],
            values=["quantity"],
            aggfunc="sum",
        )
        .reset_index()
        .rename(columns={"quantity": "return_quantity"})
    )
    return out


def _safe_pct(numer: pd.Series, denom: pd.Series) -> pd.Series:
    out = (numer / denom) * 100
    return out.replace([np.inf, -np.inf], np.nan)


def apply_mbr_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Notebook cells 31-71: ads ratios, contribution, growth, alerts, inventory health."""
    out = df.copy()

    for col in (
        "quantity",
        "total_sales",
        "ad_sales",
        "ad_spend",
        "total_gross_sales",
        "total_revenue",
        "return_quantity",
        "afn_fulfillable_quantity",
        "afn_inbound_receiving_quantity",
        "amazon_reserved",
        "customer_reserved",
        "fc_transfer",
        "fc_processing",
        "inv_age_0_to_30_days",
        "inv_age_31_to_60_days",
        "inv_age_61_to_90_days",
        "inv_age_91_to_180_days",
        "inv_age_181_to_270_days",
        "inv_age_271_to_365_days",
        "inv_age_365_plus_days",
    ):
        if col not in out.columns:
            out[col] = 0
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0)

    out["organic_sales"] = out["total_sales"] - out["ad_sales"]
    out["organics_sales_pct"] = _safe_pct(out["organic_sales"], out["total_sales"])
    out["acos"] = _safe_pct(out["ad_spend"], out["ad_sales"])
    out["tacos"] = _safe_pct(out["ad_spend"], out["total_sales"])

    out["year_month_dt"] = pd.to_datetime(out["year_month"].astype(str), format="%Y-%m", errors="coerce")
    out = out.sort_values(["sku", "year_month_dt"])

    monthly_total_organic = out.groupby("year_month_dt")["organic_sales"].transform("sum")
    out["pct_organic_current_month"] = _safe_pct(out["organic_sales"], monthly_total_organic)
    out["pct_organic_previous_month"] = out.groupby("sku")["pct_organic_current_month"].shift(1)

    monthly_total = out.groupby("year_month_dt")["total_sales"].transform("sum")
    out["pct_contribution_current_month"] = _safe_pct(out["total_sales"], monthly_total)
    out["pct_contribution_previous_month"] = out.groupby("sku")[
        "pct_contribution_current_month"
    ].shift(1)

    out["sku_type"] = np.where(
        out["pct_contribution_current_month"] >= 5,
        "Critical",
        np.where(
            (out["pct_contribution_current_month"] >= 2)
            & (out["pct_contribution_current_month"] < 5),
            "Non-Critical",
            "Review",
        ),
    )
    out["sales_alert"] = np.where(
        (out["pct_contribution_current_month"] < out["pct_contribution_previous_month"])
        & (out["pct_contribution_current_month"] >= 2),
        "Sales Contribution Down",
        "Stable Sales",
    )
    out["organic_alert"] = np.where(
        out["pct_organic_current_month"] < out["pct_organic_previous_month"],
        "Organic Contribution Down",
        "Stable Organic",
    )

    out["sellable"] = out["afn_fulfillable_quantity"] + out["fc_transfer"]
    out["sellable_with_inbound"] = out["sellable"] + out["afn_inbound_receiving_quantity"]
    out["inventory_utilization_pct"] = np.where(
        out["sellable"].ne(0),
        (out["quantity"] / out["sellable"]) * 100,
        np.nan,
    )

    out["aged_inventory_units"] = (
        out["inv_age_181_to_270_days"]
        + out["inv_age_271_to_365_days"]
        + out["inv_age_365_plus_days"]
    )
    out["aged_inventory_pct"] = _safe_pct(out["aged_inventory_units"], out["sellable"])
    out["fresh_inventory"] = (
        out["inv_age_0_to_30_days"]
        + out["inv_age_31_to_60_days"]
        + out["inv_age_61_to_90_days"]
    )
    out["fresh_inventory_pct"] = _safe_pct(out["fresh_inventory"], out["sellable"])
    out["inventory_age_risk"] = np.select(
        [
            out["aged_inventory_pct"] > 30,
            out["aged_inventory_pct"].between(10, 30, inclusive="right"),
        ],
        ["High Risk", "Medium Risk"],
        default="Healthy",
    )

    out["prev_sales"] = out.groupby("sku")["total_sales"].shift(1)
    out["mom_growth_pct"] = _safe_pct(
        out["total_sales"] - out["prev_sales"], out["prev_sales"]
    )
    out["growth_status_mom"] = np.where(
        out["mom_growth_pct"] > 20,
        "Fast Growing",
        np.where(out["mom_growth_pct"] < -20, "Declining", "Stable"),
    )

    out["prev_year_sales"] = out.groupby("sku")["total_sales"].shift(12)
    out["yoy_growth_pct"] = _safe_pct(
        out["total_sales"] - out["prev_year_sales"], out["prev_year_sales"]
    )
    out["growth_status_yoy"] = np.where(
        out["yoy_growth_pct"] > 20,
        "Fast Growing",
        np.where(out["yoy_growth_pct"] < -20, "Declining", "Stable"),
    )

    out["ad_dependency_pct"] = _safe_pct(out["ad_sales"], out["total_sales"])
    out["ad_dependency_type"] = np.where(
        out["ad_dependency_pct"] > 70,
        "Highly Ad Dependent",
        np.where(
            (out["ad_dependency_pct"] >= 40) & (out["ad_dependency_pct"] <= 70),
            "Moderate",
            "Strong Organic SKU",
        ),
    )

    # Notebook cell 62 - fixed obvious typo: ad_dependency_pct < 0 -> < 50
    growth_ad_conditions = [
        (out["ad_dependency_pct"] > 50)
        & (out["mom_growth_pct"] > 0)
        & (out["mom_growth_pct"] <= 50),
        (out["ad_dependency_pct"] > 50) & (out["mom_growth_pct"] > 50),
        (out["ad_dependency_pct"] > 50) & (out["mom_growth_pct"] < 0),
        (out["ad_dependency_pct"] < 50)
        & (out["mom_growth_pct"] > 0)
        & (out["mom_growth_pct"] <= 50),
        (out["ad_dependency_pct"] < 50) & (out["mom_growth_pct"] > 50),
        (out["ad_dependency_pct"] < 50) & (out["mom_growth_pct"] < 0),
    ]
    growth_ad_choices = [
        "Ad Driven Growth",
        "High Growth via Ads",
        "Wasted Ad Spend",
        "Healthy Organic Growth",
        "Organic Star SKU",
        "Organic Decline",
    ]
    out["growth_ad_alert"] = np.select(
        growth_ad_conditions, growth_ad_choices, default="Stable"
    )

    ad_spend_median = out["ad_spend"].median()
    spend_conditions = [
        (out["ad_spend"] > ad_spend_median)
        & (out["mom_growth_pct"] < 0)
        & (out["pct_organic_current_month"] < 0),
        (out["ad_spend"] > ad_spend_median)
        & (out["mom_growth_pct"] >= 0)
        & (out["mom_growth_pct"] < 10)
        & (out["pct_organic_current_month"] < 0),
        (out["ad_spend"] > ad_spend_median)
        & (out["mom_growth_pct"] > 20)
        & (out["pct_organic_current_month"] > 10),
        (out["ad_spend"] < ad_spend_median)
        & (out["mom_growth_pct"] > 30)
        & (out["pct_organic_current_month"] > 20),
        (out["ad_spend"] < ad_spend_median)
        & (out["mom_growth_pct"] > 0)
        & (out["pct_organic_current_month"] < 0),
    ]
    spend_choices = [
        "Severe Wasted Spend",
        "Inefficient Ad Spend",
        "Efficient Ad Scaling",
        "Organic Strong Growth",
        "Weak Organic Momentum",
    ]
    out["spend_performance_alert"] = np.select(
        spend_conditions, spend_choices, default="Healthy"
    )

    out["overspending_alert"] = np.where(
        (out["tacos"] > 20) & (out["pct_contribution_current_month"] < 2),
        "Overspending on Low Contributor",
        "Normal",
    )

    out["prev_ad_spend"] = out.groupby("sku")["ad_spend"].shift(1)
    out["ad_spend_growth_pct"] = _safe_pct(
        out["ad_spend"] - out["prev_ad_spend"], out["prev_ad_spend"]
    )

    out["roas_current_month"] = np.where(
        out["ad_spend"] > 0, out["ad_sales"] / out["ad_spend"], np.nan
    )
    out["tacos_current_month"] = out["tacos"]
    out["tacos_previous_month"] = out.groupby("sku")["tacos"].shift(1)
    out["roas_previous_month"] = out.groupby("sku")["roas_current_month"].shift(1)

    cannibal_conditions = [
        (out["ad_spend_growth_pct"] > 40)
        & (out["pct_organic_current_month"] < out["pct_organic_previous_month"])
        & (out["mom_growth_pct"] < 5)
        & (out["tacos_current_month"] > out["tacos_previous_month"])
        & (out["roas_current_month"] < out["roas_previous_month"]),
        (out["ad_spend_growth_pct"] > 20)
        & (out["pct_organic_current_month"] < out["pct_organic_previous_month"])
        & (out["mom_growth_pct"] < 10),
    ]
    out["organic_cannibalization_alert"] = np.select(
        cannibal_conditions,
        ["Critical Cannibalization", "Moderate Cannibalization"],
        default="Healthy",
    )

    out["platform"] = "amazon"
    out["year_month"] = out["year_month_dt"].dt.to_period("M").astype(str)
    out = out.drop(columns=["year_month_dt"], errors="ignore")
    return out


def enrich_with_material(
    sku_df: pd.DataFrame,
    *,
    client: str,
    geo: str,
) -> pd.DataFrame:
    if sku_df.empty:
        return sku_df
    try:
        item = cogs_local.load_cogs_frames(
            client,
            geos=[geo],
            channel="amazon",
            columns=list(COGS_COLS),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[{client}] [{geo}] COGS material enrich skipped: {exc}")
        return sku_df

    if item.empty:
        print(f"[{client}] [{geo}] COGS empty - material columns left blank")
        for col in COGS_COLS:
            if col != "sku" and col not in sku_df.columns:
                sku_df[col] = np.nan
        return sku_df

    item = item.drop_duplicates(subset=["sku"], keep="last")
    merged = pd.merge(sku_df, item, on="sku", how="left")
    print(
        f"[{client}] [{geo}] material enrich matched "
        f"{merged['material'].notna().sum():,}/{len(merged):,} rows"
    )
    return merged


def build_material_mbr(sku_df: pd.DataFrame) -> pd.DataFrame:
    """Notebook material pivot (cells 84+) - sum numeric metrics by material dims."""
    if sku_df.empty or "material" not in sku_df.columns:
        return pd.DataFrame()

    index_cols = [
        c
        for c in (
            "geography",
            "year_month",
            "material",
            "product_category",
            "product_sub_category",
            "product_type",
        )
        if c in sku_df.columns
    ]
    value_cols = [
        c
        for c in (
            "quantity",
            "total_sales",
            "return_quantity",
            "afn_fulfillable_quantity",
            "amazon_reserved",
            "customer_reserved",
            "fc_transfer",
            "fc_processing",
            "afn_inbound_receiving_quantity",
            "inv_age_0_to_30_days",
            "inv_age_31_to_60_days",
            "inv_age_61_to_90_days",
            "inv_age_91_to_180_days",
            "inv_age_181_to_270_days",
            "inv_age_271_to_365_days",
            "inv_age_365_plus_days",
            "units_shipped_t7",
            "units_shipped_t30",
            "units_shipped_t60",
            "units_shipped_t90",
            "estimated_storage_cost_next_month",
            "total_revenue",
            "ad_spend",
            "ad_sales",
            "total_gross_sales",
            "organic_sales",
            "days_in_stock",
            "total_days",
            "days_out_of_stock",
        )
        if c in sku_df.columns
    ]
    if not index_cols or not value_cols:
        return pd.DataFrame()

    work = sku_df.dropna(subset=["material"]).copy()
    if work.empty:
        return pd.DataFrame()

    for col in value_cols:
        work[col] = pd.to_numeric(work[col], errors="coerce").fillna(0)

    material = (
        pd.pivot_table(
            work,
            index=index_cols,
            values=value_cols,
            aggfunc="sum",
        )
        .reset_index()
    )

    material["sellable"] = material.get("afn_fulfillable_quantity", 0) + material.get(
        "fc_transfer", 0
    )
    material["sellable_with_inbound"] = material["sellable"] + material.get(
        "afn_inbound_receiving_quantity", 0
    )
    material["inventory_utilization_pct"] = np.where(
        material["sellable"].ne(0),
        (material["quantity"] / material["sellable"]) * 100,
        np.nan,
    )
    material["organic_sales"] = material.get("total_sales", 0) - material.get("ad_sales", 0)
    material["acos"] = _safe_pct(material.get("ad_spend", 0), material.get("ad_sales", 0))
    material["tacos"] = _safe_pct(material.get("ad_spend", 0), material.get("total_sales", 0))
    material["platform"] = "amazon"
    return material


# =============================================================================
# Per-geography pipeline
# =============================================================================

def build_geography_mbr(
    cfg: MbrConfig,
    geo: str,
    *,
    years: Optional[Sequence[str]] = None,
    ads_master: Optional[pd.DataFrame] = None,
    build_material: bool = True,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    client = cfg.client_code
    print(f"\n>>> STEP: [{client}] {geo} - load sanity inputs")

    orders = load_parquet_or_empty(
        _resolve_geo_parquet(
            cfg.sanity_root, "orders", geo, "amazon_orders_database", "orders_database"
        ),
        client=client,
        geo=geo,
        label="orders",
        columns=ORDERS_COLS,
    )
    inventory = load_parquet_or_empty(
        _resolve_geo_parquet(
            cfg.sanity_root,
            "inventory_database",
            geo,
            "amazon_inventory_database",
            "inventory_database",
        ),
        client=client,
        geo=geo,
        label="inventory_database",
        columns=INVENTORY_COLS,
    )
    ageing = load_parquet_or_empty(
        _resolve_geo_parquet(
            cfg.sanity_root, "ageing", geo, "amazon_ageing_inventory", "ageing_inventory"
        ),
        client=client,
        geo=geo,
        label="ageing",
    )
    ledger = load_parquet_or_empty(
        _resolve_geo_parquet(
            cfg.sanity_root,
            "ledger",
            geo,
            "amazon_ledger_inventory",
            "ledger_inventory",
        ),
        client=client,
        geo=geo,
        label="ledger",
        columns=LEDGER_COLS,
    )

    returns = pd.DataFrame()
    if cfg.include_returns:
        returns = load_parquet_or_empty(
            _resolve_geo_parquet(
                cfg.sanity_root,
                "returns",
                geo,
                "amazon_return_database",
                "return_database",
            ),
            client=client,
            geo=geo,
            label="returns",
            columns=RETURN_COLS,
        )
    else:
        print(f"[{client}] [{geo}] returns SKIPPED (client config)")

    if orders.empty:
        print(f"[{client}] [{geo}] skip - orders required and empty")
        return pd.DataFrame(), pd.DataFrame()

    print(f">>> STEP: [{client}] {geo} - orders monthly pivot")
    orders_m = _filter_years(_orders_monthly(orders), years)

    print(f">>> STEP: [{client}] {geo} - inventory x ageing monthly snapshot")
    inv_m = _filter_years(_inventory_ageing_monthly(inventory, ageing), years)

    print(f">>> STEP: [{client}] {geo} - ledger instock / EIQ")
    ledger_m = _filter_years(_ledger_instock(ledger, ageing), years)

    print(f">>> STEP: [{client}] {geo} - merge orders x ledger x inventory")
    merged = pd.merge(orders_m, ledger_m, on=["year_month", "sku"], how="left")
    if not inv_m.empty:
        inv_join = inv_m.drop(columns=["geography"], errors="ignore")
        merged = pd.merge(merged, inv_join, on=["year_month", "sku"], how="left")
    merged["geography"] = geo.upper()

    print(f">>> STEP: [{client}] {geo} - ads merge (filter country for this geo)")
    ads = ads_for_geo(
        ads_master if ads_master is not None else pd.DataFrame(),
        client=client,
        geo=geo,
    )
    if not ads.empty:
        merged = pd.merge(merged, ads, on=["year_month", "sku"], how="left")
    for col in ("ad_sales", "ad_spend", "total_gross_sales", "total_revenue"):
        if col not in merged.columns:
            merged[col] = 0.0
        merged[col] = pd.to_numeric(merged[col], errors="coerce").fillna(0.0)

    print(f">>> STEP: [{client}] {geo} - returns merge")
    ret_m = _returns_monthly(returns)
    if not ret_m.empty:
        merged = pd.merge(merged, ret_m, on=["year_month", "sku"], how="left")
    if "return_quantity" not in merged.columns:
        merged["return_quantity"] = 0
    merged["return_quantity"] = pd.to_numeric(
        merged["return_quantity"], errors="coerce"
    ).fillna(0)

    print(f">>> STEP: [{client}] {geo} - MBR metrics + alerts")
    sku_df = apply_mbr_metrics(merged)
    sku_df["client"] = client
    sku_df["client_id"] = cfg.client_id
    sku_df["geography"] = geo.upper()

    print(f">>> STEP: [{client}] {geo} - COGS material enrich")
    sku_df = enrich_with_material(sku_df, client=client, geo=geo)

    material_df = pd.DataFrame()
    if build_material:
        print(f">>> STEP: [{client}] {geo} - material roll-up")
        material_df = build_material_mbr(sku_df)
        if not material_df.empty:
            material_df["client"] = client
            material_df["client_id"] = cfg.client_id
            material_df["geography"] = geo.upper()

    print(
        f"[{client}] [{geo}] SKU MBR rows={len(sku_df):,} "
        f"material rows={len(material_df):,}"
    )
    return sku_df, material_df


# =============================================================================
# Save
# =============================================================================

def save_geography_outputs(
    df: pd.DataFrame,
    output_dir: Path,
    *,
    name_suffix: str,
) -> List[Path]:
    if df.empty:
        return []
    if "geography" not in df.columns:
        raise KeyError("Expected 'geography' column")

    output_dir.mkdir(parents=True, exist_ok=True)
    saved: List[Path] = []
    print(f"\n>>> STEP: save {name_suffix} -> {output_dir}")
    for geography, geo_df in df.groupby("geography", sort=True):
        geo_name = str(geography).upper()
        parquet_path = output_dir / f"{geo_name}_{name_suffix}.parquet"
        csv_path = output_dir / f"{geo_name}_{name_suffix}.csv"
        geo_df.to_parquet(parquet_path, index=False)
        geo_df.to_csv(csv_path, index=False)
        saved.extend([parquet_path, csv_path])
        print(
            f"  [{geo_name}] {len(geo_df):,} rows -> "
            f"{parquet_path.name}, {csv_path.name}"
        )
    return saved


# =============================================================================
# Build pipeline
# =============================================================================

def build_mbr_report(
    *,
    client: str = CLIENT,
    geos: Optional[Sequence[str]] = None,
    years: Optional[Sequence[str]] = None,
    save_output: bool = SAVE_OUTPUT,
    upload_to_azure: bool = UPLOAD_TO_AZURE,
    build_material: bool = BUILD_MATERIAL,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    cfg = get_mbr_config(client, geos)
    years = PROCESS_YEARS if years is None and PROCESS_YEARS is not None else years
    ads_path = resolve_ads_path(cfg)

    print("=" * 60)
    print(f"Client : {cfg.client_code} ({cfg.client_name})")
    print(f"Script : {Path(__file__).resolve()}")
    print(f"ID     : {cfg.client_id}")
    print(f"Geos   : {cfg.geos}")
    print(f"Years  : {list(years) if years else 'ALL'}")
    print(f"Sanity : {cfg.sanity_root}")
    print(f"Output : {cfg.output_dir}")
    print(f"Ads    : {ads_path or '(none - ad metrics will be 0)'}")
    print(f"Azure  : {upload_to_azure}")
    print("=" * 60)

    # One all-geo ads file; each geo filters country (USA/CA/UK/...) - not hardcoded USA
    ads_master = load_ads_master(
        ads_path,
        client=cfg.client_code,
        client_id=cfg.client_id,
    )

    sku_frames: List[pd.DataFrame] = []
    material_frames: List[pd.DataFrame] = []
    run_log = ReportRunLog(cfg.client_code, "mbr")
    try:
        for geo in cfg.geos:
            try:
                sku_df, material_df = build_geography_mbr(
                    cfg,
                    geo,
                    years=years,
                    ads_master=ads_master,
                    build_material=build_material,
                )
                if not sku_df.empty:
                    sku_frames.append(sku_df)
                if not material_df.empty:
                    material_frames.append(material_df)
                run_log.append(
                    f"[{cfg.client_code}] [{geo}] "
                    f"sku={len(sku_df):,} material={len(material_df):,}"
                )
            except Exception as exc:  # noqa: BLE001
                print(f"[{cfg.client_code}] [{geo}] ERROR: {exc}")
                run_log.append(f"[{cfg.client_code}] [{geo}] ERROR: {exc}")

        sku_master = (
            pd.concat(sku_frames, ignore_index=True, sort=False)
            if sku_frames
            else pd.DataFrame()
        )
        material_master = (
            pd.concat(material_frames, ignore_index=True, sort=False)
            if material_frames
            else pd.DataFrame()
        )
        print(
            f"\n[{cfg.client_code}] combined MBR "
            f"geos_ok={len(sku_frames)}/{len(cfg.geos)} "
            f"sku_rows={len(sku_master):,} material_rows={len(material_master):,}"
        )
        run_log.append(
            f"[{cfg.client_code}] combined MBR "
            f"geos_ok={len(sku_frames)}/{len(cfg.geos)} "
            f"sku_rows={len(sku_master):,} material_rows={len(material_master):,}"
        )

        if save_output:
            saved: List[Path] = []
            if not sku_master.empty:
                saved.extend(
                    save_geography_outputs(
                        sku_master, cfg.output_dir, name_suffix=SKU_PARQUET_SUFFIX
                    )
                )
            if not material_master.empty:
                saved.extend(
                    save_geography_outputs(
                        material_master,
                        cfg.output_dir,
                        name_suffix=MATERIAL_PARQUET_SUFFIX,
                    )
                )
            if upload_to_azure and saved:
                upload_parquets_to_azure(
                    saved,
                    client_code=cfg.client_code,
                    blob_folder=AZURE_BLOB_FOLDER,
                    label="mbr parquet",
                )
    finally:
        run_log.flush()

    print("-" * 60)
    print(
        f"Done. SKU shape: {sku_master.shape} | "
        f"Material shape: {material_master.shape}"
    )
    return sku_master, material_master


# =============================================================================
# CLI / pipeline entry
# =============================================================================

def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Client-wise Amazon Monthly Business Report (MBR)"
    )
    parser.add_argument("--client", default=CLIENT, choices=known_clients())
    parser.add_argument("--geos", default=None, help="Comma-separated geo codes")
    parser.add_argument("--years", default=None, help="Comma-separated years")
    parser.add_argument("--no-save", action="store_true")
    parser.add_argument("--no-material", action="store_true")
    parser.add_argument(
        "--no-azure",
        action="store_true",
        help="Skip uploading saved parquet files to Azure",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> Tuple[pd.DataFrame, pd.DataFrame]:
    args = parse_args(argv)
    geos = (
        [g.strip() for g in str(args.geos).split(",") if g.strip()]
        if args.geos
        else None
    )
    years = (
        [y.strip() for y in str(args.years).split(",") if y.strip()]
        if args.years
        else None
    )
    sku_master, material_master = build_mbr_report(
        client=args.client,
        geos=geos if geos else PROCESS_GEOS,
        years=years,
        save_output=not args.no_save,
        upload_to_azure=UPLOAD_TO_AZURE and not args.no_azure,
        build_material=BUILD_MATERIAL and not args.no_material,
    )
    if not sku_master.empty:
        print(sku_master.shape)
        print(sku_master.head())
        print(sku_master.columns.tolist())
    return sku_master, material_master


def run(
    *,
    client: str = CLIENT,
    geos: Optional[Sequence[str]] = None,
    years: Optional[Sequence[str]] = None,
    **_kwargs,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Pipeline CLI entrypoint: run(client='ESH', geos=['US','UK'])."""
    return main(
        layouts.cli_argv(
            client=client,
            geos=list(geos) if geos else None,
            years=list(years) if years else None,
        )
    )


if __name__ == "__main__":
    main()
    print_script_completed("MBR_report")
