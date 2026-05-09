"""
Shared data transforms for the pipeline.
Uses pandas internally for efficient vectorized computation.
API: list[DataPoint] -> list[DataPoint]
"""

import calendar
from datetime import date

import pandas as pd

from pipeline.base_provider import DataPoint


def normalize_date(dt: date, frequency: str) -> date:
    """Normalize date to period-end (last day of month/quarter/year).

    Args:
        dt: The date to normalize.
        frequency: "M" (monthly), "Q" (quarterly), "A" (annual), "W" (weekly), "D" (daily).

    Returns:
        Date normalized to the last day of the period.
    """
    if frequency == "M":
        last_day = calendar.monthrange(dt.year, dt.month)[1]
        return date(dt.year, dt.month, last_day)
    if frequency == "Q":
        quarter_end_month = ((dt.month - 1) // 3 + 1) * 3
        last_day = calendar.monthrange(dt.year, quarter_end_month)[1]
        return date(dt.year, quarter_end_month, last_day)
    if frequency == "A":
        return date(dt.year, 12, 31)
    return dt  # weekly/daily: keep as-is


def compute_yoy(points: list[DataPoint], periods: int = 12, source: str = "") -> list[DataPoint]:
    """Compute year-over-year % change from index/level values.

    Args:
        points: DataPoints with raw index values (e.g. CPI index, PPI index).
        periods: Lookback periods for YoY (12 for monthly, 4 for quarterly).
        source: Source name to set on output DataPoints. If empty, keeps original.

    Returns:
        New DataPoints with YoY % change values, dropping the first `periods` rows per group.
    """
    if not points:
        return []

    df = pd.DataFrame([
        {"indicator": p.indicator, "country": p.country, "date": p.date, "value": p.value, "source": p.source}
        for p in points
    ])

    df = df.sort_values("date")
    df["yoy"] = df.groupby(["indicator", "country"])["value"].pct_change(periods=periods) * 100
    df = df.dropna(subset=["yoy"])
    df["yoy"] = df["yoy"].round(2)

    result_source = source or ""
    return [
        DataPoint(
            indicator=row["indicator"],
            country=row["country"],
            date=row["date"],
            value=row["yoy"],
            source=result_source or row["source"],
        )
        for _, row in df.iterrows()
    ]


def compute_trade_balance(points: list[DataPoint], source: str = "") -> list[DataPoint]:
    """Compute trade-balance = exports - imports from existing data points.

    Args:
        points: DataPoints containing 'exports' and 'imports' indicators.
        source: Source name to set on output DataPoints.

    Returns:
        New DataPoints with indicator='trade-balance' and value = exports - imports.
    """
    exports = {(p.country, p.date): p.value for p in points if p.indicator == "exports"}
    imports = {(p.country, p.date): p.value for p in points if p.indicator == "imports"}

    result_source = source or "computed"
    return [
        DataPoint(
            indicator="trade-balance",
            country=key[0],
            date=key[1],
            value=round(exp_val - imports[key], 2),
            source=result_source,
            adjustment="",
        )
        for key, exp_val in exports.items()
        if key in imports
    ]
