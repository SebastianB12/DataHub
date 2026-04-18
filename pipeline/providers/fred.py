import os
from datetime import date
from fredapi import Fred
from dotenv import load_dotenv

from pipeline.base_provider import BaseProvider, DataPoint
from pipeline.db import upsert_data_points, log_pipeline_run

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

# FRED Series ID → our indicator slug
SERIES_MAP = {
    # GDP & Growth
    "GDP": "gdp",  # Nominal GDP (Billions USD, quarterly)
    "GDPC1": "gdp-real",  # Real GDP (Billions chained 2017 USD, quarterly)
    "A191RL1Q225SBEA": "gdp-growth",  # Real GDP growth rate (% change, quarterly)
    "A939RC0Q052SBEA": "gdp-per-capita",  # GDP per capita (USD, quarterly)
    # Inflation & Prices
    "CPIAUCSL": "inflation-cpi",  # CPI for All Urban Consumers (Index, monthly) → we compute YoY %
    "CPILFESL": "core-cpi",  # Core CPI excl. food & energy (Index, monthly) → we compute YoY %
    "PPIACO": "ppi",  # PPI All Commodities (Index, monthly) → we compute YoY %
    # Labor
    "UNRATE": "unemployment",  # Unemployment Rate (%, monthly)
    "EMRATIO": "employment-rate",  # Employment-Population Ratio (%, monthly)
    "POPTHM": "population",  # Population (Thousands, monthly)
    # Monetary
    "FEDFUNDS": "interest-rate",  # Federal Funds Rate (%, monthly)
    "WALCL": "central-bank-balance",  # Fed Total Assets (Millions USD, weekly)
    "M2SL": "money-supply-m2",  # M2 Money Stock (Billions USD, monthly)
    # Trade
    "BOPGSTB": "trade-balance",  # Trade Balance (Millions USD, monthly)
    "NETFI": "current-account",  # Current Account (Billions USD, quarterly)
    "BOPGEXP": "exports",  # Exports (Millions USD, monthly)
    "BOPGIMP": "imports",  # Imports (Millions USD, monthly)
    # Government
    "GFDEGDQ188S": "government-debt",  # Federal Debt to GDP (%, quarterly)
    "FYFSGDA188S": "budget-deficit",  # Federal Surplus/Deficit to GDP (%, annual)
}

# Series that are indexes where we need to compute YoY % change
YOY_SERIES = {"CPIAUCSL", "CPILFESL", "PPIACO"}

# Unit conversions: FRED value → our standard unit
UNIT_CONVERSIONS = {
    "WALCL": 1 / 1000,  # Millions → Billions
    "BOPGSTB": 1 / 1000,  # Millions → Billions
    "BOPGEXP": 1 / 1000,  # Millions → Billions
    "BOPGIMP": 1 / 1000,  # Millions → Billions
    "POPTHM": 1 / 1000,  # Thousands → Millions
}


class FredProvider(BaseProvider):
    name = "fred"
    display_name = "Federal Reserve Economic Data"

    def __init__(self):
        self.fred = Fred(api_key=os.environ["FRED_API_KEY"])

    def _fetch_series(self, series_id: str, indicator_slug: str) -> list[DataPoint]:
        """Fetch a single FRED series and convert to DataPoints."""
        series = self.fred.get_series(series_id)
        series = series.dropna()

        points = []
        conversion = UNIT_CONVERSIONS.get(series_id, 1)

        if series_id in YOY_SERIES:
            # Compute year-over-year % change from index values
            yoy = series.pct_change(periods=12) * 100  # 12 months
            yoy = yoy.dropna()
            for dt, value in yoy.items():
                points.append(DataPoint(
                    indicator=indicator_slug,
                    country="US",
                    date=dt.date(),
                    value=round(float(value), 2),
                    source="fred",
                ))
        else:
            for dt, value in series.items():
                points.append(DataPoint(
                    indicator=indicator_slug,
                    country="US",
                    date=dt.date(),
                    value=round(float(value) * conversion, 2),
                    source="fred",
                ))

        return points

    def fetch(self) -> list[DataPoint]:
        """Fetch all US indicators from FRED."""
        all_points = []

        for series_id, indicator_slug in SERIES_MAP.items():
            try:
                points = self._fetch_series(series_id, indicator_slug)
                all_points.extend(points)
                print(f"  OK {indicator_slug}: {len(points)} data points")
            except Exception as e:
                print(f"  FAIL {indicator_slug} ({series_id}): {e}")

        return all_points


def run():
    """Run the FRED provider and write to Supabase."""
    provider = FredProvider()
    print(f"Fetching data from {provider.display_name}...")

    try:
        points = provider.fetch()
        print(f"\nTotal: {len(points)} data points")

        # Convert to dicts for Supabase
        rows = [
            {
                "indicator": p.indicator,
                "country": p.country,
                "date": p.date.isoformat(),
                "value": p.value,
                "source": p.source,
            }
            for p in points
        ]

        # Upsert in batches of 500
        total_upserted = 0
        batch_size = 500
        for i in range(0, len(rows), batch_size):
            batch = rows[i : i + batch_size]
            count = upsert_data_points(batch)
            total_upserted += count
            print(f"  Upserted batch {i // batch_size + 1}: {count} rows")

        log_pipeline_run("fred", "success", total_upserted)
        print(f"\nDone. {total_upserted} rows upserted to Supabase.")

    except Exception as e:
        log_pipeline_run("fred", "failed", error_message=str(e))
        print(f"\nFailed: {e}")
        raise


if __name__ == "__main__":
    run()
