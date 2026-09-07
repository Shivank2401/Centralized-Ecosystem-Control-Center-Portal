"""
Per-client DEFAULT_INVALID_SKUS store (JSON).

File: config_manager/invalid_skus.json

Shape:
  {
    "ESH": ["SKU1", "SKU2", ...],
    "KNC": ["..."],
    "EMM": []
  }

Used by esh_sku_cleaning / knc_sku_cleaning and managed by
report_script/want_to_update/invalid_skus.py.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set

from config_manager import paths as cfg_paths

SUPPORTED_CLIENTS = ("ESH", "KNC", "EMM")

# Seed used only when creating a missing JSON file (migrated from hard-coded sets).
_SEED: Dict[str, List[str]] = {
    "ESH": [
        "17 0HPU PJMJ",
        "B08MTDXPJW",
        "C0 QDB6 K3Y0",
        "C6 T58V R7J8",
        "HP X0Z9 88SI",
        "P9 5UO8 O0NF",
        "QN ZU4B IC2Z",
        "QS VWOY YRKJ",
        "RF IZ6R 7TGG",
        "9H-NFLE-BXIK",
        "RL",
        "PG-T2DK-AU7",
        "0Q",
        "0Q-G7M8-XO0D",
        "SHIPBOB (11187988)",
        "NEW",
        "CBP",
        "NOT FOUND",
        "SHIPBOB (12004200)",
        "0",
        "SHOPIFY",
        "SHIPBOB - CUTLERY",
        "B01G0ULCIW",
        "N",
        "MU05ADNHCN",
        "MU05ADNHCN-FR",
        "MU05ADNHCN-DE",
        "5I",
        "PG",
        "0X-UJDE-0K11",
        "7P-5RQS-GTD2",
        "AFL65SQ100P01",
        "AFL8SQ150P01",
        "BCU1",
        "CPHC12OZ",
        "CPHC16",
        "CPHC16OZ",
        "BST16",
        "BKDO",
        "PLP08SQ20",
        "5.30 INBOUND",
        "GP-YQFC-SIMM",
        "PG-T2DK-AU71",
        "FBA18VLXSWJFMISSING1",
        "FBA19D7Y7F67MISSING1",
        "ZD-568O-AHI2",
        "UNEXPECTEDITEMFBA15KP0K5C5",
        "UNEXPECTEDRETURN01",
        "WB-F912-8O71",
        "S1-D0TO-SGO9",
        "SU-Y9ME-6L54",
        "0G-K222-V5ZT",
        "V9-CRG6-3PPL",
        "BTP-UKPARENT",
        "BTP-VARITION",
        "CBPS",
        "CBP-PARENT",
        "ZD",
        "FBA18VLXSWJF.MISS",
        "MUSW05HBVFDFBFD-DE",
        "MUSW05HBVFDFBFD",
        "3L-L0OI-VPOU",
        "5I-XN7W-YJO9",
        "CBC-SL-LD-PT",
    ],
    "KNC": [
        "RTDSTRAWNEW",
        "X7-JI27-U1G1",
        "FBA15KJR0STC.MISSING1",
        "FUELCITRUSPANEU",
        "UNCOMMINGLED.MSKU.1721922811104",
    ],
    "EMM": [],
}

_CACHE: Optional[Dict[str, Set[str]]] = None


def invalid_skus_path() -> Path:
    return cfg_paths.project_root() / "config_manager" / "invalid_skus.json"


def _normalize_sku(value: object) -> str:
    return str(value).strip().upper()


def _normalize_client(client: str) -> str:
    code = str(client).strip().upper()
    if code not in SUPPORTED_CLIENTS:
        raise ValueError(
            f"Unsupported client {client!r}. Choose one of: {', '.join(SUPPORTED_CLIENTS)}"
        )
    return code


def parse_sku_blob(text: str) -> List[str]:
    """
    Split a pasted blob into SKUs.

    Accepts newlines, commas, semicolons, or whitespace-separated tokens.
    """
    if not text:
        return []
    raw = text.replace(",", "\n").replace(";", "\n")
    out: List[str] = []
    seen: Set[str] = set()
    for line in raw.splitlines():
        for token in line.split():
            sku = _normalize_sku(token)
            if not sku or sku in seen:
                continue
            seen.add(sku)
            out.append(sku)
    return out


def _empty_store() -> Dict[str, Set[str]]:
    return {c: set() for c in SUPPORTED_CLIENTS}


def _seed_store() -> Dict[str, Set[str]]:
    store = _empty_store()
    for client, skus in _SEED.items():
        store[client] = {_normalize_sku(s) for s in skus if str(s).strip()}
    return store


def _sets_to_jsonable(store: Dict[str, Set[str]]) -> Dict[str, List[str]]:
    return {
        client: sorted(store.get(client, set()))
        for client in SUPPORTED_CLIENTS
    }


def save_store(store: Dict[str, Set[str]]) -> Path:
    """Persist the in-memory store and refresh the module cache."""
    global _CACHE
    path = invalid_skus_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _sets_to_jsonable(store)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _CACHE = {c: set(payload[c]) for c in SUPPORTED_CLIENTS}
    return path


def load_store(*, force_reload: bool = False) -> Dict[str, Set[str]]:
    """Load JSON (create seeded file if missing)."""
    global _CACHE
    if _CACHE is not None and not force_reload:
        return {c: set(v) for c, v in _CACHE.items()}

    path = invalid_skus_path()
    if not path.is_file():
        store = _seed_store()
        save_store(store)
        print(f"[invalid_skus] Created seeded store: {path}")
        return {c: set(v) for c, v in _CACHE.items()}  # type: ignore[union-attr]

    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid invalid_skus.json shape (expected object): {path}")

    store = _empty_store()
    for client in SUPPORTED_CLIENTS:
        values = raw.get(client, [])
        if values is None:
            values = []
        if not isinstance(values, list):
            raise ValueError(f"Client {client} must be a list of SKUs in {path}")
        store[client] = {_normalize_sku(s) for s in values if str(s).strip()}

    _CACHE = store
    return {c: set(v) for c, v in store.items()}


def clear_invalid_skus_cache() -> None:
    global _CACHE
    _CACHE = None


def get_invalid_skus(client: str, *, force_reload: bool = False) -> Set[str]:
    """Return the invalid-SKU set for one client (upper-cased)."""
    code = _normalize_client(client)
    store = load_store(force_reload=force_reload)
    return set(store.get(code, set()))


def list_invalid_skus(client: str, *, force_reload: bool = False) -> List[str]:
    return sorted(get_invalid_skus(client, force_reload=force_reload))


def add_invalid_skus(client: str, skus: Iterable[str]) -> Dict[str, object]:
    """
    Add one or more SKUs for a client. Returns summary counts.

    Existing SKUs are left as-is (case-insensitive).
    """
    code = _normalize_client(client)
    incoming = [_normalize_sku(s) for s in skus if str(s).strip()]
    # de-dupe preserving order
    seen: Set[str] = set()
    unique: List[str] = []
    for sku in incoming:
        if sku in seen:
            continue
        seen.add(sku)
        unique.append(sku)

    store = load_store(force_reload=True)
    before = set(store[code])
    added = [s for s in unique if s not in before]
    skipped = [s for s in unique if s in before]
    store[code].update(added)
    path = save_store(store)
    return {
        "client": code,
        "path": path,
        "requested": len(unique),
        "added": added,
        "skipped_existing": skipped,
        "total": len(store[code]),
    }
