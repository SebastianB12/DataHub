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

# SERIES entries support two forms:
#   1. "dataflow": curated short ID resolved server-side via the /all/ALL path
#      (used for the legacy curated CPI/PPI/IND/etc. flows).
#   2. "dataflow_full" + "filter_key": full Esploradati SDMX dataflow ID with a
#      key-path filter (positional SDMX dimensions, dot-separated). This narrows
#      the response so large flows like the confidence indicators stay fast.
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
    # Consumer confidence — raw climate dataflow; only COF_21_WE.N is currently
    # published (weighted-estimate raw, base 2021=100). FIDCONS_10 SA stops at 2020.
    {"slug": "consumer-confidence",   "dataflow_full": "30_264_DF_DCSC_FIDCONS_1",
     "filter_key": "M.IT.COF_21_WE.N.....", "freq": "M", "unit": "Index (2021=100)",
     "adjustment": "NSA", "conversion": 1.0,
     "note": "ISTAT raw climate, consumer confidence indicator (COF_21_WE, weighted)"},
    # Business confidence (manufacturing) — SA climate dataflow (FIDIMPRMAN_17),
    # CLIMAMAN_21 with ADJUSTMENT=Y, NACE=C (manufacturing total), all firm sizes.
    {"slug": "business-confidence",   "dataflow_full": "111_263_DF_DCSC_FIDIMPRMAN_17",
     "filter_key": "M.IT.CLIMAMAN_21.Y.C.TOTAL", "freq": "M", "unit": "Index (2021=100)",
     "adjustment": "SA", "conversion": 1.0,
     "note": "ISTAT SA climate, mfg confidence (CLIMAMAN_21, NACE C)"},
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
    return _fetch_url(url, freq)


def _fetch_filtered(dataflow_full: str, filter_key: str, freq: str,
                    last_n: int = 360) -> list[tuple[date, float]]:
    """Fetch a single SDMX series via positional key-path filter.

    `filter_key` is the dot-separated SDMX key (e.g. ``M.IT.CLIMAMAN_21.Y.C.TOTAL``).
    Wildcards are empty between dots; trailing dots wildcard tail dimensions.
    """
    url = f"{BASE}/IT1,{dataflow_full},1.0/{filter_key}/ALL?lastNObservations={last_n}"
    return _fetch_url(url, freq)


def _fetch_url(url: str, freq: str) -> list[tuple[date, float]]:
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
            if "dataflow_full" in cfg:
                df_id = cfg["dataflow_full"]
                series_id = f"ISTAT/IT1,{df_id},1.0/{cfg['filter_key']}"
                fetcher = lambda c=cfg: _fetch_filtered(c["dataflow_full"], c["filter_key"], c["freq"])
            else:
                df_id = cfg["dataflow"]
                series_id = f"ISTAT/IT1,{df_id},1.0"
                fetcher = lambda c=cfg: _fetch(c["dataflow"], c["freq"])
            try:
                pairs = fetcher()
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"], country="IT",
                        date=normalize_date(dt, cfg["freq"]),
                        value=round(v * cfg["conversion"], 4),
                        source="istat",
                        unit=cfg["unit"],
                        series_id=series_id,
                        adjustment=cfg["adjustment"],
                    ))
                print(f"  OK {cfg['slug']}/IT (ISTAT {df_id}): {len(pairs)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['slug']}/IT (ISTAT {df_id}): {e}")
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
