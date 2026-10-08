#!/usr/bin/env python3
"""
ESH Amazon Shipping Queue — download, SKU-map, clean, upload by country.

Covers:
  - Client: ESH — geos from pipeline/CLI (or geography.yaml amazon geos)
  - Raw Azure: CONTAINER_NAME_ESH → data_dump/shipping_queue/amazon/...
  - SKU map: esh_sku_cleaning (same as orders_report) via local cogs slices
  - Local: sanity_data/ESH/shipping_queue/{GEO}_amazon_shipping_queue.parquet|.csv
  - Azure out: CONTAINER_NAME_ESH → sanity_data/shipping_queue/{GEO}_amazon_shipping_queue.csv|.parquet

Style: step-by-step prints (>>> STEP). Clean/discrepancy formulas unchanged.

Run:
    python report_script/shipping_queue/esh_shipping_queue.py
    python report_script/shipping_queue/esh_shipping_queue.py --countries US,AE
    # pipeline: run(client='ESH', geos=['US'])
"""

from __future__ import annotations

import argparse
import io
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from io import StringIO
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd
from azure.storage.blob import BlobServiceClient, ContentSettings
from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config_manager import esh_sku_cleaning, layouts, paths
from config_manager.report_helpers import print_script_completed
from report_script.amazon_reports.azure_parquet_upload import (
    azure_connection_string,
    azure_container_for_client,
)

# =============================================================================
# Client configuration (ESH — KNC lives in knc_shipping_queue.py)
# =============================================================================

CLIENT = "ESH"


@dataclass(frozen=True)
class ShippingQueueClientConfig:
    client_code: str
    local_file_prefix: str


def _esh_config() -> ShippingQueueClientConfig:
    return ShippingQueueClientConfig(
        client_code="ESH",
        local_file_prefix="ESH",
    )


CLIENT_CONFIGS: Dict[str, Callable[[], ShippingQueueClientConfig]] = {
    "ESH": _esh_config,
}


def get_client_config(client: str = CLIENT) -> ShippingQueueClientConfig:
    key = str(client).strip().upper()
    if key not in CLIENT_CONFIGS:
        known = ", ".join(sorted(CLIENT_CONFIGS))
        raise ValueError(f"esh_shipping_queue supports {known} only (got '{client}')")
    return CLIENT_CONFIGS[key]()


# =============================================================================
# STORAGE PATHS — where files live (input vs output)
# =============================================================================
#
# RAW INPUT (container CONTAINER_NAME_ESH):
#   data_dump/shipping_queue/amazon/YYYY/MM/DD/{cc}_shipments_summary.csv
#
# COGS / SKU MAPPING:
#   esh_sku_cleaning.load_sku_mapping / clean_sku_column (local cogs slices)
#
# LOCAL OUTPUT (orders-style):
#   sanity_data/{CLIENT}/shipping_queue/{GEO}_amazon_shipping_queue.parquet|.csv
#
# AZURE OUTPUT (CONTAINER_NAME_ESH | CONTAINER_NAME_KNC):
#   sanity_data/shipping_queue/{GEO}_amazon_shipping_queue.csv|.parquet

OUTPUT_SUBDIR = "shipping_queue"
NAME_SUFFIX = "amazon_shipping_queue"
AZURE_BLOB_FOLDER = "sanity_data/shipping_queue"


def output_dir_for(client_code: str = CLIENT) -> Path:
    """Local root: sanity_data/{CLIENT}/shipping_queue (mirrors orders)."""
    return paths.sanity_data_root() / str(client_code).strip().upper() / OUTPUT_SUBDIR


def country_output_stem(country_code: str) -> str:
    """e.g. US_amazon_shipping_queue (uppercase country code + suffix)."""
    return f"{normalize_country_code(country_code).upper()}_{NAME_SUFFIX}"


DEFAULT_OUTPUT_FOLDER = str(output_dir_for(CLIENT))

# =============================================================================
# COLUMN DEFINITIONS — raw Amazon export → cleaned snake_case names
# =============================================================================

REQUIRED_COLS = [
    "shipmentId",
    "shipmentName",
    "destinationFC",
    "shipmentStatus",
    "mskus",
    "CREATING_date",
    "RECEIVING_date",
    "SHIPPED_date",
    "CLOSED_date",
    "merchantSKU",
    "expectedQuantity_item",
    "totalReceivedQuantity",
    "totalDiscrepancyQuantity",
]

# dict rename: old_key → new_key (pandas .rename(columns=...))
COL_RENAME = {
    "shipmentName": "shipment_name",
    "shipmentId": "shipment_id",
    "destinationFC": "destination_fc",
    "shipmentStatus": "shipment_status",
    "mskus": "total_skus",
    "CREATING_date": "creating_date",
    "RECEIVING_date": "receiving_date",
    "SHIPPED_date": "shipped_date",
    "CLOSED_date": "closed_date",
    "merchantSKU": "sku",
    "expectedQuantity_item": "total_expected_quantity",
    "totalReceivedQuantity": "total_received_quantity",
    "totalDiscrepancyQuantity": "total_discrepancy_quantity",
}

# Parsed to YYYY-MM-DD strings after cleaning
DATE_COLS = ["creating_date", "receiving_date", "shipped_date", "closed_date"]

# =============================================================================
# GEOGRAPHY — pipeline/CLI geos (SKU cleaning uses esh_sku_cleaning + local COGS)
# =============================================================================


def _clean_env(value: str) -> str:
    return value.strip().strip('"').strip("'").strip(",").strip()


def normalize_country_code(country_code: str) -> str:
    """Standard 2-letter ISO country code, lowercase (e.g. us, ae, uk)."""
    cc = (country_code or "").strip().lower()
    if len(cc) != 2 or not cc.isalpha():
        raise ValueError(
            f"country_code must be a 2-letter code (e.g. 'us', 'ae'), got: {country_code!r}"
        )
    return cc


def get_client_id(client_code: str = CLIENT) -> str:
    """Client identifier appended to Azure CSV/Parquet exports."""
    env_id = _clean_env(os.getenv("CLIENT_ID", ""))
    if env_id:
        return env_id
    return str(layouts.client_identity(client_code).get("client_id") or "").strip()


def dataframe_with_client_id(df: pd.DataFrame, client_code: str = CLIENT) -> pd.DataFrame:
    """Add client_id as the first column (Azure / local parquet exports)."""
    out = df.copy()
    if "client_id" in out.columns:
        out = out.drop(columns=["client_id"])
    client_id = get_client_id(client_code)
    if client_id:
        out.insert(0, "client_id", client_id)
    return out


def default_amazon_geos(client_code: str = CLIENT) -> List[str]:
    """Amazon geos from geography.yaml / layouts (no .env cogs_sheet_* needed)."""
    sheets = layouts.cogs_sheets_for(client_code, channel="amazon") or {}
    codes: List[str] = []
    for geo in sheets.keys():
        try:
            codes.append(normalize_country_code(str(geo)))
        except ValueError:
            continue
    return sorted(set(codes))


def resolve_geographies(
    requested: Optional[Sequence[str]] = None,
    *,
    client_code: str = CLIENT,
) -> dict[str, dict[str, str]]:
    """
    Build { 'us': {'country_code': 'us'}, ... }.

    Prefer explicit pipeline/CLI geos; otherwise all amazon geos for the client.
    """
    if requested:
        tokens = [str(g).strip() for g in requested if str(g).strip()]
        if tokens and not any(t.lower() == "all" for t in tokens):
            geos: dict[str, dict[str, str]] = {}
            unknown: List[str] = []
            for raw in tokens:
                try:
                    code = normalize_country_code(raw)
                except ValueError:
                    unknown.append(raw)
                    continue
                geos[code] = {"country_code": code}
            if unknown:
                print(f"Unknown/invalid countries skipped: {', '.join(unknown)}")
            return geos

    geos = {
        code: {"country_code": code}
        for code in default_amazon_geos(client_code)
    }
    return geos


# =============================================================================
# AZURE — connection settings from .env
# =============================================================================


def load_azure_settings() -> tuple[str, str]:
    """Return (connection_string, CONTAINER_NAME_ESH) from environment."""
    conn = azure_connection_string()
    container = azure_container_for_client(CLIENT)
    return conn, container


def load_raw_shipping_container() -> str:
    """Container for raw shipping queue CSVs (CONTAINER_NAME_ESH)."""
    return _clean_env(os.getenv("CONTAINER_NAME_ESH", ""))


# =============================================================================
# AZURE — resolve raw shipping queue blob path (with lookback)
# =============================================================================


def azure_shipping_queue_csv_blob_path(
    *,
    country_code: str,
    blob_service_client: BlobServiceClient,
    container_name: str,
    day: date | datetime | None = None,
    channel: str = "amazon",
    max_lookback_days: int = 10,
) -> str:
    """
    Walk backward from `day` (default: today) until a blob exists.

    Country codes are normalized to lowercase for further processing.
    Blob filenames are tried as both lowercase and uppercase (Azure is case-sensitive;
    older dumps used US_..., newer ones use us_...).
    """
    cc_raw = (country_code or "").strip()
    if not cc_raw:
        raise ValueError("country_code is required (e.g. 'uk').")
    cc = cc_raw.lower()

    # channel is accepted for API compatibility; paths are Amazon-only today.
    _ = (channel or "amazon").strip().lower() or "amazon"

    d = day.date() if isinstance(day, datetime) else (day or datetime.now().date())
    container_client = blob_service_client.get_container_client(container_name)

    for i in range(max_lookback_days):
        check_date = d - timedelta(days=i)
        base = (
            f"data_dump/shipping_queue/amazon/{check_date:%Y}/{check_date:%m}/{check_date:%d}/"
        )
        # Prefer lowercase; fall back to uppercase for older dumps.
        for name_cc in (cc, cc.upper()):
            blob_path = f"{base}{name_cc}_shipments_summary.csv"
            print(f"Checking blob path: {container_name}/{blob_path}")
            blob_client = container_client.get_blob_client(blob_path)
            if blob_client.exists():
                print(f"Found shipping queue file for date: {check_date}")
                return blob_path

    raise FileNotFoundError(
        f"No shipping queue file found for last {max_lookback_days} days for {cc} "
        f"in container '{container_name}'"
    )


# =============================================================================
# AZURE — download raw CSV into a pandas DataFrame
# =============================================================================


def download_shipping_queue_csv(
    *,
    country_code: str,
    day: date | datetime | None = None,
    connection_string: str | None = None,
    container: str | None = None,
    blob_path: str | None = None,
    max_lookback_days: int = 10,
    channel: str = "amazon",
) -> pd.DataFrame:
    """
    Download the latest available shipping queue CSV from Azure Blob.

    Uses azure_shipping_queue_csv_blob_path() unless blob_path is passed explicitly.
    """
    conn, _helper_cont = load_azure_settings()
    conn_use = _clean_env(connection_string or conn)
    cont_use = _clean_env(container or load_raw_shipping_container())
    if not conn_use:
        raise ValueError("AZURE_STORAGE_CONNECTION_STRING is missing in .env")
    if not cont_use:
        raise ValueError(
            "CONTAINER_NAME_ESH is missing in .env "
            "(raw shipping CSVs container, e.g. thrive-client-ecosoulhome)"
        )

    bsc = BlobServiceClient.from_connection_string(conn_use)
    cc = normalize_country_code(country_code)

    if blob_path:
        blob = blob_path
        print(f"[download] Using explicit blob: {cont_use}/{blob}")
    else:
        print(
            f"[download] Resolving blob for {cc} in container '{cont_use}' "
            f"(lookback={max_lookback_days} days)"
        )
        blob = azure_shipping_queue_csv_blob_path(
            country_code=cc,
            blob_service_client=bsc,
            container_name=cont_use,
            day=day,
            channel=channel,
            max_lookback_days=max_lookback_days,
        )
        print(f"[download] Resolved: {cont_use}/{blob}")

    raw_bytes = bsc.get_blob_client(container=cont_use, blob=blob).download_blob().readall()
    if not raw_bytes:
        return pd.DataFrame()
    text = raw_bytes.decode("utf-8", errors="replace").strip()
    if not text:
        return pd.DataFrame()
    return pd.read_csv(StringIO(text))


# =============================================================================
# COGS / SKU — same path as orders_report (esh_sku_cleaning + local cogs slices)
# =============================================================================


def load_sku_mapping_for_country(country_code: str) -> dict[str, str]:
    """Load alias → master SKU map for one geo via esh_sku_cleaning (local COGS)."""
    cc = normalize_country_code(country_code)
    return esh_sku_cleaning.load_sku_mapping(geos=[cc.upper()], channel="amazon")


# =============================================================================
# TRANSFORM — date parsing
# =============================================================================


def parse_dates(df: pd.DataFrame) -> pd.DataFrame:
    """
    Convert date columns to consistent YYYY-MM-DD strings.

    pd.to_datetime(..., errors='coerce') — invalid values become NaT.
    dayfirst=True — handles DD/MM/YYYY style exports common outside US.
    """
    out = df.copy()
    for col in DATE_COLS:
        if col not in out.columns:
            continue
        cleaned = out[col].replace(["", "nan", "None", "NaT", "NaN"], None)
        out[col] = (
            pd.to_datetime(cleaned, errors="coerce", dayfirst=True)
            .dt.strftime("%Y-%m-%d")
        )
    return out


# =============================================================================
# TRANSFORM — core shipping queue cleaning logic
# =============================================================================


def process_shipping_queue(
    raw_df: pd.DataFrame,
    *,
    sku_mapping: dict[str, str],
) -> pd.DataFrame:
    """
    Clean one raw shipping queue export.

    Steps:
      1. Keep only known columns, rename to snake_case.
      2. Normalize shipment_status to Title Case ("in_transit" → "In Transit").
      3. Recompute discrepancy only for Closed / Receiving statuses.
      4. Parse dates, strip trailing dashes from SKU, apply COGS mapping.
    """
    if raw_df is None or raw_df.empty:
        return pd.DataFrame()

    keep = [c for c in REQUIRED_COLS if c in raw_df.columns]
    if not keep:
        print("[process] None of the expected columns found in raw file.")
        return pd.DataFrame()

    main = raw_df.loc[:, keep].copy()
    main = main.rename(columns=COL_RENAME)

    if "sku" not in main.columns:
        return pd.DataFrame()

    # --- Shipment status: human-readable Title Case ---
    if "shipment_status" in main.columns:
        raw_status = main["shipment_status"].astype(str).str.strip()
        # Regex: collapse underscores/hyphens to spaces, then title-case
        norm = (
            raw_status.str.replace(r"[\-_]+", " ", regex=True)
            .str.replace(r"\s+", " ", regex=True)
            .str.strip()
            .str.title()
        )
        main["shipment_status"] = norm

        # Discrepancy: only meaningful when shipment is Closed or still Receiving
        # np.where(condition, value_if_true, value_if_false)
        status_check = ["Closed", "Receiving"]
        if {"total_expected_quantity", "total_received_quantity"}.issubset(main.columns):
            main["total_discrepancy_quantity"] = np.where(
                main["shipment_status"].isin(status_check),
                main["total_expected_quantity"] - main["total_received_quantity"],
                0,
            )

    main = parse_dates(main)

    # Strip trailing single/double dash from SKU (Amazon listing quirk)
    main["sku"] = (
        main["sku"].astype(str).str.replace(r"-{1,2}$", "", regex=True).str.strip()
    )

    # Same cleaner as orders_report, but keep merchant SKU when cleaner yields null
    # (shipping queue must retain shipment lines; orders drops missing more aggressively).
    before_sku = main["sku"].astype(str).str.strip()
    rows_before = len(main)
    main = esh_sku_cleaning.clean_sku_column(
        main,
        sku_column="sku",
        sku_mapping=sku_mapping,
        drop_missing=False,
    )
    still_missing = main["sku"].isna()
    if still_missing.any():
        restored = before_sku.loc[still_missing].str.upper()
        restored = restored.replace({"NAN": np.nan, "NONE": np.nan, "": np.nan})
        main.loc[still_missing, "sku"] = restored
        print(
            f"  Kept {int(still_missing.sum()):,} merchant SKU(s) without COGS master match"
        )
    main = main[main["sku"].notna()].copy()
    dropped = rows_before - len(main)
    if dropped:
        print(f"  Dropped {dropped:,} row(s) with empty SKUs")
    main["platform"] = "amazon"
    return main


# =============================================================================
# OUTPUT — save local CSV (append + dedupe) and upload processed files to Azure
# =============================================================================


def dedupe_keys(df: pd.DataFrame) -> list[str]:
    """Stable row identity for append merges."""
    candidates = [
        "shipment_id",
        "sku",
        "destination_fc",
        "shipment_status",
        "creating_date",
    ]
    return [c for c in candidates if c in df.columns]


def save_local_csv(df: pd.DataFrame, output_path: str) -> pd.DataFrame:
    """
    Write CSV locally. If file exists, append and dedupe (keep latest row).

    pd.concat — stack old + new rows.
    drop_duplicates(subset=..., keep='last') — last run wins on conflicts.
    """
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    if os.path.exists(output_path):
        try:
            existing = pd.read_csv(output_path)
            combined = pd.concat([existing, df], ignore_index=True, sort=False)
            keys = dedupe_keys(combined)
            if keys:
                combined = combined.drop_duplicates(subset=keys, keep="last")
            else:
                combined = combined.drop_duplicates(keep="last")
            final_df = combined
        except Exception as exc:
            print(f"[save] Append failed ({exc}); overwriting.")
            final_df = df
    else:
        final_df = df

    final_df.to_csv(output_path, index=False)
    return final_df


def local_output_paths(country_code: str, output_dir: Path | None = None) -> tuple[Path, Path]:
    """
    Local CSV + parquet paths:
      sanity_data/ESH/shipping_queue/{COUNTRY_CODE}_amazon_shipping_queue.parquet|.csv
    """
    out = Path(output_dir) if output_dir else output_dir_for(CLIENT)
    stem = country_output_stem(country_code)
    return out / f"{stem}.csv", out / f"{stem}.parquet"


def save_local_outputs(
    df: pd.DataFrame,
    country_code: str,
    output_dir: Path | None = None,
    *,
    client_code: str = CLIENT,
) -> tuple[pd.DataFrame, Path, Path]:
    """Save CSV (append+dedupe) and parquet (overwrite) with client_id."""
    csv_path, pq_path = local_output_paths(country_code, output_dir)
    upload_df = dataframe_with_client_id(df, client_code)

    final_df = save_local_csv(upload_df, str(csv_path))
    # Re-apply client_id after append merge, then write both formats
    final_df = dataframe_with_client_id(final_df, client_code)
    final_df.to_csv(csv_path, index=False)
    pq_path.parent.mkdir(parents=True, exist_ok=True)
    final_df.to_parquet(pq_path, index=False, engine="pyarrow")
    print(f"[save] Local CSV ({len(final_df)} rows): {csv_path}")
    print(f"[save] Local parquet ({len(final_df)} rows): {pq_path}")
    return final_df, csv_path, pq_path


def upload_outputs_to_azure(
    df: pd.DataFrame,
    country_code: str,
    *,
    csv_path: Optional[Path] = None,
    parquet_path: Optional[Path] = None,
    client_code: str = CLIENT,
) -> list[str]:
    """
    Upload cleaned queue to CONTAINER_NAME_ESH|KNC:

      sanity_data/shipping_queue/{COUNTRY_CODE}_amazon_shipping_queue.csv
      sanity_data/shipping_queue/{COUNTRY_CODE}_amazon_shipping_queue.parquet
    """
    conn = azure_connection_string()
    container = azure_container_for_client(client_code)
    if not conn:
        print("[upload] Skipped: missing AZURE_STORAGE_CONNECTION_STRING")
        return []
    if not container:
        print(f"[upload] Skipped: missing CONTAINER_NAME_{client_code.upper()}")
        return []

    stem = country_output_stem(country_code)
    csv_blob = f"{AZURE_BLOB_FOLDER}/{stem}.csv"
    pq_blob = f"{AZURE_BLOB_FOLDER}/{stem}.parquet"
    upload_df = dataframe_with_client_id(df, client_code)

    bsc = BlobServiceClient.from_connection_string(conn)
    container_client = bsc.get_container_client(container)
    uploaded: list[str] = []

    # Prefer uploading the just-saved local files when present
    if csv_path is not None and Path(csv_path).is_file():
        with Path(csv_path).open("rb") as fh:
            container_client.get_blob_client(csv_blob).upload_blob(
                fh,
                overwrite=True,
                content_settings=ContentSettings(content_type="text/csv"),
            )
    else:
        csv_buffer = io.StringIO()
        upload_df.to_csv(csv_buffer, index=False)
        container_client.get_blob_client(csv_blob).upload_blob(
            csv_buffer.getvalue().encode("utf-8"),
            overwrite=True,
            content_settings=ContentSettings(content_type="text/csv"),
        )
    uploaded.append(f"{container}/{csv_blob}")
    print(f"[upload] CSV  -> {container}/{csv_blob}")

    if parquet_path is not None and Path(parquet_path).is_file():
        with Path(parquet_path).open("rb") as fh:
            container_client.get_blob_client(pq_blob).upload_blob(
                fh,
                overwrite=True,
                content_settings=ContentSettings(content_type="application/octet-stream"),
            )
    else:
        pq_buffer = io.BytesIO()
        upload_df.to_parquet(pq_buffer, index=False, engine="pyarrow")
        pq_buffer.seek(0)
        container_client.get_blob_client(pq_blob).upload_blob(
            pq_buffer,
            overwrite=True,
            content_settings=ContentSettings(content_type="application/octet-stream"),
        )
    uploaded.append(f"{container}/{pq_blob}")
    print(f"[upload] Parquet -> {container}/{pq_blob}")

    return uploaded


# =============================================================================
# PIPELINE — one country end-to-end
# =============================================================================


def process_country(
    geo: dict[str, str],
    output_folder: str,
    *,
    day: date | datetime | None = None,
    lookback_days: int = 40,
    upload_to_azure: bool = True,
) -> str:
    """Download → map SKUs → clean → save local → optional Azure upload."""
    cc = normalize_country_code(geo["country_code"])
    prefix = f"[{cc}]"

    print(f"\n{'=' * 60}\nShipping Queue - {cc} - START\n{'=' * 60}")

    print(f"\n>>> STEP: [{cc}] load COGS / SKU mapping (esh_sku_cleaning)")
    try:
        sku_mapping = load_sku_mapping_for_country(cc)
        print(f"{prefix} SKU mapping entries: {len(sku_mapping):,}")
    except FileNotFoundError as exc:
        print(f"{prefix} {exc}")
        return ""
    except Exception as exc:
        print(f"{prefix} COGS / SKU mapping failed: {exc}")
        return ""

    print(f"\n>>> STEP: [{cc}] download raw shipping queue")
    try:
        raw = download_shipping_queue_csv(
            country_code=cc,
            day=day,
            max_lookback_days=lookback_days,
        )
    except FileNotFoundError as exc:
        print(f"{prefix} {exc}")
        raw = pd.DataFrame()
    except Exception as exc:
        print(f"{prefix} Download failed: {exc}")
        raw = pd.DataFrame()

    print(f"\n>>> STEP: [{cc}] clean / map SKUs / discrepancy")
    out_df = process_shipping_queue(raw, sku_mapping=sku_mapping)
    if out_df.empty:
        print(f"{prefix} No rows after processing (nothing to save/upload).")
        return ""

    out_df["country"] = cc
    out_df["country_code"] = cc.upper()

    print(f"\n>>> STEP: [{cc}] save local CSV + parquet")
    final_df, csv_path, pq_path = save_local_outputs(
        out_df, cc, Path(output_folder), client_code=CLIENT
    )
    local_path = str(csv_path)

    if upload_to_azure:
        print(
            f"\n>>> STEP: [{cc}] upload CSV + parquet -> "
            f"CONTAINER_NAME_{CLIENT}/{AZURE_BLOB_FOLDER}/"
            f"{country_output_stem(cc)}.{{csv,parquet}}"
        )
        try:
            uploaded = upload_outputs_to_azure(
                final_df,
                cc,
                csv_path=csv_path,
                parquet_path=pq_path,
                client_code=CLIENT,
            )
            if not uploaded:
                print(f"{prefix} Azure upload produced no blobs (check CONTAINER_NAME_{CLIENT}).")
        except Exception as exc:
            print(f"{prefix} Azure upload skipped: {type(exc).__name__}: {exc}")

    print(f"{'=' * 60}\nShipping Queue - {cc} - DONE\n{'=' * 60}")
    return local_path


# =============================================================================
# CLI — argparse and main entry point
# =============================================================================


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Clean Amazon shipping queue exports by country (Azure in/out)."
    )
    p.add_argument(
        "--countries",
        default="ALL",
        help="Comma-separated country codes (e.g. US,AE) or ALL.",
    )
    p.add_argument(
        "--output-folder",
        default=DEFAULT_OUTPUT_FOLDER,
        help=f"Local folder for processed CSV (default: {DEFAULT_OUTPUT_FOLDER}).",
    )
    p.add_argument(
        "--lookback-days",
        type=int,
        default=40,
        help="Days to search backward for the latest raw shipping queue blob.",
    )
    p.add_argument(
        "--day",
        default="",
        help="Start date for blob search (YYYY-MM-DD). Default: today.",
    )
    p.add_argument(
        "--no-azure-upload",
        action="store_true",
        help="Only save local CSV; do not upload processed CSV/Parquet to Azure.",
    )
    p.add_argument(
        "--env-file",
        default=".env",
        help="Path to .env file (default: .env in current directory).",
    )
    return p.parse_args(argv)


def _run_with_args(args: argparse.Namespace) -> list[str]:
    load_dotenv(args.env_file)

    print(f"\n>>> STEP: setup ESH shipping queue (client={CLIENT})")
    default_out = str(output_dir_for(CLIENT))
    if not args.output_folder or args.output_folder == DEFAULT_OUTPUT_FOLDER:
        output_folder = default_out
    else:
        output_folder = args.output_folder

    day: date | None = None
    if args.day:
        day = datetime.strptime(str(args.day).strip(), "%Y-%m-%d").date()

    requested = [c.strip() for c in str(args.countries).split(",") if c.strip()]
    print("\n>>> STEP: resolve geographies (pipeline/CLI -> geography.yaml)")
    geographies = resolve_geographies(requested or None, client_code=CLIENT)
    selected = sorted(geographies.keys())
    if not selected:
        print("No valid countries selected.")
        return []

    print(f"Countries: {', '.join(cc.upper() for cc in selected)}")
    print(f"Local output folder: {output_folder}")
    print(
        f"Azure upload: CONTAINER_NAME_{CLIENT}/{AZURE_BLOB_FOLDER}/"
        f"{{COUNTRY_CODE}}_{NAME_SUFFIX}.csv|.parquet"
    )

    print("\n>>> STEP: process selected countries")
    finished: list[str] = []
    for code in selected:
        path = process_country(
            geographies[code],
            output_folder,
            day=day,
            lookback_days=int(args.lookback_days),
            upload_to_azure=not args.no_azure_upload,
        )
        if path:
            print(f"Finished: {path}")
            finished.append(path)

    print(f"\n>>> STEP: ESH shipping queue complete ({len(finished)} file(s))")
    return finished


def run(
    *,
    client: str = CLIENT,
    geos: Optional[Sequence[str]] = None,
    countries: Optional[str] = None,
    output_folder: Optional[str] = None,
    lookback_days: int = 40,
    day: Optional[str] = None,
    no_azure_upload: bool = False,
    env_file: str = ".env",
    **_kwargs,
) -> list[str]:
    """Pipeline CLI entrypoint: run(client='ESH', geos=['US','AE'])."""
    key = str(client).strip().upper()
    if key not in CLIENT_CONFIGS:
        print(
            f"[skip] esh_shipping_queue supports {', '.join(sorted(CLIENT_CONFIGS))} "
            f"only (got client={client})"
        )
        return []

    cfg = get_client_config(key)
    print(f"ESH shipping queue (client={cfg.client_code})")

    if countries:
        country_arg = str(countries)
    elif geos:
        country_arg = ",".join(str(g).strip() for g in geos if str(g).strip())
    else:
        country_arg = "ALL"

    ns = argparse.Namespace(
        countries=country_arg,
        output_folder=output_folder or DEFAULT_OUTPUT_FOLDER,
        lookback_days=lookback_days,
        day=day or "",
        no_azure_upload=no_azure_upload,
        env_file=env_file,
    )
    return _run_with_args(ns)


def main(argv: Optional[Sequence[str]] = None) -> list[str]:
    return _run_with_args(parse_args(argv))


if __name__ == "__main__":
    main()
    print_script_completed("esh_shipping_queue")
