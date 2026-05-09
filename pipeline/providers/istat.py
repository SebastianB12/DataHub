"""ISTAT direct provider — modern Esploradati endpoint (post-2023 platform).

Uses esploradati.istat.it/SDMXWS/rest — the new SDMX REST web service that
replaced the legacy sdmx.istat.it endpoint (which had read timeouts on most
requests). The new endpoint is stable and returns fresh data.

Confirmed curated dataflows (IT1, all version 1.0):
  CPI    Consumer Price Index (PCPI_IX, base 2025=100, monthly)
  PPI    Producer Price Index (PPPI_IX, base 2021=100, monthly)
  IND    Industrial production index (AIP_SA_IX, SA, monthly)
  UEM    Unemployment (LU_PE_SA_NUM, thousand persons, quarterly)
  EMP    Employment (LE_PE_SA_NUM, thousand persons, quarterly)
  POP    Population (LP_PE_NUM, annual)
  WOE    Index of contractual hourly earnings (LCEAI_H_IX, monthly)

URL pattern:
  https://esploradati.istat.it/SDMXWS/rest/data/IT1,{DATAFLOW},1.0/all/ALL
  Accept: application/vnd.sdmx.data+csv;version=1.0.0

CSV schema:
  DATAFLOW,DATA_DOMAIN,REF_AREA,INDICATOR,COUNTERPART_AREA,FREQ,TIME_PERIOD,
  OBS_VALUE,COMMENT,BASE_PER,UNIT_MULT,OBS_STATUS,TIME_FORMAT
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

BASE = "https://esploradati.istat.it/SDMXWS/rest/data"

SERIES = [
    {"slug": "inflation-cpi",         "dataflow": "CPI", "freq": "M", "unit": "Index", "adjustment": "NSA",
     "conversion": 1.0, "note": "ISTAT modern Esploradati CPI (PCPI_IX, base 2025=100)"},
    {"slug": "ppi",                   "dataflow": "PPI", "freq": "M", "unit": "Index", "adjustment": "NSA",
     "conversion": 1.0, "note": "ISTAT modern Esploradati PPI (PPPI_IX, base 2021=100)"},
    {"slug": "industrial-production", "dataflow": "IND", "freq": "M", "unit": "Index", "adjustment": "SA",
     "conversion": 1.0, "note": "ISTAT modern Esploradati IP (AIP_SA_IX seasonally adjusted)"},
    {"slug": "unemployed-persons",    "dataflow": "UEM", "freq": "Q", "unit": "Thousand", "adjustment": "SA",
     "conversion": 1.0, "note": "ISTAT modern Esploradati Unemployed (LU_PE_SA_NUM)"},
    {"slug": "employed-persons",      "dataflow": "EMP", "freq": "Q", "unit": "Thousand", "adjustment": "SA",
     "conversion": 1.0, "note": "ISTAT modern Esploradati Employed (LE_PE_SA_NUM)"},
    {"slug": "population",            "dataflow": "POP", "freq": "A", "unit": "Million", "adjustment": "NSA",
     "conversion": 1e-6, "note": "ISTAT modern Esploradati Population (LP_PE_NUM)"},
]

HDR = {
    "Accept": "application/vnd.sdmx.data+csv;version=1.0.0",
    "User-Agent": "EconPulse/0.1 (Sebastian/SVM-AG)",
}


def _parse_period(p: str, freq: str) -> date | None:
    try:
        if freq == "M" and "-" in p:
            yy, mm = p.split("-")
            return date(int(yy), int(mm), 1)
        if freq == "Q" and "-Q" in p:
            yy, q = p.split("-Q")
            return date(int(yy), {"1":1,"2":4,"3":7,"4":10}[q], 1)
        if freq == "A" and len(p) == 4:
            return date(int(p), 1, 1)
    except Exception:
        pass
    return None


def _fetch(dataflow: str, freq: str) -> list[tuple[date, float]]:
    url = f"{BASE}/IT1,{dataflow},1.0/all/ALL"
    r = requests.get(url, headers=HDR, timeout=120)
    r.raise_for_status()
    reader = csv.DictReader(io.StringIO(r.text))
    out = []
    for row in reader:
        per = row.get("TIME_PERIOD", "")
        val = row.get("OBS_VALUE", "")
        if not per or not val:
            continue
        try:
            v = float(val)
        except ValueError:
            continue
        dt = _parse_period(per, freq)
        if dt:
            out.append((dt, v))
    return sorted(out)


class IstatProvider(BaseProvider):
    name = "istat"
    display_name = "ISTAT (Italy)"

    def fetch(self) -> list[DataPoint]:
        out: list[DataPoint] = []
        for cfg in SERIES:
            try:
                pairs = _fetch(cfg["dataflow"], cfg["freq"])
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"], country="IT",
                        date=normalize_date(dt, cfg["freq"]),
                        value=round(v * cfg["conversion"], 4),
                        source="istat",
                        unit=cfg["unit"],
                        series_id=f"ISTAT/IT1,{cfg['dataflow']},1.0",
                        adjustment=cfg["adjustment"],
                    ))
                print(f"  OK {cfg['slug']}/IT (ISTAT {cfg['dataflow']}): {len(pairs)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['slug']}/IT (ISTAT {cfg['dataflow']}): {e}")
        return out


def run():
    p = IstatProvider()
    print(f"Fetching from {p.display_name} (Esploradati)...")
    try:
        pts = p.fetch()
        print(f"\nTotal: {len(pts)} data points")
        rows = datapoints_to_rows(pts)
        total = 0
        for i in range(0, len(rows), 500):
            count = upsert_data_points(rows[i:i+500])
            total += count
        log_pipeline_run("istat", "success", total)
        print(f"\nDone. {total} rows upserted.")
    except Exception as e:
        log_pipeline_run("istat", "failed", error_message=str(e))
        print(f"\nFailed: {e}")
        raise


if __name__ == "__main__":
    run()
