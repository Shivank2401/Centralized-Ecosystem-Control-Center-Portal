"""
Export any local file (CSV / Parquet / Excel / …) to Azure Blob Storage.

User picks:
  1. Local file path
  2. Container key: esh | knc | emm  (maps to CONTAINER_NAME_* in .env)
  3. Blob folder / prefix under that container (existing or new)
  4. Destination blob name — or keep the uploaded file's name + extension

Portal:
  Dedicated Data → Azure Upload page (multipart upload via /api/azure/*).
  Also registered as utility report; when run from pipeline, set kwargs/env:
    local_path / UTILITY_AZURE_LOCAL_PATH
    container_key / UTILITY_AZURE_CONTAINER_KEY
    blob_folder / UTILITY_AZURE_BLOB_FOLDER
    blob_name / UTILITY_AZURE_BLOB_NAME  (optional — keep source name if empty)

CLI:
    python report_script/utility_codes/d_export_file_to_azure.py
    python report_script/utility_codes/d_export_file_to_azure.py \\
        --file data.csv --container esh --folder sanity_data/uploads --name my_data.csv
    python report_script/utility_codes/d_export_file_to_azure.py --list-folders --container knc
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config_manager import paths as cfg_paths  # noqa: F401  # loads .env

# Allowed upload extensions (user can still upload other types via --force)
DEFAULT_ALLOWED_EXTENSIONS = {
    ".csv",
    ".parquet",
    ".xlsx",
    ".xls",
    ".tsv",
    ".txt",
    ".json",
}

# Short keys shown in UI / CLI → env var holding the real Azure container name
CONTAINER_KEY_ENV: Dict[str, str] = {
    "esh": "CONTAINER_NAME_ESH",
    "knc": "CONTAINER_NAME_KNC",
    "emm": "CONTAINER_NAME_EMAMI",
}

CONTAINER_KEY_DEFAULTS: Dict[str, str] = {
    "esh": "thrive-client-ecosoulhome",
    "knc": "thrive-client-kinetica",
    "emm": "thrive-client-emami",
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
    raise EnvironmentError(
        "Missing Azure credentials. Set AZURE_STORAGE_CONNECTION_STRING "
        "or AZURE_STORAGE_ACCOUNT_NAME + AZURE_STORAGE_ACCOUNT_KEY in .env."
    )


def normalize_container_key(key: str) -> str:
    k = str(key or "").strip().lower()
    # allow aliases
    aliases = {
        "esh": "esh",
        "ecosoul": "esh",
        "ecosoulhome": "esh",
        "knc": "knc",
        "kinetica": "knc",
        "emm": "emm",
        "emami": "emm",
        "emami_report": "emm",
    }
    if k not in aliases:
        raise ValueError(
            f"Unknown container key {key!r}. Use one of: esh, knc, emm."
        )
    return aliases[k]


def resolve_container_name(container_key: str) -> str:
    key = normalize_container_key(container_key)
    env_name = CONTAINER_KEY_ENV[key]
    name = _clean_env(os.getenv(env_name, "")) or CONTAINER_KEY_DEFAULTS[key]
    return name


def list_container_options() -> List[Dict[str, str]]:
    """Portal/CLI: available container keys with resolved Azure names."""
    out = []
    for key in ("esh", "knc", "emm"):
        out.append(
            {
                "key": key,
                "label": key.upper() if key != "emm" else "EMM",
                "container_name": resolve_container_name(key),
                "env_var": CONTAINER_KEY_ENV[key],
            }
        )
    return out


def _blob_service():
    from azure.storage.blob import BlobServiceClient

    return BlobServiceClient.from_connection_string(azure_connection_string())


def normalize_blob_folder(folder: str) -> str:
    folder = str(folder or "").strip().replace("\\", "/")
    folder = folder.lstrip("/")
    return folder.rstrip("/")


def join_blob_path(folder: str, filename: str) -> str:
    folder = normalize_blob_folder(folder)
    filename = str(filename or "").strip().lstrip("/")
    if not filename:
        raise ValueError("Destination blob name is required.")
    if folder:
        return f"{folder}/{filename}"
    return filename


def list_blob_folders(
    container_key: str,
    *,
    prefix: str = "",
    max_results: int = 500,
) -> Dict[str, Any]:
    """
    List virtual folders (and optional blobs) under a container prefix.

    Returns folders (unique next-segment prefixes) + sample blob files at this level.
    """
    container_name = resolve_container_name(container_key)
    prefix = normalize_blob_folder(prefix)
    list_prefix = f"{prefix}/" if prefix else ""

    service = _blob_service()
    container = service.get_container_client(container_name)

    folders: set[str] = set()
    files: List[Dict[str, Any]] = []
    count = 0

    for blob in container.list_blobs(name_starts_with=list_prefix):
        count += 1
        if count > max_results * 20:
            # safety: don't walk forever on huge containers
            break
        name = blob.name
        rest = name[len(list_prefix) :] if list_prefix else name
        if not rest:
            continue
        if "/" in rest:
            segment = rest.split("/", 1)[0]
            folder_path = f"{list_prefix}{segment}".rstrip("/")
            folders.add(folder_path)
        else:
            files.append(
                {
                    "name": rest,
                    "path": name,
                    "size": getattr(blob, "size", None),
                }
            )
            if len(files) >= max_results:
                break

    folder_list = sorted(folders)
    return {
        "container_key": normalize_container_key(container_key),
        "container_name": container_name,
        "prefix": prefix,
        "folders": [{"name": f.rsplit("/", 1)[-1], "path": f} for f in folder_list],
        "files": files[:max_results],
        "truncated": count > max_results * 20 or len(files) >= max_results,
    }


def upload_local_file(
    local_path: str | Path,
    *,
    container_key: str,
    blob_folder: str = "",
    blob_name: str | None = None,
    overwrite: bool = True,
    allowed_extensions: Optional[set[str]] = None,
) -> Dict[str, Any]:
    """Upload a local file to Azure. Returns result dict for portal/CLI."""
    path = Path(local_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")

    allowed = allowed_extensions if allowed_extensions is not None else DEFAULT_ALLOWED_EXTENSIONS
    ext = path.suffix.lower()
    if allowed and ext not in allowed:
        raise ValueError(
            f"Unsupported extension {ext!r}. Allowed: {', '.join(sorted(allowed))}"
        )

    dest_name = (blob_name or "").strip() or path.name
    # If user passed a stem without extension, keep source extension
    if blob_name and "." not in Path(dest_name).name and ext:
        dest_name = f"{dest_name}{ext}"

    container_name = resolve_container_name(container_key)
    blob_path = join_blob_path(blob_folder, dest_name)

    service = _blob_service()
    blob_client = service.get_blob_client(container=container_name, blob=blob_path)

    size = path.stat().st_size
    print(f"Uploading: {path}")
    print(f"  -> {container_name}/{blob_path}  ({size:,} bytes)")

    with path.open("rb") as fh:
        blob_client.upload_blob(fh, overwrite=overwrite)

    print("Upload complete.")
    return {
        "status": "success",
        "message": f"Uploaded to {container_name}/{blob_path}",
        "local_path": str(path),
        "container_key": normalize_container_key(container_key),
        "container_name": container_name,
        "blob_folder": normalize_blob_folder(blob_folder),
        "blob_name": dest_name,
        "blob_path": blob_path,
        "bytes": size,
        "outputs": [f"azure://{container_name}/{blob_path}"],
        "stats": {"bytes": size},
    }


def _prompt(msg: str, default: str = "") -> str:
    hint = f" [{default}]" if default else ""
    raw = input(f"{msg}{hint}: ").strip()
    return raw if raw else default


def _interactive() -> Dict[str, Any]:
    print("\n=== Export file to Azure ===")
    options = list_container_options()
    print("Containers:")
    for i, opt in enumerate(options, 1):
        print(f"  {i}. {opt['key']}  ->  {opt['container_name']}")

    choice = _prompt("Select container (esh/knc/emm or number)", "esh")
    if choice.isdigit():
        idx = int(choice) - 1
        if idx < 0 or idx >= len(options):
            raise ValueError("Invalid container selection")
        container_key = options[idx]["key"]
    else:
        container_key = choice

    listing = list_blob_folders(container_key, prefix="")
    print(f"\nTop-level folders in {listing['container_name']}:")
    if not listing["folders"]:
        print("  (none — you can type a new folder path)")
    else:
        for f in listing["folders"][:40]:
            print(f"  - {f['path']}")

    blob_folder = _prompt("Blob folder / prefix (blank = container root)", "")
    local = _prompt("Local file path")
    keep = _prompt("Keep original file name? (Y/n)", "Y").lower() not in {"n", "no"}
    blob_name = "" if keep else _prompt("Destination file name (with extension)")

    return upload_local_file(
        local,
        container_key=container_key,
        blob_folder=blob_folder,
        blob_name=blob_name or None,
    )


def run(
    *,
    client: str = "ESH",
    geos: Optional[Sequence[str]] = None,
    local_path: Optional[str] = None,
    container_key: Optional[str] = None,
    blob_folder: Optional[str] = None,
    blob_name: Optional[str] = None,
    interactive: bool = False,
    **_kwargs: Any,
) -> Dict[str, Any]:
    """
    Pipeline / portal entrypoint.

    Prefer explicit kwargs from API. Falls back to UTILITY_AZURE_* env vars.
    If nothing is set and interactive=True (CLI), prompt on stdin.
    """
    _ = (client, geos)

    path = (local_path or _clean_env(os.getenv("UTILITY_AZURE_LOCAL_PATH", ""))).strip()
    ckey = (
        container_key or _clean_env(os.getenv("UTILITY_AZURE_CONTAINER_KEY", ""))
    ).strip()
    folder = (
        blob_folder
        if blob_folder is not None
        else _clean_env(os.getenv("UTILITY_AZURE_BLOB_FOLDER", ""))
    )
    name = (
        blob_name
        if blob_name is not None
        else _clean_env(os.getenv("UTILITY_AZURE_BLOB_NAME", ""))
    )

    if not path or not ckey:
        if interactive or sys.stdin.isatty():
            return _interactive()
        raise ValueError(
            "Missing upload params. Provide local_path + container_key "
            "(or UTILITY_AZURE_LOCAL_PATH + UTILITY_AZURE_CONTAINER_KEY), "
            "or use the Portal page Data → Azure Upload."
        )

    return upload_local_file(
        path,
        container_key=ckey,
        blob_folder=folder or "",
        blob_name=name or None,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Upload a local CSV/Parquet/Excel file to Azure Blob Storage."
    )
    parser.add_argument("--file", "-f", dest="local_path", help="Local file to upload")
    parser.add_argument(
        "--container",
        "-c",
        dest="container_key",
        choices=["esh", "knc", "emm"],
        help="Container key (esh / knc / emm)",
    )
    parser.add_argument(
        "--folder",
        dest="blob_folder",
        default=None,
        help="Blob folder / prefix inside the container",
    )
    parser.add_argument(
        "--name",
        dest="blob_name",
        default=None,
        help="Destination blob file name (default: keep source name)",
    )
    parser.add_argument(
        "--list-folders",
        action="store_true",
        help="List folders under --container (optional --folder as prefix)",
    )
    parser.add_argument(
        "--list-containers",
        action="store_true",
        help="Print esh/knc/emm → Azure container name mapping",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.list_containers:
        for opt in list_container_options():
            print(f"{opt['key']}: {opt['container_name']}  ({opt['env_var']})")
        return 0

    if args.list_folders:
        if not args.container_key:
            parser.error("--list-folders requires --container")
        listing = list_blob_folders(
            args.container_key, prefix=args.blob_folder or ""
        )
        print(f"Container: {listing['container_name']}")
        print(f"Prefix   : {listing['prefix'] or '(root)'}")
        print("Folders:")
        for f in listing["folders"]:
            print(f"  {f['path']}")
        if listing["files"]:
            print("Files at this level:")
            for f in listing["files"][:50]:
                print(f"  {f['path']}")
        return 0

    if args.local_path and args.container_key:
        result = upload_local_file(
            args.local_path,
            container_key=args.container_key,
            blob_folder=args.blob_folder or "",
            blob_name=args.blob_name,
        )
        print(result["message"])
        return 0

    # Interactive / env-driven
    result = run(
        local_path=args.local_path,
        container_key=args.container_key,
        blob_folder=args.blob_folder,
        blob_name=args.blob_name,
        interactive=True,
    )
    print(result.get("message", "Done"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
