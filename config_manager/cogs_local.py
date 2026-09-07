"""
Local standardized COGS slices under the project folder:

  cogs/{client}/{country}_{channel}_cogs.parquet  (preferred)
  cogs/{client}/{country}_{channel}_cogs.csv      (fallback)

Produced by ``supply_chain.d_download_cogs`` (Azure → local).
Azure is refreshed by ``want_to_update.esh_cogs`` / ``knc_cogs`` (Excel → blob).
Consumed by SKU cleaners, sanity reports, shipping queues, etc.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

import pandas as pd

from config_manager import layouts
from config_manager import paths as cfg_paths


def _to_snake(name: str) -> str:
    name = str(name).strip().lower()
    name = re.sub(r"[^a-z0-9]+", "_", name)
    name = re.sub(r"_+", "_", name)
    return name.strip("_")


def _clean_col(c: str) -> str:
    c = str(c).strip()
    c = c.replace("\ufeff", "")
    c = c.replace("ï»¿", "")
    return c.strip('"').strip("'")


def client_cogs_dir(client: str) -> Path:
    """{project_root}/cogs/{client}/"""
    return cfg_paths.project_root() / "cogs" / str(client).strip().lower()


def cogs_slice_stem(country: str, channel: str = "amazon") -> str:
    return f"{str(country).strip().lower()}_{str(channel).strip().lower()}_cogs"


def resolve_cogs_slice_path(
    client: str,
    country: str,
    channel: str = "amazon",
) -> Path:
    """
    Prefer parquet, then csv under cogs/{client}/.
    Accepts lowercase or uppercase country in the filename stem.
    Raises FileNotFoundError if neither exists.
    """
    base = client_cogs_dir(client)
    cc = str(country).strip()
    ch = str(channel).strip().lower()
    stems = []
    for geo in (cc.lower(), cc.upper(), cc):
        stem = f"{geo}_{ch}_cogs"
        if stem not in stems:
            stems.append(stem)

    candidates: List[Path] = []
    for stem in stems:
        candidates.append(base / f"{stem}.parquet")
        candidates.append(base / f"{stem}.csv")

    for path in candidates:
        if path.is_file():
            return path

    expected = f"{cc.lower()}_{ch}_cogs.parquet|.csv"
    raise FileNotFoundError(
        f"Local COGS missing for {client.upper()} {country}/{channel}. "
        f"Expected {expected} under {base}. "
        f"Run Stage supply_chain → Download COGS "
        f"(after want_to_update → {client.upper()} COGS uploaded to Azure)."
    )


def read_cogs_slice(
    client: str,
    country: str,
    channel: str = "amazon",
) -> pd.DataFrame:
    """Load one geo/channel COGS frame with snake_case columns."""
    path = resolve_cogs_slice_path(client, country, channel)
    if path.suffix.lower() == ".parquet":
        df = pd.read_parquet(path)
    else:
        df = pd.read_csv(path)
    df = df.copy()
    df.rename(columns=lambda x: _to_snake(_clean_col(x)), inplace=True)
    print(f"  Loaded local COGS {path}: {len(df):,} rows")
    return df


def sheet_names_to_geos(
    client: str,
    sheet_names: Sequence[str],
) -> List[str]:
    """Map legacy Excel sheet names (or bare geo codes) → geography codes."""
    sheets_map = layouts.cogs_sheets_for(client)
    reverse = {str(v).strip(): str(k).upper() for k, v in sheets_map.items()}
    # also allow case-insensitive sheet match
    reverse_ci = {str(v).strip().lower(): str(k).upper() for k, v in sheets_map.items()}
    known_geos = {str(k).upper() for k in sheets_map}

    out: List[str] = []
    seen: set[str] = set()
    for raw in sheet_names:
        name = str(raw).strip()
        if not name:
            continue
        geo: Optional[str] = None
        if name in reverse:
            geo = reverse[name]
        elif name.lower() in reverse_ci:
            geo = reverse_ci[name.lower()]
        elif name.upper() in known_geos:
            geo = name.upper()
        if geo and geo not in seen:
            out.append(geo)
            seen.add(geo)
    return out


def resolve_geos(
    client: str,
    *,
    geos: Optional[Sequence[str]] = None,
    sheet_names: Optional[Sequence[str]] = None,
) -> List[str]:
    """
    Resolve which geography codes to load.

    Priority: explicit geos → sheet_names (mapped) → all geos from geography.yaml.
    """
    if geos is not None:
        cleaned = [str(g).strip().upper() for g in geos if str(g).strip()]
        if cleaned:
            return cleaned
    if sheet_names is not None:
        mapped = sheet_names_to_geos(client, sheet_names)
        if mapped:
            return mapped
    return [str(g).upper() for g in layouts.cogs_sheets_for(client)]


def load_cogs_frames(
    client: str,
    *,
    geos: Optional[Sequence[str]] = None,
    sheet_names: Optional[Sequence[str]] = None,
    channel: str = "amazon",
    columns: Optional[Sequence[str]] = None,
) -> pd.DataFrame:
    """
    Concat local COGS slices for the client.

    ``columns`` if set: keep only those snake_case columns that exist.
    """
    wanted = resolve_geos(client, geos=geos, sheet_names=sheet_names)
    frames: List[pd.DataFrame] = []
    for geo in wanted:
        try:
            df = read_cogs_slice(client, geo, channel=channel)
        except FileNotFoundError as exc:
            print(f"[WARN] {exc}")
            continue
        if columns is not None:
            keep = [c for c in columns if c in df.columns]
            missing = [c for c in columns if c not in df.columns]
            if missing:
                print(f"[WARN] {client.upper()} {geo} COGS missing columns {missing} — skipping")
                continue
            df = df.loc[:, keep].copy()
        frames.append(df)

    if not frames:
        cols = list(columns) if columns is not None else []
        return pd.DataFrame(columns=cols)

    return pd.concat(frames, ignore_index=True).drop_duplicates()


def to_pascal_sku_alias_frame(df: pd.DataFrame, alias_cols: Iterable[str]) -> pd.DataFrame:
    """
    Shipping-queue helper: expose SKU / ON_1.. as PascalCase for legacy mappers.
    Accepts snake_case local exports or already-Pascal Azure frames.
    """
    out = df.copy()
    rename: Dict[str, str] = {}
    lower_map = {_to_snake(c): c for c in out.columns}

    def pick(*candidates: str) -> Optional[str]:
        for cand in candidates:
            key = _to_snake(cand)
            if key in lower_map:
                return lower_map[key]
        return None

    sku_src = pick("sku", "SKU")
    if sku_src and sku_src != "SKU":
        rename[sku_src] = "SKU"

    for alias in alias_cols:
        src = pick(alias, alias.upper(), alias.lower())
        if src and src != alias.upper():
            rename[src] = alias.upper()

    if rename:
        out = out.rename(columns=rename)
    return out
