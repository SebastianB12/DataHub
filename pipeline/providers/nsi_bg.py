"""NSI Bulgaria provider — direct SDMX-ML files via the Bulgarian National Bank
SDDS Plus dissemination endpoint (BNB hosts the standardised IMF-format SDMX
files on behalf of NSI as part of Bulgaria's Special Data Dissemination
Standard Plus participation).

Source label: ``nsi_bg`` — the data is **produced by NSI** (National Statistical
Institute, Bulgaria) for CPI / PPI / Employment, even though the file lives on
www.bnb.bg/bnbweb/groups/public/documents/bnb_sdmx/. TE attributes the same
indicators as "National Statistical Institute, Bulgaria".

Why this endpoint and not NSI's SDMX-RI directly?
  * www.nsi.bg/sdmxwebclient/ exposes only ~20 dataflows (Tourism, Agriculture,
    SBS, NA_MAIN) — no CPI, PPI, LFS dataflows are published.
  * www.nsi.bg/restsdmx/sdmx.ashx is behind an F5 WAF that rejects every
    GET/POST with "Request Rejected" (support ID).
  * BNB's bnb_sdmx/ directory hosts the canonical SDDS Plus SDMX-ML 2.1
    StructureSpecificData files: cpi.xml, ppi.xml, emp.xml, bop_bpm6.xml,
    cgo.xml. These are refreshed monthly and contain the full history.

Endpoint: https://www.bnb.bg/bnbweb/groups/public/documents/bnb_sdmx/<topic>.xml
Format:   SDMX-ML 2.1 StructureSpecific (IMF ECOFIN_DSD)
Auth:     none required

Verified 2026-05-09 (network test from this environment, public unauth):
  cpi.xml   PCPI_IX  M  base 2025=100   1995-01..2026-03   375 obs
  ppi.xml   PPPI_IX  M  base 2021=100   2005-01..2026-03   255 obs
  emp.xml   LE_PE_NUM Q (UNIT_MULT=3, thousand persons)    2010-Q1..2025-Q4   64 obs
"""
import os
import re
from datetime import date

import requests
from dotenv import load_dotenv

from pipeline.base_provider import BaseProvider, DataPoint
from pipeline.transforms import normalize_date
from pipeline.db import upsert_data_points, log_pipeline_run, datapoints_to_rows

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

BASE = "https://www.bnb.bg/bnbweb/groups/public/documents/bnb_sdmx"

HDR = {
    "User-Agent": "EconPulse/0.1 (Sebastian/SVM-AG)",
    "Accept": "application/xml, text/xml",
}

# series mapping
SERIES = [
    {
        "slug": "inflation-cpi", "topic": "cpi", "freq": "M",
        "indicator_id": "PCPI_IX",
        "unit": "Index (2025=100)",
        "adjustment": "NSA",
        "conversion": 1.0,
        "note": "NSI Bulgaria CPI (PCPI_IX) base 2025=100, monthly, via BNB SDDS Plus SDMX",
    },
    {
        "slug": "ppi", "topic": "ppi", "freq": "M",
        "indicator_id": "PPPI_IX",
        "unit": "Index (2021=100)",
        "adjustment": "NSA",
        "conversion": 1.0,
        "note": "NSI Bulgaria PPI (PPPI_IX) base 2021=100, monthly, via BNB SDDS Plus SDMX",
    },
    {
        "slug": "employed-persons", "topic": "emp", "freq": "Q",
        "indicator_id": "LE_PE_NUM",
        "unit": "Thousand",
        "adjustment": "NSA",
        # SDMX UNIT_MULT="3" => 1e3 already-thousands. Values in file ~2800 = thousand persons.
        "conversion": 1.0,
        "note": "NSI Bulgaria Employed Persons (LE_PE_NUM), thousand persons, quarterly (NA basis), via BNB SDDS Plus SDMX",
    },
]


def _parse_period(p: str, freq: str) -> date | None:
    try:
        if freq == "M":
            yy, mm = p.split("-")
            return date(int(yy), int(mm), 1)
        if freq == "Q":
            # SDMX-ML format "2025-Q4"
            yy, q = p.split("-Q")
            return date(int(yy), {"1": 1, "2": 4, "3": 7, "4": 10}[q], 1)
        if freq == "A" and len(p) == 4:
            return date(int(p), 1, 1)
    except Exception:
        return None
    return None


def _fetch_topic(topic: str, freq: str) -> list[tuple[date, float]]:
    """Download the SDMX-ML StructureSpecific file and return (date, value) pairs.

    The file uses message:DataSet > Series > Obs. We extract the first Series
    block (each topic file contains exactly one series) and its observations.
    """
    url = f"{BASE}/{topic}.xml"
    r = requests.get(url, headers=HDR, timeout=60)
    r.raise_for_status()
    xml = r.text
    # parse all <Obs TIME_PERIOD="..." OBS_VALUE="..." ...>
    obs = re.findall(
        r'<Obs\s+TIME_PERIOD="([^"]+)"\s+OBS_VALUE="([^"]+)"',
        xml,
    )
    out: list[tuple[date, float]] = []
    for per, val in obs:
        dt = _parse_period(per, freq)
        if dt is None:
            continue
        try:
            v = float(val)
        except ValueError:
            continue
        out.append((dt, v))
    return sorted(out)


class NsiBgProvider(BaseProvider):
    name = "nsi_bg"
    display_name = "NSI Bulgaria (via BNB SDDS Plus SDMX)"

    def fetch(self) -> list[DataPoint]:
        out: list[DataPoint] = []
        for cfg in SERIES:
            try:
                pairs = _fetch_topic(cfg["topic"], cfg["freq"])
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"],
                        country="BG",
                        date=normalize_date(dt, cfg["freq"]),
                        value=round(v * cfg["conversion"], 4),
                        source="nsi_bg",
                        unit=cfg["unit"],
                        series_id=f"NSI-BG/{cfg['indicator_id']}",
                        adjustment=cfg["adjustment"],
                    ))
                print(f"  OK {cfg['slug']}/BG ({cfg['indicator_id']}): {len(pairs)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['slug']}/BG ({cfg['indicator_id']}): {e}")
        return out


def run():
    p = NsiBgProvider()
    print(f"Fetching from {p.display_name}...")
    try:
        pts = p.fetch()
        print(f"\nTotal: {len(pts)} data points")
        rows = datapoints_to_rows(pts)
        total = 0
        for i in range(0, len(rows), 500):
            count = upsert_data_points(rows[i:i+500])
            total += count
        log_pipeline_run("nsi_bg", "success", total)
        print(f"\nDone. {total} rows upserted.")
    except Exception as e:
        log_pipeline_run("nsi_bg", "failed", error_message=str(e))
        print(f"\nFailed: {e}")
        raise


if __name__ == "__main__":
    run()
