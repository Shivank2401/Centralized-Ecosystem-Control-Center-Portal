"""
Shared helpers for Amazon reports (`report_script/amazon_reports`, stage key `common`).

Used by manage_fba / reserved / ageing / ledger scripts — no client-specific paths.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

import pandas as pd

SUPPORTED_EXTENSIONS = {".csv", ".xlsx", ".xls", ".json", ".ndjson"}
IGNORE_FILE_NAMES = {".ds_store", "thumbs.db"}
IGNORE_FILE_PREFIXES = ("~$", ".")


@dataclass
class LoadStats:
    geographies: Set[str] = field(default_factory=set)
    year_folders: Set[str] = field(default_factory=set)
    month_folders: Set[str] = field(default_factory=set)
    files_processed: int = 0
    files_failed: int = 0
    total_rows: int = 0
    detail: Dict[Tuple[str, str], dict] = field(default_factory=dict)

    def _bucket(self, geography: str, year: str) -> dict:
        key = (geography, str(year))
        if key not in self.detail:
            self.detail[key] = {
                "month_folders": 0,
                "files_processed": 0,
                "files_failed": 0,
                "rows": 0,
            }
        return self.detail[key]

    def record_month_folder(self, geography: str, year: str, month: str) -> None:
        self.month_folders.add(f"{geography}/{year}/{month}")
        self._bucket(geography, year)["month_folders"] += 1

    def record_file_ok(self, geography: str, year: str, rows: int) -> None:
        self.files_processed += 1
        self.total_rows += rows
        bucket = self._bucket(geography, year)
        bucket["files_processed"] += 1
        bucket["rows"] += rows

    def record_file_failed(self, geography: str, year: str) -> None:
        self.files_failed += 1
        self._bucket(geography, year)["files_failed"] += 1

    def summary_table(self) -> pd.DataFrame:
        rows = []
        for (geography, year), counts in sorted(
            self.detail.items(), key=lambda item: (item[0][0].lower(), item[0][1])
        ):
            rows.append(
                {
                    "geography": geography,
                    "year": year,
                    "month_folders": counts["month_folders"],
                    "files_processed": counts["files_processed"],
                    "files_failed": counts["files_failed"],
                    "rows": counts["rows"],
                }
            )
        return pd.DataFrame(
            rows,
            columns=[
                "geography",
                "year",
                "month_folders",
                "files_processed",
                "files_failed",
                "rows",
            ],
        )

    def format_summary(self, title: str = "Inventory Load Summary") -> str:
        """Plain-text load summary (also used for sanity run logs)."""
        lines = [
            "=" * 40,
            title,
            "=" * 40,
            f"Geographies       : {len(self.geographies)}",
            f"Year folders      : {len(self.year_folders)}",
            f"Month folders     : {len(self.month_folders)}",
            f"Files processed   : {self.files_processed}",
            f"Files failed      : {self.files_failed}",
            f"Total rows        : {self.total_rows:,}",
            "=" * 40,
        ]
        detail_df = self.summary_table()
        if detail_df.empty:
            lines.append("")
            lines.append("No geography/year detail available.")
            return "\n".join(lines)

        lines.append("")
        lines.append("Geography x Year breakdown")
        lines.append("-" * 72)
        display_df = detail_df.copy()
        display_df["rows"] = display_df["rows"].map(lambda n: f"{n:,}")
        lines.append(display_df.to_string(index=False))
        lines.append("-" * 72)

        geo_rollup = (
            detail_df.groupby("geography", sort=True)
            .agg(
                year_folders=("year", "nunique"),
                month_folders=("month_folders", "sum"),
                files_processed=("files_processed", "sum"),
                files_failed=("files_failed", "sum"),
                rows=("rows", "sum"),
            )
            .reset_index()
        )
        geo_rollup["rows"] = geo_rollup["rows"].map(lambda n: f"{n:,}")
        lines.append("")
        lines.append("Geography totals")
        lines.append("-" * 72)
        lines.append(geo_rollup.to_string(index=False))
        lines.append("-" * 72)
        return "\n".join(lines)

    def print_summary(self, title: str = "Inventory Load Summary") -> str:
        text = self.format_summary(title)
        print(text)
        return text


def to_snake(name: str) -> str:
    name = str(name).strip().lower()
    name = re.sub(r"[^a-z0-9]+", "_", name)
    name = re.sub(r"_+", "_", name)
    return name.strip("_")


def _clean_col(c: str) -> str:
    """
    Strip BOM / quotes / junk so Amazon header variants collapse to one name.

    DE short exports often arrive as ``\\ufeff\"snapshot-date\"`` or latin-1
    misreads ``ï»¿\"snapshot-date\"`` / ``Ã¯Â»Â¿\"snapshot-date\"``.
    """
    c = str(c).strip()
    for bom in (
        "\ufeff",
        "\ufffe",
        "\u00ef\u00bb\u00bf",  # UTF-8 BOM bytes read as latin-1 → ï»¿
        "ï»¿",
        "Ã¯Â»Â¿",  # double-mojibake of the same BOM
    ):
        c = c.replace(bom, "")
    c = c.strip().strip('"').strip("'").strip()
    # Drop any leftover leading non-alnum (quoted BOM, weird spaces)
    c = re.sub(r"^[^A-Za-z0-9]+", "", c)
    return c.strip('"').strip("'").strip()


def coalesce_snake_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize headers to snake_case and merge columns that map to the same name.

    Amazon exports often differ only by BOM/quotes (e.g. ``snapshot-date`` vs
    ``﻿\"snapshot-date\"``). A blind ``concat`` + ``drop_duplicates`` on column
    names keeps one variant and nulls the other — fix by row-wise coalesce.
    """
    if df.empty:
        return df.copy()

    out = df.copy()
    groups: Dict[str, List[str]] = {}
    for raw in out.columns:
        snake = to_snake(_clean_col(raw))
        groups.setdefault(snake, []).append(str(raw))

    merged: Dict[str, pd.Series] = {}
    for snake, raw_cols in groups.items():
        if len(raw_cols) == 1:
            merged[snake] = out[raw_cols[0]]
            continue
        series = out[raw_cols[0]]
        for col in raw_cols[1:]:
            series = series.combine_first(out[col])
        merged[snake] = series

    return pd.DataFrame(merged, index=out.index)


def load_existing_parquet_outputs(
    output_dir: Path,
    name_suffix: str,
) -> pd.DataFrame:
    """Load all existing `{CODE}_{suffix}.parquet` files from output_dir."""
    if not output_dir.is_dir():
        print(f"[INFO] No existing output folder yet: {output_dir}")
        return pd.DataFrame()

    files = sorted(output_dir.glob(f"*_{name_suffix}.parquet"))
    if not files:
        print(f"[INFO] No existing parquet files matching *_{name_suffix}.parquet")
        return pd.DataFrame()

    frames: List[pd.DataFrame] = []
    print(f"\nLoading existing parquet outputs from: {output_dir}")
    for path in files:
        try:
            df = pd.read_parquet(path)
            print(f"  [{path.name}] {len(df):,} rows")
            frames.append(df)
        except Exception as exc:  # noqa: BLE001
            print(f"  [WARN] Could not read {path.name}: {exc}")

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True, sort=False)


def merge_append_dedupe(
    existing_df: pd.DataFrame,
    new_df: pd.DataFrame,
    subset: Optional[Sequence[str]] = None,
) -> pd.DataFrame:
    """
    Append new rows onto existing history and drop duplicates.
    keep='last' so freshly processed rows win for the same key.
    """
    frames = [df for df in (existing_df, new_df) if df is not None and not df.empty]
    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True, sort=False)
    before = len(combined)

    subset_cols = list(subset) if subset is not None else []
    usable_subset = [c for c in subset_cols if c in combined.columns]
    if usable_subset:
        combined = combined.drop_duplicates(subset=usable_subset, keep="last")
    else:
        combined = combined.drop_duplicates(keep="last")

    combined = combined.drop_duplicates(keep="last").reset_index(drop=True)
    removed = before - len(combined)
    print(
        f"\nMerge + dedupe: existing={len(existing_df):,}  new={len(new_df):,}  "
        f"combined_before={before:,}  after={len(combined):,}  removed={removed:,}"
        f"  subset={usable_subset or 'all columns'}"
    )
    return combined


def print_script_completed(script_name: str, *, detail: str = "") -> None:
    """Standard success banner after a report script finishes without error."""
    name = str(script_name or "script").strip() or "script"
    suffix = f" ({detail})" if detail else ""
    print(f"\n[SUCCESS] {name}{suffix} completed successfully.\n")
