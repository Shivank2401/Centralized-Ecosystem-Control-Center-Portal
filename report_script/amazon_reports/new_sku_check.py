"""
New-SKU vs COGS checklist helper for common sanity reports.

Covers:
  - Clients: ESH + KNC (per geography)
  - Compares final-frame SKUs to cogs/{client}/{geo}_amazon_cogs.parquet|.csv
  - Optional alias→master map (ON_1..ON_n) via esh/knc SKU cleaning
  - Used by manage_fba, reserved, ageing, ledger, orders, inventory_database, vector

Not a standalone pipeline stage — call check_final_dataframe_new_skus before export.

Adding a NEW client (no compare logic changes needed):
  1. Add client in client.yaml + COGS slices under cogs/{CLIENT}/
  2. Register sku cleaner in SKU_BACKEND_BY_CLIENT below ("esh" | "knc" | custom)
  3. Ensure a matching SKU cleaning module exists (or extend load_client_sku_mapping)

Style: clear steps. Compare logic unchanged.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set

import pandas as pd

from config_manager import cogs_local, esh_sku_cleaning, knc_sku_cleaning
from config_manager.report_helpers import to_snake


# =============================================================================
# Constants / client → SKU backend
# =============================================================================

_INVALID_SKUS = {"", "NAN", "NONE", "UNKNOWN", "NAT", "NULL"}

# Map client code → which SKU cleaning module to use.
# New client: add one line here (and implement cleaner if not esh/knc).
SKU_BACKEND_BY_CLIENT: Dict[str, str] = {
    "ESH": "esh",
    "KNC": "knc",
}


def _sku_backend_for(client: str) -> str:
    code = str(client).strip().upper()
    return SKU_BACKEND_BY_CLIENT.get(code, "esh")


# =============================================================================
# Helpers
# =============================================================================

def _norm_sku(value) -> str:
    return str(value).strip().upper()


def _sku_set(series: pd.Series) -> Set[str]:
    out: Set[str] = set()
    for raw in series.dropna().unique():
        sku = _norm_sku(raw)
        if sku and sku not in _INVALID_SKUS:
            out.add(sku)
    return out


def _load_client_sku_mapping(
    client: str,
    geography_code: str,
    *,
    channel: Optional[str] = None,
) -> Dict[str, str]:
    """Alias -> master SKU mapping for one client/geo."""
    geos = [str(geography_code).strip().upper()] if geography_code else None
    backend = _sku_backend_for(client)
    if backend == "knc":
        return knc_sku_cleaning.load_sku_mapping(geos=geos, channel=channel)
    return esh_sku_cleaning.load_sku_mapping(geos=geos, channel=channel)


def _mapped_frame_skus(
    series: pd.Series,
    *,
    client: str,
    geography_code: str,
    apply_mapping: bool,
    channel: Optional[str] = None,
) -> Set[str]:
    """
    Normalize frame SKUs; optionally map aliases (ON_1/ON_2/ON_3...) to master SKU.
    """
    frame_skus = _sku_set(series)
    if not apply_mapping or not frame_skus:
        return frame_skus

    mapping = _load_client_sku_mapping(client, geography_code, channel=channel)
    if not mapping:
        return frame_skus

    mapped: Set[str] = set()
    for sku in frame_skus:
        mapped.add(str(mapping.get(sku, sku)).strip().upper())
    return {s for s in mapped if s and s not in _INVALID_SKUS}


# =============================================================================
# COGS sheet SKUs
# =============================================================================

def cogs_sheet_skus(client: str, geography_code: str, channel: Optional[str] = None) -> Set[str]:
    """SKU values from that client/geo local COGS slice (the `sku` column)."""
    try:
        path = cogs_local.resolve_cogs_slice_path(client, geography_code, channel=channel)
    except FileNotFoundError as exc:
        print(f"[WARN] {exc}")
        return set()

    if path.suffix.lower() == ".parquet":
        df = pd.read_parquet(path)
    else:
        df = pd.read_csv(path)
    df = df.copy()
    df.rename(columns=lambda x: to_snake(str(x).strip()), inplace=True)
    if "sku" not in df.columns:
        print(
            f"[WARN] [{str(client).upper()}] [{str(geography_code).upper()}] "
            f"COGS sheet has no sku column ({path.name})"
        )
        return set()
    return _sku_set(df["sku"])


# =============================================================================
# Per-geo + final-frame checks
# =============================================================================

def report_new_skus_vs_cogs(
    df: pd.DataFrame,
    *,
    client: str,
    geography_code: str,
    sku_column: str = "sku",
    label: str = "",
    quiet: bool = False,
    apply_mapping: bool = True,
    channel: Optional[str] = None,
    **_ignored,
) -> List[str]:
    """
    SKUs in this geography's final dataframe that are not in that geo's COGS sheet.
    """
    tag = f"[{str(client).upper()}] [{str(geography_code).upper()}]"
    if label:
        tag = f"{tag} [{label}]"

    if df is None or df.empty or sku_column not in getattr(df, "columns", []):
        if not quiet:
            print(f"  {tag} No rows — skip new-SKU vs COGS check")
        return []

    cogs_skus = cogs_sheet_skus(client, geography_code, channel=channel)
    frame_skus = _mapped_frame_skus(
        df[sku_column],
        client=client,
        geography_code=geography_code,
        apply_mapping=apply_mapping,
        channel=channel,
    )
    missing = sorted(frame_skus - cogs_skus)
    if quiet:
        return missing
    ch = f" channel={channel}" if channel else ""
    if missing:
        print(f"  {tag} NEW SKUs not in COGS sheet ({len(missing)}){ch}:")
        preview = missing[:50]
        for sku in preview:
            print(f"    - {sku}")
        if len(missing) > 50:
            print(f"    ... +{len(missing) - 50} more")
    else:
        print(f"  {tag} No new SKUs — all present in COGS sheet{ch}")
    return missing


def check_final_dataframe_new_skus(
    df: pd.DataFrame,
    *,
    client: str,
    label: str = "",
    sku_column: str = "sku",
    geography_column: str = "geography",
    run_log=None,
    channel: Optional[str] = None,
) -> Dict[str, List[str]]:
    """
    Client + geo-wise check on the final dataframe, immediately before export.

    Groups ``df`` by geography and compares each slice to local COGS SKUs
    (``cogs/{client}/{geo}_{channel}_cogs`` when ``channel`` is set; else
    default channel / amazon stem).

    When ``run_log`` is a ReportRunLog, the same text is appended for file review.
    """
    from report_script.amazon_reports.run_logs import format_new_skus_section

    print(f"\n>>> STEP: new-SKU vs COGS [{str(client).upper()}]" + (f" ({label})" if label else ""))

    if df is None or df.empty:
        msg = f"[{str(client).upper()}] No rows — skip new-SKU vs COGS check"
        print(msg)
        if run_log is not None:
            run_log.append(msg)
        return {}
    if sku_column not in df.columns:
        msg = (
            f"[{str(client).upper()}] No '{sku_column}' column — skip new-SKU vs COGS check"
        )
        print(msg)
        if run_log is not None:
            run_log.append(msg)
        return {}

    ch_note = f" channel={channel}" if channel else ""
    print(
        f"[{str(client).upper()}] New SKUs vs COGS sheet "
        f"(final dataframe, before export){ch_note}"
    )
    alerts: Dict[str, List[str]] = {}
    if geography_column in df.columns:
        for geography, geo_df in df.groupby(geography_column, sort=True):
            code = str(geography).strip().upper()
            alerts[code] = report_new_skus_vs_cogs(
                geo_df,
                client=client,
                geography_code=code,
                sku_column=sku_column,
                label=label,
                channel=channel,
            )
    else:
        alerts["ALL"] = report_new_skus_vs_cogs(
            df,
            client=client,
            geography_code="ALL",
            sku_column=sku_column,
            label=label,
            channel=channel,
        )
    print_new_sku_rollup(client, alerts, label=label)

    from report_script.amazon_reports.run_logs import export_new_skus_csv

    csv_path = export_new_skus_csv(
        client,
        label or "unknown",
        alerts,
        started_at=getattr(run_log, "started_at", None) if run_log is not None else None,
    )
    if csv_path is not None:
        msg = (
            f"[{str(client).upper()}] Full missing-SKU list ({sum(len(v) for v in alerts.values())} row(s)): "
            f"{csv_path}"
        )
        print(msg)
        if run_log is not None:
            run_log.append(msg)

    if run_log is not None:
        run_log.blank()
        run_log.append(format_new_skus_section(client, alerts, label=label))
    return alerts


def print_new_sku_rollup(
    client: str,
    alerts: Dict[str, List[str]],
    *,
    label: str = "",
) -> None:
    """Print a short per-geo rollup when any new SKUs were found."""
    if not any(alerts.values()):
        return
    title = f"[{str(client).upper()}] New-SKU alert rollup"
    if label:
        title = f"{title} ({label})"
    print(f"\n{title}:")
    for geo, skus in sorted(alerts.items()):
        if skus:
            print(f"  {geo}: {len(skus)} SKU(s)")


# =============================================================================
# Back-compat
# =============================================================================

def cogs_master_skus(
    *,
    sku_backend: str = "",
    geography_code: str,
    sku_mapping: Optional[dict] = None,
    geos=None,
    client: str = "",
    **_ignored,
) -> Set[str]:
    _ = (sku_backend, sku_mapping, geos)
    if not client:
        client = "KNC" if str(sku_backend).strip().lower() == "knc" else "ESH"
    return cogs_sheet_skus(client, geography_code)
