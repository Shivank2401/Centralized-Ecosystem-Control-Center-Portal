"""Environment status — presence / path checks only; never expose secret values."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Set

from pipeline_engine.registry import ConfigRegistry

_SECRET_RE = re.compile(
    r"(PASSWORD|SECRET|TOKEN|CONNECTION_STRING|ACCOUNT_KEY|_KEY$)",
    re.IGNORECASE,
)

# Optional keys operators commonly need; values never returned.
_OPTIONAL_KEYS = [
    "SANITY_DATA_ROOT",
    "PINCODE_DATA_DIR",
    "INVENTORY_BASE",
    "ESH_CENTRAL_ROOT",
    "ESH_COUNTRY_HELPER_PATH",
    "ESH_DEMAND_INSTOCK_ROOT",
    "ESH_REVENUE_ROOT",
    "ESH_RETAIL_ROOT",
    "ESH_WALMART_ROOT",
    "ESH_PINCODE_PATH",
    "EMAMI_DATA_ROOT",
    "EMAMI_OUTPUT_ROOT",
    "EMAMI_HELPER_FILE",
    "EMAMI_COGS_PATH",
    "PROCESS_YEAR",
    # KNC Shopify sales / inventory roots (shopify_reports)
    "KNC_SHOPIFY_UK_SALES_ROOT",
    "KNC_SHOPIFY_IE_SALES_ROOT",
    "KNC_SHOPIFY_UK_INVENTORY_ROOT",
    "KNC_SHOPIFY_IE_INVENTORY_ROOT",
    "KNC_SHOPIFY_UK_LEDGER_ROOT",
    "KNC_SHOPIFY_IE_LEDGER_ROOT",
    "AZURE_STORAGE_CONNECTION_STRING",
    "AZURE_STORAGE_ACCOUNT_NAME",
    "AZURE_STORAGE_ACCOUNT_KEY",
    "CONTAINER_NAME_ESH",
    "CONTAINER_NAME_KNC",
    "CONTAINER_NAME_EMAMI",
    "ITEM_MASTER_AZURE_CONNECTION_STRING",
    "ITEM_MASTER_CONTAINER",
    "ITEM_MASTER_BLOB_PREFIX",
    "ITEM_MASTER_LOCAL_DIR",
    "MYSQL_HOST",
    "MYSQL_PORT",
    "MYSQL_USER",
    "MYSQL_PASSWORD",
    "MYSQL_DATABASE",
    "UTILITY_IMAGE_FOLDER",
    "UTILITY_IMAGE_OUTPUT",
]


class EnvironmentService:
    def __init__(self, registry: ConfigRegistry | None = None) -> None:
        self.registry = registry or ConfigRegistry()

    def _is_secret(self, key: str) -> bool:
        return bool(_SECRET_RE.search(key))

    def _is_path_like(self, key: str) -> bool:
        upper = key.upper()
        return any(
            upper.endswith(sfx) for sfx in ("_ROOT", "_PATH", "_DIR", "_FOLDER", "_OUTPUT")
        ) or upper in {"INVENTORY_BASE", "SANITY_DATA_ROOT", "PINCODE_DATA_DIR"}

    def _entry(self, key: str, *, required: bool, category: str) -> Dict[str, Any]:
        raw = os.getenv(key)
        set_ = bool(raw and str(raw).strip())
        secret = self._is_secret(key)
        path_exists = None
        if set_ and self._is_path_like(key) and not secret:
            try:
                path_exists = Path(str(raw).strip().strip('"')).exists()
            except OSError:
                path_exists = False
        return {
            "key": key,
            "set": set_,
            "required": required,
            "secret": secret,
            "path_like": self._is_path_like(key),
            "path_exists": path_exists,
            "category": category,
            # Never return values — UI only sees status.
            "value": None,
        }

    def snapshot(self) -> Dict[str, Any]:
        seen: Set[str] = set()
        entries: List[Dict[str, Any]] = []

        for code, cfg in self.registry.clients(include_disabled=True).items():
            for key, required in (
                (cfg.data_root_env, True),
                (cfg.cogs_path_env, False),
            ):
                if not key or key in seen:
                    continue
                seen.add(key)
                entries.append(self._entry(key, required=required, category=f"client:{code}"))

        for key in _OPTIONAL_KEYS:
            if key in seen:
                continue
            seen.add(key)
            entries.append(self._entry(key, required=False, category="optional"))

        required_missing = [e["key"] for e in entries if e["required"] and not e["set"]]
        path_missing = [
            e["key"]
            for e in entries
            if e["set"] and e["path_like"] and e["path_exists"] is False
        ]

        return {
            "ok": len(required_missing) == 0,
            "required_missing": required_missing,
            "path_missing": path_missing,
            "variables": entries,
            "note": "Secret and path values are never sent to the browser — only set/missing status.",
        }
