"""CZSO (Czech Statistical Office) direct provider.

Backend: data.csu.gov.cz/opendata/sady/{KOD}/distribuce/csv (open-data CSV).

Datasets used:
  CEN0101E  Index spotřebitelských cen (CPI) — monthly index, COICOP-2018 (CP01-13)
  CEN0201A  Indexy cen průmyslových výrobců (PPI) — monthly
  PRU01D    Index průmyslové produkce — monthly, NACE B/C/D
  ZAM01     Zaměstnanost a nezaměstnanost (LFS) — quarterly
  NEZ01     Registrovaná nezaměstnanost — annual (skip; eurostat fallback)
  KPR1      Bazický indeks salda indikátoru důvěry — monthly base 2005=100
  OBC01     Index tržeb v maloobchodě — monthly
  NUC06Q    Hlavní souhrnné ukazatele HDP — quarterly mil. Kč
  WNUC03A   Roční národní účty — annual mil. Kč
  WNUC05D   Vládní finanční statistika — annual
"""
import csv
import io
import os
import re
import time
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
YEAR_RE = re.compile(r"^(\d{4})$")

_CSV_CACHE: dict[str, list[dict]] = {}


def _fetch_csv(kod: str) -> list[dict]:
    """Stream a CZSO open-data CSV (with in-memory cache)."""
    if kod in _CSV_CACHE:
        return _CSV_CACHE[kod]
    url = f"{BASE}/{kod}/distribuce/csv"
    r = requests.get(url, headers=HDR, timeout=300, stream=True)
    r.raise_for_status()
    r.encoding = "utf-8"
    rows = list(csv.DictReader(io.StringIO(r.text)))
    _CSV_CACHE[kod] = rows
    time.sleep(1.0)  # be polite
    return rows


def _to_month_date(s: str) -> date | None:
    m = MONTH_RE.match(s or "")
    if not m:
        return None
    return date(int(m.group(1)), int(m.group(2)), 1)


def _to_quarter_date(s: str) -> date | None:
    m = QUARTER_RE.match(s or "")
    if not m:
        return None
    yy = int(m.group(1))
    q = int(m.group(2))
    return date(yy, {1: 1, 2: 4, 3: 7, 4: 10}[q], 1)


def _to_year_date(s: str) -> date | None:
    m = YEAR_RE.match(s or "")
    if not m:
        return None
    return date(int(m.group(1)), 1, 1)


def _flt(v: str) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# === CPI ===

def fetch_cpi() -> list[tuple[date, float]]:
    """CEN0101E: monthly all-items CPI, base 2025=100, CZ."""
    out: list[tuple[date, float]] = []
    for r in _fetch_csv("CEN0101E"):
        if (r.get("IndicatorType") == "6134"
                and r.get("CZCOICOP2.CZCOP1") == "0"
                and r.get("CZCOICOP2.CZCOP23") == ""
                and r.get("EKAKTIOCDS") == "0"
                and r.get("UZ02P") == "CZ"
                and r.get("TYPUDAJE4A") == "IZ2025"):
            dt = _to_month_date(r.get("CASMKMQRM12", ""))
            v = _flt(r.get("Hodnota", ""))
            if dt and v is not None:
                out.append((dt, v))
    return sorted(out)


def _fetch_cpi_subcomponent(coicop_code: str) -> list[tuple[date, float]]:
    """CEN0101E filtered to one COICOP-2018 top-level division (01..13)."""
    out: list[tuple[date, float]] = []
    for r in _fetch_csv("CEN0101E"):
        if (r.get("IndicatorType") == "6134"
                and r.get("CZCOICOP2.CZCOP1") == coicop_code
                and r.get("CZCOICOP2.CZCOP23") == ""
                and r.get("EKAKTIOCDS") == "0"
                and r.get("UZ02P") == "CZ"
                and r.get("TYPUDAJE4A") == "IZ2025"):
            dt = _to_month_date(r.get("CASMKMQRM12", ""))
            v = _flt(r.get("Hodnota", ""))
            if dt and v is not None:
                out.append((dt, v))
    return sorted(out)


# === PPI ===

def fetch_ppi() -> list[tuple[date, float]]:
    out: list[tuple[date, float]] = []
    for r in _fetch_csv("CEN0201A"):
        if (r.get("IndicatorType") == "6140"
                and r.get("TYPUDAJE5") == "IZ2015"
                and r.get("HPS") == "BTE36"
                and r.get("Uz0") == "CZ"):
            dt = _to_month_date(r.get("CASMKMQR", ""))
            v = _flt(r.get("Hodnota", ""))
            if dt and v is not None:
                out.append((dt, v))
    return sorted(out)


# === Industrial production / mining / manufacturing (PRU01D) ===

def _fetch_pru01d_nace(nace1: str) -> list[tuple[date, float]]:
    """PRU01D — monthly index, base 2021=100, given NACE-section code (B,C,D, or BCD)."""
    out: list[tuple[date, float]] = []
    for r in _fetch_csv("PRU01D"):
        if (r.get("IndicatorType") == "5249BI"
                and r.get("NACEIPP.NACE1") == nace1
                and r.get("NACEIPP.NACE2") == ""
                and r.get("Uz0") == "CZ"):
            dt = _to_month_date(r.get("CASMQ", ""))
            v = _flt(r.get("Hodnota", ""))
            if dt and v is not None:
                out.append((dt, v))
    return sorted(out)


def fetch_industrial_production() -> list[tuple[date, float]]:
    return _fetch_pru01d_nace("BCD")


def fetch_mining_production() -> list[tuple[date, float]]:
    return _fetch_pru01d_nace("B")


def fetch_manufacturing_production() -> list[tuple[date, float]]:
    return _fetch_pru01d_nace("C")


# === Labour: ZAM01 ===

def _fetch_zam01(indicator_type: str) -> list[tuple[date, float]]:
    out: list[tuple[date, float]] = []
    for r in _fetch_csv("ZAM01"):
        if (r.get("IndicatorType") == indicator_type
                and r.get("POHL1") == "0"
                and r.get("Uz02h.STAT") == "CZ"
                and r.get("Uz02h.KRAJ") == ""):
            dt = _to_quarter_date(r.get("CASRQX", ""))
            v = _flt(r.get("Hodnota", ""))
            if dt and v is not None:
                out.append((dt, v))
    return sorted(out)


def fetch_unemployment_rate() -> list[tuple[date, float]]:
    """ZAM01 6290 — quarterly ILO unemployment rate %, age 15+, both genders, CZ."""
    return _fetch_zam01("6290")


def fetch_employed_persons() -> list[tuple[date, float]]:
    """ZAM01 6285Z — quarterly Employed persons (thousand persons)."""
    return _fetch_zam01("6285Z")


def fetch_unemployed_persons() -> list[tuple[date, float]]:
    """ZAM01 6284 — quarterly Unemployed persons (thousand persons)."""
    return _fetch_zam01("6284")


# === Confidence (KPR1) ===

def _fetch_kpr1(indicator_type: str) -> list[tuple[date, float]]:
    out: list[tuple[date, float]] = []
    for r in _fetch_csv("KPR1"):
        if r.get("IndicatorType") == indicator_type and r.get("Uz0") == "CZ":
            dt = _to_month_date(r.get("CasM", ""))
            v = _flt(r.get("Hodnota", ""))
            if dt and v is not None:
                out.append((dt, v))
    return sorted(out)


def fetch_business_confidence() -> list[tuple[date, float]]:
    """KPR1 5865 — monthly business confidence (Podnikatelé), base index."""
    return _fetch_kpr1("5865")


def fetch_consumer_confidence() -> list[tuple[date, float]]:
    """KPR1 5866 — monthly consumer confidence (Spotřebitelé), base index."""
    return _fetch_kpr1("5866")


# === Retail (OBC01) ===

def fetch_retail_sales() -> list[tuple[date, float]]:
    """OBC01 — monthly retail sales YoY index, NACE 47, constant prices, NSA."""
    out: list[tuple[date, float]] = []
    for r in _fetch_csv("OBC01"):
        if (r.get("Uz0") == "CZ"
                and r.get("CZNACEOB") == "47"
                and r.get("TYPCENA") == "P"
                and r.get("OCIST") == "0"
                and r.get("TYPUDAJVM") == "IR"
                and r.get("CASRQM.CAS_M", "")):
            dt = _to_month_date(r.get("CASRQM.CAS_M", ""))
            v = _flt(r.get("Hodnota", ""))
            if dt and v is not None:
                out.append((dt, v))
    return sorted(out)


# === NUC06Q (quarterly GDP components, current prices, mil Kč) ===

def _fetch_nuc06q(indicator_type: str) -> list[tuple[date, float]]:
    out: list[tuple[date, float]] = []
    for r in _fetch_csv("NUC06Q"):
        if (r.get("IndicatorType") == indicator_type
                and r.get("Uz0") == "CZ"
                and r.get("NACEHDPQ", "0") in ("0", "")):
            dt = _to_quarter_date(r.get("CasQ", ""))
            v = _flt(r.get("Hodnota", ""))
            if dt and v is not None:
                out.append((dt, v))
    return sorted(out)


def fetch_consumer_spending() -> list[tuple[date, float]]:
    """NUC06Q 10000DOM — Final consumption expenditure of households, current prices, mil. Kč."""
    return _fetch_nuc06q("10000DOM")


def fetch_gfcf() -> list[tuple[date, float]]:
    """NUC06Q 9991BC — Gross fixed capital formation, current prices, mil. Kč."""
    return _fetch_nuc06q("9991BC")


# === Government finance (WNUC05D, annual) ===

def fetch_government_debt() -> list[tuple[date, float]]:
    """WNUC05D 600602 — Annual general government gross consolidated debt, mil. Kč."""
    out: list[tuple[date, float]] = []
    for r in _fetch_csv("WNUC05D"):
        if r.get("IndicatorType") == "600602" and r.get("Uz0") == "CZ":
            dt = _to_year_date(r.get("CasR", ""))
            v = _flt(r.get("Hodnota", ""))
            if dt and v is not None:
                out.append((dt, v))
    return sorted(out)


def fetch_gdp_real_yoy() -> list[tuple[date, float]]:
    """WNUC01D 9988J10 — Quarterly real GDP, SA, YoY % change."""
    out: list[tuple[date, float]] = []
    for r in _fetch_csv("WNUC01D"):
        if r.get("IndicatorType") == "9988J10" and r.get("Uz0") == "CZ":
            dt = _to_quarter_date(r.get("CasQ", ""))
            v = _flt(r.get("Hodnota", ""))
            if dt and v is not None:
                out.append((dt, v))
    return sorted(out)


# === Series registry ===

SERIES = [
    # Existing
    {"slug": "inflation-cpi",         "kod": "CEN0101E", "fetcher": fetch_cpi,
     "freq": "M", "unit": "Index (2025=100)",   "adjustment": "NSA",
     "series_id": "CZSO/CEN0101E",
     "note": "CZSO CEN0101E CPI total all-items index, base 2025=100"},
    {"slug": "ppi",                   "kod": "CEN0201A", "fetcher": fetch_ppi,
     "freq": "M", "unit": "Index (2015=100)",   "adjustment": "NSA",
     "series_id": "CZSO/CEN0201A",
     "note": "CZSO CEN0201A PPI total industry (BTE36), base 2015=100"},
    {"slug": "industrial-production", "kod": "PRU01D",   "fetcher": fetch_industrial_production,
     "freq": "M", "unit": "Index (2021=100)",   "adjustment": "NSA",
     "series_id": "CZSO/PRU01D/BCD",
     "note": "CZSO PRU01D Industrial Production index, base 2021=100, total industry"},
    {"slug": "unemployment",          "kod": "ZAM01",    "fetcher": fetch_unemployment_rate,
     "freq": "Q", "unit": "%",                  "adjustment": "NSA",
     "series_id": "CZSO/ZAM01/6290",
     "note": "CZSO ZAM01 ILO unemployment rate (Obecná míra nezaměstnanosti)"},
    # === NEW (038_cz_gapfill) ===
    {"slug": "business-confidence", "kod": "KPR1", "fetcher": fetch_business_confidence,
     "freq": "M", "unit": "Index (2005=100)", "adjustment": "SA",
     "series_id": "CZSO/KPR1/5865",
     "note": "CZSO KPR1 Business confidence (Podnikatelé) bazický index"},
    {"slug": "consumer-confidence", "kod": "KPR1", "fetcher": fetch_consumer_confidence,
     "freq": "M", "unit": "Index (2005=100)", "adjustment": "SA",
     "series_id": "CZSO/KPR1/5866",
     "note": "CZSO KPR1 Consumer confidence (Spotřebitelé) bazický index"},
    {"slug": "consumer-spending", "kod": "NUC06Q", "fetcher": fetch_consumer_spending,
     "freq": "Q", "unit": "mil Kc", "adjustment": "NSA",
     "series_id": "CZSO/NUC06Q/10000DOM",
     "note": "CZSO NUC06Q Final consumption of households, current prices, mil. Kc, quarterly"},
    {"slug": "gross-fixed-capital-formation", "kod": "NUC06Q", "fetcher": fetch_gfcf,
     "freq": "Q", "unit": "mil Kc", "adjustment": "NSA",
     "series_id": "CZSO/NUC06Q/9991BC",
     "note": "CZSO NUC06Q Gross fixed capital formation, current prices, mil. Kc, quarterly"},
    {"slug": "employed-persons", "kod": "ZAM01", "fetcher": fetch_employed_persons,
     "freq": "Q", "unit": "thousand persons", "adjustment": "NSA",
     "series_id": "CZSO/ZAM01/6285Z",
     "note": "CZSO ZAM01 Employed persons (Zaměstnaní), tis. osob, quarterly"},
    {"slug": "unemployed-persons", "kod": "ZAM01", "fetcher": fetch_unemployed_persons,
     "freq": "Q", "unit": "thousand persons", "adjustment": "NSA",
     "series_id": "CZSO/ZAM01/6284",
     "note": "CZSO ZAM01 Unemployed persons (Nezaměstnaní), tis. osob, quarterly"},
    {"slug": "retail-sales", "kod": "OBC01", "fetcher": fetch_retail_sales,
     "freq": "M", "unit": "Index (previous year=100, constant prices)", "adjustment": "NSA",
     "series_id": "CZSO/OBC01/47",
     "note": "CZSO OBC01 Retail sales NACE 47, constant prices, YoY index, NSA"},
    {"slug": "mining-production", "kod": "PRU01D", "fetcher": fetch_mining_production,
     "freq": "M", "unit": "Index (2021=100)", "adjustment": "NSA",
     "series_id": "CZSO/PRU01D/B",
     "note": "CZSO PRU01D Mining and quarrying (NACE B), base 2021=100"},
    {"slug": "manufacturing-production", "kod": "PRU01D", "fetcher": fetch_manufacturing_production,
     "freq": "M", "unit": "Index (2021=100)", "adjustment": "NSA",
     "series_id": "CZSO/PRU01D/C",
     "note": "CZSO PRU01D Manufacturing (NACE C), base 2021=100"},
    {"slug": "government-debt", "kod": "WNUC05D", "fetcher": fetch_government_debt,
     "freq": "A", "unit": "mil Kc", "adjustment": "NSA",
     "series_id": "CZSO/WNUC05D/600602",
     "note": "CZSO WNUC05D General government gross consolidated debt, mil. Kc, annual"},
    # CPI sub-components — CEN0101E with COICOP-2018 CP01-13 filter
    {"slug": "cpi-food",                "kod": "CEN0101E",
     "fetcher": lambda: _fetch_cpi_subcomponent("01"),
     "freq": "M", "unit": "Index (2025=100)", "adjustment": "NSA",
     "series_id": "CZSO/CEN0101E/COICOP=01",
     "note": "CZSO CEN0101E CPI COICOP-2018 division 01 Food and non-alcoholic beverages, base 2025=100"},
    {"slug": "cpi-clothing",            "kod": "CEN0101E",
     "fetcher": lambda: _fetch_cpi_subcomponent("03"),
     "freq": "M", "unit": "Index (2025=100)", "adjustment": "NSA",
     "series_id": "CZSO/CEN0101E/COICOP=03",
     "note": "CZSO CEN0101E CPI COICOP-2018 division 03 Clothing and footwear, base 2025=100"},
    {"slug": "cpi-housing-utilities",   "kod": "CEN0101E",
     "fetcher": lambda: _fetch_cpi_subcomponent("04"),
     "freq": "M", "unit": "Index (2025=100)", "adjustment": "NSA",
     "series_id": "CZSO/CEN0101E/COICOP=04",
     "note": "CZSO CEN0101E CPI COICOP-2018 division 04 Housing, water, electricity, gas and other fuels, base 2025=100"},
    {"slug": "cpi-transportation",      "kod": "CEN0101E",
     "fetcher": lambda: _fetch_cpi_subcomponent("07"),
     "freq": "M", "unit": "Index (2025=100)", "adjustment": "NSA",
     "series_id": "CZSO/CEN0101E/COICOP=07",
     "note": "CZSO CEN0101E CPI COICOP-2018 division 07 Transport, base 2025=100"},
    {"slug": "cpi-recreation-and-culture", "kod": "CEN0101E",
     "fetcher": lambda: _fetch_cpi_subcomponent("09"),
     "freq": "M", "unit": "Index (2025=100)", "adjustment": "NSA",
     "series_id": "CZSO/CEN0101E/COICOP=09",
     "note": "CZSO CEN0101E CPI COICOP-2018 division 09 Recreation and culture, base 2025=100"},
    {"slug": "cpi-education",           "kod": "CEN0101E",
     "fetcher": lambda: _fetch_cpi_subcomponent("10"),
     "freq": "M", "unit": "Index (2025=100)", "adjustment": "NSA",
     "series_id": "CZSO/CEN0101E/COICOP=10",
     "note": "CZSO CEN0101E CPI COICOP-2018 division 10 Education, base 2025=100"},
    # food-inflation = CPI 01 YoY. Same index; frontend can derive YoY. Use as separate slug for parity.
    {"slug": "food-inflation",          "kod": "CEN0101E",
     "fetcher": lambda: _fetch_cpi_subcomponent("01"),
     "freq": "M", "unit": "Index (2025=100)", "adjustment": "NSA",
     "series_id": "CZSO/CEN0101E/COICOP=01:food-inflation",
     "note": "CZSO CEN0101E CPI COICOP-2018 01 Food (same index used as food-inflation level)"},

    # === Migration 072 (2026-05-15): CZ TE-conformity gap-fill ===
    # gdp-real YoY %: WNUC01D 9988J10 quarterly real GDP YoY % SA.
    {"slug": "gdp-real", "kod": "WNUC01D", "fetcher": fetch_gdp_real_yoy,
     "freq": "Q", "unit": "% YoY", "adjustment": "SA",
     "series_id": "CZSO/WNUC01D/9988J10",
     "note": "CZSO WNUC01D Quarterly real GDP, YoY % SA"},
    # government-debt-total: alias of government-debt (annual gross debt, mil Kc).
    # Wired as separate slug for inventory parity (TE attributes to CZSO).
    {"slug": "government-debt-total", "kod": "WNUC05D", "fetcher": fetch_government_debt,
     "freq": "A", "unit": "mil Kc", "adjustment": "NSA",
     "series_id": "CZSO/WNUC05D/600602:total",
     "note": "CZSO WNUC05D General government gross consolidated debt (alias of government-debt)"},
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
                        series_id=cfg["series_id"],
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
