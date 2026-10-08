"""
Upload just-saved local Amazon report parquet files to Azure Blob Storage.

Used by ageing / manage_fba / reserved / ledger / inventory_database after local export.
Container: CONTAINER_NAME_ESH or CONTAINER_NAME_KNC (from .env).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Sequence

_AZURE_CONTAINER_ENV: Dict[str, str] = {
    "ESH": "CONTAINER_NAME_ESH",
    "KNC": "CONTAINER_NAME_KNC",
}


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
    return ""


def azure_container_for_client(client_code: str) -> str:
    key = str(client_code).strip().upper()
    env_name = _AZURE_CONTAINER_ENV.get(key)
    if not env_name:
        return ""
    return _clean_env(os.getenv(env_name, ""))


def upload_parquets_to_azure(
    parquet_paths: Sequence[Path],
    *,
    client_code: str,
    blob_folder: str,
    label: str = "parquet",
) -> List[str]:
    """
    Upload local parquet files to:
      {CONTAINER_NAME_ESH|KNC}/{blob_folder}/{filename}.parquet
    """
    paths = [
        Path(p)
        for p in parquet_paths
        if Path(p).suffix.lower() == ".parquet"
    ]
    if not paths:
        return []

    conn = azure_connection_string()
    container = azure_container_for_client(client_code)
    if not conn:
        print("[azure] Skipped: missing AZURE_STORAGE_CONNECTION_STRING (or account/key)")
        return []
    if not container:
        env_hint = _AZURE_CONTAINER_ENV.get(
            str(client_code).strip().upper(), "CONTAINER_NAME_*"
        )
        print(f"[azure] Skipped: missing {env_hint} for client {client_code}")
        return []

    from azure.storage.blob import BlobServiceClient, ContentSettings

    folder = str(blob_folder or "").strip().strip("/").replace("\\", "/")
    bsc = BlobServiceClient.from_connection_string(conn)
    container_client = bsc.get_container_client(container)

    uploaded: List[str] = []
    print(f"\n>>> STEP: upload {label} → {container}/{folder}/")
    for path in paths:
        if not path.is_file():
            print(f"  [skip] missing local file: {path}")
            continue
        blob_path = f"{folder}/{path.name}" if folder else path.name
        with path.open("rb") as fh:
            container_client.get_blob_client(blob_path).upload_blob(
                fh,
                overwrite=True,
                content_settings=ContentSettings(content_type="application/octet-stream"),
            )
        uploaded.append(f"{container}/{blob_path}")
        print(f"  [ok] {path.name} -> {container}/{blob_path}")
    return uploaded
