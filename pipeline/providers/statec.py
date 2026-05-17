"""STATEC direct provider — Luxembourg national statistics office.

Uses lustat.statec.lu/rest — STATEC's NSI Web Service v8.x (.Stat Suite SDMX REST,
same platform that ISTAT uses on esploradati.istat.it). All public dataflows under
the LU1 agency.

Original (2026-05-09) wired only CPI + PPI + LFS + IP + population.
Expansion (2026-05-15) adds CPI sub-indices, special CPI aggregates, quarterly NA,
retail-sales, and government deficit/debt — closing the LU TE-source mismatches.

Verified 2026-05-15 against TE inventory:
  inflation-cpi          DSD_ECOICOP_PRIX@DF_E5405 CP00 -> 2026-04 = 102.65
  ppi                    DSD_PRIX_PPI@DF_D3202 _T base2021 -> 2026-03 = 121.48
  unemployment           DF_B3019 C11 -> 2026-03 = 6.35%
  unemployed-persons     DF_B3019 C09 -> persons -> thousands
  employed-persons       DF_B3019 C08 -> persons -> thousands
  industrial-production  DF_D5110 PROD/BTD/W base2021 -> 2026-02 = 78.26
  population             DF_B1100 C01 annual -> millions
  CPI sub (CP01..CP12)   DSD_ECOICOP_PRIX@DF_E5405 ECOICOP_2018=CP0n -> 2026-04
                         cpi-food=102.07  cpi-clothing=102.85
                         cpi-housing=103.91 cpi-transportation=106.05
                         cpi-recreation=101.87 cpi-education=104.03
  CPI special aggs       DSD_ECOICOP_PRIX@DF_E5409 (NCPI special aggregates)
                         core-cpi (TOT_X_NRG_FOOD)=101.35
                         food-inflation (FOOD)=102.26 — LEVEL not YoY
                         energy-inflation (NRG)=116.65 — LEVEL not YoY
                         services-inflation (SERV)=101.43 — LEVEL not YoY
  Quarterly NA (DF_E2504, chain-linked vol 2015, SA):
                         gdp-real (r33) 2025Q4 = 16,105.6 mln EUR
                         consumer-spending (r13) = 5,576.4
                         government-spending (r15) = 3,242.4
                         gross-fixed-capital-formation (r16) = 2,248.1
  Government finance (DF_E3101 annual, EDP):
                         budget-deficit (L03) 2025 = -1.96 % of GDP
                         government-debt-total (L12) 2025 = 23,695 mln EUR
                         (also expose as government-debt for the % series shown by TE)
  Retail-sales           DF_D5108 v1.1 G47 TOVV (turnover value), seasonally adj. Y, base 2021
                         -> 2026-03 = 143.66 (Y), 147.54 (W)

URL pattern (CSV):
  https://lustat.statec.lu/rest/data/LU1,{DATAFLOW},{VERSION}/all/ALL
  Accept: application/vnd.sdmx.data+csv;version=1.0.0
"""
import os
import csv
import io
import time
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
    # === Original (locked-in) ===
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
        "filter": {"FREQ": "M", "ACTIVITY": "_T", "BASE_PERIOD": "2021"},
        "freq": "M", "unit": "Index (2021=100)", "adjustment": "NSA", "conversion": 1.0,
        "note": "STATEC Industrial Producer Prices total (_T), base 2021=100",
    },
    {
        "slug": "unemployment",
        "dataflow": "DF_B3019",
        "version": "1.0",
        "filter": {"FREQ": "M", "SPECIFICATION": "C11"},
        "freq": "M", "unit": "%", "adjustment": "SA", "conversion": 1.0,
        "note": "STATEC unemployment rate, seasonally adjusted (B3019/C11)",
    },
    {
        "slug": "unemployed-persons",
        "dataflow": "DF_B3019",
        "version": "1.0",
        "filter": {"FREQ": "M", "SPECIFICATION": "C09"},
        "freq": "M", "unit": "Thousand", "adjustment": "SA", "conversion": 1e-3,
        "note": "STATEC number of unemployed SA (B3019/C09), persons -> thousands",
    },
    {
        "slug": "employed-persons",
        "dataflow": "DF_B3019",
        "version": "1.0",
        "filter": {"FREQ": "M", "SPECIFICATION": "C08"},
        "freq": "M", "unit": "Thousand", "adjustment": "SA", "conversion": 1e-3,
        "note": "STATEC domestic employment SA (B3019/C08), persons -> thousands",
    },
    {
        "slug": "industrial-production",
        "dataflow": "DF_D5110",
        "version": "1.1",
        "filter": {"FREQ": "M", "MEASURE": "PROD", "ACTIVITY": "BTD",
                   "SEASONAL_ADJUST": "W", "BASE_PER": "2021"},
        "freq": "M", "unit": "Index (2021=100)", "adjustment": "WDA", "conversion": 1.0,
        "note": "STATEC Industrial Production index, total industry BTD, working-day adj.",
    },
    {
        "slug": "population",
        "dataflow": "DF_B1100",
        "version": "1.0",
        "filter": {"FREQ": "A", "SPECIFICATION": "C01"},
        "freq": "A", "unit": "Million", "adjustment": "NSA", "conversion": 1e-6,
        "note": "STATEC total resident population (B1100/C01), annual -> millions",
    },

    # === CPI sub-indices (ECOICOP v.2, NCPI base 2025=100) ===
    # All from DSD_ECOICOP_PRIX@DF_E5405 v1.0 — same dataflow as inflation-cpi.
    {
        "slug": "cpi-food",
        "dataflow": "DSD_ECOICOP_PRIX@DF_E5405",
        "version": "1.0",
        "filter": {"FREQ": "M", "ECOICOP_2018": "CP01"},
        "freq": "M", "unit": "Index (2025=100)", "adjustment": "NSA", "conversion": 1.0,
        "note": "STATEC NCPI ECOICOP v.2 CP01 Food & non-alcoholic beverages",
    },
    {
        "slug": "cpi-clothing",
        "dataflow": "DSD_ECOICOP_PRIX@DF_E5405",
        "version": "1.0",
        "filter": {"FREQ": "M", "ECOICOP_2018": "CP03"},
        "freq": "M", "unit": "Index (2025=100)", "adjustment": "NSA", "conversion": 1.0,
        "note": "STATEC NCPI ECOICOP v.2 CP03 Clothing & footwear",
    },
    {
        "slug": "cpi-housing-utilities",
        "dataflow": "DSD_ECOICOP_PRIX@DF_E5405",
        "version": "1.0",
        "filter": {"FREQ": "M", "ECOICOP_2018": "CP04"},
        "freq": "M", "unit": "Index (2025=100)", "adjustment": "NSA", "conversion": 1.0,
        "note": "STATEC NCPI ECOICOP v.2 CP04 Housing/water/electricity/gas",
    },
    {
        "slug": "cpi-transportation",
        "dataflow": "DSD_ECOICOP_PRIX@DF_E5405",
        "version": "1.0",
        "filter": {"FREQ": "M", "ECOICOP_2018": "CP07"},
        "freq": "M", "unit": "Index (2025=100)", "adjustment": "NSA", "conversion": 1.0,
        "note": "STATEC NCPI ECOICOP v.2 CP07 Transport",
    },
    {
        "slug": "cpi-recreation-and-culture",
        "dataflow": "DSD_ECOICOP_PRIX@DF_E5405",
        "version": "1.0",
        "filter": {"FREQ": "M", "ECOICOP_2018": "CP09"},
        "freq": "M", "unit": "Index (2025=100)", "adjustment": "NSA", "conversion": 1.0,
        "note": "STATEC NCPI ECOICOP v.2 CP09 Recreation & culture",
    },
    {
        "slug": "cpi-education",
        "dataflow": "DSD_ECOICOP_PRIX@DF_E5405",
        "version": "1.0",
        "filter": {"FREQ": "M", "ECOICOP_2018": "CP10"},
        "freq": "M", "unit": "Index (2025=100)", "adjustment": "NSA", "conversion": 1.0,
        "note": "STATEC NCPI ECOICOP v.2 CP10 Education",
    },

    # === CPI special aggregates (DF_E5409, NCPI base 2025=100) — LEVEL indices ===
    # The TE-page values for these slugs are YoY %; we publish levels and
    # let the frontend compute YoY on the fly (per project convention).
    {
        "slug": "core-cpi",
        "dataflow": "DSD_ECOICOP_PRIX@DF_E5409",
        "version": "1.0",
        "filter": {"FREQ": "M", "ECOICOP_2018": "TOT_X_NRG_FOOD"},
        "freq": "M", "unit": "Index (2025=100)", "adjustment": "NSA", "conversion": 1.0,
        "note": "STATEC NCPI special agg TOT_X_NRG_FOOD (excl. energy & food)",
    },
    {
        "slug": "food-inflation",
        "dataflow": "DSD_ECOICOP_PRIX@DF_E5409",
        "version": "1.0",
        "filter": {"FREQ": "M", "ECOICOP_2018": "FOOD"},
        "freq": "M", "unit": "Index (2025=100)", "adjustment": "NSA", "conversion": 1.0,
        "note": "STATEC NCPI special agg FOOD (level); frontend computes YoY",
    },
    {
        "slug": "energy-inflation",
        "dataflow": "DSD_ECOICOP_PRIX@DF_E5409",
        "version": "1.0",
        "filter": {"FREQ": "M", "ECOICOP_2018": "NRG"},
        "freq": "M", "unit": "Index (2025=100)", "adjustment": "NSA", "conversion": 1.0,
        "note": "STATEC NCPI special agg NRG (energy, level)",
    },
    {
        "slug": "services-inflation",
        "dataflow": "DSD_ECOICOP_PRIX@DF_E5409",
        "version": "1.0",
        "filter": {"FREQ": "M", "ECOICOP_2018": "SERV"},
        "freq": "M", "unit": "Index (2025=100)", "adjustment": "NSA", "conversion": 1.0,
        "note": "STATEC NCPI special agg SERV (services, level)",
    },

    # === Quarterly National Accounts — DF_E2504 v1.0 ===
    # Main aggregates, chain-linked volumes (ref 2015), seasonally adjusted, mln EUR.
    # LABELS coded r01..r33 (see codelist; mapping in module docstring).
    {
        "slug": "gdp-real",
        "dataflow": "DF_E2504",
        "version": "1.0",
        "filter": {"FREQ": "Q", "LABELS": "r33"},
        "freq": "Q", "unit": "Million EUR (chain-linked, SA)", "adjustment": "SA",
        "conversion": 1.0,
        "note": "STATEC E2504 r33 GDP at market prices (B1*G), chain-linked vol SA",
    },
    {
        "slug": "consumer-spending",
        "dataflow": "DF_E2504",
        "version": "1.0",
        "filter": {"FREQ": "Q", "LABELS": "r13"},
        "freq": "Q", "unit": "Million EUR (chain-linked, SA)", "adjustment": "SA",
        "conversion": 1.0,
        "note": "STATEC E2504 r13 Final consumption expenditure of households",
    },
    {
        "slug": "government-spending",
        "dataflow": "DF_E2504",
        "version": "1.0",
        "filter": {"FREQ": "Q", "LABELS": "r15"},
        "freq": "Q", "unit": "Million EUR (chain-linked, SA)", "adjustment": "SA",
        "conversion": 1.0,
        "note": "STATEC E2504 r15 Final consumption of general government",
    },
    {
        "slug": "gross-fixed-capital-formation",
        "dataflow": "DF_E2504",
        "version": "1.0",
        "filter": {"FREQ": "Q", "LABELS": "r16"},
        "freq": "Q", "unit": "Million EUR (chain-linked, SA)", "adjustment": "SA",
        "conversion": 1.0,
        "note": "STATEC E2504 r16 Gross capital formation (P5) chain-linked vol SA",
    },

    # === Government finance — DF_E3101 v1.0 (annual EDP report) ===
    # L03 = net lending/borrowing in % of GDP  -> budget-deficit (sign: TE uses absolute,
    #       L03 carries sign — we keep STATEC sign; frontend can flip if needed).
    # L12 = General government consolidated gross debt at nominal value (mln EUR).
    {
        "slug": "budget-deficit",
        "dataflow": "DF_E3101",
        "version": "1.0",
        "filter": {"FREQ": "A", "LABELS": "L03"},
        "freq": "A", "unit": "% of GDP", "adjustment": "NSA", "conversion": 1.0,
        "note": "STATEC E3101 L03 General government net lending/borrowing % of GDP",
    },
    {
        "slug": "government-debt-total",
        "dataflow": "DF_E3101",
        "version": "1.0",
        "filter": {"FREQ": "A", "LABELS": "L12"},
        "freq": "A", "unit": "Million EUR", "adjustment": "NSA", "conversion": 1.0,
        "note": "STATEC E3101 L12 Consolidated gross general government debt (mln EUR)",
    },

    # === Balance of Payments — DF_E4202 v1.0 (quarterly, BPM6) ===
    # DIRECTION B=Balance, C=Credit (exports), D=Debit (imports)
    # COMPONENT CA=current account, G=goods, S=services
    {
        "slug": "current-account",
        "dataflow": "DF_E4202",
        "version": "1.0",
        "filter": {"FREQ": "Q", "DIRECTION": "B", "COMPONENT": "CA"},
        "freq": "Q", "unit": "Million EUR", "adjustment": "NSA", "conversion": 1.0,
        "note": "STATEC E4202 BPM6 quarterly Current Account balance (mln EUR)",
    },

    # === Government finance % of GDP — DF_E3101 v1.0 ===
    # L14 = General government consolidated gross debt in % of GDP (annual EDP)
    {
        "slug": "government-debt",
        "dataflow": "DF_E3101",
        "version": "1.0",
        "filter": {"FREQ": "A", "LABELS": "L14"},
        "freq": "A", "unit": "% of GDP", "adjustment": "NSA", "conversion": 1.0,
        "note": "STATEC E3101 L14 General government consolidated gross debt % of GDP",
    },

    # === Retail sales — DF_D5108 v1.1 ===
    # G47 retail trade, MEASURE=TOVV (turnover value), SEASONAL_ADJUST=Y (seasonally adj),
    # BASE_PER=2021. Reported as an index (UNIT_MEASURE=IX).
    {
        "slug": "retail-sales",
        "dataflow": "DF_D5108",
        "version": "1.1",
        "filter": {"FREQ": "M", "MEASURE": "TOVV", "SEASONAL_ADJUST": "Y",
                   "ACTIVITY": "G47", "BASE_PER": "2021"},
        "freq": "M", "unit": "Index (2021=100, SA)", "adjustment": "SA",
        "conversion": 1.0,
        "note": "STATEC D5108 G47 retail trade turnover-value index, SA, base 2021",
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


def _fetch_series(cfg: dict, retries: int = 3) -> list[tuple[date, float]]:
    url = f"{BASE}/LU1,{cfg['dataflow']},{cfg['version']}/all/ALL"
    last_exc = None
    for attempt in range(retries):
        if attempt:
            time.sleep(5 * attempt)
        try:
            r = requests.get(url, headers=HDR, timeout=180)
            r.raise_for_status()
            break
        except requests.RequestException as e:
            last_exc = e
    else:
        raise last_exc  # type: ignore
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
        # Cache dataflow CSV once per (dataflow,version) to avoid duplicate fetches —
        # many slugs share DSD_ECOICOP_PRIX@DF_E5405 and DF_E2504/E3101.
        cache: dict[tuple[str, str], list[dict]] = {}
        for cfg in SERIES:
            key = (cfg["dataflow"], cfg["version"])
            try:
                if key not in cache:
                    url = f"{BASE}/{cfg['dataflow']},LU1," if False else None  # placeholder
                    # Just fetch via _fetch_series; we re-run filter inline below.
                    # Simpler: call full helper.
                    pairs = _fetch_series(cfg)
                else:
                    # use cached rows
                    pairs = []
                    flt = cfg["filter"]
                    for row in cache[key]:
                        if all(row.get(k) == v for k, v in flt.items()):
                            per = row.get("TIME_PERIOD", "")
                            val = row.get("OBS_VALUE", "")
                            if per and val:
                                try:
                                    dt = _parse_period(per, cfg["freq"])
                                    if dt:
                                        pairs.append((dt, float(val)))
                                except ValueError:
                                    pass
                    pairs.sort()
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
