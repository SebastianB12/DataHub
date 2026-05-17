"""AkShareCnProvider — China macroeconomic data via akshare (V2 stateless).

akshare wraps Eastmoney/Sina/Cnstock/Tushare endpoints that mirror NBS/PBoC/
SAFE/GACC official releases. Bypasses GeoIP-blocking that prevents direct
NBS API access from non-China IPs.

V2 stateless: provider.fetch_series(SeriesSpec) -> list[Observation].
Keine indicator/country/source-Knowledge mehr. Wird vom Dispatcher pro
data_series-Row gerufen.

SeriesSpec.series_id format:
  - "akshare:<function>:<colspec>"   z.B. "akshare:macro_china_cpi:全国-当月"
  - "akshare:<function>"              fuer Funktionen mit nur einer relevanten Spalte
                                       (z.B. macro_china_urban_unemployment).

<colspec> kann entweder:
  - eine literale DataFrame-Spalten-Bezeichnung sein (z.B. "全国-同比增长"), ODER
  - ein Alias (z.B. "M2", "M1", "exp-yoy"), der in COLUMN_ALIASES aufgeloest wird.

FUNCTION_CONFIGS beschreibt pro akshare-Funktion:
  date_col, date_parser, freq (default), default conversion, optionaler post-step
  (z.B. "monthly_last" fuer tagliche Reihen), optionaler row-filter, und ggfs.
  per-column overrides fuer conversion/freq.
"""
from __future__ import annotations

import re
from datetime import date

import pandas as pd

from pipeline.base_provider import (
    BaseProvider, SeriesSpec, Observation,
    ProviderError, TransientProviderError,
)
from pipeline.transforms import normalize_date
from pipeline.dispatcher import register_provider


# ---------------- Date parsers ----------------

def _parse_chinese_month(label) -> date | None:
    m = re.match(r"(\d{4})年(\d{1,2})月", str(label))
    if not m:
        return None
    return date(int(m.group(1)), int(m.group(2)), 1)


def _parse_chinese_quarter(label) -> date | None:
    m = re.match(r"(\d{4})年第([1-4])季度", str(label))
    if not m:
        return None
    return date(int(m.group(1)), {"1": 1, "2": 4, "3": 7, "4": 10}[m.group(2)], 1)


def _parse_iso_date(s) -> date | None:
    if isinstance(s, pd.Timestamp):
        return s.date()
    s = str(s).strip()
    if not s or s == "nan":
        return None
    m = re.match(r"^(\d{4})\.(\d{1,2})$", s)
    if m:
        return date(int(m.group(1)), int(m.group(2)), 1)
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", s)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return _parse_chinese_month(s) or _parse_chinese_quarter(s)


def _parse_yyyymm_compact(s) -> date | None:
    m = re.match(r"^(\d{4})(\d{2})$", str(s).strip())
    if not m:
        return None
    return date(int(m.group(1)), int(m.group(2)), 1)


def _parse_yyyy_m_dot(s) -> date | None:
    m = re.match(r"^(\d{4})\.(\d{1,2})$", str(s).strip())
    if not m:
        return None
    return date(int(m.group(1)), int(m.group(2)), 1)


def _parse_cn_full_date(s) -> date | None:
    m = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", str(s).strip())
    if not m:
        return None
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def _parse_yyyy_dash_m(s) -> date | None:
    m = re.match(r"^(\d{4})-(\d{1,2})$", str(s).strip())
    if not m:
        return None
    return date(int(m.group(1)), int(m.group(2)), 1)


_PARSERS = {
    "cn_month":        _parse_chinese_month,
    "cn_quarter":      _parse_chinese_quarter,
    "iso":             _parse_iso_date,
    "yyyymm_compact":  _parse_yyyymm_compact,
    "yyyy_m_dot":      _parse_yyyy_m_dot,
    "cn_full_date":    _parse_cn_full_date,
    "yyyy_dash_m":     _parse_yyyy_dash_m,
}


# ---------------- Column-Aliases (DB-series_id -> DataFrame-Spalte) ----------------
#
# Manche stored series_ids verwenden kurze, sprechende Aliases ("M2", "exp-yoy")
# statt der rohen chinesischen DataFrame-Spaltennamen. Hier mappen wir diese auf.

COLUMN_ALIASES: dict[tuple[str, str], str] = {
    ("macro_china_money_supply", "M2"): "货币和准货币(M2)-数量(亿元)",
    ("macro_china_money_supply", "M1"): "货币(M1)-数量(亿元)",
    ("macro_china_money_supply", "M0"): "流通中的现金(M0)-数量(亿元)",
    ("macro_china_hgjck", "exp-yoy"):   "当月出口额-同比增长",
    ("macro_china_hgjck", "imp-yoy"):   "当月进口额-同比增长",
}


# ---------------- Function-Configs ----------------
#
# Pro akshare-Funktion: date_col / date_parser / freq / optionaler post-step /
# optionaler row-filter (immer aktiv) / optionale per-column-overrides (conv).
#
# "default_col" wird verwendet wenn series_id KEINEN colspec hat
# (z.B. "akshare:macro_china_urban_unemployment").

FUNCTION_CONFIGS: dict[str, dict] = {
    "macro_china_cpi": {
        "date_col": "月份", "date_parser": "cn_month", "freq": "M",
    },
    "macro_china_ppi": {
        "date_col": "月份", "date_parser": "cn_month", "freq": "M",
    },
    "macro_china_lpr": {
        "date_col": "TRADE_DATE", "date_parser": "iso", "freq": "M",
        "post": "monthly_last",
    },
    "macro_china_foreign_exchange_gold": {
        "date_col": "统计时间", "date_parser": "iso", "freq": "M",
        "column_overrides": {
            # raw 国家外汇储备 ist in 亿美元 -> Billion USD: × 0.1
            "国家外汇储备": {"conv": 0.1},
            # raw 黄金储备 ist in 万盎司 -> Million Troy Ounces: × 0.01
            "黄金储备":     {"conv": 0.01},
        },
    },
    "macro_china_money_supply": {
        "date_col": "月份", "date_parser": "cn_month", "freq": "M",
        # 亿元 -> Billion CNY: × 0.1
        "conv": 0.1,
    },
    "macro_china_gyzjz": {
        "date_col": "月份", "date_parser": "cn_month", "freq": "M",
    },
    "macro_china_consumer_goods_retail": {
        "date_col": "月份", "date_parser": "cn_month", "freq": "M",
        "conv": 0.1,
    },
    "macro_china_pmi": {
        "date_col": "月份", "date_parser": "cn_month", "freq": "M",
    },
    "macro_china_gdzctz": {
        "date_col": "月份", "date_parser": "cn_month", "freq": "M",
    },
    "macro_china_gdp": {
        "date_col": "季度", "date_parser": "cn_quarter", "freq": "Q",
        "filter_quarter_only": True,
        "column_overrides": {
            "国内生产总值-绝对值": {"conv": 0.1},  # 亿元 -> Billion CNY
        },
    },
    "macro_china_urban_unemployment": {
        "date_col": "date", "date_parser": "yyyymm_compact", "freq": "M",
        "default_col": "value",
        "filter": {"item": "全国城镇调查失业率"},
    },
    "macro_china_central_bank_balance": {
        "date_col": "统计时间", "date_parser": "yyyy_m_dot", "freq": "M",
        "conv": 0.1,
    },
    "macro_china_hgjck": {
        "date_col": "月份", "date_parser": "cn_month", "freq": "M",
    },
    "macro_rmb_loan": {
        "date_col": "月份", "date_parser": "yyyy_dash_m", "freq": "M",
        "conv": 0.1,
    },
    "macro_china_new_financial_credit": {
        "date_col": "月份", "date_parser": "cn_month", "freq": "M",
        "default_col": "当月",
        "conv": 0.1,  # 亿元 -> Billion CNY
    },
    "macro_china_reserve_requirement_ratio": {
        "date_col": "生效时间", "date_parser": "cn_full_date", "freq": "M",
        "default_col": "大型金融机构-调整后",
    },
    "macro_china_shibor_all": {
        "date_col": "日期", "date_parser": "iso", "freq": "M",
        "post": "monthly_last",
    },
    "macro_china_real_estate": {
        "date_col": "日期", "date_parser": "iso", "freq": "M",
    },
    "macro_china_enterprise_boom_index": {
        "date_col": "季度", "date_parser": "cn_quarter", "freq": "Q",
    },
}


# ---------------- Helpers ----------------

_TRANSIENT_HINTS = (
    "timeout", "timed out", "Connection",
    "ConnectionError", "ProxyError", "RemoteDisconnected",
    "Max retries exceeded", "Read timed out",
    "HTTPSConnectionPool", "Temporary failure",
)


def _is_transient(exc: BaseException) -> bool:
    msg = str(exc)
    return any(s in msg for s in _TRANSIENT_HINTS)


def _resolve_parser(name):
    if callable(name):
        return name
    return _PARSERS.get(name)


def _row_passes_filter(row, cfg) -> bool:
    if cfg.get("filter_quarter_only"):
        if "-" in str(row.get(cfg["date_col"], "")):
            return False
    flt = cfg.get("filter") or {}
    for col, expected in flt.items():
        if str(row.get(col, "")).strip() != str(expected).strip():
            return False
    return True


def _collapse_monthly_last(obs: list[Observation]) -> list[Observation]:
    """For daily-like series: keep latest observation per (year, month), normalized to M."""
    by_month: dict[tuple[int, int], Observation] = {}
    for o in obs:
        key = (o.date.year, o.date.month)
        if key not in by_month or o.date > by_month[key].date:
            by_month[key] = o
    return [
        Observation(date=normalize_date(o.date, "M"), value=o.value)
        for o in by_month.values()
    ]


def _parse_series_id(series_id: str) -> tuple[str, str | None]:
    """Split 'akshare:<func>[:<colspec>]' -> (func, colspec or None)."""
    s = (series_id or "").strip()
    if not s:
        raise ProviderError("akshare: empty series_id")
    parts = s.split(":", 2)
    if len(parts) < 2 or parts[0] != "akshare":
        raise ProviderError(
            f"akshare: series_id {series_id!r} must start with 'akshare:<function>'"
        )
    func = parts[1].strip()
    colspec = parts[2].strip() if len(parts) == 3 and parts[2].strip() else None
    return func, colspec


# ---------------- Provider ----------------

class AkShareCnProvider(BaseProvider):
    name = "akshare"
    display_name = "akshare (China NBS/PBoC/SAFE/GACC mirrors)"

    def fetch_series(self, spec: SeriesSpec) -> list[Observation]:
        func, colspec = _parse_series_id(spec.series_id)

        cfg = FUNCTION_CONFIGS.get(func)
        if cfg is None:
            raise ProviderError(f"akshare: unknown function {func!r}")

        # Resolve column name
        value_col: str
        if colspec:
            value_col = COLUMN_ALIASES.get((func, colspec), colspec)
        else:
            default_col = cfg.get("default_col")
            if not default_col:
                raise ProviderError(
                    f"akshare: series_id {spec.series_id!r} has no colspec and "
                    f"function {func} has no default_col"
                )
            value_col = default_col

        # Call akshare
        try:
            import akshare as ak
        except ImportError as e:
            raise ProviderError(f"akshare not installed: {e}") from e

        try:
            fn = getattr(ak, func, None)
            if fn is None:
                raise ProviderError(f"akshare: function {func} not found in akshare module")
            df = fn()
        except ProviderError:
            raise
        except Exception as e:
            if _is_transient(e):
                raise TransientProviderError(f"akshare {func}: {e}") from e
            raise ProviderError(f"akshare {func}: {e}") from e

        if df is None or not hasattr(df, "columns") or len(df) == 0:
            return []

        date_col = cfg["date_col"]
        if value_col not in df.columns or date_col not in df.columns:
            raise ProviderError(
                f"akshare {func}: missing column (value={value_col!r}, date={date_col!r}); "
                f"cols={list(df.columns)}"
            )

        # Effective conversion: spec.conversion * column_override (if any) * function-level default (else 1)
        col_overrides = (cfg.get("column_overrides") or {}).get(value_col) or {}
        col_conv = col_overrides.get("conv", cfg.get("conv", 1.0))
        spec_conv = spec.conversion if spec.conversion is not None else 1.0
        conv = float(spec_conv) * float(col_conv)

        # Effective frequency: spec.freq_hint overrides cfg
        freq = spec.freq_hint or cfg.get("freq", "M")
        # Normalize 'T' (INSEE trimestre) to 'Q' for safety
        if freq == "T":
            freq = "Q"

        date_parser = _resolve_parser(cfg.get("date_parser", "iso"))
        if date_parser is None:
            raise ProviderError(f"akshare {func}: unknown date_parser {cfg.get('date_parser')!r}")

        out: list[Observation] = []
        for _, row in df.iterrows():
            if not _row_passes_filter(row, cfg):
                continue
            raw_val = row[value_col]
            if pd.isna(raw_val):
                continue
            try:
                value = float(raw_val) * conv
            except (TypeError, ValueError):
                continue
            dt = date_parser(row[date_col])
            if dt is None:
                continue
            # For daily series collapsed later, keep raw date for sorting
            if cfg.get("post") == "monthly_last":
                out.append(Observation(date=dt, value=round(value, 6)))
            else:
                out.append(Observation(
                    date=normalize_date(dt, freq),
                    value=round(value, 6),
                ))

        if cfg.get("post") == "monthly_last":
            out = _collapse_monthly_last(out)

        return out


# ---------------- Registration ----------------
# DB stores fetch_provider='akshare'. Register under 'akshare'; also expose
# legacy alias 'akshare_cn' for any historical configs that still reference it.

try:
    _provider = AkShareCnProvider()
    register_provider(_provider)
    # Alias-Registration: same instance under second name.
    class _AkShareCnAlias(AkShareCnProvider):
        name = "akshare_cn"
    register_provider(_AkShareCnAlias())
except ProviderError as e:
    print(f"[warn] AkShareCnProvider not registered: {e}")
