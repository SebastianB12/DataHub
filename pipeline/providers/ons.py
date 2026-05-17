"""
OnsProvider — ONS Beta API + Bank of England IADB
Fetches all 19 indicators for UK (GB).

ONS API: https://api.beta.ons.gov.uk/v1/data?uri=/{path}
BoE IADB: https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp
No API keys required.
"""

import csv
import io
import re
import time
from datetime import date

import requests

from pipeline.base_provider import BaseProvider, DataPoint
from pipeline.transforms import normalize_date
from pipeline.db import upsert_data_points, log_pipeline_run, datapoints_to_rows

ONS_BASE = "https://www.ons.gov.uk/generator"
BOE_BASE = "https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp"

# Month name -> number
MONTH_MAP = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}

# ONS series: (uri_path, indicator, conversion, unit)
ONS_SERIES = [
    # GDP & Growth (gdp + gdp-per-capita come from World Bank, not ONS)
    {
        "uri": "/economy/grossdomesticproductgdp/timeseries/abmi/qna",
        "indicator": "gdp-real",
        "conversion": 1 / 1000,  # GBP millions (CVM) -> billions
        "unit": "Billion GBP",
        "adjustment": "SA",
    },
    # gdp-growth dropped 2026-04-30 — derived in frontend from gdp-real via Display-Toggle (% YoY)
    # Inflation & Prices
    {
        "uri": "/economy/inflationandpriceindices/timeseries/d7bt/mm23",
        "indicator": "inflation-cpi",
        "conversion": 1,  # CPI Index 2015=100
        "unit": "Index",
        "adjustment": "NSA",
    },
    {
        "uri": "/economy/inflationandpriceindices/timeseries/dkc7/mm23",
        "indicator": "core-cpi",
        "conversion": 1,  # Core CPI Index 2015=100
        "unit": "Index",
        "adjustment": "NSA",
    },
    {
        # GB7S = "PPI Index Output Domestic - C Manufactured products, excl Duty, 2015=100"
        # Replaces old JVZ7 (discontinued 2020-10-21 during PPI re-basing).
        "uri": "/economy/inflationandpriceindices/timeseries/gb7s/ppi",
        "indicator": "ppi",
        "conversion": 1,  # raw index value
        "unit": "Index",
        "adjustment": "NSA",
    },
    # Labor
    {
        "uri": "/employmentandlabourmarket/peoplenotinwork/unemployment/timeseries/mgsx/lms",
        "indicator": "unemployment",
        "conversion": 1,  # %
        "unit": "%",
        "adjustment": "SA",
    },
    {
        # MGRZ = All persons in employment (16+), SA, thousands
        "uri": "/employmentandlabourmarket/peopleinwork/employmentandemployeetypes/timeseries/mgrz/lms",
        "indicator": "employed-persons",
        "conversion": 1,
        "unit": "Thousand",
        "adjustment": "SA",
    },
    {
        # LF22 = LFS: Economic activity rate: UK: All: Aged 16-64 (%): SA — matches TE headline (~79%).
        # (MGWG is the inactivity rate — was used here previously by mistake.)
        "uri": "/employmentandlabourmarket/peopleinwork/employmentandemployeetypes/timeseries/lf22/lms",
        "indicator": "labor-force-participation-rate",
        "conversion": 1,
        "unit": "%",
        "adjustment": "SA",
    },
    {
        # MGSC = Unemployed persons (16+), SA, thousands
        "uri": "/employmentandlabourmarket/peoplenotinwork/unemployment/timeseries/mgsc/lms",
        "indicator": "unemployed-persons",
        "conversion": 1,
        "unit": "Thousand",
        "adjustment": "SA",
    },
    {
        # MGWY = Unemployment rate, 16-24, SA, %
        "uri": "/employmentandlabourmarket/peoplenotinwork/unemployment/timeseries/mgwy/lms",
        "indicator": "youth-unemployment-rate",
        "conversion": 1,
        "unit": "%",
        "adjustment": "SA",
    },
    {
        "uri": "/employmentandlabourmarket/peopleinwork/employmentandemployeetypes/timeseries/lf24/lms",
        "indicator": "employment-rate",
        "conversion": 1,  # %
        "unit": "%",
        "adjustment": "SA",
    },
    {
        "uri": "/economy/grossdomesticproductgdp/timeseries/ebaq/pn2",
        "indicator": "population",
        "conversion": 1 / 1000,  # thousands -> millions
        "unit": "Millions",
        "adjustment": "",
    },
    # Trade
    {
        "uri": "/economy/nationalaccounts/balanceofpayments/timeseries/ikbj/mret",
        "indicator": "trade-balance",
        "conversion": 1 / 1000,  # GBP millions -> billions
        "unit": "Billion GBP",
        "adjustment": "SA",
    },
    {
        "uri": "/economy/nationalaccounts/balanceofpayments/timeseries/hbop/pnbp",
        "indicator": "current-account",
        "conversion": 1 / 1000,  # GBP millions -> billions
        "unit": "Billion GBP",
        "adjustment": "SA",
    },
    {
        "uri": "/economy/nationalaccounts/balanceofpayments/timeseries/ikbh/mret",
        "indicator": "exports",
        "conversion": 1 / 1000,  # GBP millions -> billions
        "unit": "Billion GBP",
        "adjustment": "SA",
    },
    {
        "uri": "/economy/nationalaccounts/balanceofpayments/timeseries/ikbi/mret",
        "indicator": "imports",
        "conversion": 1 / 1000,  # GBP millions -> billions
        "unit": "Billion GBP",
        "adjustment": "SA",
    },
    # Earnings
    {
        # KAB9 = Average Weekly Earnings Total Pay (incl bonuses), GBP, SA
        "uri": "/employmentandlabourmarket/peopleinwork/earningsandworkinghours/timeseries/kab9/lms",
        "indicator": "wages",
        "conversion": 1,
        "unit": "GBP/Week",
        "adjustment": "SA",
    },
    # CPI subcomponents (Index)
    {
        # L522 = CPI Food & non-alcoholic beverages Index, 2015=100, NSA monthly
        "uri": "/economy/inflationandpriceindices/timeseries/l522/mm23",
        "indicator": "food-inflation",
        "conversion": 1,
        "unit": "Index",
        "adjustment": "NSA",
    },
    # Production — fixed 2026-05-16: K22A is MANUFACTURING (Section C), K222 is
    # all PRODUCTION (Sections B-E). Previous mapping was swapped (verified against
    # ONS Title metadata: K22A = "IOP: C:MANUFACTURING: CVMSA", K222 = "IOP: B-E:PRODUCTION: CVMSA").
    {
        # K222 = Index of Production all-industries (B-E), 2022=100, SA, monthly
        "uri": "/economy/economicoutputandproductivity/output/timeseries/k222/diop",
        "indicator": "industrial-production",
        "conversion": 1,
        "unit": "Index",
        "adjustment": "SA",
    },
    {
        # K22A = Manufacturing Index of Production (Section C), 2022=100, SA, monthly
        "uri": "/economy/economicoutputandproductivity/output/timeseries/k22a/diop",
        "indicator": "manufacturing-production",
        "conversion": 1,
        "unit": "Index",
        "adjustment": "SA",
    },
    {
        # K224 = Mining and quarrying Index of Production B, 2022=100, SA, monthly
        "uri": "/economy/economicoutputandproductivity/output/timeseries/k224/diop",
        "indicator": "mining-production",
        "conversion": 1,
        "unit": "Index",
        "adjustment": "SA",
    },
    # Retail
    {
        # J5EK = Retail Sales Index incl fuel, volume, SA, 2022=100, monthly. TE source.
        "uri": "/businessindustryandtrade/retailindustry/timeseries/j5ek/drsi",
        "indicator": "retail-sales",
        "conversion": 1,
        "unit": "Index",
        "adjustment": "SA",
    },
    # Government
    {
        # HF6W = PS: Net Debt (excluding public sector banks): £bn: CPNSA (absolute level — TE headline)
        "uri": "/economy/governmentpublicsectorandtaxes/publicsectorfinance/timeseries/hf6w/pusf",
        "indicator": "government-debt",
        "conversion": 1,  # GBP Billion (already £bn)
        "unit": "Billion GBP",
        "adjustment": "NSA",
    },
    {
        "uri": "/economy/governmentpublicsectorandtaxes/publicsectorfinance/timeseries/j5ij/pusf",
        "indicator": "budget-deficit",
        "conversion": -1,  # ONS reports net borrowing (positive = deficit); invert to TE convention (deficit negative)
        "unit": "% of GDP",
        "adjustment": "",
    },
]

# Bank of England series
BOE_SERIES = [
    {
        "code": "IUDBEDR",
        "indicator": "interest-rate",
        "conversion": 1,  # already %
        "freq": "daily",
        "unit": "%",
        "adjustment": "",
    },
    {
        "code": "LPMAUYM",
        "indicator": "money-supply-m2",
        "conversion": 1 / 1000,  # GBP millions -> billions
        "freq": "monthly",
        "unit": "Billion GBP",
        "adjustment": "SA",
    },
    {
        # LPMVTVX = Mortgage approvals for house purchase (count per month, SA)
        "code": "LPMVTVX",
        "indicator": "mortgage-approvals",
        "conversion": 1 / 1000,  # convert to thousands
        "freq": "monthly",
        "unit": "Thousand",
        "adjustment": "SA",
    },
    {
        # LPMBL22 = "Bank of England total balance sheet" (monthly, GBP millions).
        # Replaces old RPQB56A (quarterly Bankers' Department, last update 2024-12).
        "code": "LPMBL22",
        "indicator": "central-bank-balance",
        "conversion": 1 / 1000,  # GBP millions -> billions
        "freq": "monthly",
        "unit": "Billion GBP",
        "adjustment": "",
    },
]


def _parse_ons_period(period_str: str) -> tuple[date, str] | None:
    """Parse ONS period: '2024 Q1', '2024 JAN', '2024'. Returns (date, freq)."""
    period_str = period_str.strip()
    try:
        # Quarterly: "2024 Q1"
        m = re.match(r"^(\d{4})\s+Q(\d)$", period_str)
        if m:
            year, q = int(m.group(1)), int(m.group(2))
            month = {1: 1, 2: 4, 3: 7, 4: 10}[q]
            return date(year, month, 1), "Q"

        # Monthly: "2024 JAN"
        m = re.match(r"^(\d{4})\s+([A-Z]{3})$", period_str)
        if m:
            year = int(m.group(1))
            month = MONTH_MAP.get(m.group(2))
            if month:
                return date(year, month, 1), "M"

        # Annual: "2024"
        if re.match(r"^\d{4}$", period_str):
            return date(int(period_str), 1, 1), "A"
    except (ValueError, KeyError):
        pass
    return None


def _fetch_ons_csv(uri_path: str, max_retries: int = 3) -> list[tuple[date, float]]:
    """Fetch an ONS time series via CSV generator and return (date, value) pairs."""
    url = ONS_BASE
    headers = {"User-Agent": "EconPulse/1.0 (macroeconomic data pipeline)"}

    for attempt in range(max_retries):
        resp = requests.get(url, params={"format": "csv", "uri": uri_path}, headers=headers, timeout=30)
        if resp.status_code == 429:
            wait = 5 * (attempt + 1)
            print(f"    Rate limited, waiting {wait}s...")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        break
    else:
        resp.raise_for_status()  # raise last error

    # Parse all values with their frequency
    freq_priority = {"M": 1, "Q": 2, "A": 3}  # lower = more granular = preferred
    all_values: dict[date, tuple[float, int]] = {}  # date -> (value, priority)
    lines = resp.text.splitlines()

    for line in lines:
        parts = line.strip().strip('"').split('","')
        if len(parts) < 2:
            parts = line.strip().split(",")
        if len(parts) < 2:
            continue

        period_str = parts[0].strip().strip('"')
        value_str = parts[1].strip().strip('"')

        if not re.match(r"^\d{4}", period_str):
            continue

        parsed = _parse_ons_period(period_str)
        if not parsed:
            continue
        dt, freq = parsed
        norm_dt = normalize_date(dt, freq)

        try:
            value = float(value_str)
        except ValueError:
            continue

        priority = freq_priority.get(freq, 9)
        existing = all_values.get(norm_dt)
        # Keep the most granular (lowest priority number) for each date
        if existing is None or priority < existing[1]:
            all_values[norm_dt] = (value, priority)

    return [(dt, val) for dt, (val, _) in sorted(all_values.items())]


def _parse_boe_date(date_str: str) -> date | None:
    """Parse BoE date: '02 Jan 2020' or '01/Jan/2024'."""
    try:
        clean = date_str.strip()
        # Try space-separated: "02 Jan 2020"
        parts = clean.split()
        if len(parts) == 3:
            day = int(parts[0])
            month_str = parts[1][:3].upper()
            year = int(parts[2])
            month = MONTH_MAP.get(month_str)
            if month:
                return date(year, month, day)
        # Try slash-separated: "01/Jan/2024"
        parts = clean.split("/")
        if len(parts) == 3:
            day = int(parts[0])
            month_str = parts[1][:3].upper()
            year = int(parts[2])
            month = MONTH_MAP.get(month_str)
            if month:
                return date(year, month, day)
    except (ValueError, IndexError):
        pass
    return None


def _fetch_boe_csv(series_code: str) -> list[tuple[date, float]]:
    """Fetch a Bank of England IADB series as CSV."""
    params = {
        "csv.x": "yes",
        "Datefrom": "01/Jan/1975",
        "Dateto": "now",
        "SeriesCodes": series_code,
        "CSVF": "TN",
        "UsingCodes": "Y",
        "VPD": "Y",
        "VFD": "N",
    }
    headers = {"User-Agent": "EconPulse/1.0 (macroeconomic data pipeline)"}
    resp = requests.get(BOE_BASE, params=params, headers=headers, timeout=30)
    resp.raise_for_status()

    results: list[tuple[date, float]] = []
    reader = csv.DictReader(io.StringIO(resp.text))

    for row in reader:
        date_str = row.get("DATE", "")
        value_str = row.get(series_code, "")

        dt = _parse_boe_date(date_str)
        if not dt or not value_str:
            continue

        try:
            results.append((dt, float(value_str)))
        except ValueError:
            continue

    return results


class OnsProvider(BaseProvider):
    name = "ons"
    display_name = "Office for National Statistics (UK)"

    def fetch(self) -> list[DataPoint]:
        all_points: list[DataPoint] = []

        # Fetch ONS series
        for series in ONS_SERIES:
            try:
                raw = _fetch_ons_csv(series["uri"])
                conversion = series["conversion"]
                points = [
                    DataPoint(
                        indicator=series["indicator"],
                        country="GB",
                        date=dt,
                        value=round(value * conversion, 2),
                        source="ons",
                        unit=series["unit"],
                        adjustment=series.get("adjustment", ""),
                    )
                    for dt, value in raw
                ]

                all_points.extend(points)
                print(f"  OK {series['indicator']}: {len(points)} data points")

                time.sleep(3)  # ONS rate limits aggressively

            except Exception as e:
                print(f"  FAIL {series['indicator']}: {e}")

        # Fetch Bank of England series
        for series in BOE_SERIES:
            try:
                raw = _fetch_boe_csv(series["code"])
                conversion = series["conversion"]

                # For daily interest rate: keep only month-end values
                if series["freq"] == "daily":
                    monthly: dict[tuple[int, int], tuple[date, float]] = {}
                    for dt, value in raw:
                        key = (dt.year, dt.month)
                        if key not in monthly or dt > monthly[key][0]:
                            monthly[key] = (dt, value)
                    raw = list(monthly.values())

                boe_freq = {"daily": "M", "monthly": "M", "quarterly": "Q"}.get(series["freq"], "M")
                points = [
                    DataPoint(
                        indicator=series["indicator"],
                        country="GB",
                        date=normalize_date(dt, boe_freq),
                        value=round(value * conversion, 2),
                        source="ons",
                        unit=series["unit"],
                        adjustment=series.get("adjustment", ""),
                    )
                    for dt, value in raw
                ]
                all_points.extend(points)
                print(f"  OK {series['indicator']} (BoE): {len(points)} data points")

            except Exception as e:
                print(f"  FAIL {series['indicator']} (BoE): {e}")

        return all_points


def run():
    """Run the ONS provider and write to Supabase."""
    provider = OnsProvider()
    print(f"Fetching data from {provider.display_name}...")

    try:
        points = provider.fetch()
        print(f"\nTotal: {len(points)} data points")

        # Deduplicate: keep first value per (indicator, country, date)
        seen: set[tuple[str, str, str]] = set()
        unique_points: list = []
        for p in points:
            key = (p.indicator, p.country, p.date.isoformat())
            if key in seen:
                continue
            seen.add(key)
            unique_points.append(p)
        rows = datapoints_to_rows(unique_points)
        print(f"After dedup: {len(rows)} unique rows")

        total_upserted = 0
        batch_size = 500
        for i in range(0, len(rows), batch_size):
            batch = rows[i : i + batch_size]
            count = upsert_data_points(batch)
            total_upserted += count
            print(f"  Upserted batch {i // batch_size + 1}: {count} rows")

        log_pipeline_run("ons", "success", total_upserted)
        print(f"\nDone. {total_upserted} rows upserted to Supabase.")

    except Exception as e:
        log_pipeline_run("ons", "failed", error_message=str(e))
        print(f"\nFailed: {e}")
        raise


if __name__ == "__main__":
    run()
