"""
Local standardized COGS slices under the project folder:

  cogs/{client}/{country}_{channel}_cogs.parquet  (preferred)
  cogs/{client}/{country}_{channel}_cogs.csv      (fallback)

Produced by ``helper_files_nd_saving.download_cogs`` (Azure → local).
Azure is refreshed by ``want_to_update.esh_cogs`` / ``knc_cogs`` (Excel → blob).

Report consumers MUST use this module (not ESH_COGS_PATH / KNC_COGS_PATH Excel).
Channel selection is driven by ``geography.yaml`` (`cogs_channel` / `cogs_channels`).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

import pandas as pd

from config_manager import layouts
from config_manager import paths as cfg_paths
from config_manager.loader import load_geographies


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


def geo_cogs_meta(client: str, geography: str) -> Dict[str, object]:
    """Return default channel / excel sheets for a geo from geography.yaml."""
    geos = load_geographies(client)
    g = geos.get(str(geography).strip().upper())
    if g is None:
        return {"channel": "amazon", "sheet_name": None, "channels": {}}
    return {
        "channel": g.default_channel or "amazon",
        "sheet_name": g.cogs_sheet_name,
        "channels": dict(g.cogs_channels or {}),
    }


def resolve_channel(
    client: str,
    geography: str,
    *,
    channel: Optional[str] = None,
) -> str:
    """
    Resolve local COGS channel for a geo.

    - Explicit ``channel`` wins (e.g. Shopify reports force ``shopify`` for UK).
    - Else ``geography.yaml`` → ``default_channel``.
    Local file is always ``{geo}_{channel}_cogs.*`` under ``cogs/{client}/``.
    """
    if channel is not None and str(channel).strip():
        return str(channel).strip().lower()
    meta = geo_cogs_meta(client, geography)
    return str(meta.get("channel") or "amazon").strip().lower() or "amazon"


def resolve_cogs_slice_path(
    client: str,
    country: str,
    channel: Optional[str] = None,
) -> Path:
    """
    Prefer parquet, then csv under cogs/{client}/.
    Channel defaults from geography.yaml when omitted.
    """
    ch = resolve_channel(client, country, channel=channel)
    base = client_cogs_dir(client)
    cc = str(country).strip()
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
        f"Local COGS missing for {client.upper()} {country}/{ch}. "
        f"Expected {expected} under {base}. "
        f"Run Stage helper_files_nd_saving → Download COGS "
        f"(after want_to_update → {client.upper()} COGS uploaded to Azure)."
    )


def read_cogs_slice(
    client: str,
    country: str,
    channel: Optional[str] = None,
) -> pd.DataFrame:
    """Load one geo/channel COGS frame with snake_case columns."""
    ch = resolve_channel(client, country, channel=channel)
    path = resolve_cogs_slice_path(client, country, channel=ch)
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
    reverse_ci = {str(v).strip().lower(): str(k).upper() for k, v in sheets_map.items()}
    # Also match optional cogs_channels values
    for geo, cfg in load_geographies(client).items():
        for sheet in (cfg.cogs_channels or {}).values():
            reverse.setdefault(str(sheet).strip(), geo)
            reverse_ci.setdefault(str(sheet).strip().lower(), geo)
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
    channel: Optional[str] = None,
    columns: Optional[Sequence[str]] = None,
) -> pd.DataFrame:
    """
    Concat local COGS slices for the client.

    When ``channel`` is None, each geo uses ``geography.yaml`` → ``cogs_channel``
    (so KNC IE loads shopify, UK loads amazon, etc.).
    """
    wanted = resolve_geos(client, geos=geos, sheet_names=sheet_names)
    frames: List[pd.DataFrame] = []
    for geo in wanted:
        ch = resolve_channel(client, geo, channel=channel)
        try:
            df = read_cogs_slice(client, geo, channel=ch)
        except FileNotFoundError as exc:
            print(f"[WARN] {exc}")
            continue
        if columns is not None:
            keep = [c for c in columns if c in df.columns]
            missing = [c for c in columns if c not in df.columns]
            if missing:
                print(
                    f"[WARN] {client.upper()} {geo}/{ch} COGS missing columns "
                    f"{missing} — skipping"
                )
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
