"""
AkshareCnProvider — China macroeconomic data via akshare library.

akshare wraps Eastmoney/Sina/Cnstock/Tushare endpoints which mirror NBS/PBoC/
SAFE/GACC official releases. Bypasses GeoIP-blocking that prevents direct
NBS API access from non-China IPs. Reverse-engineered but stable API.

Per-slug config maps our indicator slug to:
- akshare function name (`ak.macro_china_*`)
- column name(s) for value extraction
- date column + parser
- unit + conversion

Adding a new CN slug = one entry in CN_SERIES + an indicator_sources row.
No HTTP/HTML parsing of our own.
"""

import re
from datetime import date

import pandas as pd

from pipeline.base_provider import BaseProvider, DataPoint
from pipeline.transforms import normalize_date
from pipeline.db import upsert_data_points, log_pipeline_run, datapoints_to_rows


def _parse_chinese_month(label: str) -> date | None:
    """Parse '2026年03月份' or '2026年03月' to date(2026,3,1)."""
    m = re.match(r"(\d{4})年(\d{1,2})月", str(label))
    if not m:
        return None
    return date(int(m.group(1)), int(m.group(2)), 1)


def _parse_chinese_quarter(label: str) -> date | None:
    """Parse '2026年第1季度' to date(2026,1,1) (start of quarter)."""
    m = re.match(r"(\d{4})年第([1-4])季度", str(label))
    if not m:
        return None
    return date(int(m.group(1)), {"1": 1, "2": 4, "3": 7, "4": 10}[m.group(2)], 1)


def _parse_iso_date(s: str) -> date | None:
    """Parse '2026-03-01' or '2026.3' or '2026年3月份' or 'YYYY/MM/DD'."""
    if isinstance(s, (pd.Timestamp,)):
        return s.date()
    s = str(s).strip()
    if not s or s == "nan":
        return None
    # try '2026.3' or '2026.03'
    m = re.match(r"^(\d{4})\.(\d{1,2})$", s)
    if m:
        return date(int(m.group(1)), int(m.group(2)), 1)
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", s)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return _parse_chinese_month(s) or _parse_chinese_quarter(s)


def _parse_yyyymm_compact(s) -> date | None:
    """'202603' → date(2026, 3, 1)."""
    s = str(s).strip()
    m = re.match(r"^(\d{4})(\d{2})$", s)
    if not m:
        return None
    return date(int(m.group(1)), int(m.group(2)), 1)


def _parse_yyyy_m_dot(s) -> date | None:
    """'2026.3' or '2026.03' → date(2026, 3, 1)."""
    s = str(s).strip()
    m = re.match(r"^(\d{4})\.(\d{1,2})$", s)
    if not m:
        return None
    return date(int(m.group(1)), int(m.group(2)), 1)


def _parse_cn_full_date(s) -> date | None:
    """'2025年05月07日' → date(2025, 5, 7)."""
    s = str(s).strip()
    m = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", s)
    if not m:
        return None
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def _parse_yyyy_dash_m(s) -> date | None:
    """'2026-04' → date(2026, 4, 1)."""
    s = str(s).strip()
    m = re.match(r"^(\d{4})-(\d{1,2})$", s)
    if not m:
        return None
    return date(int(m.group(1)), int(m.group(2)), 1)


# Per-slug config:
# func          → akshare function name (string)
# value_col     → column name with the published value
# date_col      → column name with the period
# date_parser   → callable label → date or 'cn_month' / 'cn_quarter' / 'iso'
# freq          → 'M' / 'Q' / 'A' / 'D'
# unit          → output unit string
# conversion    → multiplier on raw value (default 1)
# adjustment    → 'NSA' / 'SA' / ''
# filter        → optional dict {col: value} to filter rows (e.g. macro_china_new_house_price has 城市 column)
CN_SERIES: list[dict] = [
    # Inflation — value 1.0% YoY March 2026 (verified vs TE)
    {
        "indicator": "inflation-cpi-yoy",  # NEW slug variant: published YoY %
        "func": "macro_china_cpi",
        "value_col": "全国-同比增长",
        "date_col": "月份",
        "date_parser": "cn_month",
        "freq": "M",
        "unit": "% YoY",
        "adjustment": "NSA",
    },
    # Inflation Rate headline (NBS CPI YoY % — what TE shows as 'China Inflation Rate')
    {
        "indicator": "inflation-cpi",
        "func": "macro_china_cpi",
        "value_col": "全国-同比增长",  # National YoY %
        "date_col": "月份",
        "date_parser": "cn_month",
        "freq": "M",
        "unit": "% YoY",
        "adjustment": "NSA",
        "note": "NBS National CPI YoY % — matches TE 'China Inflation Rate'.",
    },
    # PPI YoY
    {
        "indicator": "ppi-yoy",
        "func": "macro_china_ppi",
        "value_col": "当月同比增长",
        "date_col": "月份",
        "date_parser": "cn_month",
        "freq": "M",
        "unit": "% YoY",
    },
    # Interest Rate (LPR 1Y)
    {
        "indicator": "interest-rate",
        "func": "macro_china_lpr",
        "value_col": "LPR1Y",
        "date_col": "TRADE_DATE",
        "date_parser": "iso",
        "freq": "M",  # daily fix → we'll keep latest per month at insert
        "unit": "%",
        "post": "monthly_last",  # collapse daily to month-end
    },
    # LPR 5Y
    {
        "indicator": "loan-prime-rate-5y",
        "func": "macro_china_lpr",
        "value_col": "LPR5Y",
        "date_col": "TRADE_DATE",
        "date_parser": "iso",
        "freq": "M",
        "unit": "%",
        "post": "monthly_last",
    },
    # Foreign Exchange Reserves (PBoC FX-only) - 100 million USD
    {
        "indicator": "foreign-exchange-reserves",
        "func": "macro_china_foreign_exchange_gold",
        "value_col": "国家外汇储备",
        "date_col": "统计时间",
        "date_parser": "iso",
        "freq": "M",
        "unit": "Billion USD",
        "conversion": 0.1,
    },
    # Gold Reserves — TE shows in Tonnes (WGC-labelled but PBoC data).
    # akshare raw is 万盎司 (10,000 troy oz). 1 troy oz = 0.0311034768 kg = 3.11034768e-5 Tonnes.
    # 万盎司 → Tonnes: × 10000 × 3.11034768e-5 = × 0.311034768
    {
        "indicator": "gold-reserves",
        "func": "macro_china_foreign_exchange_gold",
        "value_col": "黄金储备",
        "date_col": "统计时间",
        "date_parser": "iso",
        "freq": "M",
        "unit": "Tonnes",
        "conversion": 0.311034768,
        "note": "PBoC monthly gold reserves in Tonnes (TE labels WGC but underlying is PBoC).",
    },
    # Money Supply M2 - 100 million yuan
    {
        "indicator": "money-supply-m2",
        "func": "macro_china_money_supply",
        "value_col": "货币和准货币(M2)-数量(亿元)",
        "date_col": "月份",
        "date_parser": "cn_month",
        "freq": "M",
        "unit": "Billion CNY",
        "conversion": 0.1,  # 亿元 (100mln) → Billion: × 0.1
    },
    {
        "indicator": "money-supply-m1",
        "func": "macro_china_money_supply",
        "value_col": "货币(M1)-数量(亿元)",
        "date_col": "月份",
        "date_parser": "cn_month",
        "freq": "M",
        "unit": "Billion CNY",
        "conversion": 0.1,
    },
    {
        "indicator": "money-supply-m0",
        "func": "macro_china_money_supply",
        "value_col": "流通中的现金(M0)-数量(亿元)",
        "date_col": "月份",
        "date_parser": "cn_month",
        "freq": "M",
        "unit": "Billion CNY",
        "conversion": 0.1,
    },
    # Industrial Production YoY (NBS) — gyzjz = "工业增加值" / industrial added value
    # The macro_china_industrial_production_yoy fn (calendar feed) ends ~Aug 2025;
    # gyzjz is the current NBS press-release table, fresh through latest month.
    {
        "indicator": "industrial-production-yoy",
        "func": "macro_china_gyzjz",
        "value_col": "同比增长",
        "date_col": "月份",
        "date_parser": "cn_month",
        "freq": "M",
        "unit": "% YoY",
    },
    # Retail Sales (Consumer Goods Retail) - 亿元 → Bil CNY
    {
        "indicator": "retail-sales",
        "func": "macro_china_consumer_goods_retail",
        "value_col": "当月",
        "date_col": "月份",
        "date_parser": "cn_month",
        "freq": "M",
        "unit": "Billion CNY",
        "conversion": 0.1,
    },
    # NBS Manufacturing PMI
    {
        "indicator": "manufacturing-pmi",
        "func": "macro_china_pmi",
        "value_col": "制造业-指数",
        "date_col": "月份",
        "date_parser": "cn_month",
        "freq": "M",
        "unit": "Points",
    },
    # NBS Non-Manufacturing PMI (services + construction)
    {
        "indicator": "non-manufacturing-pmi",
        "func": "macro_china_pmi",
        "value_col": "非制造业-指数",
        "date_col": "月份",
        "date_parser": "cn_month",
        "freq": "M",
        "unit": "Points",
    },
    # Fixed Asset Investment (cumulative YTD growth)
    {
        "indicator": "fixed-asset-investment",
        "func": "macro_china_gdzctz",
        "value_col": "同比增长",
        "date_col": "月份",
        "date_parser": "cn_month",
        "freq": "M",
        "unit": "% YoY",
    },
    # GDP quarterly (current price, 亿元)
    {
        "indicator": "gdp-real",
        "func": "macro_china_gdp",
        "value_col": "国内生产总值-绝对值",
        "date_col": "季度",
        "date_parser": "cn_quarter",
        "freq": "Q",
        "unit": "Billion CNY",
        "conversion": 0.1,
        "filter_quarter_only": True,  # skip half-year/full-year aggregate rows
    },
    # GDP YoY growth quarterly
    {
        "indicator": "gdp-growth-rate",
        "func": "macro_china_gdp",
        "value_col": "国内生产总值-同比增长",
        "date_col": "季度",
        "date_parser": "cn_quarter",
        "freq": "Q",
        "unit": "% YoY",
        "filter_quarter_only": True,
    },
    # Surveyed Urban Unemployment Rate (NBS monthly)
    {
        "indicator": "unemployment",
        "func": "macro_china_urban_unemployment",
        "value_col": "value",
        "date_col": "date",
        "date_parser": "yyyymm_compact",
        "freq": "M",
        "unit": "%",
        "filter": {"item": "全国城镇调查失业率"},
    },
    # PBoC Total Assets / Central Bank Balance (亿元)
    {
        "indicator": "central-bank-balance",
        "func": "macro_china_central_bank_balance",
        "value_col": "总资产",
        "date_col": "统计时间",
        "date_parser": "yyyy_m_dot",
        "freq": "M",
        "unit": "Billion CNY",
        "conversion": 0.1,
    },
    # Exports YoY (Customs trade summary)
    {
        "indicator": "exports-yoy",
        "func": "macro_china_hgjck",
        "value_col": "当月出口额-同比增长",
        "date_col": "月份",
        "date_parser": "cn_month",
        "freq": "M",
        "unit": "% YoY",
    },
    # Imports YoY
    {
        "indicator": "imports-yoy",
        "func": "macro_china_hgjck",
        "value_col": "当月进口额-同比增长",
        "date_col": "月份",
        "date_parser": "cn_month",
        "freq": "M",
        "unit": "% YoY",
    },
    # New Bank Loans (PBoC, monthly new RMB loans 新增人民币贷款 in 亿元).
    # Note: macro_china_new_financial_credit reports a different aggregate that does
    # NOT match TE; macro_rmb_loan tracks the exact PBoC headline figure.
    {
        "indicator": "new-bank-loans",
        "func": "macro_rmb_loan",
        "value_col": "新增人民币贷款-总额",
        "date_col": "月份",
        "date_parser": "yyyy_dash_m",
        "freq": "M",
        "unit": "Billion CNY",
        "conversion": 0.1,
        "note": "PBoC monthly new RMB loans (matches TE 'China New Loans').",
    },
    # Cash Reserve Ratio (RRR) — adjustment events; we take 大型金融机构-调整后
    {
        "indicator": "cash-reserve-ratio",
        "func": "macro_china_reserve_requirement_ratio",
        "value_col": "大型金融机构-调整后",
        "date_col": "生效时间",
        "date_parser": "cn_full_date",
        "freq": "M",
        "unit": "%",
    },
    # Interbank Rate — 3M SHIBOR daily fix (collapse to monthly last)
    {
        "indicator": "interbank-rate",
        "func": "macro_china_shibor_all",
        "value_col": "3M-定价",
        "date_col": "日期",
        "date_parser": "iso",
        "freq": "M",
        "unit": "%",
        "post": "monthly_last",
    },
    # Housing Index — NBS National Real Estate Climate Index (国房景气指数)
    {
        "indicator": "housing-index",
        "func": "macro_china_real_estate",
        "value_col": "最新值",
        "date_col": "日期",
        "date_parser": "iso",
        "freq": "M",
        "unit": "Index",
    },
    # Business Confidence — TE reuses NBS Manufacturing PMI series here (e.g.,
    # April 2026 = 50.30 matches NBS PMI exactly). Honor TE convention.
    {
        "indicator": "business-confidence",
        "func": "macro_china_pmi",
        "value_col": "制造业-指数",
        "date_col": "月份",
        "date_parser": "cn_month",
        "freq": "M",
        "unit": "Points",
        "note": "Mirrors NBS Manufacturing PMI (TE convention for China Business Confidence).",
    },
]


def _resolve_date(label, parser):
    if callable(parser):
        return parser(label)
    if parser == "cn_month":
        return _parse_chinese_month(label)
    if parser == "cn_quarter":
        return _parse_chinese_quarter(label)
    if parser == "iso":
        return _parse_iso_date(label)
    if parser == "yyyymm_compact":
        return _parse_yyyymm_compact(label)
    if parser == "yyyy_m_dot":
        return _parse_yyyy_m_dot(label)
    if parser == "cn_full_date":
        return _parse_cn_full_date(label)
    if parser == "yyyy_dash_m":
        return _parse_yyyy_dash_m(label)
    return None


def _row_passes_filter(row, cfg):
    if cfg.get("filter_quarter_only"):
        # GDP table has rows like '2025年第1季度' (single Q) AND '2025年第1-4季度' (cumulative)
        if "-" in str(row.get(cfg["date_col"], "")):
            return False
    flt = cfg.get("filter") or {}
    for col, expected in flt.items():
        if str(row.get(col, "")).strip() != str(expected).strip():
            return False
    return True


def _collapse_monthly_last(points: list[DataPoint]) -> list[DataPoint]:
    """For daily series, keep only the latest observation per (year, month)."""
    by_month: dict[tuple[int, int, str, str], DataPoint] = {}
    for p in points:
        key = (p.date.year, p.date.month, p.indicator, p.country)
        existing = by_month.get(key)
        if existing is None or p.date > existing.date:
            by_month[key] = p
    # Re-normalize date to month-end
    out = []
    for p in by_month.values():
        out.append(DataPoint(
            indicator=p.indicator, country=p.country,
            date=normalize_date(p.date, "M"),
            value=p.value, source=p.source, unit=p.unit,
            series_id=p.series_id, adjustment=p.adjustment,
        ))
    return out


class AkshareCnProvider(BaseProvider):
    name = "akshare_cn"
    display_name = "akshare (China NBS/PBoC/SAFE/GACC mirrors)"

    def fetch(self) -> list[DataPoint]:
        import akshare as ak

        all_points: list[DataPoint] = []
        for cfg in CN_SERIES:
            slug = cfg["indicator"]
            fname = cfg["func"]
            try:
                df = getattr(ak, fname)()
            except Exception as exc:
                print(f"  FAIL {slug} ({fname}): {exc}")
                continue

            value_col = cfg["value_col"]
            date_col = cfg["date_col"]
            date_parser = cfg.get("date_parser", "iso")
            unit = cfg.get("unit", "")
            conversion = float(cfg.get("conversion") or 1)
            adjustment = cfg.get("adjustment", "")
            freq = cfg.get("freq", "M")

            if value_col not in df.columns or date_col not in df.columns:
                print(f"  FAIL {slug}: column missing (value={value_col}, date={date_col}); cols={list(df.columns)}")
                continue

            slug_pts: list[DataPoint] = []
            for _, row in df.iterrows():
                if not _row_passes_filter(row, cfg):
                    continue
                raw_val = row[value_col]
                if pd.isna(raw_val):
                    continue
                try:
                    value = float(raw_val) * conversion
                except (ValueError, TypeError):
                    continue
                dt = _resolve_date(row[date_col], date_parser)
                if not dt:
                    continue
                slug_pts.append(DataPoint(
                    indicator=slug, country="CN",
                    date=normalize_date(dt, freq),
                    value=round(value, 2),
                    source="akshare", unit=unit,
                    series_id=f"akshare:{fname}:{value_col}",
                    adjustment=adjustment,
                ))

            if cfg.get("post") == "monthly_last":
                slug_pts = _collapse_monthly_last(slug_pts)

            all_points.extend(slug_pts)
            latest = max(slug_pts, key=lambda p: p.date) if slug_pts else None
            print(f"  OK {slug:30} ({fname:40}): {len(slug_pts):4} pts; "
                  f"latest={latest.date if latest else 'none'} val={latest.value if latest else 'none'}")
        return all_points


def run():
    provider = AkshareCnProvider()
    print(f"Fetching data from {provider.display_name}...")
    try:
        points = provider.fetch()
        print(f"\nTotal: {len(points)} data points")
        if not points:
            log_pipeline_run("akshare_cn", "success", 0)
            return
        rows = datapoints_to_rows(points)
        total = 0
        for i in range(0, len(rows), 500):
            count = upsert_data_points(rows[i:i + 500])
            total += count
            print(f"  Upserted batch {i // 500 + 1}: {count} rows")
        log_pipeline_run("akshare_cn", "success", total)
        print(f"Done. {total} rows upserted.")
    except Exception as exc:
        log_pipeline_run("akshare_cn", "failed", error_message=str(exc))
        print(f"Failed: {exc}")
        raise


if __name__ == "__main__":
    run()
