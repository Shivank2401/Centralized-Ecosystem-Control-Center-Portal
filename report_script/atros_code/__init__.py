"""KNC Atros executive reporting package."""

from __future__ import annotations

from typing import Any

import pandas as pd


def build_pnl_dataframe(**kwargs: Any) -> pd.DataFrame:
    from .pnl_report import build_pnl_dataframe as implementation

    return implementation(**kwargs)


def build_ad_sales_dataframe(**kwargs: Any) -> pd.DataFrame:
    from .ad_sales_report import build_ad_sales_dataframe as implementation

    return implementation(**kwargs)


def build_decomposition_chart_dataframe(**kwargs: Any) -> pd.DataFrame:
    from .decomposition_chart import build_decomposition_chart_dataframe as implementation

    return implementation(**kwargs)

__all__ = [
    "build_ad_sales_dataframe",
    "build_decomposition_chart_dataframe",
    "build_pnl_dataframe",
]
