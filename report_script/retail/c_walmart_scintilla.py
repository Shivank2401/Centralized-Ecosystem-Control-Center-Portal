"""
ESH Walmart / Scintilla retail sync.

Ports main_walmart_scintilla.py into the pipeline:
  - processing logic unchanged
  - Azure paths match the working main script
  - credentials / local Walmart root come from .env

Azure layout (same as main_walmart_scintilla.py):
  container : CONTAINER_NAME_ESH  (thrive-client-ecosoulhome)
  folder    : WALMART_BLOB_PREFIX (default sanity_data/retail)

Store sales / inventory / sales / order_forecast sync:
  Excel → CSV archive under {dataset}/{year}/{month}/ →
  read ALL CSVs in that folder → full-row dedupe →
  append onto local sanity_report/{report}.csv → full-row dedupe →
  save local CSV → ask user yes/no → optional upload/replace Azure parquet
  (no daily Azure parquet download)

SKU helper still uses the legacy append-only hash sync (also gated by the same prompt).

Run:
  python report_script/retail/c_walmart_scintilla.py
  python report_script/retail/c_walmart_scintilla.py --upload-azure
  python report_script/retail/c_walmart_scintilla.py --skip-azure
  # or via run_pipeline.py → Stage: retail → Walmart Scintilla
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from io import BytesIO
from pathlib import Path
from typing import Optional, Sequence

import numpy as np
import pandas as pd
from datetime import datetime
from azure.core.exceptions import ServiceRequestError, ServiceResponseError
from azure.storage.blob import BlobServiceClient, BlobType, ExponentialRetry

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config_manager import paths as cfg_paths
from config_manager.report_helpers import print_script_completed


def to_snake(name: str) -> str:
    """Convert column name to snake_case format."""
    name = name.strip()
    name = name.lower()
    name = re.sub(r"[^a-z0-9]+", "_", name)
    name = re.sub(r"_+", "_", name)
    name = name.strip("_")
    return name


def _clean_env(value: str) -> str:
    return str(value or "").strip().strip('"').strip("'")


def _azure_connection_string() -> str:
    """Prefer full connection string; else build from account name + key."""
    conn = _clean_env(os.getenv("AZURE_STORAGE_CONNECTION_STRING", ""))
    if conn:
        return conn
    account = _clean_env(os.getenv("AZURE_STORAGE_ACCOUNT_NAME", ""))
    key = _clean_env(os.getenv("AZURE_STORAGE_ACCOUNT_KEY", ""))
    if account and key:
        return (
            "DefaultEndpointsProtocol=https;"
            f"AccountName={account};"
            f"AccountKey={key};"
            "EndpointSuffix=core.windows.net"
        )
    raise EnvironmentError(
        "Missing Azure credentials in .env. Set AZURE_STORAGE_CONNECTION_STRING "
        "or AZURE_STORAGE_ACCOUNT_NAME + AZURE_STORAGE_ACCOUNT_KEY."
    )


def _azure_container() -> str:
    container = _clean_env(os.getenv("CONTAINER_NAME_ESH", ""))
    if not container:
        raise EnvironmentError(
            "Missing CONTAINER_NAME_ESH in .env "
            "(e.g. thrive-client-ecosoulhome)."
        )
    return container


def _azure_blob_folder() -> str:
    """Same default as main_walmart_scintilla.py."""
    raw = _clean_env(os.getenv("WALMART_BLOB_PREFIX", "sanity_data/retail"))
    return raw.strip("/")


# ---------------------------------------------------------------------------
# Azure sync helpers (logic from main_walmart_scintilla.py)
# ---------------------------------------------------------------------------

def format_mb(num_bytes: float) -> str:
    return f"{num_bytes / (1024 ** 2):.2f} MB"


def download_existing_parquet(client, *, upload_max_workers: int) -> pd.DataFrame:
    """Download existing blob as parquet; fallback to CSV for old files."""
    print("Downloading existing Azure file (for dedupe check)...")
    start = time.time()
    try:
        downloader = client.download_blob(max_concurrency=upload_max_workers)
        total = downloader.size or 0
        if total:
            print(f"  Remote blob size : {format_mb(total)} ({total:,} bytes)")

        chunks = []
        downloaded = 0
        last_pct = -1
        for chunk in downloader.chunks():
            chunks.append(chunk)
            downloaded += len(chunk)
            if total:
                pct = int(downloaded / total * 100)
                if pct >= last_pct + 10 or downloaded == total:
                    print(
                        f"  Download progress: {format_mb(downloaded)} / "
                        f"{format_mb(total)} ({pct}%)"
                    )
                    last_pct = pct

        blob_bytes = b"".join(chunks)
        try:
            azure_df = pd.read_parquet(BytesIO(blob_bytes))
            source_format = "parquet"
        except Exception:
            azure_df = pd.read_csv(BytesIO(blob_bytes), low_memory=False)
            source_format = "csv"

        print(f"  Existing rows    : {len(azure_df):,}")
        print(f"  Existing format  : {source_format}")
        print(f"  Download time    : {time.time() - start:.1f}s")
        return azure_df
    except Exception as exc:
        print(f"  File not found / download failed ({exc}). Treating as empty.")
        return pd.DataFrame()


def build_azure_dtype_checklist(azure_df: pd.DataFrame) -> dict:
    """
    Build and print a column-dtype checklist from the downloaded Azure file.
    This schema is the source of truth for casting local data before append.
    """
    if azure_df is None or azure_df.empty:
        print("  Azure dtype checklist: (empty — no existing schema)")
        return {}

    checklist = {col: dtype for col, dtype in azure_df.dtypes.items()}
    print("  Azure dtype checklist:")
    for col, dtype in checklist.items():
        print(f"    [ ] {col:<45} -> {dtype}")
    print(f"  Checklist columns  : {len(checklist)}")
    return checklist


def _cast_series_to_dtype(series: pd.Series, target_dtype) -> pd.Series:
    """Cast one series to a target dtype as safely as possible."""
    target = str(target_dtype)

    # String-like targets
    if target in {"object", "string", "str"} or target.startswith("string"):
        def _to_str(value):
            if pd.isna(value):
                return pd.NA
            if isinstance(value, (float, np.floating)) and float(value).is_integer():
                return str(int(value))
            if isinstance(value, (int, np.integer)):
                return str(int(value))
            return str(value)

        if target == "object":
            return series.map(lambda v: None if pd.isna(v) else _to_str(v))
        return series.map(_to_str).astype("string")

    # Datetime targets
    if "datetime" in target:
        return pd.to_datetime(series, errors="coerce")

    # Boolean targets
    if target in {"bool", "boolean"} or target.startswith("bool"):
        try:
            return series.astype("boolean")
        except (TypeError, ValueError):
            return series.map(lambda v: pd.NA if pd.isna(v) else bool(v)).astype("boolean")

    # Numeric targets (int / float)
    if pd.api.types.is_integer_dtype(target_dtype) or pd.api.types.is_float_dtype(target_dtype):
        numeric = pd.to_numeric(series, errors="coerce")
        try:
            return numeric.astype(target_dtype)
        except (TypeError, ValueError):
            # Nullable integer fallback when NaNs are present
            if pd.api.types.is_integer_dtype(target_dtype):
                return numeric.astype("Int64")
            return numeric.astype("Float64")

    # Fallback: best-effort cast
    try:
        return series.astype(target_dtype)
    except (TypeError, ValueError):
        return series


def cast_df_to_schema(df: pd.DataFrame, schema: dict, *, label: str = "local") -> pd.DataFrame:
    """
    Cast dataframe columns to match an Azure dtype checklist.
    Prints pass/fail status per column.
    """
    if df is None or df.empty:
        return df if df is not None else pd.DataFrame()
    if not schema:
        print(f"  No Azure schema — keeping {label} dtypes as-is.")
        return df.copy()

    out = df.copy()
    print(f"  Casting {label} columns to Azure schema:")
    for col, target_dtype in schema.items():
        if col not in out.columns:
            print(f"    [skip] {col:<43} (missing in {label})")
            continue

        before = out[col].dtype
        try:
            out[col] = _cast_series_to_dtype(out[col], target_dtype)
            after = out[col].dtype
            status = "ok" if str(after) == str(target_dtype) or (
                pd.api.types.is_numeric_dtype(after) and pd.api.types.is_numeric_dtype(target_dtype)
            ) else "cast"
            print(f"    [{status}] {col:<43} {before} -> {after} (target: {target_dtype})")
        except Exception as exc:
            print(f"    [fail] {col:<43} keep {before} ({exc})")

    # Keep any brand-new local-only columns (not in Azure schema)
    new_cols = [c for c in out.columns if c not in schema]
    if new_cols:
        print(f"  New local-only columns kept as-is: {new_cols}")

    return out


def _normalize_for_hash(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize cell values so azure vs local hashes match after schema casting.

    Object columns in Azure often still hold ints/floats, while cast_df_to_schema
    stringifies local object columns — without this, every row looks 'new'.
    """
    out = df.copy()
    for col in out.columns:
        out[col] = out[col].map(
            lambda v: ""
            if v is None or (isinstance(v, float) and pd.isna(v)) or pd.isna(v)
            else (
                str(int(v))
                if isinstance(v, (float, np.floating)) and float(v).is_integer()
                else str(int(v))
                if isinstance(v, (int, np.integer))
                else str(v)
            )
        )
    return out


def get_new_rows_only(azure_df: pd.DataFrame, new_df: pd.DataFrame) -> pd.DataFrame:
    """
    Return rows from new_df that are not already present in azure_df.
    Uses row hashing so we don't rewrite the full historical file.
    """
    if new_df is None or new_df.empty:
        return pd.DataFrame()

    cleaned_new = new_df.drop_duplicates(keep="last").reset_index(drop=True)

    if azure_df is None or azure_df.empty:
        print("  No existing Azure rows — all local rows are new.")
        return cleaned_new

    # Align columns for fair comparison where possible
    compare_cols = [c for c in cleaned_new.columns if c in azure_df.columns]
    if not compare_cols:
        print("  Column mismatch — uploading all local rows as new.")
        return cleaned_new

    azure_cmp = _normalize_for_hash(azure_df.reindex(columns=compare_cols))
    new_cmp = _normalize_for_hash(cleaned_new.reindex(columns=compare_cols))

    azure_hashes = set(pd.util.hash_pandas_object(azure_cmp, index=False).tolist())
    new_hashes = pd.util.hash_pandas_object(new_cmp, index=False)
    mask = ~new_hashes.isin(azure_hashes)
    new_only = cleaned_new.loc[mask].reset_index(drop=True)

    print(f"  Local rows        : {len(cleaned_new):,}")
    print(f"  Already in Azure  : {(~mask).sum():,}")
    print(f"  Truly new rows    : {len(new_only):,}")
    return new_only


def upload_parquet_block_blob(client, df: pd.DataFrame, *, upload_max_workers: int) -> None:
    """Upload full dataframe as parquet block blob (overwrite)."""
    print("  Uploading merged data as parquet block blob...")
    start = time.time()
    buffer = BytesIO()
    df.to_parquet(buffer, index=False)
    data = buffer.getvalue()
    total_size = len(data)
    print(f"  Upload size       : {format_mb(total_size)} ({total_size:,} bytes)")

    client.upload_blob(
        data=data,
        overwrite=True,
        blob_type=BlobType.BLOCKBLOB,
        max_concurrency=upload_max_workers,
    )
    elapsed = time.time() - start
    speed = (total_size / (1024 ** 2)) / elapsed if elapsed > 0 else 0
    print(f"  Upload time       : {elapsed:.1f}s | {speed:.2f} MB/s")


def blob_exists(blob_client) -> bool:
    """Return True if the Azure blob already exists."""
    try:
        return bool(blob_client.exists())
    except Exception as exc:
        print(f"  WARN: blob exists() check failed ({exc}); assuming missing.")
        return False


def read_archive_month_csvs(
    archive_folder: Path,
    *,
    dataset_label: str = "archive",
) -> pd.DataFrame:
    """
    Read and append all .csv files from one archive year/month folder only.

    Raises FileNotFoundError / ValueError when the folder or CSVs are missing.
    """
    archive_folder = Path(archive_folder)
    print(f"Reading {dataset_label} archive folder: {archive_folder}")

    if not archive_folder.exists():
        raise FileNotFoundError(
            f"{dataset_label} archive folder does not exist: {archive_folder}"
        )
    if not archive_folder.is_dir():
        raise NotADirectoryError(
            f"{dataset_label} archive path is not a directory: {archive_folder}"
        )

    csv_paths = sorted(
        p for p in archive_folder.iterdir() if p.is_file() and p.suffix.lower() == ".csv"
    )
    if not csv_paths:
        raise ValueError(
            f"No CSV files found in {dataset_label} archive folder: {archive_folder}"
        )

    print(f"  CSV files found ({len(csv_paths)}):")
    frames = []
    for path in csv_paths:
        print(f"    - {path.name}")
        try:
            frame = pd.read_csv(path, low_memory=False)
        except Exception as exc:
            raise RuntimeError(
                f"Failed reading {dataset_label} archive CSV {path.name}: {exc}"
            ) from exc
        if frame.empty:
            print(f"      WARN: empty CSV skipped ({path.name})")
            continue
        print(f"      rows={len(frame):,} cols={len(frame.columns)}")
        frames.append(frame)

    if not frames:
        raise ValueError(
            f"All CSV files in {dataset_label} archive folder were empty: {archive_folder}"
        )

    monthly_df = pd.concat(frames, ignore_index=True, sort=False)
    print(f"  Appended archive rows (before dedupe): {len(monthly_df):,}")
    return monthly_df


def dedupe_archive_dataframe(df: pd.DataFrame, *, label: str = "archive") -> pd.DataFrame:
    """Full-row dedupe on archive data; print before/after report."""
    before = len(df)
    out = df.drop_duplicates().reset_index(drop=True)
    after = len(out)
    removed = before - after
    print(f"  [{label}] rows before dedupe : {before:,}")
    print(f"  [{label}] rows after dedupe  : {after:,}")
    print(f"  [{label}] duplicates removed : {removed:,}")
    return out


def save_and_load_archive_month(
    processed_df: pd.DataFrame,
    *,
    archive_folder: Path,
    csv_filename: str,
    dataset_label: str,
) -> tuple[pd.DataFrame, int]:
    """
    Save current processed CSV into archive_folder, then read ALL CSVs in that
    same year/month folder and full-row dedupe.

    Returns (deduped_monthly_df, archive_rows_before_dedupe).
    """
    archive_folder = Path(archive_folder)
    archive_folder.mkdir(parents=True, exist_ok=True)
    csv_path = archive_folder / csv_filename
    processed_df.to_csv(csv_path, index=False)
    print(f"Saved {dataset_label} CSV: {csv_path}")

    print(f"Loading all {dataset_label} CSVs from current archive folder...")
    monthly_raw = read_archive_month_csvs(archive_folder, dataset_label=dataset_label)
    archive_rows_before_dedupe = len(monthly_raw)
    monthly_df = dedupe_archive_dataframe(
        monthly_raw, label=f"{dataset_label} archive"
    )
    return monthly_df, archive_rows_before_dedupe


def load_local_sanity_csv(csv_path: Path, *, dataset_label: str) -> pd.DataFrame:
    """Load existing local sanity_report CSV, or empty DataFrame if missing."""
    csv_path = Path(csv_path)
    if not csv_path.exists():
        print(f"  Local sanity CSV not found for {dataset_label}: {csv_path}")
        print("  Starting with empty local history.")
        return pd.DataFrame()
    try:
        df = pd.read_csv(csv_path, low_memory=False)
    except Exception as exc:
        raise RuntimeError(
            f"Failed reading local sanity CSV for {dataset_label} ({csv_path}): {exc}"
        ) from exc
    print(f"  Local sanity CSV loaded: {csv_path}")
    print(f"  Existing local rows   : {len(df):,}")
    return df


def save_local_sanity_csv(df: pd.DataFrame, csv_path: Path, *, dataset_label: str) -> Path:
    """Overwrite local sanity_report CSV with the combined history."""
    csv_path = Path(csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(csv_path, index=False)
    print(f"  Saved local sanity CSV ({dataset_label}): {csv_path}")
    print(f"  Local rows written    : {len(df):,}")
    return csv_path


def prompt_yes_no(message: str, *, default: bool = False) -> bool:
    """
    Ask the user a yes/no question.

    Accepts: y/yes/n/no (case-insensitive). Empty input uses ``default``.
    """
    suffix = " [Y/n]: " if default else " [y/N]: "
    while True:
        try:
            raw = input(message + suffix).strip().lower()
        except EOFError:
            print("\n  No interactive input — defaulting to "
                  f"{'YES' if default else 'NO'}.")
            return default
        if not raw:
            return default
        if raw in {"y", "yes"}:
            return True
        if raw in {"n", "no"}:
            return False
        print("  Please enter y/yes or n/no.")


def resolve_azure_upload_choice(
    *,
    upload_azure: Optional[bool] = None,
) -> bool:
    """
    Decide whether to replace Azure parquet files.

    Priority:
      1) Explicit CLI/run flag (True/False)
      2) Interactive yes/no prompt (default No)
    """
    if upload_azure is True:
        print("Azure upload: YES (flag --upload-azure)")
        return True
    if upload_azure is False:
        print("Azure upload: NO (flag --skip-azure)")
        return False

    print()
    print("=" * 60)
    print("LOCAL sanity_report CSV files have been updated.")
    print("Please review them before replacing Azure parquet files.")
    print("=" * 60)
    return prompt_yes_no(
        "Upload/replace Azure parquet files from the local CSV masters?",
        default=False,
    )


def upload_dataframe_parquet_with_retries(
    df: pd.DataFrame,
    *,
    name: str,
    filename: str,
    blob_service_client: BlobServiceClient,
    container_name: str,
    blob_folder: str,
    upload_max_workers: int,
    upload_max_retries: int,
) -> pd.DataFrame:
    """Upload/replace one Azure parquet blob from an in-memory DataFrame."""
    if df is None or df.empty:
        print(f"  [{name}] empty frame — skipping Azure upload.")
        return df if df is not None else pd.DataFrame()

    parquet_filename = filename if filename.endswith(".parquet") else f"{filename}.parquet"
    blob_path = f"{blob_folder}/{parquet_filename}"
    blob_client = blob_service_client.get_blob_client(
        container=container_name,
        blob=blob_path,
    )

    print("=" * 60)
    print(f"Uploading dataset : {name}")
    print(f"Blob path         : {blob_path}")
    print(f"Rows              : {len(df):,}")
    print("=" * 60)

    last_error = None
    for attempt in range(1, upload_max_retries + 1):
        try:
            print(f"Upload attempt {attempt}/{upload_max_retries}...")
            upload_parquet_block_blob(
                blob_client, df, upload_max_workers=upload_max_workers
            )
            print(f"Upload successful for {name}")
            print(f"  Final rows       : {len(df):,}")
            print()
            return df.reset_index(drop=True)
        except (
            ServiceResponseError,
            ServiceRequestError,
            TimeoutError,
            OSError,
        ) as exc:
            last_error = exc
            print(f"  Upload failed on attempt {attempt}/{upload_max_retries}: {exc}")
            if attempt == upload_max_retries:
                break
            wait_s = 5 * attempt
            print(f"  Retrying in {wait_s}s...")
            time.sleep(wait_s)

    raise RuntimeError(
        f"Azure upload failure for {name} after {upload_max_retries} attempts. "
        f"Last error: {last_error}"
    )


def sync_archive_month_to_azure(
    monthly_df: pd.DataFrame,
    filename: str,
    *,
    name: str,
    report_title: str,
    blob_service_client: BlobServiceClient,
    container_name: str,
    blob_folder: str,
    upload_max_workers: int,
    upload_max_retries: int,
    archive_rows_before_dedupe: Optional[int] = None,
    sanity_report_dir: Optional[Path] = None,
    local_csv_name: Optional[str] = None,
    upload_to_azure: bool = False,
) -> pd.DataFrame:
    """
    Archive-month sync (inventory / sales / order_forecast / store_sales):

      1) Read local sanity_report/{report}.csv (history master; no Azure download)
      2) Append month-archive DF
      3) Full-row drop_duplicates
      4) Save updated local CSV
      5) Optionally upload/replace Azure parquet (when upload_to_azure=True)
    """
    if sanity_report_dir is None:
        raise ValueError("sanity_report_dir is required for local CSV master sync")

    parquet_filename = filename if filename.endswith(".parquet") else f"{filename}.parquet"
    csv_name = local_csv_name or Path(parquet_filename).with_suffix(".csv").name
    local_csv_path = Path(sanity_report_dir) / csv_name

    print("=" * 60)
    print(f"Updating local master : {name}")
    print(f"Local CSV             : {local_csv_path}")
    print(f"Azure blob (pending)  : {blob_folder}/{parquet_filename}")
    print(f"Archive rows          : {len(monthly_df):,}")
    print("=" * 60)

    archive_before = (
        archive_rows_before_dedupe
        if archive_rows_before_dedupe is not None
        else len(monthly_df)
    )
    archive_after = len(monthly_df)
    archive_dupes_removed = max(archive_before - archive_after, 0)

    existing_local_df = load_local_sanity_csv(local_csv_path, dataset_label=name)
    local_rows_before = len(existing_local_df)

    if existing_local_df.empty:
        combined_df = monthly_df.copy()
    else:
        combined_df = pd.concat(
            [existing_local_df, monthly_df],
            ignore_index=True,
            sort=False,
        )

    combined_before = len(combined_df)
    final_df = combined_df.drop_duplicates().reset_index(drop=True)
    final_rows = len(final_df)
    total_dupes_removed = combined_before - final_rows
    net_new_rows = final_rows - local_rows_before

    print("=" * 40)
    print(report_title)
    print("=" * 40)
    print(f"Local CSV rows before update     : {local_rows_before:,}")
    print(f"New archive rows before dedupe   : {archive_before:,}")
    print(f"New archive rows after dedupe    : {archive_after:,}")
    print(f"Duplicates removed from archive  : {archive_dupes_removed:,}")
    print(f"Combined rows before dedupe      : {combined_before:,}")
    print(f"Final rows after dedupe          : {final_rows:,}")
    print(f"Total duplicates removed         : {total_dupes_removed:,}")
    print(f"Net new rows added               : {net_new_rows:,}")
    print("=" * 40)
    if net_new_rows > 0:
        print("New data was added successfully (local CSV)")
    else:
        print("No new unique rows found (local CSV)")
    print("=" * 40)

    if final_df.empty:
        print(f"  Final {name} frame is empty — skipping local save and Azure upload.")
        return final_df

    save_local_sanity_csv(final_df, local_csv_path, dataset_label=name)

    if not upload_to_azure:
        print(f"  [{name}] Local CSV saved — Azure upload deferred pending user confirmation.")
        print()
        return final_df

    return upload_dataframe_parquet_with_retries(
        final_df,
        name=name,
        filename=parquet_filename,
        blob_service_client=blob_service_client,
        container_name=container_name,
        blob_folder=blob_folder,
        upload_max_workers=upload_max_workers,
        upload_max_retries=upload_max_retries,
    )


# Backward-compatible alias
def sync_store_sales_archive_to_azure(*args, **kwargs) -> pd.DataFrame:
    kwargs.setdefault("name", "store_sales")
    kwargs.setdefault("report_title", "WALMART SCINTILLA STORE SALES REPORT")
    return sync_archive_month_to_azure(*args, **kwargs)


def sync_dataframe_to_azure(
    name: str,
    new_df: pd.DataFrame,
    filename: str,
    *,
    blob_service_client: BlobServiceClient,
    container_name: str,
    blob_folder: str,
    remove_duplicates: bool,
    append_only_sync: bool,
    upload_max_workers: int,
    upload_max_retries: int,
) -> pd.DataFrame:
    """
    Download Azure parquet, build dtype checklist, cast local DF to match,
    dedupe, append, then upload merged parquet.
    """
    blob_path = f"{blob_folder}/{filename}"
    blob_client = blob_service_client.get_blob_client(
        container=container_name,
        blob=blob_path,
    )

    print("=" * 60)
    print(f"Syncing dataset : {name}")
    print(f"Blob path       : {blob_path}")
    print(f"New local rows  : {len(new_df):,}")
    print(f"Mode            : {'append-only' if append_only_sync else 'full rewrite'}")
    print("=" * 60)

    azure_df = download_existing_parquet(
        blob_client, upload_max_workers=upload_max_workers
    )
    azure_schema = build_azure_dtype_checklist(azure_df)

    # Cast local dataframe columns to match Azure schema before append
    aligned_new_df = cast_df_to_schema(new_df, azure_schema, label="local")

    print("Finding rows that are not already in Azure...")
    new_only = (
        get_new_rows_only(azure_df, aligned_new_df)
        if remove_duplicates
        else aligned_new_df.copy()
    )

    if new_only.empty and not azure_df.empty:
        print("  No new rows to upload — keeping existing parquet as-is.")
        print(f"  Remote rows remain : {len(azure_df):,}")
        print()
        return azure_df if not azure_df.empty else aligned_new_df

    if azure_df.empty:
        merged_df = new_only.copy()
    else:
        # Align column order to Azure first, then any new local-only columns
        azure_cols = list(azure_df.columns)
        extra_cols = [c for c in new_only.columns if c not in azure_cols]
        merged_df = pd.concat(
            [azure_df, new_only.reindex(columns=azure_cols + extra_cols)],
            ignore_index=True,
        )
        # Re-apply Azure schema on merged result so parquet write stays clean
        merged_df = cast_df_to_schema(merged_df, azure_schema, label="merged")

    print(f"Merging and uploading parquet. New rows added: {len(new_only):,}")
    last_error = None
    for attempt in range(1, upload_max_retries + 1):
        try:
            print(f"Upload attempt {attempt}/{upload_max_retries}...")
            upload_parquet_block_blob(
                blob_client, merged_df, upload_max_workers=upload_max_workers
            )
            final_rows = len(merged_df)
            print(f"Upload successful for {name}")
            print(f"  New rows added   : {len(new_only):,}")
            print(f"  Final rows       : {final_rows:,}")
            print()
            return merged_df.reset_index(drop=True)

        except (
            ServiceResponseError,
            ServiceRequestError,
            TimeoutError,
            OSError,
        ) as exc:
            last_error = exc
            print(f"  Upload failed on attempt {attempt}/{upload_max_retries}: {exc}")
            if attempt == upload_max_retries:
                break
            wait_s = 5 * attempt
            print(f"  Retrying in {wait_s}s...")
            time.sleep(wait_s)

    raise RuntimeError(
        f"Upload failed after {upload_max_retries} attempts. Last error: {last_error}"
    )


def main(*, upload_azure: Optional[bool] = None) -> dict:
    """Walmart Scintilla processing + local CSV masters + optional Azure sync."""
    WALMART = cfg_paths.esh_walmart_root()
    
    archive_year = datetime.now().strftime("%Y")
    archive_month = datetime.now().strftime("%b")
    archive_day = datetime.now().strftime("%d")
    # e.g. 25-Aug-2026 — used in daily archive filenames after each source xlsx is processed
    archive_date = f"{archive_day}-{archive_month}-{archive_year}"
    print(f"Archive date stamp: {archive_date}")

    # reading sku mapper
    print("🪸 Reading sku mapper...🪸")
    Walmart_scintilla_sku = pd.read_csv(WALMART / "retail_team_files" / "sku_helper.csv")
    print(Walmart_scintilla_sku.head())
    ################################################################################################################################################################
    ################################################################# *reading inventory* ############################################################################
    ################################################################################################################################################################
    print("🦀 Reading inventory...🦀")
    Walmart_scintilla_inventory = pd.read_excel(WALMART / "eComm Inventory.xlsx")

    print(Walmart_scintilla_inventory.columns)
    Walmart_scintilla_inventory["report_date"] = (pd.to_datetime(Walmart_scintilla_inventory["report_date"],format="%d-%m-%Y",errors="coerce",).dt.strftime("%Y-%m-%d"))
    
    Walmart_scintilla_inventory = pd.merge(Walmart_scintilla_inventory,Walmart_scintilla_sku.loc[:, ["ecomm_upc_number", "WalMart SKU", "EcoSoul SKU"]],
                                           left_on="ecomm_upc_number",right_on="ecomm_upc_number",how="left")
    
    Walmart_scintilla_inventory["year"] = pd.to_datetime(Walmart_scintilla_inventory["report_date"]).dt.strftime("%Y")
    Walmart_scintilla_inventory["month"] = pd.to_datetime(Walmart_scintilla_inventory["report_date"]).dt.strftime("%b")

    Walmart_scintilla_inventory.columns = [to_snake(col) for col in Walmart_scintilla_inventory.columns]
    inventory_archive_folder = WALMART / "inventory" / str(archive_year) / str(archive_month)
    monthly_inventory_df, inventory_archive_before = save_and_load_archive_month(
        Walmart_scintilla_inventory,
        archive_folder=inventory_archive_folder,
        csv_filename=f"Walmart_scintilla_inventory_{archive_date}.csv",
        dataset_label="inventory",
    )
    print(monthly_inventory_df.head())

    ################################################################################################################################################################
    ################################################################# *reading sales* #############################################################################
    ################################################################################################################################################################
    print("🦀 Reading sales...🦀")
    Walmart_scintilla_sales = pd.read_excel(WALMART / "eComm_Sales.xlsx")

    Walmart_scintilla_sales["business_date"] = (pd.to_datetime(Walmart_scintilla_sales["business_date"],format="%d-%m-%Y",errors="coerce").dt.strftime("%Y-%m-%d"))
    Walmart_scintilla_sales = pd.merge(Walmart_scintilla_sales,Walmart_scintilla_sku.loc[:, ["item_number", "WalMart SKU", "EcoSoul SKU"]],
                                       left_on="walmart_item_number",right_on="item_number",how="left")

    Walmart_scintilla_sales["year"] = pd.to_datetime(Walmart_scintilla_sales["business_date"]).dt.strftime("%Y")
    Walmart_scintilla_sales["month"] = pd.to_datetime(Walmart_scintilla_sales["business_date"]).dt.strftime("%b")

    Walmart_scintilla_sales.columns = [to_snake(col) for col in Walmart_scintilla_sales.columns]
    sales_archive_folder = WALMART / "ecom_sales" / str(archive_year) / str(archive_month)
    monthly_sales_df, sales_archive_before = save_and_load_archive_month(
        Walmart_scintilla_sales,
        archive_folder=sales_archive_folder,
        csv_filename=f"Walmart_scintilla_sales_{archive_date}.csv",
        dataset_label="sales",
    )
    print(monthly_sales_df.head())

    ################################################################################################################################################################
    ################################################################# *reading order forecast* ############################################################################
    ################################################################################################################################################################
 
    print("🦀 Reading order forecast...🦀")
    Walmart_scintilla_Order_Forecast = pd.read_excel(WALMART / "Order Forecast.xlsx")

    Walmart_scintilla_Order_Forecast["sugg_order_dt"] = (pd.to_datetime(Walmart_scintilla_Order_Forecast["sugg_order_dt"],format="%d-%m-%Y",errors="coerce").dt.strftime("%Y-%m-%d"))
    Walmart_scintilla_Order_Forecast["order_place_dt"] = (pd.to_datetime(Walmart_scintilla_Order_Forecast["order_place_dt"],format="%d-%m-%Y",errors="coerce").dt.strftime("%Y-%m-%d"))
    Walmart_scintilla_Order_Forecast["sched_arvl_dt"] = (pd.to_datetime(Walmart_scintilla_Order_Forecast["sched_arvl_dt"],format="%d-%m-%Y",errors="coerce").dt.strftime("%Y-%m-%d"))

    Walmart_scintilla_Order_Forecast = pd.merge(Walmart_scintilla_Order_Forecast,Walmart_scintilla_sku.loc[:, ["item_number", "WalMart SKU", "EcoSoul SKU"]],
                                               left_on="wm_item_nbr",right_on="item_number",how="left")
    
    Walmart_scintilla_Order_Forecast["year"] = pd.to_datetime(Walmart_scintilla_Order_Forecast["order_place_dt"]).dt.strftime("%Y")
    Walmart_scintilla_Order_Forecast["month"] = pd.to_datetime(Walmart_scintilla_Order_Forecast["order_place_dt"]).dt.strftime("%b")

    Walmart_scintilla_Order_Forecast.columns = [to_snake(col) for col in Walmart_scintilla_Order_Forecast.columns]
    order_forecast_archive_folder = (
        WALMART / "order_forecast" / str(archive_year) / str(archive_month)
    )
    monthly_order_forecast_df, order_forecast_archive_before = save_and_load_archive_month(
        Walmart_scintilla_Order_Forecast,
        archive_folder=order_forecast_archive_folder,
        csv_filename=f"Walmart_scintilla_order_forecast_{archive_date}.csv",
        dataset_label="order_forecast",
    )

    ################################################################################################################################################################
    ################################################################# *reading store sales* ############################################################################
    ################################################################################################################################################################
    print("🦀 Reading store sales...🦀")
    Walmart_scintilla_store_sales = pd.read_excel(WALMART / "Store Sales & Inventory.xlsx")

    Walmart_scintilla_store_sales["business_date"] = (pd.to_datetime(Walmart_scintilla_store_sales["business_date"],format="%d-%m-%Y",errors="coerce",).dt.strftime("%Y-%m-%d"))
    Walmart_scintilla_store_sales = pd.merge(Walmart_scintilla_store_sales,Walmart_scintilla_sku.loc[:, ["item_number", "WalMart SKU", "EcoSoul SKU"]],
                                             left_on="walmart_item_number",right_on="item_number",how="left",)

    Walmart_scintilla_store_sales["year"] = pd.to_datetime(Walmart_scintilla_store_sales["business_date"]).dt.strftime("%Y")
    Walmart_scintilla_store_sales["month"] = pd.to_datetime(Walmart_scintilla_store_sales["business_date"]).dt.strftime("%b")

    Walmart_scintilla_store_sales.columns = [to_snake(col) for col in Walmart_scintilla_store_sales.columns]
    store_sales_archive_folder = (
        WALMART / "store_sales" / str(archive_year) / str(archive_month)
    )
    monthly_store_sales_df, store_sales_archive_before = save_and_load_archive_month(
        Walmart_scintilla_store_sales,
        archive_folder=store_sales_archive_folder,
        csv_filename=f"Walmart_scintilla_store_sales_{archive_date}.csv",
        dataset_label="store_sales",
    )

    # ==========================================================
    # Azure Storage Details (.env) — paths match main script
    # Local history master: {ESH_WALMART_ROOT}/sanity_report/*.csv
    # ==========================================================
    container_name = _azure_container()
    BLOB_FOLDER = _azure_blob_folder()
    sanity_report_dir = WALMART / "sanity_report"
    sanity_report_dir.mkdir(parents=True, exist_ok=True)
    print(f"Azure target: {container_name}/{BLOB_FOLDER}/")
    print(f"Local sanity_report: {sanity_report_dir}")

    # Upload / download tuning (same as main_walmart_scintilla.py)
    UPLOAD_MAX_WORKERS = 4
    UPLOAD_BLOCK_SIZE = 4 * 1024 * 1024  # 4 MB blocks
    UPLOAD_MAX_RETRIES = 5
    CONNECTION_TIMEOUT = 300  # seconds
    READ_TIMEOUT = 600  # seconds
    REMOVE_DUPLICATES = True
    APPEND_ONLY_SYNC = True

    connection_string = _azure_connection_string()

    blob_service_client = BlobServiceClient.from_connection_string(
        connection_string,
        connection_timeout=CONNECTION_TIMEOUT,
        read_timeout=READ_TIMEOUT,
        retry_policy=ExponentialRetry(
            initial_backoff=3,
            increment_base=3,
            retry_total=8,
        ),
        max_single_put_size=8 * 1024 * 1024,
        max_block_size=UPLOAD_BLOCK_SIZE,
    )

    # Local CSV master + Azure parquet replace (no Azure download)
    ARCHIVE_DATASETS_TO_SYNC = [
        {
            "name": "inventory",
            "df": monthly_inventory_df,
            "filename": "walmart_scintilla_inventory.parquet",
            "local_csv_name": "walmart_scintilla_inventory.csv",
            "report_title": "WALMART SCINTILLA INVENTORY REPORT",
            "archive_rows_before_dedupe": inventory_archive_before,
        },
        {
            "name": "sales",
            "df": monthly_sales_df,
            "filename": "walmart_scintilla_sales.parquet",
            "local_csv_name": "walmart_scintilla_sales.csv",
            "report_title": "WALMART SCINTILLA SALES REPORT",
            "archive_rows_before_dedupe": sales_archive_before,
        },
        {
            "name": "order_forecast",
            "df": monthly_order_forecast_df,
            "filename": "walmart_scintilla_order_forecast.parquet",
            "local_csv_name": "walmart_scintilla_order_forecast.csv",
            "report_title": "WALMART SCINTILLA ORDER FORECAST REPORT",
            "archive_rows_before_dedupe": order_forecast_archive_before,
        },
        {
            "name": "store_sales",
            "df": monthly_store_sales_df,
            "filename": "walmart_scintilla_store_sales.parquet",
            "local_csv_name": "walmart_scintilla_store_sales.csv",
            "report_title": "WALMART SCINTILLA STORE SALES REPORT",
            "archive_rows_before_dedupe": store_sales_archive_before,
        },
    ]

    sync_results = {}
    pending_azure_uploads = []
    for dataset in ARCHIVE_DATASETS_TO_SYNC:
        frame = sync_archive_month_to_azure(
            dataset["df"],
            filename=dataset["filename"],
            name=dataset["name"],
            report_title=dataset["report_title"],
            blob_service_client=blob_service_client,
            container_name=container_name,
            blob_folder=BLOB_FOLDER,
            upload_max_workers=UPLOAD_MAX_WORKERS,
            upload_max_retries=UPLOAD_MAX_RETRIES,
            archive_rows_before_dedupe=dataset["archive_rows_before_dedupe"],
            sanity_report_dir=sanity_report_dir,
            local_csv_name=dataset["local_csv_name"],
            upload_to_azure=False,  # always confirm before Azure replace
        )
        sync_results[dataset["name"]] = frame
        pending_azure_uploads.append(
            {
                "name": dataset["name"],
                "df": frame,
                "filename": dataset["filename"],
                "local_csv": str(sanity_report_dir / dataset["local_csv_name"]),
            }
        )

    print()
    print("=" * 60)
    print("Local sanity_report CSV files ready for review:")
    for item in pending_azure_uploads:
        rows = len(item["df"]) if item["df"] is not None else 0
        print(f"  - {item['local_csv']}  ({rows:,} rows)")
    print("=" * 60)

    do_upload = resolve_azure_upload_choice(upload_azure=upload_azure)
    if do_upload:
        print("Proceeding with Azure parquet replace from local CSV masters...")
        for item in pending_azure_uploads:
            sync_results[item["name"]] = upload_dataframe_parquet_with_retries(
                item["df"],
                name=item["name"],
                filename=item["filename"],
                blob_service_client=blob_service_client,
                container_name=container_name,
                blob_folder=BLOB_FOLDER,
                upload_max_workers=UPLOAD_MAX_WORKERS,
                upload_max_retries=UPLOAD_MAX_RETRIES,
            )

        # SKU helper remains on the existing append-only hash sync
        sync_results["sku"] = sync_dataframe_to_azure(
            name="sku",
            new_df=Walmart_scintilla_sku,
            filename="walmart_scintilla_sku.parquet",
            blob_service_client=blob_service_client,
            container_name=container_name,
            blob_folder=BLOB_FOLDER,
            remove_duplicates=REMOVE_DUPLICATES,
            append_only_sync=APPEND_ONLY_SYNC,
            upload_max_workers=UPLOAD_MAX_WORKERS,
            upload_max_retries=UPLOAD_MAX_RETRIES,
        )
        print("=" * 60)
        print("All Azure uploads complete")
    else:
        print("Skipped Azure parquet upload/replace. Local CSV masters were kept.")
        print("Re-run later with --upload-azure after you have reviewed the files.")
        sync_results["sku"] = Walmart_scintilla_sku
        print("=" * 60)
        print("Local CSV update complete (Azure skipped)")

    for name, result_df in sync_results.items():
        print(f"  {name:<18} -> {len(result_df):,} rows")
    print("=" * 60)
    return sync_results


def run(
    *,
    client: str = "ESH",
    geos: Optional[Sequence[str]] = None,
    upload_azure: Optional[bool] = None,
    skip_azure: bool = False,
    **_kwargs,
) -> dict:
    """Pipeline CLI entrypoint: run(client='ESH')."""
    del geos  # retail Walmart is not geo-split
    print(f"Walmart Scintilla retail sync (client={client})")
    print(f"Walmart root: {cfg_paths.esh_walmart_root()}")

    choice = upload_azure
    if skip_azure:
        choice = False
    elif upload_azure is True:
        choice = True

    return main(upload_azure=choice)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="ESH Walmart / Scintilla retail sync"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--upload-azure",
        action="store_true",
        help="Replace Azure parquet without prompting (after local CSV update)",
    )
    group.add_argument(
        "--skip-azure",
        action="store_true",
        help="Update local sanity_report CSVs only; do not upload Azure parquet",
    )
    args = parser.parse_args()
    upload_choice: Optional[bool]
    if args.upload_azure:
        upload_choice = True
    elif args.skip_azure:
        upload_choice = False
    else:
        upload_choice = None
    run(upload_azure=upload_choice)
    print_script_completed("c_walmart_scintilla")