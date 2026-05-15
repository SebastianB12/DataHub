"""NSI Bulgaria provider — direct SDMX-ML files via the Bulgarian National Bank
SDDS Plus dissemination endpoint (BNB hosts the standardised IMF-format SDMX
files on behalf of NSI as part of Bulgaria's Special Data Dissemination
Standard Plus participation).

Source label: ``nsi_bg`` — the data is **produced by NSI** (National Statistical
Institute, Bulgaria) for CPI / PPI / Employment / National Accounts / Industrial
production. BoP series come from BNB (Bulgarian National Bank). TE attributes
the same indicators as "National Statistical Institute, Bulgaria" or
"Bulgarian National Bank".

Why this endpoint and not NSI's SDMX-RI directly?
  * www.nsi.bg/sdmxwebclient/ exposes only ~20 dataflows (Tourism, Agriculture,
    SBS, NA_MAIN) — no CPI, PPI, LFS dataflows are published.
  * www.nsi.bg/restsdmx/sdmx.ashx is behind an F5 WAF that rejects every
    GET/POST with "Request Rejected" (support ID).
  * BNB's bnb_sdmx/ directory hosts the canonical SDDS Plus SDMX-ML 2.1
    StructureSpecificData files: cpi.xml, ppi.xml, emp.xml, nag.xml, ind.xml,
    bop_bpm6.xml, cgo.xml. These are refreshed monthly and contain the full
    history.

Endpoint: https://www.bnb.bg/bnbweb/groups/public/documents/bnb_sdmx/<topic>.xml
Format:   SDMX-ML 2.1 StructureSpecific (IMF ECOFIN_DSD / ESTAT NA_MAIN / IMF BOP)
Auth:     none required

Verified 2026-05-09 (network test from this environment, public unauth):
  cpi.xml      PCPI_IX   M  base 2025=100   1995-01..2026-03   375 obs
  ppi.xml      PPPI_IX   M  base 2021=100   2005-01..2026-03   255 obs
  emp.xml      LE_PE_NUM Q  thousand persons 2010-Q1..2025-Q4    64 obs
  ind.xml      AIP_IX    M  base 2021=100   2000-01..2026-03   315 obs
  nag.xml      NA_MAIN   Q  mln BGN          2000-Q1..2025-Q4   104 obs/series
  bop_bpm6.xml BOP       M  mln EUR         2007-01..2026-02   230 obs/series

Quarterly NAG series are in BGN millions (UNIT_MULT=6, UNIT_MEASURE=XDC).
BOP series are in EUR millions (UNIT_MULT=6, UNIT_MEASURE=EUR).
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

# Simple single-series files (one Series block per .xml)
SIMPLE_SERIES = [
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
        "conversion": 1.0,
        "note": "NSI Bulgaria Employed Persons (LE_PE_NUM), thousand persons, quarterly (NA basis), via BNB SDDS Plus SDMX",
    },
    {
        "slug": "industrial-production", "topic": "ind", "freq": "M",
        "indicator_id": "AIP_IX",
        "unit": "Index (2021=100)",
        "adjustment": "NSA",
        "conversion": 1.0,
        "note": "NSI Bulgaria Industrial Production Index (AIP_IX) base 2021=100, monthly, via BNB SDDS Plus SDMX",
    },
]

# NAG (National Accounts) — multi-series file. Match Series by STO/PRICES/ACTIVITY/REF_SECTOR.
# UNIT_MEASURE=XDC (BGN), UNIT_MULT=6 (mln). Quarterly, current prices (PRICES=V) or
# chain-linked volumes (PRICES=Y, reference year 2020).
# Bulgaria's official currency is BGN (pegged 1.95583 BGN = 1 EUR).
NAG_SERIES = [
    # GDP — chain-linked volumes (B1GQ, PRICES=Y), reference year 2020.
    # TE prints gdp-real as YoY% rate; the level is published here and the frontend
    # computes YoY on-the-fly. Last obs 2025-Q4 = 31,096.22 mln BGN chain-linked.
    {"slug": "gdp-real", "match": {"STO": "B1GQ", "PRICES": "Y"},
     "unit": "Million BGN (chain-linked, 2020 prices)", "adjustment": "NSA", "conversion": 1.0,
     "note": "NSI Bulgaria NAG B1GQ Gross domestic product chain-linked volumes (ref. 2020), quarterly, mln BGN"},
    # Household final consumption expenditure (P31, sector S1M)
    {"slug": "consumer-spending", "match": {"STO": "P31", "PRICES": "V", "REF_SECTOR": "S1M"},
     "unit": "Million BGN", "adjustment": "NSA", "conversion": 1.0,
     "note": "NSI Bulgaria NAG P31 Household final consumption expenditure (current prices, mln BGN)"},
    # Government final consumption expenditure (P3, sector S13)
    {"slug": "government-spending", "match": {"STO": "P3", "PRICES": "V", "REF_SECTOR": "S13"},
     "unit": "Million BGN", "adjustment": "NSA", "conversion": 1.0,
     "note": "NSI Bulgaria NAG P3 General-government final consumption expenditure (current prices, mln BGN)"},
    # Gross fixed capital formation (P51G)
    {"slug": "gross-fixed-capital-formation", "match": {"STO": "P51G", "PRICES": "V"},
     "unit": "Million BGN", "adjustment": "NSA", "conversion": 1.0,
     "note": "NSI Bulgaria NAG P51G Gross fixed capital formation (current prices, mln BGN)"},
    # Changes in inventories (P5M)
    {"slug": "changes-in-inventories", "match": {"STO": "P5M", "PRICES": "V"},
     "unit": "Million BGN", "adjustment": "NSA", "conversion": 1.0,
     "note": "NSI Bulgaria NAG P5M Changes in inventories (current prices, mln BGN)"},
    # Exports of goods + services (P6)
    {"slug": "exports", "match": {"STO": "P6", "PRICES": "V"},
     "unit": "Million BGN", "adjustment": "NSA", "conversion": 1.0,
     "note": "NSI Bulgaria NAG P6 Exports of goods and services (current prices, mln BGN)"},
    # Imports of goods + services (P7)
    {"slug": "imports", "match": {"STO": "P7", "PRICES": "V"},
     "unit": "Million BGN", "adjustment": "NSA", "conversion": 1.0,
     "note": "NSI Bulgaria NAG P7 Imports of goods and services (current prices, mln BGN)"},
]

# BOP_BPM6 — multi-series file. Match by INT_ACC_ITEM + ACCOUNTING_ENTRY.
# Source: Bulgarian National Bank (BNB). UNIT_MEASURE=EUR, UNIT_MULT=6 -> mln EUR.
BOP_SERIES = [
    # Current account balance (CA, accounting entry B = balance)
    {"slug": "current-account", "match": {"INT_ACC_ITEM": "CA", "ACCOUNTING_ENTRY": "B"},
     "unit": "Million EUR", "adjustment": "NSA", "conversion": 1.0,
     "note": "BNB Bulgaria BOP BPM6 Current account balance (mln EUR, vis-à-vis World)"},
]

# CGO — Central Government Operations (cash basis). Single-INDICATOR series.
# UNIT_MEASURE=XDC (BGN), UNIT_MULT=6 -> mln BGN. Monthly.
# Maps via INDICATOR attribute. TE budget-deficit slug is the cash net lending/
# borrowing position (GBXCCB = Central Government Cash Balance).
CGO_SERIES = [
    {"slug": "budget-deficit", "match": {"INDICATOR": "GBXCCB_G01_CA_XDC"},
     "unit": "Million BGN", "adjustment": "NSA", "conversion": 1.0,
     "note": "BNB/Bulgaria CGO Central Government Cash Balance (GBXCCB) monthly, mln BGN — TE budget-deficit"},
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


def _fetch_xml(topic: str) -> str:
    url = f"{BASE}/{topic}.xml"
    r = requests.get(url, headers=HDR, timeout=60)
    r.raise_for_status()
    return r.text


def _fetch_simple(topic: str, freq: str) -> list[tuple[date, float]]:
    """Download single-series SDMX-ML file (cpi/ppi/emp/ind) and return obs."""
    xml = _fetch_xml(topic)
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


def _fetch_multi(topic: str, match: dict, freq: str) -> list[tuple[date, float]]:
    """Download multi-series SDMX-ML file and return obs from the first Series
    block whose attributes match every key/value in ``match``."""
    xml = _fetch_xml(topic)
    blocks = re.findall(r'<Series ([^>]+)>(.*?)</Series>', xml, flags=re.S)
    for attrs, body in blocks:
        ok = True
        for k, v in match.items():
            m = re.search(rf'{k}="([^"]+)"', attrs)
            if not m or m.group(1) != v:
                ok = False
                break
        if not ok:
            continue
        obs = re.findall(
            r'TIME_PERIOD="([^"]+)"\s+OBS_VALUE="([^"]+)"',
            body,
        )
        out: list[tuple[date, float]] = []
        for per, val in obs:
            dt = _parse_period(per, freq)
            if dt is None:
                continue
            try:
                fv = float(val)
            except ValueError:
                continue
            out.append((dt, fv))
        return sorted(out)
    # No matching series block
    return []


class NsiBgProvider(BaseProvider):
    name = "nsi_bg"
    display_name = "NSI Bulgaria (via BNB SDDS Plus SDMX)"

    def fetch(self) -> list[DataPoint]:
        out: list[DataPoint] = []
        # Simple single-series files
        for cfg in SIMPLE_SERIES:
            try:
                pairs = _fetch_simple(cfg["topic"], cfg["freq"])
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

        # NAG multi-series file (quarterly national accounts)
        for cfg in NAG_SERIES:
            try:
                pairs = _fetch_multi("nag", cfg["match"], "Q")
                tag = "/".join(f"{k}={v}" for k, v in cfg["match"].items())
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"],
                        country="BG",
                        date=normalize_date(dt, "Q"),
                        value=round(v * cfg["conversion"], 4),
                        source="nsi_bg",
                        unit=cfg["unit"],
                        series_id=f"NSI-BG/NAG/{cfg['match'].get('STO','?')}",
                        adjustment=cfg["adjustment"],
                    ))
                print(f"  OK {cfg['slug']}/BG (NAG {tag}): {len(pairs)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['slug']}/BG (NAG): {e}")

        # CGO multi-series file (monthly central government operations, mln BGN)
        for cfg in CGO_SERIES:
            try:
                pairs = _fetch_multi("cgo", cfg["match"], "M")
                tag = "/".join(f"{k}={v}" for k, v in cfg["match"].items())
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"],
                        country="BG",
                        date=normalize_date(dt, "M"),
                        value=round(v * cfg["conversion"], 4),
                        source="nsi_bg",
                        unit=cfg["unit"],
                        series_id=f"NSI-BG/CGO/{cfg['match'].get('INDICATOR','?')}",
                        adjustment=cfg["adjustment"],
                    ))
                print(f"  OK {cfg['slug']}/BG (CGO {tag}): {len(pairs)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['slug']}/BG (CGO): {e}")

        # BOP_BPM6 multi-series file (monthly balance of payments, BNB)
        for cfg in BOP_SERIES:
            try:
                pairs = _fetch_multi("bop_bpm6", cfg["match"], "M")
                tag = "/".join(f"{k}={v}" for k, v in cfg["match"].items())
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"],
                        country="BG",
                        date=normalize_date(dt, "M"),
                        value=round(v * cfg["conversion"], 4),
                        source="nsi_bg",
                        unit=cfg["unit"],
                        series_id=f"NSI-BG/BOP/{cfg['match'].get('INT_ACC_ITEM','?')}_{cfg['match'].get('ACCOUNTING_ENTRY','?')}",
                        adjustment=cfg["adjustment"],
                    ))
                print(f"  OK {cfg['slug']}/BG (BOP {tag}): {len(pairs)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['slug']}/BG (BOP): {e}")

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
