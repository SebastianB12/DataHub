"""CZSO (Czech Statistical Office) direct provider.

Backend discovered via SPA reverse-engineering of data.czso.cz/datastat:
  assets/app.config.json points to data.csu.gov.cz/api/katalog/v1 (metadata)
  Public open-data CSV/JSON: https://data.csu.gov.cz/opendata/sady/{KOD}/distribuce/csv

Each dataset is a single CSV with:
  - one row per (indicator-code, dimension-combo, period)
  - period is in CASMKMQRM12/CASMKMQR/CASMQ/CASRQX/CASRMX columns
    (normal monthly: 'YYYY-MM'; quarterly: 'YYYY-Q#'; annual: 'YYYY'.
     'YYYY-MMK' is cumulation, 'YYYY-MM12' is rolling 12-month — we skip those.)

Datasets used (TE-source-conformant — TE shows "Czech Statistical Office"):
  CEN0101E  Index spotřebitelských cen — COICOP 2018, monthly index from 2015
  CEN0201A  Indexy cen průmyslových výrobců (PPI), monthly
  PRU01D    Index průmyslové produkce, monthly index (Bazický 2021=100)
  ZAM01     Zaměstnanost a nezaměstnanost (LFS), quarterly ILO unemployment rate

Filter codes:
  CPI   IndicatorType=6134, CZCOP1=0, CZCOP23='', EKAKTIOCDS=0, UZ02P=CZ,
        TYPUDAJE4A=IZ2025  -> base 2025=100 monthly index
  PPI   IndicatorType=6140, TYPUDAJE5=IZ2015, HPS=BTE36 (PRŮMYSL CELKEM), Uz0=CZ
  IP    IndicatorType=5249BI (Bazický 2021=100), NACE1=BCD (Průmysl celkem),
        NACE2='', Uz0=CZ
  UNE   IndicatorType=6290 (Obecná míra nezaměstnanosti %), POHL1=0 (Total),
        STAT=CZ, KRAJ='', period CASRQX = 'YYYY-Q#'
"""
import csv
import io
import os
import re
from datetime import date

import requests
from dotenv import load_dotenv

from pipeline.base_provider import BaseProvider, DataPoint
from pipeline.transforms import normalize_date
from pipeline.db import upsert_data_points, log_pipeline_run, datapoints_to_rows

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

BASE = "https://data.csu.gov.cz/opendata/sady"

HDR = {
    "User-Agent": "EconPulse/0.1 (Sebastian/SVM-AG)",
    "Accept": "text/csv,application/json",
}

MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")
QUARTER_RE = re.compile(r"^(\d{4})-Q([1-4])$")


def _fetch_csv(kod: str) -> list[dict]:
    """Stream a CZSO open-data CSV and return parsed rows."""
    url = f"{BASE}/{kod}/distribuce/csv"
    r = requests.get(url, headers=HDR, timeout=300, stream=True)
    r.raise_for_status()
    r.encoding = "utf-8"
    return list(csv.DictReader(io.StringIO(r.text)))


def _to_month_date(s: str) -> date | None:
    m = MONTH_RE.match(s)
    if not m:
        return None
    return date(int(m.group(1)), int(m.group(2)), 1)


def _to_quarter_date(s: str) -> date | None:
    m = QUARTER_RE.match(s)
    if not m:
        return None
    yy = int(m.group(1))
    q = int(m.group(2))
    return date(yy, {1: 1, 2: 4, 3: 7, 4: 10}[q], 1)


# === Filter functions ===

def fetch_cpi() -> list[tuple[date, float]]:
    """CEN0101E filtered to monthly all-items index, base 2025=100, CZ."""
    out = []
    for r in _fetch_csv("CEN0101E"):
        if (r.get("IndicatorType") == "6134"
                and r.get("CZCOICOP2.CZCOP1") == "0"
                and r.get("CZCOICOP2.CZCOP23") == ""
                and r.get("EKAKTIOCDS") == "0"
                and r.get("UZ02P") == "CZ"
                and r.get("TYPUDAJE4A") == "IZ2025"):
            dt = _to_month_date(r.get("CASMKMQRM12", ""))
            if dt is None:
                continue
            try:
                out.append((dt, float(r["Hodnota"])))
            except (TypeError, ValueError):
                continue
    return sorted(out)


def fetch_ppi() -> list[tuple[date, float]]:
    """CEN0201A — monthly PPI, base 2015=100, total industry BTE36, CZ."""
    out = []
    for r in _fetch_csv("CEN0201A"):
        if (r.get("IndicatorType") == "6140"
                and r.get("TYPUDAJE5") == "IZ2015"
                and r.get("HPS") == "BTE36"
                and r.get("Uz0") == "CZ"):
            dt = _to_month_date(r.get("CASMKMQR", ""))
            if dt is None:
                continue
            try:
                out.append((dt, float(r["Hodnota"])))
            except (TypeError, ValueError):
                continue
    return sorted(out)


def fetch_industrial_production() -> list[tuple[date, float]]:
    """PRU01D — monthly IP index, base 2021=100, total industry, CZ."""
    out = []
    for r in _fetch_csv("PRU01D"):
        if (r.get("IndicatorType") == "5249BI"
                and r.get("NACEIPP.NACE1") == "BCD"
                and r.get("NACEIPP.NACE2") == ""
                and r.get("Uz0") == "CZ"):
            dt = _to_month_date(r.get("CASMQ", ""))
            if dt is None:
                continue
            try:
                out.append((dt, float(r["Hodnota"])))
            except (TypeError, ValueError):
                continue
    return sorted(out)


def fetch_unemployment() -> list[tuple[date, float]]:
    """ZAM01 — quarterly ILO unemployment rate (%), age 15+, both genders, CZ."""
    out = []
    for r in _fetch_csv("ZAM01"):
        if (r.get("IndicatorType") == "6290"
                and r.get("POHL1") == "0"
                and r.get("Uz02h.STAT") == "CZ"
                and r.get("Uz02h.KRAJ") == ""):
            dt = _to_quarter_date(r.get("CASRQX", ""))
            if dt is None:
                continue
            try:
                out.append((dt, float(r["Hodnota"])))
            except (TypeError, ValueError):
                continue
    return sorted(out)


SERIES = [
    {"slug": "inflation-cpi",         "kod": "CEN0101E", "fetcher": fetch_cpi,
     "freq": "M", "unit": "Index (2025=100)",   "adjustment": "NSA",
     "note": "CZSO CEN0101E CPI total all-items index, base 2025=100"},
    {"slug": "ppi",                   "kod": "CEN0201A", "fetcher": fetch_ppi,
     "freq": "M", "unit": "Index (2015=100)",   "adjustment": "NSA",
     "note": "CZSO CEN0201A PPI total industry (BTE36), base 2015=100"},
    {"slug": "industrial-production", "kod": "PRU01D",   "fetcher": fetch_industrial_production,
     "freq": "M", "unit": "Index (2021=100)",   "adjustment": "NSA",
     "note": "CZSO PRU01D Industrial Production index, base 2021=100, total industry"},
    {"slug": "unemployment",          "kod": "ZAM01",    "fetcher": fetch_unemployment,
     "freq": "Q", "unit": "%",                  "adjustment": "NSA",
     "note": "CZSO ZAM01 ILO unemployment rate (Obecná míra nezaměstnanosti)"},
]


class CzsoProvider(BaseProvider):
    name = "czso"
    display_name = "Czech Statistical Office (CZSO)"

    def fetch(self) -> list[DataPoint]:
        out: list[DataPoint] = []
        for cfg in SERIES:
            try:
                pairs = cfg["fetcher"]()
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"], country="CZ",
                        date=normalize_date(dt, cfg["freq"]),
                        value=round(v, 4),
                        source="czso",
                        unit=cfg["unit"],
                        series_id=f"CZSO/{cfg['kod']}",
                        adjustment=cfg["adjustment"],
                    ))
                print(f"  OK {cfg['slug']}/CZ ({cfg['kod']}): {len(pairs)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['slug']}/CZ ({cfg['kod']}): {e}")
        return out


def run():
    p = CzsoProvider()
    print(f"Fetching from {p.display_name}...")
    try:
        pts = p.fetch()
        print(f"\nTotal: {len(pts)} data points")
        rows = datapoints_to_rows(pts)
        total = 0
        for i in range(0, len(rows), 500):
            count = upsert_data_points(rows[i:i+500])
            total += count
        log_pipeline_run("czso", "success", total)
        print(f"\nDone. {total} rows upserted.")
    except Exception as e:
        log_pipeline_run("czso", "failed", error_message=str(e))
        print(f"\nFailed: {e}")
        raise


if __name__ == "__main__":
    run()
