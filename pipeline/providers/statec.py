"""STATEC direct provider — Luxembourg national statistics office.

Uses lustat.statec.lu/rest — STATEC's NSI Web Service v8.x (.Stat Suite SDMX REST,
same platform that ISTAT uses on esploradati.istat.it). All public dataflows under
the LU1 agency.

TE source attribution for Luxembourg confirmed STATEC (verified 2026-05-09):
  - inflation-cpi  -> https://tradingeconomics.com/luxembourg/inflation-cpi
  - ppi            -> https://tradingeconomics.com/luxembourg/producer-prices
  - unemployment   -> https://tradingeconomics.com/luxembourg/unemployment-rate
  - industrial-pr. -> https://tradingeconomics.com/luxembourg/industrial-production

Confirmed dataflows (LU1, version as noted):
  inflation-cpi          DSD_ECOICOP_PRIX@DF_E5405 v1.0  NCPI ECOICOP v.2 (CP00)  base 2025=100, monthly
                         -> 2026-04 = 102.65, YoY 3.07% (TE match)
  ppi                    DSD_PRIX_PPI@DF_D3202 v1.0      Industrial producer prices, total (_T)
                         BASE_PERIOD 2021, monthly -> 2026-03 = 121.48 (TE exact match)
  unemployment           DF_B3019 v1.0                   Employment/unemployment SA, SPECIFICATION C11
                         (unemployment rate %) -> 2026-03 = 6.35% (TE rounds to 6.3%)
  industrial-production  DF_D5110 v1.1                   Indices of industrial activity, MEASURE=PROD,
                         ACTIVITY=BTD (industries B-D), SEASONAL_ADJUST=W (working day adjusted),
                         BASE_PER 2021, monthly -> 2026-02 = 78.26 (Index)
  unemployed-persons     DF_B3019 SPECIFICATION C09 (number of unemployed SA, persons)
  employed-persons       DF_B3019 SPECIFICATION C08 (domestic employment SA, persons)
  population             DF_B1100 v1.0 SPECIFICATION C01 (total population habitual residence), annual

URL pattern:
  https://lustat.statec.lu/rest/data/LU1,{DATAFLOW},{VERSION}/all/ALL
  Accept: application/vnd.sdmx.data+csv;version=1.0.0
"""
import os
import csv
import io
from datetime import date

import requests
from dotenv import load_dotenv

from pipeline.base_provider import BaseProvider, DataPoint
from pipeline.transforms import normalize_date
from pipeline.db import upsert_data_points, log_pipeline_run, datapoints_to_rows

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

BASE = "https://lustat.statec.lu/rest/data"

HDR = {
    "Accept": "application/vnd.sdmx.data+csv;version=1.0.0",
    "User-Agent": "EconPulse/0.1 (Sebastian/SVM-AG)",
}

# Each series spec describes:
#  - dataflow: the SDMX dataflow id (with optional DSD@ prefix)
#  - version: dataflow version
#  - filter: dict {column: required_value} applied row-by-row to pick the correct slice
#  - freq: M / Q / A
#  - other metadata for DataPoint
SERIES = [
    {
        "slug": "inflation-cpi",
        "dataflow": "DSD_ECOICOP_PRIX@DF_E5405",
        "version": "1.0",
        "filter": {"FREQ": "M", "ECOICOP_2018": "CP00"},
        "freq": "M", "unit": "Index (2025=100)", "adjustment": "NSA", "conversion": 1.0,
        "note": "STATEC NCPI ECOICOP v.2 all-items (CP00), base 2025=100",
    },
    {
        "slug": "ppi",
        "dataflow": "DSD_PRIX_PPI@DF_D3202",
        "version": "1.0",
        # _T = Total industry, BASE_PERIOD 2021 (current series)
        "filter": {"FREQ": "M", "ACTIVITY": "_T", "BASE_PERIOD": "2021"},
        "freq": "M", "unit": "Index (2021=100)", "adjustment": "NSA", "conversion": 1.0,
        "note": "STATEC Industrial Producer Prices total (_T), base 2021=100",
    },
    {
        "slug": "unemployment",
        "dataflow": "DF_B3019",
        "version": "1.0",
        # C11 = Unemployment rate %, seasonally adjusted
        "filter": {"FREQ": "M", "SPECIFICATION": "C11"},
        "freq": "M", "unit": "%", "adjustment": "SA", "conversion": 1.0,
        "note": "STATEC unemployment rate, seasonally adjusted (B3019/C11)",
    },
    {
        "slug": "unemployed-persons",
        "dataflow": "DF_B3019",
        "version": "1.0",
        # C09 = Number of unemployed SA (persons); convert to thousands
        "filter": {"FREQ": "M", "SPECIFICATION": "C09"},
        "freq": "M", "unit": "Thousand", "adjustment": "SA", "conversion": 1e-3,
        "note": "STATEC number of unemployed SA (B3019/C09), persons -> thousands",
    },
    {
        "slug": "employed-persons",
        "dataflow": "DF_B3019",
        "version": "1.0",
        # C08 = Domestic employment SA (persons); convert to thousands
        "filter": {"FREQ": "M", "SPECIFICATION": "C08"},
        "freq": "M", "unit": "Thousand", "adjustment": "SA", "conversion": 1e-3,
        "note": "STATEC domestic employment SA (B3019/C08), persons -> thousands",
    },
    {
        "slug": "industrial-production",
        "dataflow": "DF_D5110",
        "version": "1.1",
        # PROD measure, BTD = industries B (mining) + C (manufacturing) + D (energy),
        # working-day adjusted (W) which STATEC publishes alongside NSA
        "filter": {"FREQ": "M", "MEASURE": "PROD", "ACTIVITY": "BTD",
                   "SEASONAL_ADJUST": "W", "BASE_PER": "2021"},
        "freq": "M", "unit": "Index (2021=100)", "adjustment": "WDA", "conversion": 1.0,
        "note": "STATEC Industrial Production index, total industry BTD, working-day adj.",
    },
    {
        "slug": "population",
        "dataflow": "DF_B1100",
        "version": "1.0",
        # C01 = Total population (habitual residence, both sexes, all nationalities)
        "filter": {"FREQ": "A", "SPECIFICATION": "C01"},
        "freq": "A", "unit": "Million", "adjustment": "NSA", "conversion": 1e-6,
        "note": "STATEC total resident population (B1100/C01), annual -> millions",
    },
]


def _parse_period(p: str, freq: str) -> date | None:
    """Parse SDMX TIME_PERIOD strings to a date.

    Handles:
      monthly: 2026-04
      quarterly: 2026-Q1
      annual: 2026 OR 2025-12-31 (B1100 emits ISO end-of-year)
    """
    try:
        if freq == "M" and "-" in p and len(p) == 7:
            yy, mm = p.split("-")
            return date(int(yy), int(mm), 1)
        if freq == "Q" and "-Q" in p:
            yy, q = p.split("-Q")
            return date(int(yy), {"1": 1, "2": 4, "3": 7, "4": 10}[q], 1)
        if freq == "A":
            # Either a 4-digit year or full ISO date YYYY-MM-DD
            if len(p) == 4 and p.isdigit():
                return date(int(p), 1, 1)
            if len(p) == 10 and p[4] == "-":
                yy, mm, dd = p.split("-")
                return date(int(yy), int(mm), int(dd))
    except Exception:
        return None
    return None


def _fetch_series(cfg: dict) -> list[tuple[date, float]]:
    url = f"{BASE}/LU1,{cfg['dataflow']},{cfg['version']}/all/ALL"
    r = requests.get(url, headers=HDR, timeout=180)
    r.raise_for_status()
    reader = csv.DictReader(io.StringIO(r.text))
    out = []
    flt = cfg["filter"]
    for row in reader:
        # Apply all filter conditions; reject row if any mismatch.
        match = True
        for k, v in flt.items():
            if row.get(k) != v:
                match = False
                break
        if not match:
            continue
        per = row.get("TIME_PERIOD", "")
        val = row.get("OBS_VALUE", "")
        if not per or val in ("", None):
            continue
        try:
            v = float(val)
        except ValueError:
            continue
        dt = _parse_period(per, cfg["freq"])
        if dt:
            out.append((dt, v))
    out.sort()
    return out


class StatecProvider(BaseProvider):
    name = "statec_lu"
    display_name = "STATEC (Luxembourg)"

    def fetch(self) -> list[DataPoint]:
        out: list[DataPoint] = []
        for cfg in SERIES:
            try:
                pairs = _fetch_series(cfg)
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"], country="LU",
                        date=normalize_date(dt, cfg["freq"]),
                        value=round(v * cfg["conversion"], 4),
                        source="statec_lu",
                        unit=cfg["unit"],
                        series_id=f"STATEC/LU1,{cfg['dataflow']},{cfg['version']}",
                        adjustment=cfg["adjustment"],
                    ))
                print(f"  OK {cfg['slug']}/LU (STATEC {cfg['dataflow']}): {len(pairs)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['slug']}/LU (STATEC {cfg['dataflow']}): {e}")
        return out


def run():
    p = StatecProvider()
    print(f"Fetching from {p.display_name} (lustat.statec.lu)...")
    try:
        pts = p.fetch()
        print(f"\nTotal: {len(pts)} data points")
        rows = datapoints_to_rows(pts)
        total = 0
        for i in range(0, len(rows), 500):
            count = upsert_data_points(rows[i:i + 500])
            total += count
        log_pipeline_run("statec_lu", "success", total)
        print(f"\nDone. {total} rows upserted.")
    except Exception as e:
        log_pipeline_run("statec_lu", "failed", error_message=str(e))
        print(f"\nFailed: {e}")
        raise


if __name__ == "__main__":
    run()
