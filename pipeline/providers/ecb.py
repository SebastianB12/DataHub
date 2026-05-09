"""
EcbProvider — European Central Bank Data API
Fetches: interest-rate, central-bank-balance, money-supply-m2 for Euro Area (EA).
Also inserts for DE (same monetary policy).

API: https://data-api.ecb.europa.eu/service/data/{dataflow}/{key}?format=csvdata
No API key required.
"""

import csv
import io
from datetime import date

import requests

from pipeline.base_provider import BaseProvider, DataPoint
from pipeline.transforms import normalize_date
from pipeline.db import upsert_data_points, log_pipeline_run, datapoints_to_rows

BASE_URL = "https://data-api.ecb.europa.eu/service/data"

# EA member states that share ECB monetary policy. interest-rate is replicated
# for each (it's the same policy rate). Aggregate-only indicators like
# central-bank-balance and money-supply-m2 are NOT replicated — they describe
# the Eurosystem / EA aggregate, not any single member.
EA_MEMBERS = ["DE", "FR", "AT", "BE", "CY", "EE", "FI", "GR", "IE", "IT",
              "LV", "LT", "LU", "MT", "NL", "PT", "SK", "SI", "ES", "HR"]
# HR (Croatia) joined the EA on 2023-01-01. All 20 current EA members share ECB rate.

# Indicators where the ECB value applies to every EA member (shared policy).
SHARED_POLICY_INDICATORS = {"interest-rate"}

# ECB series: (dataflow, key, indicator_slug, unit_conversion)
# unit_conversion: multiply ECB value by this factor
SERIES = [
    {
        "dataflow": "FM",
        "key": "B.U2.EUR.4F.KR.MRR_FR.LEV",  # B = business day (sparse, only change dates)
        "indicator": "interest-rate",
        "conversion": 1,  # already in %
        "unit": "%",
        "adjustment": "",
    },
    {
        "dataflow": "ILM",
        "key": "W.U2.C.T000000.Z5.Z01",  # W = weekly
        "indicator": "central-bank-balance",
        "conversion": 1 / 1000,  # millions EUR -> billions EUR
        "unit": "Billion EUR",
        "adjustment": "NSA",
    },
    {
        "dataflow": "BSI",
        "key": "M.U2.Y.V.M20.X.1.U2.2300.Z01.E",  # M = monthly
        "indicator": "money-supply-m2",
        "conversion": 1 / 1000,  # millions EUR -> billions EUR
        "unit": "Billion EUR",
        "adjustment": "NSA",
    },
    {
        "dataflow": "BSI",
        "key": "M.U2.Y.V.M10.X.1.U2.2300.Z01.E",
        "indicator": "money-supply-m1",
        "conversion": 1 / 1000,
        "unit": "Billion EUR",
        "adjustment": "NSA",
    },
    {
        "dataflow": "BSI",
        "key": "M.U2.Y.V.M30.X.1.U2.2300.Z01.E",
        "indicator": "money-supply-m3",
        "conversion": 1 / 1000,
        "unit": "Billion EUR",
        "adjustment": "NSA",
    },
    {
        # Adjusted loans to euro area NFCs (S.11) granted by MFIs, total maturity, EUR.
        "dataflow": "BSI",
        "key": "M.U2.Y.U.A20T.A.1.U2.2240.Z01.E",
        "indicator": "loans-to-private-sector",
        "conversion": 1 / 1000,
        "unit": "Billion EUR",
        "adjustment": "SA",
    },
]


def _parse_period(period_str: str) -> date | None:
    """Parse ECB time period to date.
    Formats: '2024-03-15' (daily/business), '2026-W15' (weekly),
             '2024-03' (monthly), '2024-Q1' (quarterly), '2024' (annual).
    """
    from datetime import datetime
    try:
        if "-W" in period_str:
            # Weekly: use Friday of that ISO week
            return datetime.strptime(period_str + "-5", "%G-W%V-%u").date()
        if "-Q" in period_str:
            year, q = period_str.split("-Q")
            month = {"1": 1, "2": 4, "3": 7, "4": 10}[q]
            return date(int(year), month, 1)
        if len(period_str) == 10:  # YYYY-MM-DD (daily/business)
            return date.fromisoformat(period_str)
        if len(period_str) == 7:  # YYYY-MM
            year, month = period_str.split("-")
            return date(int(year), int(month), 1)
        if len(period_str) == 4:  # YYYY
            return date(int(period_str), 1, 1)
    except (ValueError, KeyError):
        pass
    return None


def _fetch_series(dataflow: str, key: str) -> list[tuple[date, float]]:
    """Fetch a single ECB series as CSV and return (date, value) pairs."""
    url = f"{BASE_URL}/{dataflow}/{key}"
    resp = requests.get(url, params={"format": "csvdata"}, timeout=30)
    resp.raise_for_status()

    reader = csv.DictReader(io.StringIO(resp.text))
    results = []
    for row in reader:
        period = _parse_period(row.get("TIME_PERIOD", ""))
        value_str = row.get("OBS_VALUE", "")
        if period and value_str:
            try:
                results.append((period, float(value_str)))
            except ValueError:
                continue
    return results


class EcbProvider(BaseProvider):
    name = "ecb"
    display_name = "European Central Bank"

    def fetch(self) -> list[DataPoint]:
        all_points: list[DataPoint] = []

        for series in SERIES:
            try:
                raw = _fetch_series(series["dataflow"], series["key"])
                conversion = series["conversion"]

                # Determine frequency from key prefix
                freq_char = series["key"][0]
                freq = {"B": "D", "D": "D", "W": "W", "M": "M", "Q": "Q", "A": "A"}.get(freq_char, "M")

                # Shared-policy indicators (interest-rate) get replicated for each
                # EA member. Aggregate indicators (central-bank-balance, M2) stay
                # EA-only — they describe the Eurosystem, not any single member.
                replicate_to = EA_MEMBERS if series["indicator"] in SHARED_POLICY_INDICATORS else []
                targets = ["EA", *replicate_to]

                for dt, value in raw:
                    converted = round(value * conversion, 2)
                    norm_dt = normalize_date(dt, freq)
                    for country in targets:
                        all_points.append(DataPoint(
                            indicator=series["indicator"],
                            country=country,
                            date=norm_dt,
                            value=converted,
                            source="ecb",
                            unit=series["unit"],
                            adjustment=series.get("adjustment", ""),
                        ))

                print(f"  OK {series['indicator']}: {len(raw)} periods x {len(targets)} countries")
            except Exception as e:
                print(f"  FAIL {series['indicator']}: {e}")

        return all_points


def run():
    """Run the ECB provider and write to Supabase."""
    provider = EcbProvider()
    print(f"Fetching data from {provider.display_name}...")

    try:
        points = provider.fetch()
        print(f"\nTotal: {len(points)} data points")

        rows = datapoints_to_rows(points)

        total_upserted = 0
        batch_size = 500
        for i in range(0, len(rows), batch_size):
            batch = rows[i : i + batch_size]
            count = upsert_data_points(batch)
            total_upserted += count
            print(f"  Upserted batch {i // batch_size + 1}: {count} rows")

        log_pipeline_run("ecb", "success", total_upserted)
        print(f"\nDone. {total_upserted} rows upserted to Supabase.")

    except Exception as e:
        log_pipeline_run("ecb", "failed", error_message=str(e))
        print(f"\nFailed: {e}")
        raise


if __name__ == "__main__":
    run()
