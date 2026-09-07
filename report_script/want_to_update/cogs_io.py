"""Shared helpers for ESH / KNC COGS: Azure upload / download + optional local IO."""
from __future__ import annotations

import os
import re
import time
from io import BytesIO
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

import pandas as pd
from azure.core.exceptions import ServiceResponseError
from azure.storage.blob import BlobServiceClient

from config_manager import paths as cfg_paths

# Blob folder inside COGS_AZURE_CONTAINER / ITEM_MASTER_CONTAINER / app-helper
CLIENT_AZURE_PREFIX: Dict[str, str] = {
    "ESH": "thrive-client-ecosoulhome/cogs",
    "KNC": "thrive-client-kinetica/cogs",
}


def to_snake(name: str) -> str:
    name = str(name).strip().lower()
    name = re.sub(r"[^a-z0-9]+", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    return name


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
        "Missing Azure credentials. Set AZURE_STORAGE_CONNECTION_STRING "
        "or AZURE_STORAGE_ACCOUNT_NAME + AZURE_STORAGE_ACCOUNT_KEY in .env."
    )


def azure_container() -> str:
    override = _clean_env(os.getenv("COGS_AZURE_CONTAINER", ""))
    if override:
        return override
    override = _clean_env(os.getenv("ITEM_MASTER_CONTAINER", ""))
    if override:
        return override
    return "app-helper"


def local_cogs_dir(client: str) -> Path:
    """{project_root}/cogs/{client}/  (lowercase client folder, e.g. knc, esh)"""
    out = cfg_paths.project_root() / "cogs" / client.strip().lower()
    out.mkdir(parents=True, exist_ok=True)
    return out


def local_cogs_path(client: str, country: str, channel: str) -> Path:
    """cogs/{client}/{country}_{channel}_cogs.parquet"""
    name = f"{str(country).strip().lower()}_{str(channel).strip().lower()}_cogs.parquet"
    return local_cogs_dir(client) / name


def save_local_cogs(df: pd.DataFrame, client: str, country: str, channel: str) -> Path:
    path = local_cogs_path(client, country, channel)
    out = df.copy()
    object_cols = out.select_dtypes(include="object").columns
    out[object_cols] = out[object_cols].astype(str)
    out.to_parquet(path, index=False)
    csv_path = path.with_suffix(".csv")
    out.to_csv(csv_path, index=False)
    print(f"  Local save -> {path} ({len(out):,} rows)")
    print(f"               -> {csv_path}")
    return path


def upload_blob_with_retry(
    blob_client,
    data,
    blob_path: str,
    *,
    max_retries: int = 3,
    max_concurrency: int = 4,
    timeout: int = 600,
) -> None:
    for attempt in range(max_retries):
        try:
            data.seek(0)
            blob_client.upload_blob(
                data,
                overwrite=True,
                max_concurrency=max_concurrency,
                timeout=timeout,
            )
            print(f"  Azure uploaded: {blob_path}")
            return
        except ServiceResponseError as exc:
            wait = (2 ** attempt) * 5
            print(
                f"  Azure upload failed (attempt {attempt + 1}/{max_retries}) "
                f"for {blob_path}: {exc}"
            )
            print(f"  Retrying in {wait}s...")
            time.sleep(wait)
        except Exception as exc:
            print(f"  Unexpected Azure error for {blob_path}: {exc}")
            raise
    raise RuntimeError(f"Upload failed after {max_retries} attempts: {blob_path}")


def _prepare_df_for_export(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    object_cols = out.select_dtypes(include="object").columns
    out[object_cols] = out[object_cols].astype(str)
    out = out.where(pd.notnull(out), None)
    return out


def upload_to_azure_parquet(
    df: pd.DataFrame,
    blob_path: str,
    *,
    connection_string: Optional[str] = None,
    container_name: Optional[str] = None,
) -> None:
    payload = _prepare_df_for_export(df)
    buffer = BytesIO()
    payload.to_parquet(buffer, index=False)
    buffer.seek(0)
    conn = connection_string or azure_connection_string()
    container = container_name or azure_container()
    bsc = BlobServiceClient.from_connection_string(
        conn, connection_timeout=600, read_timeout=600
    )
    blob = bsc.get_blob_client(container=container, blob=blob_path)
    upload_blob_with_retry(blob, buffer, blob_path)


def upload_to_azure_csv(
    df: pd.DataFrame,
    blob_path: str,
    *,
    connection_string: Optional[str] = None,
    container_name: Optional[str] = None,
) -> None:
    payload = _prepare_df_for_export(df)
    buffer = BytesIO()
    payload.to_csv(buffer, index=False)
    buffer.seek(0)
    conn = connection_string or azure_connection_string()
    container = container_name or azure_container()
    bsc = BlobServiceClient.from_connection_string(
        conn, connection_timeout=600, read_timeout=600
    )
    blob = bsc.get_blob_client(container=container, blob=blob_path)
    upload_blob_with_retry(blob, buffer, blob_path)


def azure_prefix_for_client(client: str) -> str:
    key = str(client).strip().upper()
    if key not in CLIENT_AZURE_PREFIX:
        raise ValueError(
            f"No Azure COGS prefix for client={client!r}. "
            f"Known: {sorted(CLIENT_AZURE_PREFIX)}"
        )
    return CLIENT_AZURE_PREFIX[key]


def list_cogs_blobs(
    client: str,
    *,
    extensions: Sequence[str] = (".parquet", ".csv"),
    connection_string: Optional[str] = None,
    container_name: Optional[str] = None,
) -> List[str]:
    """List blob paths under the client COGS prefix (relative to container)."""
    prefix = azure_prefix_for_client(client).rstrip("/") + "/"
    conn = connection_string or azure_connection_string()
    container = container_name or azure_container()
    bsc = BlobServiceClient.from_connection_string(
        conn, connection_timeout=600, read_timeout=600
    )
    container_client = bsc.get_container_client(container)
    exts = {e.lower() if e.startswith(".") else f".{e.lower()}" for e in extensions}
    found: List[str] = []
    for blob in container_client.list_blobs(name_starts_with=prefix):
        name = blob.name
        if any(name.lower().endswith(ext) for ext in exts):
            found.append(name)
    return sorted(found)


def download_blob_to_path(
    blob_path: str,
    dest: Path,
    *,
    connection_string: Optional[str] = None,
    container_name: Optional[str] = None,
) -> Path:
    conn = connection_string or azure_connection_string()
    container = container_name or azure_container()
    bsc = BlobServiceClient.from_connection_string(
        conn, connection_timeout=600, read_timeout=600
    )
    blob = bsc.get_blob_client(container=container, blob=blob_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    data = blob.download_blob().readall()
    dest.write_bytes(data)
    print(f"  Azure download: {blob_path} -> {dest} ({len(data):,} bytes)")
    return dest


def download_cogs_from_azure(
    client: str,
    *,
    dest_dir: Optional[Path] = None,
    geos: Optional[Sequence[str]] = None,
    extensions: Sequence[str] = (".parquet", ".csv"),
    connection_string: Optional[str] = None,
    container_name: Optional[str] = None,
) -> List[Path]:
    """
    Download latest COGS blobs for ``client`` into ``cogs/{client}/``.

    Optional ``geos`` filters blob basenames that start with the geo code
    (e.g. UK → uk_amazon_cogs.parquet, uk_shopify_cogs.parquet).
    """
    out_dir = Path(dest_dir) if dest_dir is not None else local_cogs_dir(client)
    out_dir.mkdir(parents=True, exist_ok=True)

    blobs = list_cogs_blobs(
        client,
        extensions=extensions,
        connection_string=connection_string,
        container_name=container_name,
    )
    if not blobs:
        prefix = azure_prefix_for_client(client)
        raise FileNotFoundError(
            f"No COGS blobs under container/{prefix} for client={client.upper()}."
        )

    wanted = None
    if geos is not None:
        wanted = {str(g).strip().lower() for g in geos if str(g).strip()}
        if not wanted:
            wanted = None

    saved: List[Path] = []
    for blob_path in blobs:
        basename = Path(blob_path).name
        stem = basename.rsplit(".", 1)[0].lower()
        if wanted is not None:
            # Match uk_amazon_cogs / usa_amazon_cogs when geo is UK / US
            geo_ok = False
            for g in wanted:
                aliases = {g, "usa" if g == "us" else g, "us" if g == "usa" else g}
                if any(stem.startswith(f"{a}_") for a in aliases):
                    geo_ok = True
                    break
            if not geo_ok:
                continue
        dest = out_dir / basename
        download_blob_to_path(
            blob_path,
            dest,
            connection_string=connection_string,
            container_name=container_name,
        )
        saved.append(dest)

    if not saved:
        raise FileNotFoundError(
            f"No COGS blobs matched geos={sorted(wanted or [])} for {client.upper()}."
        )
    print(f"\n{client.upper()} COGS download done — {len(saved)} file(s) -> {out_dir}")
    return saved


def load_sheet(
    cogs_path: Path,
    sheet_name: str,
    *,
    country: str,
    channel: str,
    client_id: str,
    columns: Iterable[str],
) -> pd.DataFrame:
    df = pd.read_excel(cogs_path, sheet_name=sheet_name)
    df = df.copy()
    df["country"] = country
    df["channel"] = channel
    df["client_id"] = client_id
    keep = list(columns)
    missing = [c for c in keep if c not in df.columns]
    if missing:
        raise KeyError(
            f"Sheet {sheet_name!r} missing columns {missing}. "
            f"Have: {list(df.columns)}"
        )
    df = df.loc[:, keep]
    df.columns = [to_snake(c) for c in df.columns]
    df = df.fillna(0)
    print(
        f"  Loaded {sheet_name!r} -> {country}/{channel}: "
        f"{len(df):,} rows x {len(df.columns)} cols"
    )
    return df
