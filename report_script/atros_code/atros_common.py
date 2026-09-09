"""
Shared KNC Atros helpers: paths, COGS/bulk reads, geo save, Azure upload.

Covers:
  - Client: KNC — GEO_CONFIG for UK / DE / AE (channels, COGS sheets, folder trees)
  - Local masters: sanity_data/KNC/{pnl|ads|decomposition_chart}/
  - Azure blobs: PNL / ad_sales / Decomposition_Chart under sanity_data/
  - Helpers: resolve_year_month, parse_geos, read_cogs, read_bulk_metrics, save_geo_and_combined

Not a standalone report — imported by pnl_report, ad_sales_report, decomposition_chart.

Style: clear sections + print steps on file I/O so a crash shows which helper failed.
"""

from __future__ import annotations

import calendar
import io
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import pandas as pd

from config_manager import paths
from config_manager.layouts import client_identity


# =============================================================================
# Constants
# =============================================================================

CLIENT = "KNC"

# Per-geo folders / sheets / flags (relative to KNC_DATA_ROOT)
GEO_CONFIG = {
    "UK": {
        "cogs_sheet": "Main",
        "channel": "Amazon-UK",
        "country": "UK",
        "bulk_ops": ("Bulk Operations",),
        "transaction": ("Transaction",),
        "business_report": ("Buy_box_deal_fee",),
        "inventory": ("Inventory",),
        "orders": ("App Main Files", "Orders", "Kinetica"),
        "ledger": ("Inventory", "ledger_report"),
        "txn_skiprows": 9,
        "translate_de": False,
        "kinetica_filter": False,
        "portfolio_filter": False,
    },
    "DE": {
        "cogs_sheet": "Germany-COGS",
        "channel": "Amazon-DE",
        "country": "DE",
        "bulk_ops": ("Germany", "Bulk Operations"),
        "transaction": ("Germany", "Transaction"),
        "business_report": ("Germany", "BusinessReport"),
        "inventory": ("Germany", "Inventory"),
        "orders": ("App Main Files", "Orders", "Kinetica"),
        "ledger": ("Germany", "Inventory", "ledger_report"),
        "txn_skiprows": 9,
        "translate_de": True,
        "kinetica_filter": False,
        "portfolio_filter": False,
    },
    "AE": {
        "cogs_sheet": "KCA-AE",
        "channel": "Amazon-AE",
        "country": "AE",
        "bulk_ops": ("UAE", "Bulk Operations"),
        "transaction": ("UAE", "Transaction"),
        "business_report": ("UAE", "BusinessReport"),
        "inventory": ("UAE", "Inventory"),
        "orders": ("App Main Files", "Orders", "Kinetica"),
        "ledger": ("UAE", "Inventory", "ledger_report"),
        "txn_skiprows": 8,
        "translate_de": False,
        "kinetica_filter": True,
        "portfolio_filter": True,
    },
}

SKU_OVERRIDES = {
    "200855": "KCA-200855",
    "KIN-201033": "KCA-201033",
}

REPORT_DEDUPE_KEYS = {
    "pnl": ("sku", "year_month", "channel", "client_id"),
    "ads": ("sku", "year_month", "country", "client_id"),
    "decomposition_chart": ("sku", "year_month", "country", "client_id"),
}

AZURE_BLOBS = {
    "pnl": (
        "sanity_data/PNL/final_pnl.parquet",
        "processed/csv/All_geographies_PNL.csv",
    ),
    "ads": (
        "sanity_data/ad_sales/final_ad_sales.parquet",
        "processed/csv/All_geographies_Ad_Sales_Spend_Gross_Sales.csv",
    ),
    "decomposition_chart": (
        "sanity_data/decomposition_chart/Decomposition_Chart.parquet",
        "processed/csv/All_geographies_Decomposition_Chart.csv",
    ),
}


# =============================================================================
# Paths / period helpers
# =============================================================================

def get_knc_root() -> Path:
    """Return KNC_DATA_ROOT after validating the configured client identity."""
    identity = client_identity(CLIENT)
    if identity["layout"].lower() != "knc":
        raise ValueError("KNC client is not configured with the KNC layout")
    root = paths.env_path("KNC_DATA_ROOT")
    if root is None:  # pragma: no cover
        raise EnvironmentError("KNC_DATA_ROOT is not configured")
    return root


def resolve_geo_path(geo: str, key: str) -> Path:
    """KNC_DATA_ROOT + GEO_CONFIG[geo][key] folder parts."""
    return get_knc_root().joinpath(*GEO_CONFIG[geo][key])


def resolve_year_month(
    year: int | str | None,
    month: int | str | None,
) -> tuple[int, int, str, str]:
    """
    Resolve CLI year/month → (year, month_number, mon_abbr, YYYY-MM).
    Defaults to current calendar month when omitted.
    """
    now = datetime.now()
    resolved_year = int(year) if year is not None else now.year

    if month is None:
        month_number = now.month
    elif isinstance(month, int) or str(month).strip().isdigit():
        month_number = int(month)
    else:
        token = str(month).strip().lower()[:3]
        month_lookup = {
            name.lower()[:3]: index
            for index, name in enumerate(calendar.month_name)
            if name
        }
        month_lookup.update(
            {
                name.lower()[:3]: index
                for index, name in enumerate(calendar.month_abbr)
                if name
            }
        )
        if token not in month_lookup:
            raise ValueError(f"Invalid month: {month!r}")
        month_number = month_lookup[token]

    if not 1 <= month_number <= 12:
        raise ValueError(f"Month must be 1-12, got {month_number}")

    abbreviation = calendar.month_abbr[month_number].lower()
    year_month = f"{resolved_year}-{month_number:02d}"
    return resolved_year, month_number, abbreviation, year_month


def parse_geos(geos: str | Sequence[str] | None) -> list[str]:
    """Normalize geos list; default = all GEO_CONFIG keys."""
    if geos is None:
        values = list(GEO_CONFIG)
    elif isinstance(geos, str):
        values = geos.split(",")
    else:
        values = list(geos)

    result = [str(geo).strip().upper() for geo in values if str(geo).strip()]
    unknown = sorted(set(result) - set(GEO_CONFIG))
    if unknown:
        raise ValueError(f"Unsupported KNC geographies: {', '.join(unknown)}")
    return result


def find_period_file(
    geo: str,
    key: str,
    year: int,
    month_abbr: str,
    *,
    extensions: Iterable[str] = (".csv", ".xlsx", ".xls"),
    required_tokens: Iterable[str] = (),
) -> Path | None:
    """
    Newest file under geo folder (prefer YEAR/mon, else base).
    Filename must contain all required_tokens (case-insensitive).
    """
    base = resolve_geo_path(geo, key)
    search_roots = [base / str(year) / month_abbr, base]
    tokens = [token.lower() for token in required_tokens]
    matches: list[Path] = []

    for search_root in search_roots:
        if not search_root.exists():
            continue
        for extension in extensions:
            for candidate in search_root.rglob(f"*{extension}"):
                lowered = candidate.name.lower()
                if all(token in lowered for token in tokens):
                    matches.append(candidate)
        if matches:
            break

    if not matches:
        print(f"    [common] period file not found: geo={geo} key={key} {year}/{month_abbr}")
        return None

    chosen = max(matches, key=lambda item: item.stat().st_mtime)
    print(f"    [common] period file: {chosen}")
    return chosen


# =============================================================================
# Excel / SKU helpers
# =============================================================================

def normalize_sheet_name(name: object) -> str:
    value = str(name).lower().strip().replace("-", " ").replace("_", " ")
    return re.sub(r"[^\w\s]", "", re.sub(r"\s+", " ", value))


def find_sheet(workbook: str | Path | pd.ExcelFile, target: str) -> str:
    excel = workbook if isinstance(workbook, pd.ExcelFile) else pd.ExcelFile(workbook)
    wanted = normalize_sheet_name(target)
    for sheet in excel.sheet_names:
        if normalize_sheet_name(sheet) == wanted:
            return sheet
    raise ValueError(
        f"Sheet {target!r} not found; available: {', '.join(excel.sheet_names)}"
    )


def clean_sku(value: object, mapping: Mapping[str, str] | None = None) -> str:
    if pd.isna(value):
        return "0"
    sku = re.sub(r"-{1,2}$", "", str(value).strip())
    sku = SKU_OVERRIDES.get(sku, sku)
    return (mapping or {}).get(sku, sku)


def build_sku_mapping(cogs: pd.DataFrame) -> dict[str, str]:
    """Map ON_1 / ON_2 aliases → master SKU."""
    mapping: dict[str, str] = {}
    if "SKU" not in cogs.columns:
        return mapping
    for _, row in cogs.iterrows():
        master = clean_sku(row.get("SKU"))
        for column in ("ON_1", "ON_2"):
            alias = row.get(column)
            if pd.notna(alias):
                mapping[clean_sku(alias)] = master
    return mapping


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Snake_case final-output column names (does not mutate input)."""
    result = df.copy()
    result.columns = [
        re.sub(
            r"_+",
            "_",
            str(column)
            .strip()
            .lower()
            .replace("-", "_")
            .replace(" ", "_")
            .replace("%", "percent"),
        ).strip("_")
        for column in result.columns
    ]
    return result


def numeric(series: pd.Series) -> pd.Series:
    """Coerce currency/number text to float (keeps minus signs)."""
    cleaned = (
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace(r"[^\d.\-]", "", regex=True)
    )
    return pd.to_numeric(cleaned, errors="coerce").fillna(0)


# =============================================================================
# Read COGS / bulk metrics
# =============================================================================

def read_cogs(geo: str) -> pd.DataFrame:
    """Load the geo's COGS sheet from KNC_COGS_PATH (or fallback under data root)."""
    print(f"    [common] reading COGS for {geo}...")
    configured = paths.env_path("KNC_COGS_PATH", required=False)
    candidates = [configured] if configured else []
    candidates.extend(
        [
            get_knc_root() / "pnl requirement" / "cogs.xlsx",
            get_knc_root() / "pnl_requirement" / "cogs.xlsx",
        ]
    )
    cogs_path = next(
        (candidate for candidate in candidates if candidate and candidate.exists()),
        None,
    )
    if cogs_path is None:
        raise FileNotFoundError("KNC COGS workbook not found (set KNC_COGS_PATH)")

    sheet = GEO_CONFIG[geo]["cogs_sheet"]
    print(f"    [common] COGS file: {cogs_path}  sheet={sheet}")
    return pd.read_excel(cogs_path, sheet_name=sheet)


def read_bulk_metrics(
    geo: str,
    year: int,
    month_abbr: str,
    cogs: pd.DataFrame,
    metrics: Sequence[str],
) -> pd.DataFrame:
    """
    Aggregate Sponsored Products / Brands / Display sheets by master SKU.
    metrics e.g. ("Spend",) or ("Sales",) or ("Clicks", "Units", "Impressions").
    """
    print(f"    [common] reading bulk ops for {geo} / {year}-{month_abbr} metrics={list(metrics)}")
    bulk_path = find_period_file(
        geo, "bulk_ops", year, month_abbr, extensions=(".xlsx", ".xls")
    )

    # AE fallback folder (legacy notebook location)
    if bulk_path is None and geo == "AE":
        fallback = (
            get_knc_root()
            / "UAE"
            / "pnl_requirement_files"
            / "bulk_operations_processed_ad_sales_ad_spend"
        )
        if fallback.exists():
            candidates = list(fallback.glob(f"*{month_abbr}*{year}*.xlsx"))
            bulk_path = (
                max(candidates, key=lambda item: item.stat().st_mtime)
                if candidates
                else None
            )
            if bulk_path is not None:
                print(f"    [common] AE bulk fallback: {bulk_path}")

    if bulk_path is None:
        raise FileNotFoundError(f"{geo} bulk operations workbook not found")

    mapping = build_sku_mapping(cogs)
    asin_map: dict[str, str] = {}
    if {"ASIN", "SKU"}.issubset(cogs.columns):
        asin_map = dict(
            zip(
                cogs["ASIN"].astype(str).str.strip(),
                cogs["SKU"].map(lambda x: clean_sku(x, mapping)),
            )
        )

    excel = pd.ExcelFile(bulk_path)
    pieces: list[pd.DataFrame] = []
    sheet_targets = (
        "Sponsored Products Campaigns",
        "Sponsored Brands Campaigns",
        "Sponsored Display campaigns",
    )

    for target in sheet_targets:
        try:
            sheet = find_sheet(excel, target)
        except ValueError:
            continue

        print(f"    [common] bulk sheet: {sheet}")
        frame = pd.read_excel(excel, sheet_name=sheet)

        if GEO_CONFIG[geo]["portfolio_filter"] and "Portfolio name (Informational only)" in frame.columns:
            frame = frame[
                frame["Portfolio name (Informational only)"]
                .astype(str)
                .str.contains("kinetica", case=False, na=False)
            ]

        if "Entity" in frame.columns:
            frame = frame[
                frame["Entity"].astype(str).str.contains("product ad", case=False, na=False)
            ]

        sku_column = "SKU" if "SKU" in frame.columns else None
        asin_column = next(
            (
                name
                for name in ("ASIN (Informational only)", "Creative ASINs", "ASIN")
                if name in frame.columns
            ),
            None,
        )

        rows: list[dict[str, object]] = []
        for _, row in frame.iterrows():
            skus: list[str] = []
            if sku_column and pd.notna(row.get(sku_column)):
                skus = [clean_sku(row[sku_column], mapping)]
            elif asin_column and pd.notna(row.get(asin_column)):
                asins = [
                    part.strip()
                    for part in str(row[asin_column]).split(",")
                    if part.strip()
                ]
                skus = [asin_map.get(asin, "0") for asin in asins]

            if not skus:
                continue

            for sku in skus:
                output: dict[str, object] = {"SKU": sku}
                for metric in metrics:
                    # split metric evenly across ASINs mapped to multiple SKUs
                    output[metric] = numeric(pd.Series([row.get(metric, 0)])).iloc[0] / len(skus)
                rows.append(output)

        if rows:
            pieces.append(pd.DataFrame(rows))

    if not pieces:
        print("    [common] bulk: no product-ad rows found")
        return pd.DataFrame(columns=["SKU", *metrics])

    result = pd.concat(pieces, ignore_index=True)
    out = result.groupby("SKU", as_index=False)[list(metrics)].sum()
    print(f"    [common] bulk aggregated SKUs: {len(out):,}")
    return out


# =============================================================================
# Save local masters
# =============================================================================

def concat_geo_frames(
    frames_by_geo: Mapping[str, pd.DataFrame],
    *,
    report_type: str,
    dedupe_subset: Sequence[str] | None = None,
) -> pd.DataFrame:
    frames = [
        normalize_columns(frame)
        for frame in frames_by_geo.values()
        if frame is not None and not frame.empty
    ]
    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True, sort=False)
    keys = list(dedupe_subset or REPORT_DEDUPE_KEYS.get(report_type, ()))
    existing = [key for key in keys if key in combined.columns]
    if existing:
        combined = combined.drop_duplicates(subset=existing, keep="last")
    return combined.reset_index(drop=True)


def save_geo_and_combined(
    frames_by_geo: Mapping[str, pd.DataFrame],
    *,
    client: str,
    report_subdir: str,
    name_suffix: str,
    dedupe_subset: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Save per-geo + combined parquet/CSV under sanity_data/{CLIENT}/{subdir}/."""
    print(f"\n>>> STEP: [common] save {report_subdir} masters")
    output_dir = paths.sanity_data_root() / client.upper() / report_subdir
    output_dir.mkdir(parents=True, exist_ok=True)

    for geo, frame in frames_by_geo.items():
        geo_frame = normalize_columns(frame)
        stem = output_dir / f"{geo.upper()}_{name_suffix}"
        geo_frame.to_parquet(stem.with_suffix(".parquet"), index=False)
        geo_frame.to_csv(stem.with_suffix(".csv"), index=False)
        print(f"    [common] saved {stem.name}.parquet/.csv  rows={len(geo_frame):,}")

    combined = concat_geo_frames(
        frames_by_geo,
        report_type=report_subdir,
        dedupe_subset=dedupe_subset,
    )
    final_stem = output_dir / f"final_{name_suffix}"
    combined.to_parquet(final_stem.with_suffix(".parquet"), index=False)
    combined.to_csv(final_stem.with_suffix(".csv"), index=False)
    print(f"    [common] saved final_{name_suffix}.*  rows={len(combined):,}")
    print(f"Saved {report_subdir} masters under {output_dir}")
    return combined


# =============================================================================
# Azure upload
# =============================================================================

def prompt_yes_no(message: str, *, default: bool = False) -> bool:
    suffix = " [Y/n] " if default else " [y/N] "
    try:
        answer = input(message + suffix).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return default
    if not answer:
        return default
    return answer in {"y", "yes"}


def resolve_azure_upload_choice(
    upload_azure: bool | None,
    *,
    skip_azure: bool = False,
) -> bool:
    """Decide Azure upload after local masters are saved."""
    if skip_azure:
        print("[KNC] Azure upload: NO (flag --skip-azure)")
        return False
    if upload_azure is True:
        print("[KNC] Azure upload: YES (flag --upload-azure)")
        return True
    if upload_azure is False:
        print("[KNC] Azure upload: NO")
        return False

    print()
    print("=" * 60)
    print("LOCAL KNC masters saved under sanity_data/KNC/{pnl|ads|decomposition_chart}/")
    print("Review them before uploading to Azure.")
    print("=" * 60)
    return prompt_yes_no("Upload final report to Azure?", default=False)


def _read_frame(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path)


def upload_finals_to_azure(
    frames_or_paths: pd.DataFrame | str | Path | Mapping[str, pd.DataFrame | str | Path],
    *,
    report_type: str | None = None,
    container_name: str | None = None,
    upload_processed_csv: bool = True,
) -> None:
    """Upload final parquet (+ optional processed CSV) using env credentials."""
    print("\n>>> STEP: [common] Azure upload")
    connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "").strip()
    if not connection_string:
        raise EnvironmentError("AZURE_STORAGE_CONNECTION_STRING is not configured")

    container = container_name or os.getenv("CONTAINER_NAME_KNC", "thrive-client-kinetica")
    try:
        from azure.storage.blob import BlobServiceClient, ContentSettings
    except ImportError as exc:  # pragma: no cover
        raise ImportError("Install azure-storage-blob to upload Atros reports") from exc

    items = (
        frames_or_paths
        if isinstance(frames_or_paths, Mapping)
        else {report_type or "pnl": frames_or_paths}
    )
    service = BlobServiceClient.from_connection_string(connection_string)

    for kind, source in items.items():
        if kind not in AZURE_BLOBS:
            raise KeyError(f"Unknown Atros report type: {kind}")

        frame = source.copy() if isinstance(source, pd.DataFrame) else _read_frame(Path(source))
        parquet_blob, csv_blob = AZURE_BLOBS[kind]

        parquet_buffer = io.BytesIO()
        frame.to_parquet(parquet_buffer, index=False)
        parquet_buffer.seek(0)
        service.get_blob_client(container=container, blob=parquet_blob).upload_blob(
            parquet_buffer, overwrite=True
        )

        if upload_processed_csv:
            csv_data = frame.to_csv(index=False).encode("utf-8")
            service.get_blob_client(container=container, blob=csv_blob).upload_blob(
                csv_data,
                overwrite=True,
                content_settings=ContentSettings(content_type="text/csv"),
            )

        print(f"Uploaded {kind} final to {container}/{parquet_blob}")
