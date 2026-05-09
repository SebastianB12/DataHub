"""INE-ES Provider — Spain primary source via INE Tempus3 JSON API.
TE-Source-First: für ES-Reihen wo TE „Source: INE" zeigt.

API: https://servicios.ine.es/wstempus/js/EN/{endpoint}
- DATOS_SERIE/<COD> — fetch a single series with optional ?nult=N
- SERIES_TABLA/<TABLE_ID>?det=1 — list series in a table

Strategy: hardcoded SERIES list mapping our slug -> INE COD. Each series identified
during probe-phase by checking the COD against TE values.
"""
import os
from datetime import date
from calendar import monthrange

import requests
from dotenv import load_dotenv

from pipeline.base_provider import BaseProvider, DataPoint
from pipeline.transforms import normalize_date
from pipeline.db import upsert_data_points, log_pipeline_run, datapoints_to_rows

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

BASE_URL = "https://servicios.ine.es/wstempus/js/EN"

# INE returns FK_Periodo as month-of-year (1-12) for monthly, quarter (1-4) for
# quarterly. We need to detect periodicity from the series metadata. For now
# we hardcode it per series.
SERIES = [
    # Inflation CPI — IPC table 76125. IPC290751 = National Overall Index (level).
    # YoY change in TE matches our Eurostat HICP within 0.3%, and INE-direct gives
    # exactly the value TE shows.
    {
        "indicator": "inflation-cpi",
        "cod": "IPC290751",
        "freq": "M",
        "unit": "Index",
        "adjustment": "NSA",
        "conversion": 1.0,
        "note": "INE IPC base 2026=100, monthly index, all-items, national",
    },
    # Core CPI — IPC290851 = National Overall index without unprocessed food and energy
    # (this is the "subyacente" series TE shows).
    {
        "indicator": "core-cpi",
        "cod": "IPC290851",
        "freq": "M",
        "unit": "Index",
        "adjustment": "NSA",
        "conversion": 1.0,
        "note": "INE IPC subyacente (ex. unprocessed food + energy)",
    },
    # Food inflation — IPC290755 (Food and non-alcoholic beverages, index)
    {
        "indicator": "food-inflation",
        "cod": "IPC290755",
        "freq": "M",
        "unit": "Index",
        "adjustment": "NSA",
        "conversion": 1.0,
        "note": "INE IPC Food and non-alcoholic beverages",
    },
    # Unemployment rate quarterly EPA — both genders, national total, all ages
    {
        "indicator": "unemployment",
        "cod": "EPA452434",
        "freq": "Q",
        "unit": "%",
        "adjustment": "NSA",
        "conversion": 1.0,
        "note": "INE EPA Tasa de paro total (both genders, national, 16+)",
    },
    # PPI Industrial producer prices — Industry total, Index level
    {
        "indicator": "ppi",
        "cod": "IPR34522",
        "freq": "M",
        "unit": "Index",
        "adjustment": "NSA",
        "conversion": 1.0,
        "note": "INE IPRI Industria total (Index level, base 2025=100)",
    },
    # Industrial Production Index — total industry, index level
    {
        "indicator": "industrial-production",
        "cod": "IPI13491",
        "freq": "M",
        "unit": "Index",
        "adjustment": "NSA",
        "conversion": 1.0,
        "note": "INE IPI National Total Industry total (index level)",
    },
    # Retail sales index — constant prices, national total, headline
    {
        "indicator": "retail-sales",
        "cod": "ICM4147",
        "freq": "M",
        "unit": "Index",
        "adjustment": "NSA",
        "conversion": 1.0,
        "note": "INE ICM Volume index commercial retail trade (constant prices, no service stations)",
    },
]


def _parse_period_to_date(year: int, fk_periodo: int, freq: str) -> date | None:
    """INE periodo codes:
    - monthly: 1-12 (matches calendar months)
    - quarterly EPA: 19, 20, 21, 22 → Q1, Q2, Q3, Q4 (INE-specific)
    - quarterly other: 1-4
    - annual: 1
    """
    try:
        if freq == "M":
            month = fk_periodo
            return date(year, month, 1)
        if freq == "Q":
            quarter_map = {1: 1, 2: 4, 3: 7, 4: 10,
                           19: 1, 20: 4, 21: 7, 22: 10}
            month = quarter_map[fk_periodo]
            return date(year, month, 1)
        if freq == "A":
            return date(year, 1, 1)
    except (ValueError, KeyError):
        pass
    return None


def _fetch_serie(cod: str, n_last: int = 200) -> list[tuple[date, float, int, int]]:
    """Returns list of (date_from_year_periodo, value, year, fk_periodo)."""
    url = f"{BASE_URL}/DATOS_SERIE/{cod}?nult={n_last}"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()


class IneEsProvider(BaseProvider):
    name = "ine_es"
    display_name = "INE Spain"

    def fetch(self) -> list[DataPoint]:
        out: list[DataPoint] = []
        for cfg in SERIES:
            try:
                data = _fetch_serie(cfg["cod"], n_last=400)
                obs_list = data.get("Data", [])
                for obs in obs_list:
                    val = obs.get("Valor")
                    if val is None:
                        continue
                    year = obs.get("Anyo")
                    periodo = obs.get("FK_Periodo")
                    dt = _parse_period_to_date(year, periodo, cfg["freq"])
                    if not dt:
                        continue
                    norm = normalize_date(dt, cfg["freq"])
                    out.append(DataPoint(
                        indicator=cfg["indicator"],
                        country="ES",
                        date=norm,
                        value=float(val) * cfg["conversion"],
                        source="ine_es",
                        unit=cfg["unit"],
                        series_id=f"INE:{cfg['cod']}",
                        adjustment=cfg["adjustment"],
                    ))
                print(f"  OK {cfg['indicator']}/ES (COD {cfg['cod']}): {len(obs_list)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['indicator']}/ES (COD {cfg['cod']}): {e}")
        return out


def run():
    p = IneEsProvider()
    print(f"Fetching from {p.display_name}...")
    try:
        pts = p.fetch()
        print(f"\nTotal: {len(pts)} data points")
        rows = datapoints_to_rows(pts)
        total = 0
        for i in range(0, len(rows), 500):
            count = upsert_data_points(rows[i:i+500])
            total += count
        log_pipeline_run("ine_es", "success", total)
        print(f"\nDone. {total} rows upserted.")
    except Exception as e:
        log_pipeline_run("ine_es", "failed", error_message=str(e))
        print(f"\nFailed: {e}")
        raise


if __name__ == "__main__":
    run()
