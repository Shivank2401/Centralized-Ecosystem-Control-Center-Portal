#!/usr/bin/env python3
"""
ESH Amazon FBA customer returns — notebook-style combiner.

Logic mirrors return_database.ipynb (easy to edit step-by-step):
  1. Read fba_customer_returns_* files (tsv/txt/csv)
  2. Map reason + customer-comments via return_directory.yaml
  3. Enrich dates (year_month / hour / time)
  4. Clean sku via esh_sku_cleaning (same as orders)
  5. Pivot quantity
  6. Append onto existing local master (or create) + optional Azure upload

Paths:
  - Input:  {ESH_REVENUE}/{geo_folder}/input/amazon/fba_customer_returns/
  - Local:  sanity_data/ESH/returns/{GEO}_amazon_return_database.parquet|.csv
  - Azure:  CONTAINER_NAME_ESH/sanity_data/return_report_database/{same parquet name}

Run:
    python report_script/amazon_reports/return_database.py
    python report_script/amazon_reports/return_database.py --geos US,UK
    python report_script/amazon_reports/return_database.py --years 2026
    # pipeline: run(client='ESH', geos=['US'])
"""

from __future__ import annotations

import argparse
import html
import re
import sys
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

import pandas as pd
import yaml

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config_manager import esh_sku_cleaning, layouts, paths
from config_manager.report_helpers import (
    merge_append_dedupe,
    print_script_completed,
)
from report_script.amazon_reports.azure_parquet_upload import upload_parquets_to_azure

# =============================================================================
# Run knobs (edit these first) — same segment style as orders_report
# =============================================================================

CLIENT = "ESH"  # CLI default; pipeline passes client= via run()
PROCESS_GEOS: Optional[List[str]] = None
VALID_YEARS = {"2023", "2024", "2025", "2026"}
PROCESS_YEARS: Optional[List[str]] = ["2026"]
PROCESS_MONTHS: Optional[List[str]] = None
SAVE_OUTPUT = True
UPLOAD_TO_AZURE = True
MERGE_WITH_EXISTING = True  # append new slice onto local master (create if missing)

OUTPUT_SUBDIR = "returns"
PARQUET_NAME_SUFFIX = "amazon_return_database"
AZURE_BLOB_FOLDER = "sanity_data/return_report_database"
RETURN_DIRECTORY_YAML = _PROJECT_ROOT / "config_manager" / "return_directory.yaml"

# Keys used when appending onto an existing local master (keep='last' → new wins)
DEDUPE_SUBSET = [
    "geography",
    "year_month",
    "return_date",
    "return_hour",
    "order-id",
    "sku",
    "detailed-disposition",
    "return_reason_group",
    "customer_comment_group",
    "source_file",
]

# --- notebook cell: columns to keep from raw files ---
REQUIRED_COLS = [
    "return-date",
    "order-id",
    "sku",
    "quantity",
    "detailed-disposition",
    "reason",
    "customer-comments",
]
ALLOWED_EXTENSIONS = {".tsv", ".txt", ".csv"}
FILE_PREFIX = "fba_customer_returns_"
READ_ENCODING = "cp1252"

# --- notebook cell: final column order before pivot ---
WORKING_COLS = [
    "year_month",
    "return_date",
    "return_hour",
    "return_time",
    "order-id",
    "sku",
    "quantity",
    "detailed-disposition",
    "return_reason_group",
    "customer_comment_group",
    "source_file",
]

# --- notebook cell: pivot ---
PIVOT_INDEX = [
    "year_month",
    "return_date",
    "return_hour",
    "order-id",
    "sku",
    "detailed-disposition",
    "return_reason_group",
    "customer_comment_group",
    "source_file",
]
PIVOT_VALUE = "quantity"


# =============================================================================
# Client config (ESH today; add KNC when returns roots are known)
# =============================================================================

@dataclass(frozen=True)
class ClientReturnsConfig:
    client_code: str
    client_id: str
    client_name: str
    sku_backend: str
    input_roots: Dict[str, Path]  # GEO -> folder
    cogs_sheets: Dict[str, str]
    output_dir: Path


def esh_returns_input_roots() -> Dict[str, Path]:
    """
    GEO -> local FBA returns folder.

    Edit geo folder names in layouts.ESH_REVENUE_GEO_FOLDERS (US→us, CA→canada, …).
    Pattern: {ESH_REVENUE_ROOT}/{folder}/input/amazon/fba_customer_returns
    """
    # Prefer layouts helper when available (fresh process); fall back so a
    # long-lived pipeline that cached an older layouts module still runs.
    helper = getattr(layouts, "esh_returns_geo_roots", None)
    if callable(helper):
        return helper()
    root = paths.esh_revenue_root()
    return {
        code: root / folder / "input" / "amazon" / "fba_customer_returns"
        for code, folder in layouts.ESH_REVENUE_GEO_FOLDERS.items()
    }


def _esh_config() -> ClientReturnsConfig:
    ident = layouts.client_identity("ESH")
    return ClientReturnsConfig(
        client_code=ident["client_code"],
        client_id=ident["client_id"],
        client_name=ident["client_name"],
        sku_backend="esh",
        input_roots=esh_returns_input_roots(),
        cogs_sheets=layouts.cogs_sheets_for("ESH", channel="amazon"),
        output_dir=paths.sanity_data_root() / "ESH" / OUTPUT_SUBDIR,
    )


CLIENT_CONFIGS: Dict[str, Callable[[], ClientReturnsConfig]] = {
    "ESH": _esh_config,
}


def get_client_config(client: str = CLIENT) -> ClientReturnsConfig:
    key = str(client).strip().upper()
    if key not in CLIENT_CONFIGS:
        known = ", ".join(sorted(CLIENT_CONFIGS))
        raise ValueError(f"return_database supports {known} only (got '{client}')")
    return CLIENT_CONFIGS[key]()


def output_stem(geography: str) -> str:
    return f"{str(geography).strip().upper()}_{PARQUET_NAME_SUFFIX}"


# =============================================================================
# STEP 1 — load raw return files (notebook cell 2)
# Folder layout: {returns_root}/{YYYY}/{mon}/fba_customer_returns_*
# =============================================================================

def _month_filter_tokens(months: Optional[Sequence[str]]) -> Optional[Set[str]]:
    """Same token rules as orders_report (jan, Jan-2026, etc.)."""
    if months is None:
        return None
    tokens: Set[str] = set()
    for raw in months:
        m = str(raw).strip()
        if not m:
            continue
        tokens.add(m.lower())
        if "-" in m:
            tokens.add(m.split("-", 1)[0].lower())
        for fmt in ("%b-%Y", "%b"):
            try:
                parsed = datetime.strptime(m, fmt)
                tokens.add(parsed.strftime("%b").lower())
            except ValueError:
                continue
    return tokens


def discover_year_folders(
    returns_root: Path,
    years: Optional[Sequence[str]] = None,
) -> List[Path]:
    allowed = set(VALID_YEARS)
    if years is not None:
        allowed &= {str(y).strip() for y in years}
    found: List[Path] = []
    if not returns_root.is_dir():
        return found
    for path in returns_root.iterdir():
        if path.is_dir() and path.name in allowed:
            found.append(path)
    return sorted(found, key=lambda p: p.name)


def discover_return_files(
    year_path: Path,
    months: Optional[Sequence[str]] = None,
) -> List[Path]:
    wanted = _month_filter_tokens(months)
    files: List[Path] = []
    for path in year_path.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in ALLOWED_EXTENSIONS:
            continue
        if not path.name.startswith(FILE_PREFIX):
            continue
        if wanted is not None:
            rel_parts = {part.lower() for part in path.relative_to(year_path).parts[:-1]}
            name_l = path.name.lower()
            if not ((rel_parts & wanted) or any(tok in name_l for tok in wanted)):
                continue
        files.append(path)
    return sorted(files, key=lambda p: p.as_posix().lower())


def load_raw_returns(
    base_path: Path,
    *,
    years: Optional[Sequence[str]] = None,
    months: Optional[Sequence[str]] = None,
) -> Tuple[pd.DataFrame, List[Path], List[tuple]]:
    """
    Read fba_customer_returns_* under base_path/{year}/...

    years defaults to PROCESS_YEARS / VALID_YEARS (same as orders).
    """
    if not base_path.exists():
        print(f"[skip] input folder missing: {base_path}")
        empty = pd.DataFrame(columns=REQUIRED_COLS + ["source_file"])
        return empty, [], []

    year_folders = discover_year_folders(base_path, years=years)
    if not year_folders:
        print(
            f"[skip] no year folders in {base_path} "
            f"(wanted years={list(years) if years is not None else sorted(VALID_YEARS)})"
        )
        empty = pd.DataFrame(columns=REQUIRED_COLS + ["source_file"])
        return empty, [], []

    files: List[Path] = []
    for year_path in year_folders:
        files.extend(discover_return_files(year_path, months=months))

    print(
        f"Years: {[p.name for p in year_folders]} | "
        f"Months: {list(months) if months is not None else 'ALL'} | "
        f"Files: {len(files)} under {base_path}"
    )

    dfs: List[pd.DataFrame] = []
    skipped: List[Path] = []
    failed: List[tuple] = []

    for file in files:
        try:
            print(f"Reading: {file}")
            sep = "," if file.suffix.lower() == ".csv" else "\t"
            df = pd.read_csv(
                file,
                sep=sep,
                encoding=READ_ENCODING,
                usecols=REQUIRED_COLS,
            )
            df["source_file"] = file.name
            dfs.append(df)
        except Exception as exc:
            print(f"FAILED: {file}")
            print(f"ERROR: {exc}")
            failed.append((file, str(exc)))

    if dfs:
        returns_df = pd.concat(dfs, ignore_index=True)
    else:
        returns_df = pd.DataFrame(columns=REQUIRED_COLS + ["source_file"])

    print("\n========== SUMMARY ==========")
    print(f"Files processed   : {len(dfs)}")
    print(f"Files skipped     : {len(skipped)}")
    print(f"Files failed      : {len(failed)}")
    print(f"Final rows        : {len(returns_df):,}")
    return returns_df, skipped, failed


# =============================================================================
# STEP 2 — return_directory.yaml reason + comment mapping (notebook cell 5)
# =============================================================================

@dataclass
class ReturnDirectoryMaps:
    reason_map: Dict[str, str]
    prefix_lookup: Dict[str, str]
    alias_to_group: Dict[str, str]
    keyword_rules: List[Tuple[str, re.Pattern]]
    group_labels: Dict[str, str]
    treat_as_empty: Set[str]
    cleaning_cfg: dict
    unknown_reason_group: str
    unknown_comment_group: str
    alert_unknown_reason: bool
    alert_unknown_comment: bool
    collect_unknowns: bool
    path: Path


def load_return_directory(path: Path = RETURN_DIRECTORY_YAML) -> ReturnDirectoryMaps:
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    alerts = data.get("alerts") or {}
    cleaning_cfg = data.get("cleaning") or {}
    groups_cfg = data.get("customer_comment_groups") or {}
    prefix_map = data.get("structured_comment_prefixes") or {}
    reason_map = data.get("return_reason_mapping") or {}

    alerts_enabled = bool(alerts.get("enabled", True))
    group_labels = {
        key: (cfg or {}).get("label", key) for key, cfg in groups_cfg.items()
    }

    # normalize helpers need cleaning_cfg — build maps with local helpers
    def _normalize_key(text: str) -> str:
        text = html.unescape(str(text))
        text = unicodedata.normalize(
            cleaning_cfg.get("unicode_normalize") or "NFKC", text
        )
        text = re.sub(r"\s+", " ", text).strip().lower()
        text = re.sub(r"[^\w\s|/.-]", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    treat_as_empty = {
        _normalize_key(x) for x in (cleaning_cfg.get("treat_as_empty") or [])
    }
    treat_as_empty.update({"", "nan", "none", "null", "n/a", "na"})

    alias_to_group: Dict[str, str] = {}
    keyword_rules: List[Tuple[str, re.Pattern]] = []
    for group_key, cfg in groups_cfg.items():
        if group_key == "unmapped":
            continue
        cfg = cfg or {}
        for alias in cfg.get("aliases") or []:
            nk = _normalize_key(alias)
            if nk and nk not in alias_to_group:
                alias_to_group[nk] = group_key
        for pat in cfg.get("keywords") or []:
            try:
                keyword_rules.append((group_key, re.compile(pat, re.I)))
            except re.error as exc:
                print(f"WARN bad keyword regex in {group_key}: {pat!r} ({exc})")

    return ReturnDirectoryMaps(
        reason_map=dict(reason_map),
        prefix_lookup={_normalize_key(k): v for k, v in prefix_map.items()},
        alias_to_group=alias_to_group,
        keyword_rules=keyword_rules,
        group_labels=group_labels,
        treat_as_empty=treat_as_empty,
        cleaning_cfg=cleaning_cfg,
        unknown_reason_group=alerts.get("unknown_reason_group", "Unmapped Reason"),
        unknown_comment_group=alerts.get("unknown_comment_group", "Unmapped"),
        alert_unknown_reason=alerts_enabled
        and bool(alerts.get("on_unknown_reason", True)),
        alert_unknown_comment=alerts_enabled
        and bool(alerts.get("on_unknown_comment", True)),
        collect_unknowns=bool(alerts.get("collect_unknowns", True)),
        path=path,
    )


def map_reasons_and_comments(
    returns_df: pd.DataFrame,
    maps: ReturnDirectoryMaps,
) -> pd.DataFrame:
    """Apply return_directory.yaml mappings (edit rules in YAML, not here)."""
    cleaning_cfg = maps.cleaning_cfg

    def _normalize_key(text: str) -> str:
        text = html.unescape(str(text))
        text = unicodedata.normalize(
            cleaning_cfg.get("unicode_normalize") or "NFKC", text
        )
        text = re.sub(r"\s+", " ", text).strip().lower()
        text = re.sub(r"[^\w\s|/.-]", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _clean_comment(text) -> str:
        if text is None or (isinstance(text, float) and pd.isna(text)):
            return ""
        text = html.unescape(str(text))
        text = unicodedata.normalize(
            cleaning_cfg.get("unicode_normalize") or "NFKC", text
        )
        if cleaning_cfg.get("collapse_whitespace", True):
            text = re.sub(r"\s+", " ", text).strip()
        return text

    unknown_reasons: Set[str] = set()
    unknown_comments: Set[str] = set()

    def map_return_reason(reason) -> str:
        if reason is None or (isinstance(reason, float) and pd.isna(reason)):
            code = ""
        else:
            code = str(reason).strip()
        if not code:
            return maps.unknown_reason_group
        group = maps.reason_map.get(code)
        if group is None:
            if maps.collect_unknowns or maps.alert_unknown_reason:
                unknown_reasons.add(code)
            return maps.unknown_reason_group
        return group

    def map_customer_comment(comment) -> Tuple[str, str]:
        cleaned = _clean_comment(comment)
        key = _normalize_key(cleaned)

        if key in maps.treat_as_empty:
            gk = "noise_empty"
            return gk, maps.group_labels.get(gk, gk)

        if key in maps.alias_to_group:
            gk = maps.alias_to_group[key]
            return gk, maps.group_labels.get(gk, gk)

        if "|" in key:
            head = key.split("|", 1)[0].strip()
            if head in maps.prefix_lookup:
                gk = maps.prefix_lookup[head]
                if gk == "wrong_size_ordered":
                    if re.search(r"too small|to small|smaller|tiny|snall", key):
                        gk = "size_too_small"
                    elif re.search(r"too (large|big)|to big|larger|bigger", key):
                        gk = "size_too_large"
                if gk == "no_longer_needed_changed_mind" and re.search(
                    r"late|arriv|deliver", key
                ):
                    gk = "delivery_late"
                return gk, maps.group_labels.get(gk, gk)

        for gk, cre in maps.keyword_rules:
            if cre.search(key):
                return gk, maps.group_labels.get(gk, gk)

        gk = "unmapped"
        if maps.collect_unknowns or maps.alert_unknown_comment:
            unknown_comments.add(cleaned)
        return gk, maps.group_labels.get(gk, maps.unknown_comment_group)

    out = returns_df.copy()
    out["return_reason_group"] = out["reason"].map(map_return_reason)
    mapped = out["customer-comments"].map(map_customer_comment)
    out["customer_comment_group_key"] = mapped.map(lambda x: x[0])
    out["customer_comment_group"] = mapped.map(lambda x: x[1])

    print(f"Loaded return directory: {maps.path}")
    print(f"Reason groups mapped   : {out['return_reason_group'].nunique()}")
    print(f"Comment groups mapped  : {out['customer_comment_group'].nunique()}")
    print(f"Unknown reasons        : {len(unknown_reasons)}")
    print(f"Unknown comments       : {len(unknown_comments)}")

    if maps.alert_unknown_reason and unknown_reasons:
        print("\n=== ALERT unknown return reasons ===")
        for code in sorted(unknown_reasons):
            print(f"ALERT unknown return reason: {code}")

    if maps.alert_unknown_comment and unknown_comments:
        print("\n=== ALERT unknown customer comments (unique) ===")
        for text in sorted(unknown_comments, key=str.lower):
            print(f"ALERT unknown customer comment: {text}")

    return out


# =============================================================================
# STEP 3 — dates + column select (notebook cell 6)
# =============================================================================

def enrich_dates_and_select(returns_df: pd.DataFrame) -> pd.DataFrame:
    out = returns_df.copy()
    out["return_date"] = pd.to_datetime(
        out["return-date"], utc=True
    ).dt.tz_localize(None)
    out["year_month"] = out["return_date"].dt.to_period("M").astype(str)
    out["return_hour"] = out["return_date"].dt.hour
    out["return_time"] = out["return_date"].dt.strftime("%H:%M")
    out["return_date"] = out["return_date"].apply(
        lambda x: x.strftime("%Y-%m-%d") if pd.notnull(x) else None
    )
    keep = [c for c in WORKING_COLS if c in out.columns]
    return out.loc[:, keep].copy()


# =============================================================================
# STEP 4 — SKU cleaning (notebook cell 8 / orders_report)
# =============================================================================

def clean_return_skus(
    returns_df: pd.DataFrame,
    *,
    geography: str,
    sku_backend: str = "esh",
) -> pd.DataFrame:
    geo = str(geography).strip().upper()
    print(f">>> STEP: load SKU mapping ({sku_backend}_sku_cleaning, geo={geo})")
    if sku_backend == "knc":
        from config_manager import knc_sku_cleaning

        sku_mapping = knc_sku_cleaning.load_sku_mapping(geos=[geo])
        print(f"SKU mapping entries: {len(sku_mapping):,}")
        return knc_sku_cleaning.clean_sku_column(
            returns_df, sku_column="sku", sku_mapping=sku_mapping
        )

    sku_mapping = esh_sku_cleaning.load_sku_mapping(geos=[geo], channel="amazon")
    print(f"SKU mapping entries: {len(sku_mapping):,}")
    rows_before = len(returns_df)
    print(f">>> STEP: clean sku column ({rows_before:,} rows)")
    cleaned = esh_sku_cleaning.clean_sku_column(
        returns_df,
        sku_column="sku",
        sku_mapping=sku_mapping,
        drop_missing=True,
    )
    print(
        f"Rows after SKU clean: {len(cleaned):,} "
        f"(dropped {rows_before - len(cleaned):,})"
    )
    return cleaned


# =============================================================================
# STEP 5 — pivot quantity (notebook cell 9)
# =============================================================================

def pivot_returns(returns_df: pd.DataFrame) -> pd.DataFrame:
    if returns_df.empty:
        return returns_df.copy()
    index_cols = [c for c in PIVOT_INDEX if c in returns_df.columns]
    if PIVOT_VALUE not in returns_df.columns:
        raise KeyError(f"Missing pivot value column: {PIVOT_VALUE}")
    return (
        pd.pivot_table(
            returns_df,
            index=index_cols,
            values=PIVOT_VALUE,
            aggfunc="sum",
        )
        .reset_index()
    )


# =============================================================================
# STEP 6 — save local + Azure
# =============================================================================

def load_existing_geo_output(output_dir: Path, geography: str) -> pd.DataFrame:
    """Load existing local master for one country (empty if file missing)."""
    path = output_dir / f"{output_stem(geography)}.parquet"
    if not path.is_file():
        print(f"[INFO] No existing local file yet — will create: {path.name}")
        return pd.DataFrame()
    try:
        df = pd.read_parquet(path)
        print(f"  Loaded existing {path.name}: {len(df):,} rows")
        return df
    except Exception as exc:
        print(f"[WARN] Could not read {path.name}: {exc} — starting fresh")
        return pd.DataFrame()


def save_geography_outputs(
    df: pd.DataFrame,
    *,
    geography: str,
    output_dir: Path,
) -> List[Path]:
    """Write/overwrite local CSV + parquet for one country."""
    if df.empty:
        print("[WARN] Nothing to save — DataFrame is empty")
        return []
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = output_stem(geography)
    parquet_path = output_dir / f"{stem}.parquet"
    csv_path = output_dir / f"{stem}.csv"
    df.to_parquet(parquet_path, index=False)
    df.to_csv(csv_path, index=False)
    print(f"  [{geography}] {len(df):,} rows -> {parquet_path.name}, {csv_path.name}")
    return [parquet_path, csv_path]


# =============================================================================
# Pipeline — one geo end-to-end (notebook flow)
# =============================================================================

def process_geography(
    cfg: ClientReturnsConfig,
    geography: str,
    *,
    maps: ReturnDirectoryMaps,
    years: Optional[Sequence[str]] = None,
    months: Optional[Sequence[str]] = None,
    save_output: bool = SAVE_OUTPUT,
    upload_to_azure: bool = UPLOAD_TO_AZURE,
    merge_existing: bool = MERGE_WITH_EXISTING,
) -> pd.DataFrame:
    geo = str(geography).strip().upper()
    print(f"\n{'=' * 60}")
    print(f"Returns - {cfg.client_code}/{geo} - START")
    print(f"{'=' * 60}")

    base_path = cfg.input_roots.get(geo)
    if base_path is None:
        print(f"[skip] no input root mapped for {geo}")
        return pd.DataFrame()

    print(f"\n>>> STEP: [{geo}] load raw return files")
    raw, _skipped, _failed = load_raw_returns(
        base_path, years=years, months=months
    )
    if raw.empty:
        print(f"[{geo}] No rows loaded.")
        return pd.DataFrame()

    print(f"\n>>> STEP: [{geo}] map reason + customer comments")
    mapped = map_reasons_and_comments(raw, maps)

    print(f"\n>>> STEP: [{geo}] enrich dates + select columns")
    dated = enrich_dates_and_select(mapped)

    print(f"\n>>> STEP: [{geo}] clean SKUs")
    cleaned = clean_return_skus(
        dated, geography=geo, sku_backend=cfg.sku_backend
    )
    if cleaned.empty:
        print(f"[{geo}] No rows after SKU clean.")
        return pd.DataFrame()

    print(f"\n>>> STEP: [{geo}] pivot quantity")
    pivoted = pivot_returns(cleaned)
    pivoted["client"] = cfg.client_code
    pivoted["client_id"] = cfg.client_id
    pivoted["geography"] = geo
    pivoted["platform"] = "amazon"
    print(f"[{geo}] New pivot rows: {len(pivoted):,}")

    if merge_existing:
        print(f"\n>>> STEP: [{geo}] merge with existing local master")
        existing = load_existing_geo_output(cfg.output_dir, geo)
        master = merge_append_dedupe(
            existing, pivoted, subset=DEDUPE_SUBSET
        )
    else:
        master = pivoted

    if save_output and not master.empty:
        print(f"\n>>> STEP: [{geo}] save local CSV + parquet -> {cfg.output_dir}")
        saved = save_geography_outputs(
            master, geography=geo, output_dir=cfg.output_dir
        )
        if upload_to_azure and saved:
            pq_paths = [p for p in saved if p.suffix.lower() == ".parquet"]
            print(
                f"\n>>> STEP: [{geo}] upload parquet -> "
                f"CONTAINER_NAME_{cfg.client_code}/{AZURE_BLOB_FOLDER}/"
            )
            upload_parquets_to_azure(
                pq_paths,
                client_code=cfg.client_code,
                blob_folder=AZURE_BLOB_FOLDER,
                label="return_database parquet",
            )

    print(f"{'=' * 60}")
    print(f"Returns - {cfg.client_code}/{geo} - DONE")
    print(f"{'=' * 60}")
    return master


def build_returns_dataframe(
    client: str = CLIENT,
    geos: Optional[Sequence[str]] = None,
    years: Optional[Sequence[str]] = None,
    months: Optional[Sequence[str]] = None,
    *,
    save_output: bool = SAVE_OUTPUT,
    upload_to_azure: bool = UPLOAD_TO_AZURE,
    merge_existing: bool = MERGE_WITH_EXISTING,
) -> pd.DataFrame:
    cfg = get_client_config(client)
    geos = PROCESS_GEOS if geos is None and PROCESS_GEOS is not None else geos
    years = PROCESS_YEARS if years is None and PROCESS_YEARS is not None else years
    months = PROCESS_MONTHS if months is None and PROCESS_MONTHS is not None else months
    if years is None:
        years = sorted(VALID_YEARS)

    if geos is None:
        selected = sorted(cfg.cogs_sheets.keys())
    else:
        selected = [str(g).strip().upper() for g in geos if str(g).strip()]

    print("=" * 60)
    print(f"Client : {cfg.client_code} ({cfg.client_name})")
    print(f"ID     : {cfg.client_id}")
    print(f"Years  : {list(years)}")
    print(f"Months : {list(months) if months is not None else 'ALL'}")
    print(f"Geos   : {selected}")
    print(f"Merge  : {merge_existing}")
    print(f"Output : {cfg.output_dir}")
    print(f"Azure  : {AZURE_BLOB_FOLDER}/ (upload={upload_to_azure})")
    print("=" * 60)

    print("\n>>> STEP: load return_directory.yaml")
    maps = load_return_directory()

    frames: List[pd.DataFrame] = []
    for geo in selected:
        frame = process_geography(
            cfg,
            geo,
            maps=maps,
            years=years,
            months=months,
            save_output=save_output,
            upload_to_azure=upload_to_azure,
            merge_existing=merge_existing,
        )
        if not frame.empty:
            frames.append(frame)

    if not frames:
        print("No return rows produced.")
        return pd.DataFrame()

    master = pd.concat(frames, ignore_index=True, sort=False)
    print("-" * 60)
    print(f"Done. Master shape: {master.shape}")
    return master


# =============================================================================
# CLI / pipeline entry
# =============================================================================

def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Amazon FBA customer returns combiner")
    p.add_argument("--client", default=CLIENT, choices=sorted(CLIENT_CONFIGS.keys()))
    p.add_argument("--geos", default=None, help="Comma-separated geo codes")
    p.add_argument("--years", default=None, help="Comma-separated years")
    p.add_argument("--months", default=None, help="Comma-separated month tokens")
    p.add_argument("--no-save", action="store_true")
    p.add_argument("--no-azure", action="store_true")
    p.add_argument(
        "--no-merge",
        action="store_true",
        help="Overwrite local masters instead of append+dedupe",
    )
    return p.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> pd.DataFrame:
    args = parse_args(argv)
    geos = [g.strip() for g in args.geos.split(",")] if args.geos else None
    years = [y.strip() for y in args.years.split(",")] if args.years else None
    months = [m.strip() for m in args.months.split(",")] if args.months else None
    return build_returns_dataframe(
        client=args.client,
        geos=geos,
        years=years,
        months=months,
        save_output=not args.no_save,
        upload_to_azure=UPLOAD_TO_AZURE and not args.no_azure,
        merge_existing=MERGE_WITH_EXISTING and not args.no_merge,
    )


def run(
    *,
    client: str = CLIENT,
    geos: Optional[Sequence[str]] = None,
    years: Optional[Sequence[str]] = None,
    months: Optional[Sequence[str]] = None,
    **_kwargs,
) -> pd.DataFrame:
    """Pipeline entrypoint: run(client='ESH', geos=['US'], years=['2026'])."""
    return main(
        layouts.cli_argv(
            client=client,
            geos=list(geos) if geos else None,
            years=list(years) if years else None,
            months=list(months) if months else None,
        )
    )


if __name__ == "__main__":
    main()
    print_script_completed("return_database")
