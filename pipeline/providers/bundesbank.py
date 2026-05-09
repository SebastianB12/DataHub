"""
BundesbankProvider — Deutsche Bundesbank SDMX API
Fetches German national data from Bundesbank time series database.
Primary source for: PPI (Erzeugerpreise)
Planned: M2, Trade

API: https://api.statistiken.bundesbank.de/rest/data/{flowRef}/{key}
No API key required.
"""

import csv
import io
from datetime import date

import requests

from pipeline.base_provider import BaseProvider, DataPoint
from pipeline.transforms import normalize_date
from pipeline.db import upsert_data_points, log_pipeline_run, datapoints_to_rows

BASE_URL = "https://api.statistiken.bundesbank.de/rest/data"

# Bundesbank SDMX series
SERIES = [
    {
        "flow": "BBDP1",
        "key": "M.DE.N.EPG.G.GP19SA000000.I21.A",
        "indicator": "ppi",
        "country": "DE",
        "freq": "M",
        "unit": "Index",
        "adjustment": "NSA",
        "series_label": "Erzeugerpreise gewerblicher Produkte, Gesamtindex (2021=100)",
    },
    {
        "flow": "BBBS2",
        "key": "M.DB.Y.U.M20.X.1.U2.2300.Z01.E",  # DB = Deutscher Beitrag, M20 = M2, Bestand in EUR
        "indicator": "money-supply-m2",
        "country": "DE",
        "freq": "M",
        "unit": "Billion EUR",
        "conversion": 1,  # Already in Billions (UNIT_MULT=9)
        "adjustment": "SA",
        "series_label": "Geldmenge M2, Deutscher Beitrag (saisonbereinigt)",
    },
    {
        "flow": "BBBS2",
        "key": "M.DB.Y.U.M30A.X.1.U2.2300.Z01.E",  # M30A = M3 corrected (Repos with CCP)
        "indicator": "money-supply-m3",
        "country": "DE",
        "freq": "M",
        "unit": "Billion EUR",
        "conversion": 1,
        "adjustment": "SA",
        "series_label": "Geldmenge M3 (korr. Repos m. CCP), Deutscher Beitrag",
    },
    # ============== Konsolidierter Ausweis Eurosystems / Deutscher Beitrag (BBBK10) ==============
    # Discovered via DBnomics 2026-05-01. Series in BBBK10 sind Mio EUR (UNIT_MULT=6) -> /1000 für Mrd.
    {
        "flow": "BBBK10",
        "key": "M.TXI301",
        "indicator": "money-supply-m1",
        "country": "DE",
        "freq": "M",
        "unit": "Billion EUR",
        "conversion": 0.001,  # Mio EUR -> Mrd EUR
        "adjustment": "NSA",
        "series_label": "Geldmenge M1 / Deutscher Beitrag",
    },
    {
        "flow": "BBBK10",
        "key": "M.TXI355",
        "indicator": "banks-balance-sheet",
        "country": "DE",
        "freq": "M",
        "unit": "Billion EUR",
        "conversion": 0.001,
        "adjustment": "NSA",
        "series_label": "Aktiva/Passiva Insgesamt / Deutscher Beitrag (MFI Bilanzsumme)",
    },
    {
        "flow": "BBBK10",
        "key": "M.TXI358",
        "indicator": "loans-to-private-sector",
        "country": "DE",
        "freq": "M",
        "unit": "Billion EUR",
        "conversion": 0.001,
        "adjustment": "NSA",
        "series_label": "Kredite an Unternehmen und Haushalte / Deutscher Beitrag",
    },
    # ============== Bundesbank-Wochenausweis (BBBK11) — Bilanzsumme der Bundesbank ==============
    {
        "flow": "BBBK11",
        "key": "D.TTA032",
        "indicator": "central-bank-balance",
        "country": "DE",
        "freq": "D",
        "unit": "Billion EUR",
        "conversion": 0.001,
        "adjustment": "NSA",
        "series_label": "Bilanzsumme Deutsche Bundesbank (täglich, unbewertet)",
    },
    # ============== Reserve Assets (BBFI1) ==============
    {
        "flow": "BBFI1",
        "key": "M.N.DE.W1.S121.S1.LE.A.FA.R.F._Z.X1._X.N",
        "indicator": "foreign-exchange-reserves",
        "country": "DE",
        "freq": "M",
        "unit": "Billion EUR",
        "conversion": 0.001,  # Mio EUR -> Mrd EUR
        "adjustment": "NSA",
        "series_label": "Reserve Assets Total / Bundesbank",
    },
    # DE Trade (Deutscher Außenhandel) — values in thousands EUR (UNIT_MULT=3)
    {
        "flow": "BBDA1",
        "key": "M.DE.N.SD.S.A.W1.A.V.ABA.A",  # Saldo, alle Länder, in jeweiligen Preisen, Ursprungswerte
        "indicator": "trade-balance",
        "country": "DE",
        "freq": "M",
        "unit": "Billion EUR",
        "conversion": 1 / 1_000_000,  # Thousands EUR -> Billions
        "adjustment": "NSA",
        "series_label": "Außenhandel Saldo, alle Länder",
    },
    {
        "flow": "BBDA1",
        "key": "M.DE.N.EX.S.A.W1.A.V.ABA.A",  # Exporte
        "indicator": "exports",
        "country": "DE",
        "freq": "M",
        "unit": "Billion EUR",
        "conversion": 1 / 1_000_000,
        "adjustment": "NSA",
        "series_label": "Außenhandel Exporte, alle Länder",
    },
    {
        "flow": "BBDA1",
        "key": "M.DE.N.IM.S.A.W1.A.V.ABA.A",  # Importe
        "indicator": "imports",
        "country": "DE",
        "freq": "M",
        "unit": "Billion EUR",
        "conversion": 1 / 1_000_000,
        "adjustment": "NSA",
        "series_label": "Außenhandel Importe, alle Länder",
    },
]


def _parse_period(period_str: str) -> date | None:
    """Parse Bundesbank period string."""
    try:
        if len(period_str) == 7:  # YYYY-MM
            year, month = period_str.split("-")
            return date(int(year), int(month), 1)
        if len(period_str) == 4:  # YYYY
            return date(int(period_str), 1, 1)
        if len(period_str) == 10:  # YYYY-MM-DD
            return date.fromisoformat(period_str)
    except (ValueError, IndexError):
        pass
    return None


def _fetch_series(flow: str, key: str) -> list[tuple[date, float]]:
    """Fetch a Bundesbank SDMX series as CSV."""
    url = f"{BASE_URL}/{flow}/{key}"
    resp = requests.get(url, headers={"Accept": "application/vnd.sdmx.data+csv"}, timeout=60)
    resp.raise_for_status()

    results: list[tuple[date, float]] = []
    text = resp.text.replace("\ufeff", "")
    reader = csv.DictReader(io.StringIO(text), delimiter=";")

    for row in reader:
        period_str = row.get("TIME_PERIOD", "")
        value_str = row.get("OBS_VALUE", "")
        if not period_str or not value_str:
            continue
        dt = _parse_period(period_str)
        if dt is None:
            continue
        try:
            results.append((dt, float(value_str)))
        except ValueError:
            continue

    return results


class BundesbankProvider(BaseProvider):
    name = "bundesbank"
    display_name = "Deutsche Bundesbank"

    def fetch(self) -> list[DataPoint]:
        all_points: list[DataPoint] = []

        for series in SERIES:
            try:
                raw = _fetch_series(series["flow"], series["key"])
                freq = series.get("freq", "M")

                conversion = series.get("conversion", 1)
                points = [
                    DataPoint(
                        indicator=series["indicator"],
                        country=series["country"],
                        date=normalize_date(dt, freq),
                        value=round(value * conversion, 2),
                        source="bundesbank",
                        unit=series.get("unit", ""),
                        series_id=f'{series["flow"]}.{series["key"]}',
                        adjustment=series.get("adjustment", ""),
                    )
                    for dt, value in raw
                ]
                all_points.extend(points)

                dates = [p.date for p in points]
                earliest = min(dates) if dates else "?"
                latest = max(dates) if dates else "?"
                print(f"  OK {series['indicator']} ({series['country']}): {len(points)} points ({earliest} - {latest})")

            except Exception as e:
                print(f"  FAIL {series['indicator']}: {e}")

        return all_points


def run():
    """Run the Bundesbank provider and write to Supabase."""
    provider = BundesbankProvider()
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

        log_pipeline_run("bundesbank", "success", total_upserted)
        print(f"\nDone. {total_upserted} rows upserted to Supabase.")

    except Exception as e:
        log_pipeline_run("bundesbank", "failed", error_message=str(e))
        print(f"\nFailed: {e}")
        raise


if __name__ == "__main__":
    run()
