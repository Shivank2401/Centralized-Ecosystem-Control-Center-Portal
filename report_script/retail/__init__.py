# Retail package — KeHE, Sprouts, Walmart / Scintilla (ESH)

from __future__ import annotations

import pandas as pd


def drop_duplicates_appended(
    df: pd.DataFrame,
    label: str,
    *,
    subset: list[str] | None = None,
) -> pd.DataFrame:
    """
    Drop duplicate rows from an appended / historical frame (Azure-synced
    archive concat), not from a single current-day download alone.

    keep='last' so the most recently concatenated copy wins.
    """
    if df is None or df.empty:
        return df if df is not None else pd.DataFrame()

    before = len(df)
    usable = [c for c in (subset or []) if c in df.columns]
    if usable:
        out = df.drop_duplicates(subset=usable, keep="last")
    else:
        out = df.drop_duplicates(keep="last")
    out = out.reset_index(drop=True)
    removed = before - len(out)
    print(
        f"  [{label}] appended-history dedupe: {before:,} -> {len(out):,} "
        f"(removed {removed:,})"
        + (f" subset={usable}" if usable else "")
    )
    return out
