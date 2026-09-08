#!/usr/bin/env python3
"""
KNC Amazon Shipping Queue — country-wise cleaning pipeline.

Same cleaning logic as 2_esh_shipping_queue.py; KNC-specific Azure container,
COGS blob prefix/location, client_id, and SKU alias columns (ON_1, ON_2 only).
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
# KNC CONFIG — differs from ESH (see 2_esh_shipping_queue.py)
# =============================================================================
CLIENT_ID_ENV = "CLIENT_ID_KNC"
CONTAINER_ENV = "CONTAINER_NAME_KNC"
CONTAINER_RAW_ENV = "CONTAINER_NAME_KNC_RAW"
COGS_PREFIX_ENV = "BLOB_PREFIX_COGS_KNC"
GEO_ENV_PATTERN = re.compile(r"^knc_cogs_sheet_([a-z0-9_]+)$", re.IGNORECASE)
LOCAL_FILE_PREFIX = "KNC"
# KNC COGS uses ON_1 / ON_2 / ON_3 (not ON_4..ON_5)
COGS_ALIAS_COLS = ["ON_1", "ON_2", "ON_3"]

# =============================================================================
# STORAGE PATHS
# =============================================================================
#
# RAW INPUT (container CONTAINER_NAME_KNC_RAW, e.g. thrive-client-kinetica):
#   data_dump/shipping_queue/amazon/YYYY/MM/DD/{cc}_shipments_summary.csv
#   Filename country code may be lower- or uppercase (Azure is case-sensitive; we try both).
#
# COGS (Azure only, container CONTAINER_NAME_KNC e.g. app-helper):
#   {BLOB_PREFIX_COGS_KNC}/{cc}_amazon_cogs.parquet  (preferred)
#   {BLOB_PREFIX_COGS_KNC}/{cc}_amazon_cogs.csv
#   Default prefix: helper_files/cogs  (override with BLOB_PREFIX_COGS_KNC in .env)
#
# Countries enabled via knc_cogs_sheet_{cc}=... in .env (e.g. knc_cogs_sheet_us=KNC-USA)
#
# PROCESSED OUTPUT:
#   Local:  <PROCESSED_ROOT_KNC>/shipping_queue/KNC-{cc}-Amazon_Shipping_Queue_azure.csv
#   Azure CSV (CONTAINER_NAME_KNC_RAW):
#     sanity_data/shipping_queue/{cc}_amazon_shipping_queue.csv
#   Azure Parquet (CONTAINER_NAME_KNC_RAW):
#     processed/parquet/shipping_queue/{cc}_amazon_shipping_queue.parquet
#   Azure uploads include client_id from CLIENT_ID_KNC

PROCESSED_ROOT = os.environ.get("PROCESSED_ROOT_KNC", "processed_output/knc")
DEFAULT_OUTPUT_FOLDER = os.path.join(PROCESSED_ROOT, "shipping_queue")

PROCESSED_CSV_PREFIX = "sanity_data/shipping_queue"
PROCESSED_PARQUET_PREFIX = "processed/parquet/shipping_queue"

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

DATE_COLS = ["creating_date", "receiving_date", "shipped_date", "closed_date"]

# KNC legacy SKU renames before COGS mapping
KNC_SKU_LEGACY_MAP = {
    "200855": "KCA-200855",
    "KIN-201033": "KCA-201033",
}


def _clean_env(value: str) -> str:
    return value.strip().strip('"').strip("'").strip(",").strip()


def normalize_country_code(country_code: str) -> str:
    cc = (country_code or "").strip().lower()
    if len(cc) != 2 or not cc.isalpha():
        raise ValueError(
            f"country_code must be a 2-letter code (e.g. 'us', 'ae'), got: {country_code!r}"
        )
    return cc


def get_client_id() -> str:
    client_id = _clean_env(os.getenv(CLIENT_ID_ENV, ""))
    if not client_id:
        raise ValueError(f"{CLIENT_ID_ENV} is required in .env for Azure CSV/Parquet uploads")
    return client_id


def dataframe_with_client_id(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "client_id" in out.columns:
        out = out.drop(columns=["client_id"])
    out.insert(0, "client_id", get_client_id())
    return out


def load_geographies_from_env() -> dict[str, dict[str, str]]:
    """Build country list from knc_cogs_sheet_{cc}=... keys in .env."""
    geos: dict[str, dict[str, str]] = {}
    for key in os.environ:
        match = GEO_ENV_PATTERN.match(key)
        if not match:
            continue
        code = normalize_country_code(match.group(1))
        geos[code] = {"country_code": code}
    return geos


def load_azure_settings() -> tuple[str, str]:
    """Return (connection_string, helper_container) for COGS / processed uploads."""
    conn = _clean_env(os.getenv("AZURE_STORAGE_CONNECTION_STRING", ""))
    container = _clean_env(os.getenv(CONTAINER_ENV, ""))
    return conn, container


def load_raw_shipping_container() -> str:
    """Container for raw shipping queue CSVs (CONTAINER_NAME_KNC_RAW)."""
    return _clean_env(os.getenv(CONTAINER_RAW_ENV, ""))


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
    Walk backward from `day` until a blob exists.

    Country codes are normalized to lowercase for further processing.
    Blob filenames are tried as both lowercase and uppercase (Azure is case-sensitive).
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
    conn, _helper_cont = load_azure_settings()
    conn_use = _clean_env(connection_string or conn)
    cont_use = _clean_env(container or load_raw_shipping_container())
    if not conn_use:
        raise ValueError("AZURE_STORAGE_CONNECTION_STRING is missing in .env")
    if not cont_use:
        raise ValueError(
            f"{CONTAINER_RAW_ENV} is missing in .env "
            "(raw shipping CSVs container, e.g. thrive-client-kinetica)"
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


def build_sku_mapping(convertor_helper: pd.DataFrame) -> dict[str, str]:
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
    out = df.copy()
    keys = out[sku_column].astype(str).str.strip().str.upper()
    out[sku_column] = keys.map(sku_mapping).fillna(out[sku_column])
    return out


def load_cogs_from_azure(country_code: str) -> pd.DataFrame:
    """
    Load KNC COGS for one country.

    Prefer local: cogs/knc/{cc}_amazon_cogs.parquet|.csv
    Fall back to Azure (KNC container + BLOB_PREFIX_COGS_KNC).
    """
    from config_manager import cogs_local

    cc = normalize_country_code(country_code)
    try:
        df = cogs_local.read_cogs_slice("KNC", cc, channel="amazon")
        return cogs_local.to_pascal_sku_alias_frame(
            df, COGS_ALIAS_COLS
        ).drop_duplicates()
    except FileNotFoundError as exc:
        print(f"[cogs] Local miss ({exc}); trying Azure...")

    conn, container = load_azure_settings()
    if not conn or not container:
        raise ValueError(
            f"Azure settings missing. Set AZURE_STORAGE_CONNECTION_STRING and {CONTAINER_ENV} in .env"
        )

    prefix = _clean_env(os.getenv(COGS_PREFIX_ENV, "helper_files/cogs")).strip("/")
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
        f"No KNC COGS file for '{cc}' in cogs/knc/ or Azure. Checked local + {tried}. "
        "Run Stage want_to_update → KNC COGS first."
    )


def parse_dates(df: pd.DataFrame) -> pd.DataFrame:
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


def apply_knc_legacy_sku_fixes(series: pd.Series) -> pd.Series:
    """KNC-specific hard-coded SKU corrections before COGS alias mapping."""
    out = series.astype(str).str.strip()
    for old, new in KNC_SKU_LEGACY_MAP.items():
        out = out.where(out != old, new)
    return out


def process_shipping_queue(
    raw_df: pd.DataFrame,
    *,
    sku_mapping: dict[str, str],
) -> pd.DataFrame:
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

    if "shipment_status" in main.columns:
        raw_status = main["shipment_status"].astype(str).str.strip()
        norm = (
            raw_status.str.replace(r"[\-_]+", " ", regex=True)
            .str.replace(r"\s+", " ", regex=True)
            .str.strip()
            .str.title()
        )
        main["shipment_status"] = norm

        status_check = ["Closed", "Receiving"]
        if {"total_expected_quantity", "total_received_quantity"}.issubset(main.columns):
            main["total_discrepancy_quantity"] = np.where(
                main["shipment_status"].isin(status_check),
                main["total_expected_quantity"] - main["total_received_quantity"],
                0,
            )

    main = parse_dates(main)

    main["sku"] = (
        main["sku"].astype(str).str.replace(r"-{1,2}$", "", regex=True).str.strip()
    )
    main["sku"] = apply_knc_legacy_sku_fixes(main["sku"])
    main = clean_sku_column(main, sku_column="sku", sku_mapping=sku_mapping)
    main["platform"] = "amazon"
    return main


def dedupe_keys(df: pd.DataFrame) -> list[str]:
    candidates = [
        "shipment_id",
        "sku",
        "destination_fc",
        "shipment_status",
        "creating_date",
    ]
    return [c for c in candidates if c in df.columns]


def save_local_csv(df: pd.DataFrame, output_path: str) -> pd.DataFrame:
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

    Destinations (container = CONTAINER_NAME_KNC_RAW):
      CSV:     sanity_data/shipping_queue/{cc}_amazon_shipping_queue.csv
      Parquet: processed/parquet/shipping_queue/{cc}_amazon_shipping_queue.parquet
    """
    conn, _helper_container = load_azure_settings()
    raw_container = load_raw_shipping_container()
    if not conn:
        print("[upload] Skipped: missing AZURE_STORAGE_CONNECTION_STRING")
        return
    if not raw_container:
        print(f"[upload] Skipped: missing {CONTAINER_RAW_ENV}")
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


def process_country(
    geo: dict[str, str],
    output_folder: str,
    *,
    day: date | datetime | None = None,
    lookback_days: int = 10,
    upload_to_azure: bool = True,
) -> str:
    cc = normalize_country_code(geo["country_code"])
    prefix = f"[{cc}]"

    print(f"\n{'=' * 60}\nKNC Shipping Queue — {cc} — START\n{'=' * 60}")

    try:
        product_cat = load_cogs_from_azure(cc)
    except FileNotFoundError as exc:
        print(f"{prefix} {exc}")
        return ""
    except Exception as exc:
        print(f"{prefix} COGS download failed: {exc}")
        return ""

    alias_cols = [c for c in ["SKU", *COGS_ALIAS_COLS] if c in product_cat.columns]
    convertor = product_cat.loc[:, alias_cols].drop_duplicates()
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
        f"{LOCAL_FILE_PREFIX}-{cc}-Amazon_Shipping_Queue_azure.csv",
    )
    final_df = save_local_csv(out_df, local_path)
    print(f"{prefix} Local CSV ({len(final_df)} rows): {local_path}")

    if upload_to_azure:
        try:
            upload_processed_to_azure(final_df, cc)
        except Exception as exc:
            print(f"{prefix} Azure upload skipped: {type(exc).__name__}: {exc}")

    print(f"{'=' * 60}\nKNC Shipping Queue — {cc} — DONE\n{'=' * 60}")
    return local_path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Clean KNC Amazon shipping queue exports by country (Azure in/out)."
    )
    p.add_argument("--countries", default="ALL", help="Comma-separated codes (e.g. us,ca) or ALL.")
    p.add_argument(
        "--output-folder",
        default=DEFAULT_OUTPUT_FOLDER,
        help=f"Local folder for processed CSV (default: {DEFAULT_OUTPUT_FOLDER}).",
    )
    p.add_argument(
        "--lookback-days",
        type=int,
        default=10,
        help="Days to search backward for the latest raw shipping queue blob.",
    )
    p.add_argument("--day", default="", help="Start date for blob search (YYYY-MM-DD).")
    p.add_argument(
        "--no-azure-upload",
        action="store_true",
        help="Only save local CSV; skip Azure processed upload.",
    )
    p.add_argument("--env-file", default=".env", help="Path to .env file.")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    load_dotenv(args.env_file)

    global PROCESSED_ROOT, DEFAULT_OUTPUT_FOLDER
    PROCESSED_ROOT = _clean_env(os.getenv("PROCESSED_ROOT_KNC", PROCESSED_ROOT))
    if args.output_folder == DEFAULT_OUTPUT_FOLDER:
        DEFAULT_OUTPUT_FOLDER = os.path.join(PROCESSED_ROOT, "shipping_queue")

    geographies = load_geographies_from_env()
    if not geographies:
        print("No knc_cogs_sheet_* entries in .env — cannot resolve countries.")
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

    print(f"KNC container: {_clean_env(os.getenv(CONTAINER_ENV, ''))}")
    print(f"KNC COGS prefix: {_clean_env(os.getenv(COGS_PREFIX_ENV, 'helper_files/cogs'))}")
    print(f"Countries: {', '.join(selected)}")
    print(f"Local output folder: {output_folder}")

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


from config_manager.report_helpers import print_script_completed

if __name__ == "__main__":
    main()
    print_script_completed('knc_shipping_queue')
