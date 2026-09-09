"""
Shared Azure CSV append + dedupe helpers for ESH retail (KeHE / Sprouts).

Covers:
  - Credentials: AZURE_STORAGE_CONNECTION_STRING or account/key; CONTAINER_NAME_ESH
  - Default blob folder: sanity_data/retail/ (RETAIL_BLOB_PREFIX / WALMART_BLOB_PREFIX)
  - download_existing_csv → concat → hash dedupe → upload overwrite

Not a standalone report — imported by a_kehe.py and b_sprouts.py.
"""

from __future__ import annotations

import os
import time
from io import BytesIO
from typing import Dict, Sequence, Tuple

import numpy as np
import pandas as pd
from azure.core.exceptions import ServiceRequestError, ServiceResponseError
from azure.storage.blob import BlobServiceClient, BlobType, ExponentialRetry

from report_script.retail import drop_duplicates_appended


def _clean_env(value: str) -> str:
    return str(value or "").strip().strip('"').strip("'")


def azure_connection_string() -> str:
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


def azure_container() -> str:
    container = _clean_env(os.getenv("CONTAINER_NAME_ESH", ""))
    if not container:
        raise EnvironmentError(
            "Missing CONTAINER_NAME_ESH in .env (e.g. thrive-client-ecosoulhome)."
        )
    return container


def retail_blob_prefix() -> str:
    raw = _clean_env(os.getenv("RETAIL_BLOB_PREFIX", os.getenv("WALMART_BLOB_PREFIX", "sanity_data/retail")))
    return raw.strip("/")


def format_mb(num_bytes: float) -> str:
    return f"{num_bytes / (1024 ** 2):.2f} MB"


def make_blob_service_client(
    *,
    connection_timeout: int = 300,
    read_timeout: int = 600,
    upload_block_size: int = 4 * 1024 * 1024,
) -> BlobServiceClient:
    return BlobServiceClient.from_connection_string(
        azure_connection_string(),
        connection_timeout=connection_timeout,
        read_timeout=read_timeout,
        retry_policy=ExponentialRetry(
            initial_backoff=3,
            increment_base=3,
            retry_total=8,
        ),
        max_single_put_size=8 * 1024 * 1024,
        max_block_size=upload_block_size,
    )


def download_existing_csv(client, *, upload_max_workers: int = 4) -> pd.DataFrame:
    """Download existing Azure blob as CSV (parquet fallback)."""
    print("Downloading existing Azure CSV (for append + dedupe)...")
    start = time.time()
    try:
        downloader = client.download_blob(max_concurrency=upload_max_workers)
        total = downloader.size or 0
        if total:
            print(f"  Remote blob size : {format_mb(total)} ({total:,} bytes)")

        chunks = []
        for chunk in downloader.chunks():
            chunks.append(chunk)
        blob_bytes = b"".join(chunks)

        try:
            azure_df = pd.read_csv(BytesIO(blob_bytes), low_memory=False)
            source_format = "csv"
        except Exception:
            azure_df = pd.read_parquet(BytesIO(blob_bytes))
            source_format = "parquet"

        print(f"  Existing rows    : {len(azure_df):,}")
        print(f"  Existing format  : {source_format}")
        print(f"  Download time    : {time.time() - start:.1f}s")
        return azure_df
    except Exception as exc:
        print(f"  File not found / download failed ({exc}). Treating as empty.")
        return pd.DataFrame()


def _normalize_for_hash(df: pd.DataFrame) -> pd.DataFrame:
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
    if new_df is None or new_df.empty:
        return pd.DataFrame()

    cleaned_new = new_df.drop_duplicates(keep="last").reset_index(drop=True)
    if azure_df is None or azure_df.empty:
        print("  No existing Azure rows — all local rows are new.")
        return cleaned_new

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


def upload_csv_block_blob(client, df: pd.DataFrame, *, upload_max_workers: int = 4) -> None:
    print("  Uploading merged data as CSV block blob...")
    start = time.time()
    buffer = BytesIO()
    df.to_csv(buffer, index=False)
    data = buffer.getvalue()
    total_size = len(data)
    print(f"  Upload size       : {format_mb(total_size)} ({total_size:,} bytes)")

    client.upload_blob(
        data=data,
        overwrite=True,
        blob_type=BlobType.BLOCKBLOB,
        max_concurrency=upload_max_workers,
        content_type="text/csv",
    )
    elapsed = time.time() - start
    speed = (total_size / (1024 ** 2)) / elapsed if elapsed > 0 else 0
    print(f"  Upload time       : {elapsed:.1f}s | {speed:.2f} MB/s")


def sync_dataframe_to_azure_csv(
    name: str,
    new_df: pd.DataFrame,
    blob_path: str,
    *,
    blob_service_client: BlobServiceClient,
    container_name: str,
    remove_duplicates: bool = True,
    upload_max_workers: int = 4,
    upload_max_retries: int = 5,
) -> pd.DataFrame:
    """
    Download existing Azure CSV → append only new rows → drop_duplicates on
    the combined Azure file → upload CSV back.
    """
    blob_path = str(blob_path).lstrip("/")
    blob_client = blob_service_client.get_blob_client(
        container=container_name,
        blob=blob_path,
    )

    print("=" * 60)
    print(f"Syncing dataset : {name}")
    print(f"Blob path       : {container_name}/{blob_path}")
    print(f"New local rows  : {len(new_df):,}")
    print("=" * 60)

    azure_df = download_existing_csv(blob_client, upload_max_workers=upload_max_workers)

    print("Finding rows that are not already in Azure...")
    new_only = (
        get_new_rows_only(azure_df, new_df)
        if remove_duplicates
        else (new_df.copy() if new_df is not None else pd.DataFrame())
    )

    if new_only.empty and not azure_df.empty:
        # Still re-dedupe the Azure file itself (historical duplicates)
        merged_df = drop_duplicates_appended(azure_df, f"azure {name}")
        if len(merged_df) == len(azure_df):
            print("  No new rows and Azure already clean — skipping upload.")
            print(f"  Remote rows remain : {len(azure_df):,}")
            print()
            return azure_df
        print("  No new rows, but Azure had duplicates — rewriting cleaned CSV.")
    elif azure_df.empty:
        merged_df = new_only.copy()
    else:
        azure_cols = list(azure_df.columns)
        extra_cols = [c for c in new_only.columns if c not in azure_cols]
        merged_df = pd.concat(
            [azure_df, new_only.reindex(columns=azure_cols + extra_cols)],
            ignore_index=True,
        )
        merged_df = drop_duplicates_appended(merged_df, f"azure {name}")

    if merged_df is None or merged_df.empty:
        print("  Nothing to upload.")
        print()
        return pd.DataFrame()

    last_error = None
    for attempt in range(1, upload_max_retries + 1):
        try:
            print(f"Upload attempt {attempt}/{upload_max_retries}...")
            upload_csv_block_blob(
                blob_client, merged_df, upload_max_workers=upload_max_workers
            )
            print(f"Upload successful for {name}")
            print(f"  New rows added   : {len(new_only):,}")
            print(f"  Final rows       : {len(merged_df):,}")
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


def sync_datasets_to_azure_csv(
    datasets: Sequence[Tuple[str, pd.DataFrame, str]],
    *,
    skip_azure: bool = False,
) -> Dict[str, pd.DataFrame]:
    """
    datasets: list of (name, dataframe, blob_path)
    blob_path may be full path (sanity_data/retail/foo.csv) or just filename.
    """
    if skip_azure:
        print("[azure] Skipped (--skip-azure / SKIP_AZURE)")
        return {}

    container_name = azure_container()
    prefix = retail_blob_prefix()
    print(f"Azure target: {container_name}/{prefix}/")

    blob_service_client = make_blob_service_client()
    results: Dict[str, pd.DataFrame] = {}

    for name, df, blob_path in datasets:
        path = str(blob_path).lstrip("/")
        if "/" not in path:
            path = f"{prefix}/{path}"
        results[name] = sync_dataframe_to_azure_csv(
            name=name,
            new_df=df,
            blob_path=path,
            blob_service_client=blob_service_client,
            container_name=container_name,
        )

    print("=" * 60)
    print("Azure CSV uploads complete")
    for name, result_df in results.items():
        print(f"  {name:<22} -> {len(result_df):,} rows")
    print("=" * 60)
    return results
