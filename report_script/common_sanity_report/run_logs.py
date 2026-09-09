"""
Run-log writer for common sanity scripts (text + new-SKU CSV exports).

Covers:
  - Writes sanity_data/{CLIENT}/logs/{report}/{YYYYMMDD_HHMMSS}.log + latest.log
  - New-SKU CSV: sanity_data/{CLIENT}/logs/new_skus_vs_cogs/{report}/latest.csv
  - Formatters for LoadStats, geo summaries, orders period stats, inventory_database sections

Helper only — used via ReportRunLog from report scripts.

Adding a NEW client: no code change here. Paths use ``client`` string
(``sanity_data/{CLIENT}/logs/...``). Callers just pass the new client code.

Style: clear sections. Write/format logic unchanged.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Union

import pandas as pd

from config_manager.paths import sanity_data_root
from config_manager.report_helpers import LoadStats


# =============================================================================
# Paths
# =============================================================================

def client_logs_root(client: str) -> Path:
    return sanity_data_root() / str(client).upper() / "logs"


def report_log_dir(client: str, report: str) -> Path:
    safe = str(report).strip().lower().replace(" ", "_")
    return client_logs_root(client) / safe


def new_skus_csv_dir(client: str, report: str) -> Path:
    """``sanity_data/{CLIENT}/logs/new_skus_vs_cogs/{report}/``"""
    safe = str(report).strip().lower().replace(" ", "_")
    return client_logs_root(client) / "new_skus_vs_cogs" / safe


# =============================================================================
# New-SKU CSV export
# =============================================================================

def export_new_skus_csv(
    client: str,
    report: str,
    alerts: Dict[str, List[str]],
    *,
    started_at: Optional[datetime] = None,
) -> Optional[Path]:
    """
    Write one row per missing SKU (client × report × geography).

    Files (only when at least one SKU is missing)::

        sanity_data/{CLIENT}/logs/new_skus_vs_cogs/{report}/latest.csv
        sanity_data/{CLIENT}/logs/new_skus_vs_cogs/{report}/{YYYYMMDD_HHMMSS}.csv

    Returns the ``latest.csv`` path, or ``None`` when every geo is clean.
    """
    rows: List[dict] = []
    run_at = (started_at or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    tag_client = str(client).upper()
    tag_report = str(report).strip().lower().replace(" ", "_")
    for geo, skus in sorted(alerts.items()):
        tag_geo = str(geo).strip().upper()
        for sku in skus:
            rows.append(
                {
                    "client": tag_client,
                    "report": tag_report,
                    "geography": tag_geo,
                    "sku": str(sku).strip().upper(),
                    "run_at": run_at,
                }
            )
    if not rows:
        return None

    out_dir = new_skus_csv_dir(tag_client, tag_report)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = (started_at or datetime.now()).strftime("%Y%m%d_%H%M%S")
    df = pd.DataFrame(rows, columns=["client", "report", "geography", "sku", "run_at"])
    latest = out_dir / "latest.csv"
    stamped = out_dir / f"{stamp}.csv"
    df.to_csv(latest, index=False)
    df.to_csv(stamped, index=False)
    print(f"[{tag_client}] New-SKU CSV: {latest} ({len(rows)} row(s))")
    return latest


# =============================================================================
# ReportRunLog — accumulate text, flush to disk
# =============================================================================

class ReportRunLog:
    """Accumulate one pipeline run's summary text and flush to disk."""

    def __init__(self, client: str, report: str) -> None:
        self.client = str(client).upper()
        self.report = str(report).strip().lower().replace(" ", "_")
        self.started_at = datetime.now()
        self._lines: List[str] = []
        self.path: Optional[Path] = None
        self.latest_path: Optional[Path] = None
        stamp = self.started_at.strftime("%Y-%m-%d %H:%M:%S")
        self._lines.append("=" * 72)
        self._lines.append(f"{self.client} | {self.report} | run {stamp}")
        self._lines.append("=" * 72)

    def append(self, text: Union[str, Sequence[str]]) -> None:
        if isinstance(text, str):
            chunk = text.rstrip("\n")
            if chunk:
                self._lines.append(chunk)
            return
        for item in text:
            self.append(str(item))

    def blank(self) -> None:
        self._lines.append("")

    def section(self, title: str) -> None:
        self.blank()
        self._lines.append(title)
        self._lines.append("-" * min(72, max(24, len(title))))

    def flush(self) -> Path:
        print(f"\n>>> STEP: write run log [{self.client}] {self.report}")
        out_dir = report_log_dir(self.client, self.report)
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = self.started_at.strftime("%Y%m%d_%H%M%S")
        self.path = out_dir / f"{stamp}.log"
        self.latest_path = out_dir / "latest.log"
        body = "\n".join(self._lines).rstrip() + "\n"
        self.path.write_text(body, encoding="utf-8")
        self.latest_path.write_text(body, encoding="utf-8")
        print(f"[{self.client}] Run log written: {self.path}")
        print(f"[{self.client}] Latest log   : {self.latest_path}")
        return self.path

    def __enter__(self) -> "ReportRunLog":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is not None:
            self.blank()
            self.append(f"[ERROR] Run ended with {exc_type.__name__}: {exc}")
        self.flush()


# =============================================================================
# Formatters (for log file text — logic unchanged)
# =============================================================================

def format_load_stats(stats: LoadStats, title: str = "Load Summary") -> str:
    """Mirror ``LoadStats.print_summary`` as a single string for log files."""
    return stats.format_summary(title)


def format_new_skus_section(
    client: str,
    alerts: Dict[str, List[str]],
    *,
    label: str = "",
) -> str:
    """Format final-dataframe new-SKU vs COGS results for a log file."""
    tag = str(client).upper()
    title = f"[{tag}] New SKUs vs COGS sheet (final dataframe, before export)"
    if label:
        title = f"{title} [{label}]"
    lines = [title]
    if not alerts:
        lines.append("  (no geography slices checked)")
        return "\n".join(lines)

    any_new = False
    for geo, skus in sorted(alerts.items()):
        geo_tag = f"[{tag}] [{geo}]"
        if label:
            geo_tag = f"{geo_tag} [{label}]"
        if skus:
            any_new = True
            lines.append(f"  {geo_tag} NEW SKUs not in COGS sheet ({len(skus)}):")
            preview = skus[:50]
            for sku in preview:
                lines.append(f"    - {sku}")
            if len(skus) > 50:
                lines.append(f"    ... +{len(skus) - 50} more")
        else:
            lines.append(f"  {geo_tag} No new SKUs — all present in COGS sheet")

    if any_new:
        lines.append("")
        rollup = f"[{tag}] New-SKU alert rollup"
        if label:
            rollup = f"{rollup} ({label})"
        lines.append(f"{rollup}:")
        for geo, skus in sorted(alerts.items()):
            if skus:
                lines.append(f"  {geo}: {len(skus)} SKU(s)")
    return "\n".join(lines)


def _orders_period_labels(today: Optional[pd.Timestamp] = None):
    """Match orders_report._period_labels (avoid circular import)."""
    today = today if today is not None else pd.Timestamp.today().normalize()
    ref = today - pd.Timedelta(days=1)
    if ref.day <= 2:
        current = (ref - pd.DateOffset(months=1)).to_period("M")
    else:
        current = ref.to_period("M")
    previous = current - 1
    return str(current), str(previous), str(current.year)


def format_orders_period_summary(df: pd.DataFrame) -> str:
    """
    Client × geo current/previous month orders lines.

    Example::

        [AE] current month orders (2026-08): rows=12 | qty=100 |
            total_sales_sum=1234.56 | previous month qty=90 |
            previous_month total_sales_sum=1100.00
    """
    if df is None or df.empty:
        return "[INFO] Empty orders frame — no period summary"

    current_m, previous_m, _current_y = _orders_period_labels()
    work = df.copy()
    if "year_month" not in work.columns:
        return "[WARN] No year_month column — skip orders period log"
    for col in ("quantity", "total_sales"):
        if col not in work.columns:
            work[col] = 0
    work["quantity"] = pd.to_numeric(work["quantity"], errors="coerce").fillna(0)
    work["total_sales"] = pd.to_numeric(work["total_sales"], errors="coerce").fillna(0.0)

    lines = [
        f"Orders period summary  (current={current_m}, previous={previous_m})",
        "-" * 72,
    ]
    if "geography" not in work.columns:
        ym = work["year_month"].astype(str)
        cur = work.loc[ym == current_m]
        prev = work.loc[ym == previous_m]
        lines.append(
            f"ALL current month orders ({current_m}): "
            f"rows={len(cur):,} | qty={int(round(cur['quantity'].sum())):,} | "
            f"total_sales_sum={cur['total_sales'].sum():,.2f} | "
            f"previous month qty={int(round(prev['quantity'].sum())):,} | "
            f"previous_month total_sales_sum={prev['total_sales'].sum():,.2f}"
        )
        return "\n".join(lines)

    for geo, geo_df in work.groupby("geography", sort=True):
        ym = geo_df["year_month"].astype(str)
        cur = geo_df.loc[ym == current_m]
        prev = geo_df.loc[ym == previous_m]
        lines.append(
            f"[{geo}] current month orders ({current_m}): "
            f"rows={len(cur):,} | qty={int(round(cur['quantity'].sum())):,} | "
            f"total_sales_sum={cur['total_sales'].sum():,.2f} | "
            f"previous month qty={int(round(prev['quantity'].sum())):,} | "
            f"previous_month total_sales_sum={prev['total_sales'].sum():,.2f}"
        )
    return "\n".join(lines)


def format_stock_status_counts(stock_status: Dict[str, int]) -> str:
    lines = ["Stock status counts"]
    if not stock_status:
        lines.append("  - (none)")
        return "\n".join(lines)
    for status in ("Overstock", "Understock", "Healthy"):
        if status in stock_status:
            lines.append(f"  - {status}: {stock_status[status]:,}")
    for status, count in sorted(stock_status.items()):
        if status not in {"Overstock", "Understock", "Healthy"}:
            lines.append(f"  - {status}: {count:,}")
    return "\n".join(lines)


def format_inventory_database_geo_section(
    *,
    client: str,
    geography: str,
    rows: int,
    stock_status: Optional[Dict[str, int]] = None,
    new_skus: Optional[List[str]] = None,
) -> str:
    """Per-geo inventory_database checklist block (stock status + new SKUs)."""
    tag = f"[{str(client).upper()}] [{str(geography).upper()}]"
    lines = [
        f"{tag} inventory_database",
        f"  rows={rows:,}",
    ]
    if stock_status is not None:
        lines.append("  Stock status counts")
        if stock_status:
            for status in ("Overstock", "Understock", "Healthy"):
                if status in stock_status:
                    lines.append(f"   - {status}: {stock_status[status]:,}")
            for status, count in sorted(stock_status.items()):
                if status not in {"Overstock", "Understock", "Healthy"}:
                    lines.append(f"   - {status}: {count:,}")
        else:
            lines.append("   - (none)")
    else:
        lines.append(
            "  Stock status counts: n/a "
            "(computed in vector_report with MTQ thresholds, not inventory_database)"
        )

    skus = new_skus or []
    lines.append(
        f"  New SKUs (final dataframe vs this geo COGS sheet): {len(skus):,}"
    )
    if skus:
        preview = skus[:25]
        lines.append(f"   - sample: {preview}")
        if len(skus) > 25:
            lines.append(f"   - ... +{len(skus) - 25} more")
    else:
        lines.append("   - none")
    return "\n".join(lines)
