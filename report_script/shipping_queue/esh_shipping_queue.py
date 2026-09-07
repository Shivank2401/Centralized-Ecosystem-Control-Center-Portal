#!/usr/bin/env python3
"""
ESH Amazon Shipping Queue — country-wise cleaning pipeline.

Flow:
  1. Download raw shipments summary CSV from Azure Blob (with date lookback).
  2. Map merchant SKUs to master SKUs using country COGS (ON_1..ON_5 aliases).
  3. Clean dates, status text, and discrepancy quantities.
  4. Save locally and optionally upload processed CSV + Parquet to Azure.
"""

from __future__ import annotations

import argparse
import io
import os
import re
from datetime import date, datetime, timedelta
from io import StringIO
import numpy as np
import pandas as pd
from azure.storage.blob import BlobServiceClient, ContentSettings
from dotenv import load_dotenv

# =============================================================================
# STORAGE PATHS — where files live (input vs output)
# =============================================================================
#
# RAW INPUT (container CONTAINER_NAME_ESH_RAW, e.g. thrive-client-ecosoulhome):
#   data_dump/shipping_queue/amazon/YYYY/MM/DD/{cc}_shipments_summary.csv
#   Filename country code may be lower- or uppercase (Azure is case-sensitive; we try both).
#   Country codes elsewhere in this script use lowercase (e.g. uk, ae, us).
#   If today's file is missing, walks back up to LOOKBACK_DAYS (see azure_shipping_queue_csv_blob_path).
#
# COGS / SKU MAPPING (aliases → master SKU):
#   Prefer local: cogs/esh/{cc}_amazon_cogs.parquet|.csv
#   Azure fallback: {BLOB_PREFIX_COGS}/{cc}_amazon_cogs.* in CONTAINER_NAME_ESH
#   Default Azure prefix: helper_files/cogs  (set BLOB_PREFIX_COGS in .env)
#
# PROCESSED OUTPUT — after cleaning:
#   Local (default):  <PROCESSED_ROOT>/shipping_queue/ESH-{cc}-Amazon_Shipping_Queue_azure.csv
#   Azure CSV/Parquet include a client_id column (from CLIENT_ID in .env).
#   Azure CSV (CONTAINER_NAME_ESH_RAW):
#     sanity_data/shipping_queue/{cc}_amazon_shipping_queue.csv
#   Azure Parquet (CONTAINER_NAME_ESH_RAW):
#     processed/parquet/shipping_queue/{cc}_amazon_shipping_queue.parquet
#   {cc} = lowercase 2-letter country code.
#
# Set PROCESSED_ROOT in .env or pass --output-folder on the command line.

PROCESSED_ROOT = os.environ.get("PROCESSED_ROOT", "processed_output")
DEFAULT_OUTPUT_FOLDER = os.path.join(PROCESSED_ROOT, "shipping_queue")

PROCESSED_CSV_PREFIX = "sanity_data/shipping_queue"
PROCESSED_PARQUET_PREFIX = "processed/parquet/shipping_queue"

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

# COGS Excel columns used to build alias → master SKU map
COGS_ALIAS_COLS = ["ON_1", "ON_2", "ON_3", "ON_4", "ON_5"]

# =============================================================================
# GEOGRAPHY — enabled countries (from .env cogs_sheet_{cc}=...)
# =============================================================================
# Keys like cogs_sheet_us=ESH-USA define which countries to process (value is optional label).


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


def get_client_id() -> str:
    """Client identifier appended to Azure CSV/Parquet exports."""
    client_id = _clean_env(os.getenv("CLIENT_ID", ""))
    if not client_id:
        raise ValueError("CLIENT_ID is required in .env for Azure CSV/Parquet uploads")
    return client_id


def dataframe_with_client_id(df: pd.DataFrame) -> pd.DataFrame:
    """Add client_id as the first column (Azure processed exports only)."""
    out = df.copy()
    if "client_id" in out.columns:
        out = out.drop(columns=["client_id"])
    out.insert(0, "client_id", get_client_id())
    return out


def load_geographies_from_env() -> dict[str, dict[str, str]]:
    """
    Build { 'us': {'country_code': 'us'}, ... } from keys like cogs_sheet_us=... in .env.
    """
    geos: dict[str, dict[str, str]] = {}
    pattern = re.compile(r"^cogs_sheet_([a-z0-9_]+)$", re.IGNORECASE)
    for key, value in os.environ.items():
        match = pattern.match(key)
        if not match:
            continue
        code = normalize_country_code(match.group(1))
        geos[code] = {"country_code": code}
    return geos


# =============================================================================
# AZURE — connection settings from .env
# =============================================================================


def load_azure_settings() -> tuple[str, str]:
    """Return (connection_string, helper_container) from environment.

    helper_container (CONTAINER_NAME_ESH) holds COGS / processed outputs (e.g. app-helper).
    """
    conn = _clean_env(os.getenv("AZURE_STORAGE_CONNECTION_STRING", ""))
    container = _clean_env(os.getenv("CONTAINER_NAME_ESH", ""))
    return conn, container


def load_raw_shipping_container() -> str:
    """Container for raw shipping queue CSVs (CONTAINER_NAME_ESH_RAW)."""
    return _clean_env(os.getenv("CONTAINER_NAME_ESH_RAW", ""))


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
            "CONTAINER_NAME_ESH_RAW is missing in .env "
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
# COGS — SKU alias mapping (merchant SKU → master SKU from product catalog)
# =============================================================================


def build_sku_mapping(convertor_helper: pd.DataFrame) -> dict[str, str]:
    """
    Build uppercase alias → master SKU from COGS columns SKU + ON_1..ON_5.

    Each row's SKU is the canonical master; ON_* cells are alternate listings.
    """
    mapping: dict[str, str] = {}
    for _, row in convertor_helper.iterrows():
        master = str(row.get("SKU", "")).strip()
        if not master or master.lower() == "nan":
            continue
        mapping[master.upper()] = master
        for col in COGS_ALIAS_COLS:
            if col not in convertor_helper.columns:
                continue
            alias = str(row.get(col, "")).strip()
            if alias and alias.lower() != "nan":
                mapping[alias.upper()] = master
    return mapping


def clean_sku_column(
    df: pd.DataFrame,
    *,
    sku_column: str = "sku",
    sku_mapping: dict[str, str],
) -> pd.DataFrame:
    """Replace alias SKUs with master SKU where a mapping exists."""
    out = df.copy()
    keys = out[sku_column].astype(str).str.strip().str.upper()
    out[sku_column] = keys.map(sku_mapping).fillna(out[sku_column])
    return out


def load_cogs_from_azure(country_code: str) -> pd.DataFrame:
    """
    Load COGS for one country.

    Prefer local project slice: cogs/esh/{cc}_amazon_cogs.parquet|.csv
    Fall back to Azure blob under BLOB_PREFIX_COGS.
    """
    from config_manager import cogs_local

    cc = normalize_country_code(country_code)
    try:
        df = cogs_local.read_cogs_slice("ESH", cc, channel="amazon")
        return cogs_local.to_pascal_sku_alias_frame(
            df, COGS_ALIAS_COLS
        ).drop_duplicates()
    except FileNotFoundError as exc:
        print(f"[cogs] Local miss ({exc}); trying Azure...")

    conn, container = load_azure_settings()
    if not conn or not container:
        raise ValueError(
            "Azure settings missing. Set AZURE_STORAGE_CONNECTION_STRING and CONTAINER_NAME_ESH in .env"
        )

    prefix = _clean_env(os.getenv("BLOB_PREFIX_COGS", "helper_files/cogs")).strip("/")
    stem = f"{prefix}/{cc}_amazon_cogs"

    bsc = BlobServiceClient.from_connection_string(conn)
    container_client = bsc.get_container_client(container)

    candidates = [
        (f"{stem}.parquet", "parquet"),
        (f"{stem}.csv", "csv"),
    ]
    for blob_path, fmt in candidates:
        blob_client = container_client.get_blob_client(blob_path)
        if not blob_client.exists():
            continue
        print(f"[cogs] Downloading from Azure ({fmt}): {container}/{blob_path}")
        raw = blob_client.download_blob().readall()
        if fmt == "parquet":
            df = pd.read_parquet(io.BytesIO(raw)).drop_duplicates()
        else:
            text = raw.decode("utf-8", errors="replace")
            df = pd.read_csv(StringIO(text)).drop_duplicates()
        return cogs_local.to_pascal_sku_alias_frame(df, COGS_ALIAS_COLS)

    tried = ", ".join(path for path, _ in candidates)
    raise FileNotFoundError(
        f"No COGS file for '{cc}' in cogs/esh/ or Azure. Checked local + {tried}. "
        "Run Stage want_to_update → ESH COGS first."
    )


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

    main = clean_sku_column(main, sku_column="sku", sku_mapping=sku_mapping)
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


def upload_processed_to_azure(df: pd.DataFrame, country_code: str) -> None:
    """
    Upload cleaned queue to Azure as CSV and Parquet (includes client_id column).

    Destinations (container = CONTAINER_NAME_ESH_RAW):
      CSV:     sanity_data/shipping_queue/{cc}_amazon_shipping_queue.csv
      Parquet: processed/parquet/shipping_queue/{cc}_amazon_shipping_queue.parquet
    """
    conn, _helper_container = load_azure_settings()
    raw_container = load_raw_shipping_container()
    if not conn:
        print("[upload] Skipped: missing AZURE_STORAGE_CONNECTION_STRING")
        return
    if not raw_container:
        print("[upload] Skipped: missing CONTAINER_NAME_ESH_RAW")
        return

    cc = normalize_country_code(country_code)
    csv_blob = f"{PROCESSED_CSV_PREFIX}/{cc}_amazon_shipping_queue.csv"
    pq_blob = f"{PROCESSED_PARQUET_PREFIX}/{cc}_amazon_shipping_queue.parquet"

    upload_df = dataframe_with_client_id(df)

    bsc = BlobServiceClient.from_connection_string(conn)
    raw_client = bsc.get_container_client(raw_container)

    csv_buffer = io.StringIO()
    upload_df.to_csv(csv_buffer, index=False)
    raw_client.get_blob_client(csv_blob).upload_blob(
        csv_buffer.getvalue().encode("utf-8"),
        overwrite=True,
        content_settings=ContentSettings(content_type="text/csv"),
    )
    print(f"[upload] CSV  -> {raw_container}/{csv_blob}")

    pq_buffer = io.BytesIO()
    upload_df.to_parquet(pq_buffer, index=False, engine="pyarrow")
    pq_buffer.seek(0)
    raw_client.get_blob_client(pq_blob).upload_blob(
        pq_buffer,
        overwrite=True,
        content_settings=ContentSettings(content_type="application/octet-stream"),
    )
    print(f"[upload] Parquet -> {raw_container}/{pq_blob}")


# =============================================================================
# PIPELINE — one country end-to-end
# =============================================================================


def process_country(
    geo: dict[str, str],
    output_folder: str,
    *,
    day: date | datetime | None = None,
    lookback_days: int = 7,
    upload_to_azure: bool = True,
) -> str:
    """Download → map SKUs → clean → save local → optional Azure upload."""
    cc = normalize_country_code(geo["country_code"])
    prefix = f"[{cc}]"

    print(f"\n{'=' * 60}\nShipping Queue — {cc} — START\n{'=' * 60}")

    try:
        product_cat = load_cogs_from_azure(cc)
    except FileNotFoundError as exc:
        print(f"{prefix} {exc}")
        return ""
    except Exception as exc:
        print(f"{prefix} COGS download failed: {exc}")
        return ""
    convertor = product_cat.loc[:, ["SKU", *COGS_ALIAS_COLS]].drop_duplicates()
    sku_mapping = build_sku_mapping(convertor)

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

    out_df = process_shipping_queue(raw, sku_mapping=sku_mapping)
    if out_df.empty:
        print(f"{prefix} No rows after processing.")
        return ""

    out_df["country"] = cc

    os.makedirs(output_folder, exist_ok=True)
    local_path = os.path.join(
        output_folder,
        f"ESH-{cc}-Amazon_Shipping_Queue_azure.csv",
    )
    final_df = save_local_csv(out_df, local_path)
    print(f"{prefix} Local CSV ({len(final_df)} rows): {local_path}")

    if upload_to_azure:
        try:
            upload_processed_to_azure(final_df, cc)
        except Exception as exc:
            print(f"{prefix} Azure upload skipped: {type(exc).__name__}: {exc}")

    print(f"{'=' * 60}\nShipping Queue — {cc} — DONE\n{'=' * 60}")
    return local_path


# =============================================================================
# CLI — argparse and main entry point
# =============================================================================


def parse_args() -> argparse.Namespace:
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
        default=7,
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
    return p.parse_args()


def main() -> None:
    args = parse_args()
    load_dotenv(args.env_file)

    global PROCESSED_ROOT, DEFAULT_OUTPUT_FOLDER
    PROCESSED_ROOT = _clean_env(os.getenv("PROCESSED_ROOT", PROCESSED_ROOT))
    if args.output_folder == DEFAULT_OUTPUT_FOLDER:
        DEFAULT_OUTPUT_FOLDER = os.path.join(PROCESSED_ROOT, "shipping_queue")

    geographies = load_geographies_from_env()
    if not geographies:
        print("No cogs_sheet_* entries in .env — cannot resolve countries.")
        return

    day: date | None = None
    if args.day:
        day = datetime.strptime(args.day.strip(), "%Y-%m-%d").date()

    requested = [c.strip().lower() for c in args.countries.split(",") if c.strip()]
    if not requested or "all" in requested:
        selected = sorted(geographies.keys())
    else:
        selected: list[str] = []
        unknown: list[str] = []
        for raw in requested:
            try:
                code = normalize_country_code(raw)
            except ValueError:
                unknown.append(raw)
                continue
            if code in geographies:
                selected.append(code)
            else:
                unknown.append(raw)
        if unknown:
            print(f"Unknown countries skipped: {', '.join(unknown)}")

    if not selected:
        print("No valid countries selected.")
        return

    output_folder = args.output_folder
    if output_folder == DEFAULT_OUTPUT_FOLDER and PROCESSED_ROOT:
        output_folder = os.path.join(PROCESSED_ROOT, "shipping_queue")

    print(f"Countries: {', '.join(selected)}")
    print(f"Local output folder: {output_folder}")
    print(f"Azure processed CSV prefix:    {PROCESSED_CSV_PREFIX}/")
    print(f"Azure processed Parquet prefix: {PROCESSED_PARQUET_PREFIX}/")

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


if __name__ == "__main__":
    main()
