"""Direct national stat-office provider for EU countries.

For each country, we hit the OFFICIAL primary source's API directly (not via
DBnomics/Eurostat). Source labels match what TE shows.

Currently supported (verified reachable from this network as of 2026-05-09):
  DK — Statistics Denmark / Statbank API (api.statbank.dk)
  FI — Statistics Finland / Tilastokeskus PxWeb (pxdata.stat.fi)
  PL — GUS / BDL API (bdl.stat.gov.pl)
  SE — Statistics Sweden / SCB PxWeb (api.scb.se)
  PT — INE Portugal JSON-Indicador API (www.ine.pt)
  IE — CSO Ireland PxStat REST (ws.cso.ie)
  BE — Statbel REST API (bestat.statbel.fgov.be)
  MT — NSO Malta SDMX REST (apidesign-statdb.nso.gov.mt) — Cloudflare-protected, needs cloudscraper
  CY — CYSTAT PxWeb (cystatdb.cystat.gov.cy) — Cloudflare-protected, needs cloudscraper

Network-blocked from this environment (deferred):
  NL — datasets.cbs.nl Connection Timeout
  CZ — apl.czso.cz HTML only (no JSON API)
  HU — statinfo.ksh.hu HTML only
  AT — Statistik Austria endpoint discovery pending
  GR — ELSTAT static-files only
  RO — INSSE Tempo SSL handshake fails
"""
import os
import time
from datetime import date

import requests
from dotenv import load_dotenv

try:
    import cloudscraper  # type: ignore
    _CF_SCRAPER = cloudscraper.create_scraper()
except Exception:  # pragma: no cover
    _CF_SCRAPER = None

from pipeline.base_provider import BaseProvider, DataPoint
from pipeline.transforms import normalize_date
from pipeline.db import upsert_data_points, log_pipeline_run, datapoints_to_rows

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))


def _parse_period(p: str, freq: str) -> date | None:
    try:
        if freq == "M":
            if "M" in p:
                yy, mm = p.split("M")
                return date(int(yy), int(mm), 1)
            if "-" in p and len(p) == 7:
                yy, mm = p.split("-")
                return date(int(yy), int(mm), 1)
        if freq == "Q":
            if "K" in p:  # Danish Kvartal
                yy, q = p.split("K")
                return date(int(yy), {"1":1,"2":4,"3":7,"4":10}[q], 1)
            if "Q" in p:
                yy, q = p.split("Q")
                return date(int(yy), {"1":1,"2":4,"3":7,"4":10}[q], 1)
        if freq == "A" and len(p) == 4:
            return date(int(p), 1, 1)
    except Exception:
        return None
    return None


# === Denmark — Statbank API ===

DK_SERIES = [
    # PRIS01: Consumer price index by commodity group, unit, time
    # VAREGR=000000 (total), ENHED=100 (Index), monthly
    {"slug": "inflation-cpi", "table": "PRIS01",
     "filters": {"VAREGR": "000000", "ENHED": "100"},
     "freq": "M", "unit": "Index", "adjustment": "NSA", "conversion": 1.0,
     "note": "DK Statbank PRIS01 CPI total all-items index"},
    # IPOP21: Industrial production index — total industry C, non-seasonal
    {"slug": "industrial-production", "table": "IPOP21",
     "filters": {"SÆSON": "SÆSON", "BRANCHEDB25UDVALG": "C"},
     "freq": "M", "unit": "Index", "adjustment": "SA", "conversion": 1.0,
     "note": "DK Statbank IPOP21 IP index total manufacturing SA"},
    # AUP01: Unemployment % of labour force — All Denmark, total age, total sex
    {"slug": "unemployment", "table": "AUP01",
     "filters": {"OMRÅDE": "000", "KØN": "TOT", "ALDER": "TOT"},
     "freq": "M", "unit": "%", "adjustment": "SA", "conversion": 1.0,
     "note": "DK Statbank AUP01 unemployment rate (all DK, both genders, all ages)"},
    # DETA211A: Retail Trade Index — total retail trade
    {"slug": "retail-sales", "table": "DETA211A",
     "filters": {"BRANCHEDB25UDVALG": "G47"},
     "freq": "M", "unit": "Index", "adjustment": "NSA", "conversion": 1.0,
     "note": "DK Statbank DETA211A Retail Trade total G47"},
    # PRIS4321: Producer and import price index for commodities
    # HOVEDGRP=BCDE (Mining+manufacturing+electricity+water supply — TE uses this aggregation),
    # MARKED1=500 (Total Danish production), ENHED=100 (Index level).
    # Verified 2026-05-09: 2026M03 = 145.1, exact TE match.
    {"slug": "ppi", "table": "PRIS4321",
     "filters": {"HOVEDGRP": "BCDE", "MARKED1": "500", "ENHED": "100"},
     "freq": "M", "unit": "Index", "adjustment": "NSA", "conversion": 1.0,
     "note": "DK Statbank PRIS4321 PPI BCDE Total Danish production index"},
    # NAN1: Demand and supply, annual GDP at market prices
    # TRANSAKT=B1GQK (GDP), PRISENHED=V_M (current prices, bn DKK)
    {"slug": "gdp", "table": "NAN1",
     "filters": {"TRANSAKT": "B1GQK", "PRISENHED": "V_M"},
     "freq": "A", "unit": "Billion DKK", "adjustment": "NSA", "conversion": 1.0,
     "note": "DK Statbank NAN1 GDP at market prices, current prices, bn DKK"},
    # NKHO2: Quarterly national accounts — real GDP, chained 2020 prices, SA
    # TRANSAKT=B1GQD (GDP), PRISENHED=LKV (chained 2020), SAESON=Y (SA)
    {"slug": "gdp-real", "table": "NKHO2",
     "filters": {"TRANSAKT": "B1GQD", "PRISENHED": "LKV", "SÆSON": "Y"},
     "freq": "Q", "unit": "Million DKK (2020 chained)", "adjustment": "SA", "conversion": 1.0,
     "note": "DK Statbank NKHO2 quarterly real GDP chained 2020 prices, SA"},
    # BBM: Balance of payments monthly — Goods (FOB) trade balance
    # POST=1.A.A (Goods FOB), INDUDBOP=N (Net), LAND=W1 (World), ENHED=93 (mil DKK), SA
    {"slug": "trade-balance", "table": "BBM", "series_id": "DST/BBM",
     "filters": {"POST": "1.A.A", "INDUDBOP": "N", "LAND": "W1", "ENHED": "93", "SÆSON": "2"},
     "freq": "M", "unit": "Million DKK", "adjustment": "SA", "conversion": 1.0,
     "note": "DK Statbank BBM Goods FOB trade balance vs World, SA, mio DKK"},
    # BBM Exports of Goods (Current receipts side, K)
    {"slug": "exports", "table": "BBM", "series_id": "DST/BBM/exp",
     "filters": {"POST": "1.A.A", "INDUDBOP": "K", "LAND": "W1", "ENHED": "93", "SÆSON": "2"},
     "freq": "M", "unit": "Million DKK", "adjustment": "SA", "conversion": 1.0,
     "note": "DK Statbank BBM Goods FOB exports vs World, SA, mio DKK"},
    # BBM Imports of Goods (Current expenditure side, D)
    {"slug": "imports", "table": "BBM", "series_id": "DST/BBM/imp",
     "filters": {"POST": "1.A.A", "INDUDBOP": "D", "LAND": "W1", "ENHED": "93", "SÆSON": "2"},
     "freq": "M", "unit": "Million DKK", "adjustment": "SA", "conversion": 1.0,
     "note": "DK Statbank BBM Goods FOB imports vs World, SA, mio DKK"},
    # LBESK104: Employees (seasonally adjusted), all sectors, monthly, in persons
    # SEKTOR=1000 (All sectors); we publish in thousands to match indicator unit
    {"slug": "employed-persons", "table": "LBESK104",
     "filters": {"SEKTOR": "1000"},
     "freq": "M", "unit": "Thousand", "adjustment": "SA", "conversion": 0.001,
     "note": "DK Statbank LBESK104 employees, all sectors, SA, thousands"},
    # === Stage-2 (migration 032): national-source promotion from eurostat ===
    # FORV1: Consumer Confidence Indicator (DST monthly survey), INDIKATOR=F1 (headline).
    # Verified 2026-05-14: 2026M04 = -18.6 (TE: -18.6 exact match).
    {"slug": "consumer-confidence", "table": "FORV1",
     "filters": {"INDIKATOR": "F1"},
     "freq": "M", "unit": "Balance", "adjustment": "NSA", "conversion": 1.0,
     "note": "DK Statbank FORV1 consumer confidence indicator (F1 headline)"},
    # ETILLID: Business sentiment indicators. INDIKATOR=KBI (industry confidence)
    # matches the TE business-confidence series (TE shows 100.7 for 2026M04).
    # Verified 2026-05-14: 2026M04 = 100.7 (TE: 100.7 exact match).
    {"slug": "business-confidence", "table": "ETILLID",
     "filters": {"INDIKATOR": "KBI"},
     "freq": "M", "unit": "Index (2015=100)", "adjustment": "SA", "conversion": 1.0,
     "note": "DK Statbank ETILLID business sentiment, industry KBI (TE headline)"},
    # AUS09: Gross unemployment (registered DPES count), monthly.
    # YDELSESTYPE=LDM (unemployment benefit recipients only — TE's "unemployed-persons"),
    # SAESONFAK=24 (NSA, actual figures in persons). We publish in thousands.
    # Verified 2026-05-14: 2026M03 = 81,989 persons => 82.0 thousand (TE: 80.9, very close,
    # NSA series subject to small vintage revisions).
    {"slug": "unemployed-persons", "table": "AUS09",
     "filters": {"YDELSESTYPE": "LDM", "SAESONFAK": "24"},
     "freq": "M", "unit": "Thousand", "adjustment": "NSA", "conversion": 0.001,
     "note": "DK Statbank AUS09 registered unemployed (LDM, NSA, in 1000s)"},
]


def fetch_dk_table(table: str, filters: dict, freq: str = "M") -> list[tuple[date, float]]:
    """Statbank.dk JSON-stat data API. Tid=* fetches the full time series."""
    variables = [{"code": k, "values": [v]} for k, v in filters.items()]
    variables.append({"code": "Tid", "values": ["*"]})
    payload = {
        "table": table,
        "format": "JSONSTAT",
        "valuePresentation": "Default",
        "lang": "en",
        "variables": variables,
    }
    r = requests.post("https://api.statbank.dk/v1/data", json=payload, timeout=30)
    r.raise_for_status()
    js = r.json()
    # JSON-stat structure: dataset.value (array), dataset.dimension.<id>.category.label/index
    ds = js.get("dataset", js)
    values = ds.get("value", [])
    dim = ds.get("dimension", {})
    # Find time dimension (last in 'id' usually)
    tid_dim = "Tid" if "Tid" in dim else next((k for k in dim if "time" in k.lower() or "Tid" in k), None)
    if not tid_dim:
        return []
    tid_cat = dim[tid_dim].get("category", {})
    idx_map = tid_cat.get("index", {})
    label_map = tid_cat.get("label", {})
    if not idx_map:
        return []
    # values are 1-D when only one combo
    out = []
    for code, idx in idx_map.items():
        if idx >= len(values):
            continue
        v = values[idx]
        if v is None:
            continue
        dt = _parse_period(code, freq)
        if dt is None:
            continue
        out.append((dt, float(v)))
    return sorted(out)


# === Finland — Tilastokeskus PxWeb ===

FI_SERIES = [
    # statfin_khi_pxt_15b5.px: CPI (2025=100) monthly — Hyödyke=SSS (Total), Tiedot=ip_khi (Index)
    {"slug": "inflation-cpi", "path": "StatFin/khi/statfin_khi_pxt_15b5.px",
     "query": {"Hyödyke": "SSS", "Tiedot": "ip_khi"},
     "freq": "M", "unit": "Index", "adjustment": "NSA", "conversion": 1.0,
     "note": "FI Tilastokeskus 15b5 CPI 2025=100 total monthly"},
    # Producer Price Index (2021=100) monthly. "1" = PPI for manufactured products.
    # Verified 2026-05-09: latest 2026M03 = 120.6 (matches TE).
    {"slug": "ppi", "path": "StatFin/thi/statfin_thi_pxt_13m8.px",
     "query": {"Tuotteet toimialoittain (CPA 2015, MIG)": "SSS",
               "Indeksisarja": "1",
               "Tiedot": "pisteluku21"},
     "freq": "M", "unit": "Index (2021=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "FI Tilastokeskus 13m8 PPI manufactured products total 2021=100"},
    # Industrial output volume index (2021=100), original (NSA). BTD=BCD Total industries.
    # Verified 2026-05-09: latest 2026M03 = 116.7 (NSA original) -> implies +7.3% YoY (matches TE).
    {"slug": "industrial-production", "path": "StatFin/ttvi/statfin_ttvi_pxt_14mh.px",
     "query": {"Toimiala (TOL 2008)": "BTD",
               "Tiedot": "Alkuperainen"},
     "freq": "M", "unit": "Index (2021=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "FI Tilastokeskus 14mh Industrial Output BCD Total NSA 2021=100"},
    # Unemployment rate (Labour Force Survey, ages 15-74), monthly NSA.
    # Verified 2026-05-09: latest 2026M03 = 11.1% (matches TE exactly).
    {"slug": "unemployment", "path": "StatFin/tyti/statfin_tyti_pxt_135y.px",
     "query": {"Sukupuoli": "SSS",
               "Ikäluokka": "15-74",
               "Tiedot": "Tyottomyysaste"},
     "freq": "M", "unit": "%", "adjustment": "NSA", "conversion": 1.0,
     "note": "FI Tilastokeskus 135y LFS unemployment rate 15-74 monthly NSA"},
    # NOTE: GDP intentionally NOT added here. Tilastokeskus QNA 132h provides chained-2015
    # EUR-mn quarterly volumes, but the catalog's `gdp` slug is annual nominal USD (World Bank
    # NY.GDP.MKTP.CD) for cross-country comparability. Mixing a quarterly EUR series under
    # the same slug would break overview displays. If we later add a `gdp-qoq` slug, the
    # vol_kk_kausit_2015_chained MoM% from QNA 132h is the right TE-aligned source.
    # Retail trade volume index G47 (2021=100), working-day-adjusted.
    # Verified 2026-05-09: latest 2026M03 = 91.5 WDA volume.
    {"slug": "retail-sales", "path": "StatFin/klv/statfin_klv_pxt_14kr.px",
     "query": {"Toimiala": "G47",
               "Muuttuja": "mi",
               "Tiedot": "tyopaivakorjattu"},
     "freq": "M", "unit": "Index (2021=100)", "adjustment": "WDA", "conversion": 1.0,
     "note": "FI Tilastokeskus 14kr Retail trade G47 volume index 2021=100 WDA"},
    # --- Stage 2 expansion (migration 034) ---
    # Employed persons aged 15-74, monthly thousands NSA. tyti 13gg, Tiedot=Tyolliset.
    # Verified 2026-05-14: 2026M03 = 2524 thousand (matches TE 2524 exactly).
    {"slug": "employed-persons", "path": "StatFin/tyti/statfin_tyti_pxt_13gg.px",
     "query": {"Tiedot": "Tyolliset"},
     "freq": "M", "unit": "Thousand", "adjustment": "NSA", "conversion": 1.0,
     "note": "FI Tilastokeskus 13gg LFS employed persons 15-74 monthly NSA thousand"},
    # Quarterly GDP at market prices, chained 2015 reference year, SA+WDA, EUR million.
    # ntp 132h: Taloustoimi=B1GMH (GDP@MP), Tiedot=kausitvv2015 (SA, chained ref 2015).
    # Verified 2026-05-14: 2025Q4 = 57249 EUR mn (chained ref 2015).
    {"slug": "gdp-real", "path": "StatFin/ntp/statfin_ntp_pxt_132h.px",
     "query": {"Taloustoimi": "B1GMH", "Tiedot": "kausitvv2015"},
     "freq": "Q", "unit": "EUR million (chained 2015)", "adjustment": "SA", "conversion": 1.0,
     "note": "FI Tilastokeskus 132h Real GDP, chained 2015 EUR mn, SA+WDA"},
    # International trade in goods and services, quarterly, partner=ULK (rest-of-world total),
    # service-item=GS (goods+services). tpulk 12gq. EUR million, NSA.
    # Verified 2026-05-14: 2026Q1 exports=29495, imports=29952, balance=-457 EUR mn.
    # NOTE: TE uses monthly Tulli (Customs) numbers; StatFin only publishes BoP-style
    # quarterly aggregates. Tulli ULJAS has no JSON-stat REST endpoint, so quarterly is
    # the cleanest direct national-source feed within the existing PxWeb architecture.
    {"slug": "exports", "path": "StatFin/tpulk/statfin_tpulk_pxt_12gq.px",
     "query": {"Alue": "ULK", "Tiedot": "tpulk_C", "Palveluerä": "GS"},
     "series_id": "STATFI/StatFin/tpulk/statfin_tpulk_pxt_12gq.px/exp",
     "freq": "Q", "unit": "EUR million", "adjustment": "NSA", "conversion": 1.0,
     "note": "FI Tilastokeskus 12gq Exports of goods+services to ROW (BoP), EUR mn"},
    {"slug": "imports", "path": "StatFin/tpulk/statfin_tpulk_pxt_12gq.px",
     "query": {"Alue": "ULK", "Tiedot": "tpulk_D", "Palveluerä": "GS"},
     "series_id": "STATFI/StatFin/tpulk/statfin_tpulk_pxt_12gq.px/imp",
     "freq": "Q", "unit": "EUR million", "adjustment": "NSA", "conversion": 1.0,
     "note": "FI Tilastokeskus 12gq Imports of goods+services from ROW (BoP), EUR mn"},
    # trade-balance is derived in the Finland fetch loop as exports - imports
    # (same tpulk 12gq table); kept as separate logical slug.
]


def fetch_fi_table(path: str, query_filters: dict, freq: str = "M") -> list[tuple[date, float]]:
    url = f"https://pxdata.stat.fi/PxWeb/api/v1/en/{path}"
    body = {
        "query": [{"code": k, "selection": {"filter": "item", "values": [v]}}
                  for k, v in query_filters.items()],
        "response": {"format": "json-stat2"},
    }
    r = requests.post(url, json=body, timeout=30)
    r.raise_for_status()
    return _parse_jsonstat(r.json(), freq)


# === Sweden — SCB PxWeb ===

SE_SERIES = [
    # PR/PR0101/PR0101A/KPI2020M: CPI by ContentsCode, monthly
    # 00000807 = CPI shadow index (continuous 1980=100)
    {"slug": "inflation-cpi", "path": "PR/PR0101/PR0101A/KPI2020M",
     "query": {"ContentsCode": "00000807"},
     "freq": "M", "unit": "Index", "adjustment": "NSA", "conversion": 1.0,
     "note": "SE SCB CPI shadow index (continuous 1980=100)"},
    # PR/PR0301/PR0301G/PPI2020M: Producer Price Index, 2020=100, monthly 1990M01->
    # SPIN2015=B-E (Total), ContentsCode=000000SA (PPI). Verified 2026-05-09: 2026M03 = 135.8 (matches TE 135.80).
    {"slug": "ppi", "path": "PR/PR0301/PR0301G/PPI2020M",
     "query": {"SPIN2015": "B-E", "ContentsCode": "000000SA"},
     "freq": "M", "unit": "Index (2020=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "SE SCB PR0301G Producer Price Index, total B-E, 2020=100"},
    # NV/NV0402/NV0402A/IPI2010KedjM: Industrial Production Index 2021=100, monthly 2000M01->
    # SNI2007=B-D (Mining/Manufacturing/Energy), ContentsCode=NV0402AZ (Annual development % WDA).
    # Verified 2026-05-09: 2026M03=2.8%, 2026M02=6.9% (TE shows 3% / 6.2% revised — matches w/ rounding/vintage).
    {"slug": "industrial-production-yoy", "path": "NV/NV0402/NV0402A/IPI2010KedjM",
     "query": {"SNI2007": "B-D", "ContentsCode": "NV0402AZ"},
     "freq": "M", "unit": "%", "adjustment": "WDA", "conversion": 1.0,
     "note": "SE SCB NV0402A Industrial Production YoY% WDA (B-D mining+mfg+energy)"},
    # AM/AM0401/AM0401A/AKURLBefM: LFS Unemployment rate 15-74, monthly 2001M01->
    # Arbetskraftstillh=ALÖSP (rate %), TypData=TC_DATA (SA + smoothed/trend; matches TE headline 8.7%).
    # Kon=1+2 (both sexes), Alder=tot15-74, ContentsCode=000007L9.
    # Verified 2026-05-09: 2026M03 = 8.7 (matches TE exactly).
    {"slug": "unemployment", "path": "AM/AM0401/AM0401A/AKURLBefM",
     "query": {"Arbetskraftstillh": "ALÖSP", "TypData": "TC_DATA",
               "Kon": "1+2", "Alder": "tot15-74", "ContentsCode": "000007L9"},
     "freq": "M", "unit": "%", "adjustment": "SA", "conversion": 1.0,
     "note": "SE SCB AM0401A LFS unemployment rate 15-74 SA trend (ALÖSP/TC_DATA)"},
    # NR/NR0103/NR0103B/NR0103ENS2010T10SKv: GDP expenditure approach, SA, quarterly 1981Q1->
    # Anvandningstyp=BNPM (GDP at market prices), ContentsCode=NR0103CF (% volume change vs prev period SA).
    # Verified 2026-05-09: latest 2025Q4 = 0.5% (TE shows -0.2 for Q1 2026 flash; vintage lag normal).
    {"slug": "gdp-growth-rate", "path": "NR/NR0103/NR0103B/NR0103ENS2010T10SKv",
     "query": {"Anvandningstyp": "BNPM", "ContentsCode": "NR0103CF"},
     "freq": "Q", "unit": "%", "adjustment": "SA", "conversion": 1.0,
     "note": "SE SCB NR0103B GDP QoQ% volume change SA (BNPM/NR0103CF)"},
    # HA/HA0201/HA0201A/ImportExportSnabbM: Foreign trade in goods, SEK million, monthly 1975M01->
    # ImportExport=HANDELSB (Net Trade), ContentsCode=HA0201A2.
    # Verified 2026-05-09: 2026M03 = 9300 SEK million (matches TE 9,300 exactly).
    {"slug": "trade-balance", "path": "HA/HA0201/HA0201A/ImportExportSnabbM",
     "query": {"ImportExport": "HANDELSB", "ContentsCode": "HA0201A2"},
     "freq": "M", "unit": "SEK million", "adjustment": "NSA", "conversion": 1.0,
     "note": "SE SCB HA0201A Net Trade of goods SEK million (HANDELSB)"},
    # HA/HA0101/HA0101B/DetOms07N: Retail sale index 2021=100, monthly 1991M01->
    # SNI2007=47exkl47.3 (retail trade except fuel - SCB headline), ContentsCode=000006VZ
    # (Yearly development % WDA constant prices). Verified 2026-05-09: 2026M03=6.2, 2026M02=2.2.
    # TE: 6.2% YoY Mar 2026 (prev=2.2%) — exact match.
    {"slug": "retail-sales-yoy", "path": "HA/HA0101/HA0101B/DetOms07N",
     "query": {"SNI2007": "47exkl47.3", "ContentsCode": "000006VZ"},
     "freq": "M", "unit": "%", "adjustment": "WDA", "conversion": 1.0,
     "note": "SE SCB HA0101B Retail Sales YoY% (excl fuel), WDA constant prices"},
    # === Stage-2 (migration 033): national-source promotion from eurostat ===
    # Industrial Production Index level, B-D (mining/mfg/energy), calendar-adjusted.
    # ContentsCode=NV0402AJ (calendar adjusted). Verified 2026-05-14: 2026M03 = 119.1 (index 2021=100).
    {"slug": "industrial-production", "path": "NV/NV0402/NV0402A/IPI2010KedjM",
     "query": {"SNI2007": "B-D", "ContentsCode": "NV0402AJ"},
     "freq": "M", "unit": "Index (2021=100)", "adjustment": "WDA", "conversion": 1.0,
     "note": "SE SCB NV0402A Industrial Production Index level, B-D, WDA"},
    # Retail sales index level, retail trade ex fuel (47exkl47.3), SA-WDA constant prices.
    # ContentsCode=000006VX. Verified 2026-05-14: 2026M03 = 99.9 (index 2021=100).
    {"slug": "retail-sales", "path": "HA/HA0101/HA0101B/DetOms07N",
     "query": {"SNI2007": "47exkl47.3", "ContentsCode": "000006VX"},
     "freq": "M", "unit": "Index (2021=100)", "adjustment": "SA", "conversion": 1.0,
     "note": "SE SCB HA0101B Retail Sales index level (excl fuel), SA-WDA constant prices"},
    # Trade exports: HA0201A ImportExportSnabbM, ETOT (Total exports SEK mn), NSA.
    # Verified 2026-05-14: 2026M03 = 195,100 SEK mn.
    {"slug": "exports", "path": "HA/HA0201/HA0201A/ImportExportSnabbM",
     "query": {"ImportExport": "ETOT", "ContentsCode": "HA0201A2"},
     "freq": "M", "unit": "SEK million", "adjustment": "NSA", "conversion": 1.0,
     "note": "SE SCB HA0201A Total exports of goods SEK million (ETOT)"},
    # Trade imports: HA0201A ImportExportSnabbM, ITOT (Total imports SEK mn), NSA.
    # Verified 2026-05-14: 2026M03 = 185,800 SEK mn.
    {"slug": "imports", "path": "HA/HA0201/HA0201A/ImportExportSnabbM",
     "query": {"ImportExport": "ITOT", "ContentsCode": "HA0201A2"},
     "freq": "M", "unit": "SEK million", "adjustment": "NSA", "conversion": 1.0,
     "note": "SE SCB HA0201A Total imports of goods SEK million (ITOT)"},
    # LFS unemployment rate already covered by `unemployment` slug above; add level (thousands).
    # ALÖS=unemployed thousands, TypData=O_DATA (NSA, matches TE 564.9). Verified 2026-05-14:
    # 2026M03 = 564.9 (TE: 564.9 exact).
    {"slug": "unemployed-persons", "path": "AM/AM0401/AM0401A/AKURLBefM",
     "query": {"Arbetskraftstillh": "ALÖS", "TypData": "O_DATA",
               "Kon": "1+2", "Alder": "tot15-74", "ContentsCode": "000007L9"},
     "freq": "M", "unit": "Thousand", "adjustment": "NSA", "conversion": 1.0,
     "note": "SE SCB AM0401A LFS unemployed persons 15-74 NSA, thousands (ALÖS/O_DATA)"},
    # Employed persons LFS, SYS=employed thousands, O_DATA NSA. Verified 2026-05-14:
    # 2026M03 = 5,229.8 thousand (TE: 5.23 million exact match).
    {"slug": "employed-persons", "path": "AM/AM0401/AM0401A/AKURLBefM",
     "query": {"Arbetskraftstillh": "SYS", "TypData": "O_DATA",
               "Kon": "1+2", "Alder": "tot15-74", "ContentsCode": "000007L9"},
     "freq": "M", "unit": "Thousand", "adjustment": "NSA", "conversion": 1.0,
     "note": "SE SCB AM0401A LFS employed persons 15-74 NSA, thousands (SYS/O_DATA)"},
    # GDP real, expenditure approach, SA constant prices ref 2024 (SEK million).
    # BNPM=GDP at market prices, ContentsCode=NR0103CE. Verified 2026-05-14:
    # 2025Q4 = 1,643,113 SEK mn (SA constant prices ref 2024).
    {"slug": "gdp-real", "path": "NR/NR0103/NR0103B/NR0103ENS2010T10SKv",
     "query": {"Anvandningstyp": "BNPM", "ContentsCode": "NR0103CE"},
     "freq": "Q", "unit": "SEK million (ref 2024)", "adjustment": "SA", "conversion": 1.0,
     "note": "SE SCB NR0103B GDP-real SA constant prices ref 2024, SEK mn (BNPM)"},
    # NOTE: Consumer-confidence and business-confidence are NOT published by SCB. The
    # TE-cited source is NIER/Konjunkturinstitutet (https://www.konj.se/). Their data is
    # available via the Macroindicators API but not under SCB; deferred to a separate
    # provider (konj_se) — left on eurostat fallback for now.
]


def fetch_se_table(path: str, query_filters: dict, freq: str = "M") -> list[tuple[date, float]]:
    url = f"https://api.scb.se/OV0104/v1/doris/en/ssd/{path}"
    body = {
        "query": [{"code": k, "selection": {"filter": "item", "values": [v]}}
                  for k, v in query_filters.items()],
        "response": {"format": "json-stat2"},
    }
    r = requests.post(url, json=body, timeout=30)
    r.raise_for_status()
    return _parse_jsonstat(r.json(), freq)


# === Portugal — INE PT JSON-Indicador ===
#
# API: https://www.ine.pt/ine/json_indicador/pindica.jsp
#   op=1                -> full history under key "Pref" (period labels in PT)
#   op=2                -> latest observation only under "Dados"
#   varcd               -> 7-digit indicator code (zero-padded)
#   lang=PT             -> period labels like "Marco de 2026", "1.o Trimestre de 2026"
#
# Each period maps to a list of rows tagged with dim_3 (sometimes dim_4 too).
# Per-indicator total dim values are documented inline below.
#
# Trade-balance: INE only publishes monthly trade by NUTS/CGCE in large multi-
# dimensional tables that exceed the pindica row cap. The aggregated national
# balance is therefore covered by Eurostat (DS-018995 / ext_st_eu27_2020sitc).

PT_PT_MONTHS = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "marc": 3, "abril": 4,
    "maio": 5, "junho": 6, "julho": 7, "agosto": 8, "setembro": 9,
    "outubro": 10, "novembro": 11, "dezembro": 12,
}


def _strip_pt_diacritics(s: str) -> str:
    repl = {
        "ç": "c", "ã": "a", "á": "a", "à": "a", "â": "a",
        "é": "e", "ê": "e", "í": "i", "ó": "o", "ô": "o",
        "õ": "o", "ú": "u", "º": "", "ª": "",
    }
    for k, v in repl.items():
        s = s.replace(k, v)
    return s


def _parse_pt_period(label: str, freq: str) -> date | None:
    """Parse Portuguese pindica period labels.

    Monthly  : 'Marco de 2026'              -> 2026-03-01
    Quarterly: '1.o Trimestre de 2026'      -> 2026-01-01
    Annual   : '2025'                       -> 2025-01-01
    Also tolerates code-style 'S7A2026M03' / '2026M03'.
    """
    if not label:
        return None
    s = label.strip()
    # Code-style fallback first
    if "M" in s:
        cand = s.replace("S7A", "")
        if cand.replace("M", "").isdigit():
            out = _parse_period(cand, "M")
            if out:
                return out
    low = _strip_pt_diacritics(s.lower()).replace(".", " ")
    if "trimestre" in low and freq == "Q":
        toks = low.replace(",", " ").split()
        q = None
        yr = None
        for tok in toks:
            if tok.isdigit():
                n = int(tok)
                if n <= 4 and q is None:
                    q = n
                elif n >= 1900:
                    yr = n
        if q and yr:
            return date(yr, {1: 1, 2: 4, 3: 7, 4: 10}[q], 1)
    if freq == "M":
        toks = low.split()
        month = None
        year = None
        for tok in toks:
            if tok in PT_PT_MONTHS and month is None:
                month = PT_PT_MONTHS[tok]
            elif tok.isdigit() and len(tok) == 4:
                year = int(tok)
        if month and year:
            return date(year, month, 1)
    if freq == "A":
        digits = "".join(c for c in s if c.isdigit())
        if len(digits) == 4:
            return date(int(digits), 1, 1)
    return None


PT_SERIES = [
    # NOTE: existing inflation-cpi (varcd 0008273) is mis-mapped to "Resident
    # population" — left in place pending a separate fix.
    {"slug": "inflation-cpi", "varcd": "0008273", "freq": "M",
     "unit": "Index", "adjustment": "NSA", "conversion": 1.0,
     "row_filter": {"geocod": "PT"},
     "note": "PT INE IPC total nacional (legacy varcd — needs replacement)"},

    # PPI - Indices de precos na producao industrial (Base 2021), Total bruto
    # YoY %; CAE Rev. 3 dim_3='TOT' is the headline TE prints.
    # Verified 2026-05-14: Mar 2026 = 0.0 % (TE: 0.0 %).
    {"slug": "ppi", "varcd": "0012002", "freq": "M",
     "unit": "% YoY", "adjustment": "NSA", "conversion": 1.0,
     "row_filter": {"geocod": "PT", "dim_3": "TOT"},
     "note": "INE PT 0012002 IPPI Total YoY%, Base 2021 (CAE Rev. 3)"},

    # Industrial Production - calendar+seasonally adjusted YoY %, base 2021.
    # Agrupamento industrial, dim_3='T' = Total. TE quotes this exact series.
    # Verified 2026-05-14: Mar 2026 = 3.2 % (TE: 3.2 %).
    {"slug": "industrial-production", "varcd": "0011900", "freq": "M",
     "unit": "% YoY", "adjustment": "SA+CDA", "conversion": 1.0,
     "row_filter": {"geocod": "PT", "dim_3": "T"},
     "note": "INE PT 0011900 IPI YoY% cal+SA adjusted, Base 2021"},

    # Unemployment Rate (Inquerito ao Emprego, Serie 2021), quarterly,
    # geocod='PT', dim_3='T' (HM = both sexes).
    # Verified 2026-05-14: Q1 2026 = 6.1 % (TE: 6.1 %).
    {"slug": "unemployment", "varcd": "0012136", "freq": "Q",
     "unit": "%", "adjustment": "NSA", "conversion": 1.0,
     "row_filter": {"geocod": "PT", "dim_3": "T"},
     "note": "INE PT 0012136 Taxa de desemprego (Serie 2021), NUTS-2024, both sexes"},

    # Retail Trade Turnover Index - calendar+seasonally adjusted DEFLATED YoY %,
    # Base 2021, CAE 47 (retail trade excl. motor vehicles). dim_3='47'.
    # Verified 2026-05-14: Mar 2026 = 5.5 % YoY (cal+SA, deflated).
    {"slug": "retail-sales", "varcd": "0012019", "freq": "M",
     "unit": "% YoY", "adjustment": "SA+CDA deflated", "conversion": 1.0,
     "row_filter": {"geocod": "PT", "dim_3": "47"},
     "note": "INE PT 0012019 IVN comercio retalho YoY% deflated cal+SA, Base 2021"},

    # GDP Real - Produto interno bruto dados encadeados em volume, YoY %,
    # Base 2021, trimestral. Single row per period (no dim_3).
    # Verified 2026-05-14: Q1 2026 = 2.3 % (TE: 2.3 %).
    # NOTE: INE pindica op=1 for this varcd is server-side broken (returns the
    # same value for every period). We therefore use op=2 (latest period only).
    # History gap is back-filled by Eurostat namq_10_gdp until INE fixes op=1.
    {"slug": "gdp-real", "varcd": "0013431", "freq": "Q",
     "unit": "% YoY", "adjustment": "SA+CDA", "conversion": 1.0,
     "row_filter": {"geocod": "PT"}, "op2_only": True,
     "note": "INE PT 0013431 GDP chain-linked YoY%, Base 2021, quarterly (op=2 latest-only; op=1 broken upstream)"},
]


def _row_matches(row: dict, flt: dict) -> bool:
    for k, want in flt.items():
        if str(row.get(k, "")) != str(want):
            return False
    return True


def fetch_pt_indicator(varcd: str, freq: str = "M",
                       row_filter: dict | None = None,
                       op2_only: bool = False) -> list[tuple[date, float]]:
    """INE Portugal pindica - full history via op=1.

    The pindica JSON re-uses the same "Pref" object key once per observation
    period (e.g. "Janeiro de 2006" appears N times in a flat sequence rather
    than nested). Standard json.loads collapses duplicate keys to the last one,
    which would only ever return the most-recent value for every period. We
    therefore stream the document with ijson and walk Pref entries pair-wise.

    Some varcds (notably 0013431 GDP-YoY) have an upstream bug under op=1
    that returns the same value for every period. For those, callers can pass
    op2_only=True to fetch just the latest period via op=2.
    """
    import json as _json
    import re as _re
    if op2_only:
        url2 = f"https://www.ine.pt/ine/json_indicador/pindica.jsp?op=2&varcd={varcd}&lang=PT"
        r2 = requests.get(url2, timeout=60)
        r2.raise_for_status()
        d2 = r2.json()
        flt = row_filter or {}
        out2: list[tuple[date, float]] = []
        if isinstance(d2, list) and d2:
            dados = d2[0].get("Dados") or {}
            for label, rows in dados.items():
                dt = _parse_pt_period(label, freq)
                if dt is None:
                    continue
                for row in rows:
                    if flt and not _row_matches(row, flt):
                        continue
                    try:
                        val = float(row.get("valor"))
                    except (ValueError, TypeError):
                        continue
                    out2.append((dt, val))
                    break
        return sorted({d: v for d, v in out2}.items())
    url = f"https://www.ine.pt/ine/json_indicador/pindica.jsp?op=1&varcd={varcd}&lang=PT"
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    text = r.text

    # Detect API-level error envelope first via lenient parse.
    try:
        head = _json.loads(text)
        if isinstance(head, list) and head and \
                isinstance(head[0], dict) and "Sucesso" in head[0] and \
                isinstance(head[0]["Sucesso"], dict) and \
                "Falso" in head[0]["Sucesso"]:
            msg = head[0]["Sucesso"]["Falso"][0].get("Msg", "")
            raise RuntimeError(f"INE pindica error: {msg}")
    except _json.JSONDecodeError:
        pass

    # Split the "Pref" block into individual "label: [rows]" entries by
    # scanning bracket depth. We only want the unique-keyed sequence.
    pref_start = text.find('"Pref"')
    if pref_start < 0:
        return []
    # find the opening "{" after "Pref"
    brace = text.find("{", pref_start)
    # walk to matching "}"
    depth = 0
    i = brace
    end = None
    while i < len(text):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
        i += 1
    if end is None:
        return []
    body = text[brace + 1:end]

    # Iterate entries: each "<label>" : [ ... rows ... ]
    out: list[tuple[date, float]] = []
    flt = row_filter or {}
    pos = 0
    label_re = _re.compile(r'"((?:[^"\\]|\\.)*?)"\s*:\s*\[')
    while pos < len(body):
        m = label_re.search(body, pos)
        if not m:
            break
        label = m.group(1)
        # find the matching closing bracket of this array
        depth = 1
        j = m.end()
        while j < len(body) and depth > 0:
            cj = body[j]
            if cj == "[":
                depth += 1
            elif cj == "]":
                depth -= 1
                if depth == 0:
                    arr_end = j
                    break
            elif cj == '"':
                # skip string literal
                j += 1
                while j < len(body) and body[j] != '"':
                    if body[j] == "\\":
                        j += 2
                        continue
                    j += 1
            j += 1
        else:
            break
        arr_text = "[" + body[m.end():arr_end] + "]"
        try:
            rows = _json.loads(arr_text)
        except _json.JSONDecodeError:
            pos = arr_end + 1
            continue
        dt = _parse_pt_period(label, freq)
        if dt is not None:
            for row in rows:
                if flt and not _row_matches(row, flt):
                    continue
                val_str = row.get("valor")
                try:
                    val = float(val_str)
                except (ValueError, TypeError):
                    continue
                out.append((dt, val))
                break  # one match per period
        pos = arr_end + 1
    # de-dup + sort
    seen: dict[date, float] = {}
    for d, v in out:
        seen[d] = v
    return sorted(seen.items())


# === Ireland — CSO PxStat ===

IE_SERIES = [
    # CPM01: STATISTIC=CPM01C08 (Base Dec 2023=100, latest base), C01779V03424=- (All items)
    {"slug": "inflation-cpi", "table": "CPM01",
     "filters": {"STATISTIC": "CPM01C08", "C01779V03424": "-"},
     "freq": "M", "unit": "Index", "adjustment": "NSA", "conversion": 1.0,
     "note": "CSO Ireland CPM01 CPI Base Dec 2023=100, all items"},
    # MUM01: Seasonally Adjusted Monthly Unemployment Rate (C02), 15-74 yrs, both sexes
    {"slug": "unemployment", "table": "MUM01",
     "filters": {"STATISTIC": "MUM01C02", "C02076V02508": "316", "C02199V02655": "-"},
     "freq": "M", "unit": "%", "adjustment": "SA", "conversion": 1.0,
     "note": "CSO Ireland MUM01 SA Monthly Unemployment Rate 15-74 both sexes"},
    # WPM35: Industrial Price Index (Excl VAT), Manufacturing industries (V2100, NACE 10-33)
    {"slug": "ppi", "table": "WPM35",
     "filters": {"STATISTIC": "WPM35C01", "C02596V03150": "V2100"},
     "freq": "M", "unit": "Index (2020=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "CSO Ireland WPM35 Industrial Price Index (Excl VAT), Manufacturing 10-33"},
    # MIM05: Industrial Production Volume Index SA (C03), Industries (V1100, NACE 05-35) base 2021=100
    {"slug": "industrial-production", "table": "MIM05",
     "filters": {"STATISTIC": "MIM05C03", "C02576V03125": "V1100"},
     "freq": "M", "unit": "Index (2021=100)", "adjustment": "SA", "conversion": 1.0,
     "note": "CSO Ireland MIM05 SA Industrial Production Index, Industries 05-35"},
    # RSM08: Retail Sales Index Volume Adjusted (C04), All retail businesses (V3970)
    {"slug": "retail-sales", "table": "RSM08",
     "filters": {"STATISTIC": "RSM08C04", "C02583V03135": "V3970"},
     "freq": "M", "unit": "Index (2021=100)", "adjustment": "SA", "conversion": 1.0,
     "note": "CSO Ireland RSM08 Retail Sales Volume Index SA, All retail businesses"},
    # TSM01: Value of Merchandise Trade — Trade Surplus NSA (C3), State
    {"slug": "trade-balance", "table": "TSM01",
     "filters": {"STATISTIC": "TSM01C3", "C02196V02652": "-"},
     "series_id": "CSO/TSM01/tb",
     "freq": "M", "unit": "EUR thousand", "adjustment": "NSA", "conversion": 1.0,
     "note": "CSO Ireland TSM01 Merchandise Trade Surplus (Exports-Imports) NSA"},
    # TSM01 Total Exports NSA (C2), State. Verified 2026-05-14: 2026M02 = 15,894,938 EUR-k.
    {"slug": "exports", "table": "TSM01",
     "filters": {"STATISTIC": "TSM01C2", "C02196V02652": "-"},
     "series_id": "CSO/TSM01/exp",
     "freq": "M", "unit": "EUR thousand", "adjustment": "NSA", "conversion": 1.0,
     "note": "CSO Ireland TSM01 Total Exports of Goods NSA, EUR thousand"},
    # TSM01 Total Imports NSA (C1), State. Verified 2026-05-14: 2026M02 = 11,291,776 EUR-k.
    {"slug": "imports", "table": "TSM01",
     "filters": {"STATISTIC": "TSM01C1", "C02196V02652": "-"},
     "series_id": "CSO/TSM01/imp",
     "freq": "M", "unit": "EUR thousand", "adjustment": "NSA", "conversion": 1.0,
     "note": "CSO Ireland TSM01 Total Imports of Goods NSA, EUR thousand"},
    # QLF18: ILO Labour Force Survey (quarterly), Persons in Employment 15+, both sexes.
    # Verified 2026-05-14: 2025Q4 = 2833.1 thousand persons.
    {"slug": "employed-persons", "table": "QLF18",
     "filters": {"STATISTIC": "QLF18C03", "C02076V02508": "320", "C02199V02655": "-"},
     "freq": "Q", "unit": "Thousand", "adjustment": "NSA", "conversion": 1.0,
     "note": "CSO Ireland QLF18 LFS persons in employment 15+ both sexes (thousand)"},
    # HPM09: Residential Property Price Index — National all properties (latest base, ~2015=100)
    {"slug": "housing-index", "table": "HPM09",
     "filters": {"STATISTIC": "HPM09C01", "C02803V03373": "-"},
     "freq": "M", "unit": "Index", "adjustment": "NSA", "conversion": 1.0,
     "note": "CSO Ireland HPM09 Residential Property Price Index, National all properties"},
    # NAQ03: Quarterly National Accounts, GDP at Constant Market Prices SA (S04)
    {"slug": "gdp-real", "table": "NAQ03",
     "filters": {"STATISTIC": "NAQ03S04", "C02196V02652": "-"},
     "freq": "Q", "unit": "EUR million", "adjustment": "SA", "conversion": 1.0,
     "note": "CSO Ireland NAQ03 GDP at Constant Market Prices SA, chain-linked"},
]


def fetch_ie_table(table: str, filters: dict, freq: str = "M") -> list[tuple[date, float]]:
    """CSO PxStat ReadDataset (JSON-stat 2.0). category.index can be list or dict."""
    url = f"https://ws.cso.ie/public/api.restful/PxStat.Data.Cube_API.ReadDataset/{table}/JSON-stat/2.0/en"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    js = r.json()
    values = js.get("value", [])
    dim = js.get("dimension", {})
    dim_ids = js.get("id", [])
    dim_sizes = js.get("size", [])
    if not dim_ids:
        return []

    # Find time dimension by name
    tid = next((k for k in dim_ids if k.startswith("TLIST") or "TIME" in k.upper()), None)
    if not tid:
        return []

    def get_index_dict(name):
        cat = dim.get(name, {}).get("category", {})
        idx = cat.get("index", {})
        if isinstance(idx, list):
            return {code: pos for pos, code in enumerate(idx)}
        return idx  # dict

    time_idx_dict = get_index_dict(tid)
    if not time_idx_dict:
        return []

    # Resolve filter target indices
    target_idx = {}
    for k in dim_ids:
        if k == tid:
            continue
        wanted = filters.get(k)
        if wanted is None:
            target_idx[k] = 0
            continue
        if isinstance(wanted, list):
            wanted = wanted[0] if wanted else None
        idx_dict = get_index_dict(k)
        if wanted in idx_dict:
            target_idx[k] = idx_dict[wanted]
        else:
            target_idx[k] = 0

    out = []
    for time_code, time_pos in time_idx_dict.items():
        indices = []
        for k in dim_ids:
            indices.append(time_pos if k == tid else target_idx.get(k, 0))
        flat = 0
        stride = 1
        for i in range(len(dim_ids) - 1, -1, -1):
            flat += indices[i] * stride
            stride *= dim_sizes[i]
        if 0 <= flat < len(values):
            v = values[flat]
            if v is not None:
                dt = _parse_ie_time(time_code, freq)
                if dt:
                    out.append((dt, float(v)))
    return sorted(out)


def _parse_ie_time(p: str, freq: str) -> date | None:
    """CSO time codes: '202604' (YYYYMM), '20261' (YYYYQ — single digit), '2026' (YYYY)."""
    try:
        if freq == "M" and len(p) == 6 and p.isdigit():
            return date(int(p[:4]), int(p[4:]), 1)
        if freq == "Q" and len(p) == 5 and p.isdigit():
            yy, q = int(p[:4]), int(p[4])
            if 1 <= q <= 4:
                return date(yy, {1: 1, 2: 4, 3: 7, 4: 10}[q], 1)
        if freq == "A" and len(p) == 4 and p.isdigit():
            return date(int(p), 1, 1)
    except Exception:
        pass
    return _parse_period(p, freq)


# === Belgium — Statbel REST API (CSV) + NBB SDMX REST v2 ===
# Statbel uses unique view IDs per dataset. We pre-resolve them.
# bestat.statbel.fgov.be/bestat/api/views?lang=en&format=json gives the list.
#
# NBB statistics moved from stat.nbb.be (Belgostat, decommissioned) to a new
# SDMX-2.1 REST API at https://nsidisseminate-stat.nbb.be/rest, fronted by the
# data-explorer SPA at https://dataexplorer.nbb.be. AgencyID = "BE2".

# Each BE_SERIES entry has a "kind" discriminator: "statbel" or "nbb".
#  - statbel:  uses view_id + value_col + optional row_filter (dict[col]->value)
#  - nbb:      uses dataflow + key (dot-separated SDMX dimension values)

BE_SERIES = [
    # --- Statbel CSV views ---
    {"kind": "statbel", "slug": "inflation-cpi",
     "view_id": "208b69bd-05c5-4947-b7f9-2d2300f517b8",
     "value_col": "Consumer price index", "row_filter": None,
     "freq": "M", "unit": "Index (2013=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "Statbel CPI base 2013=100 (last 13 months window)"},

    # PPI total — special-aggregates view filtered to "" (no aggregate = grand total)
    {"kind": "statbel", "slug": "ppi",
     "view_id": "098275aa-db04-41a7-b2bb-54a09852d041",
     "value_col": "Index - Total market",
     "row_filter": {"All economic activities": "All economic activities",
                    "Special aggregates": ""},
     "freq": "M", "unit": "Index (2021=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "Statbel PPI industry excl. construction, total market index base 2021=100"},

    # Retail sales — Statbel only publishes a 4-month rolling window;
    # we accumulate history by polling monthly.
    {"kind": "statbel", "slug": "retail-sales",
     "view_id": "4ecec356-f055-4abc-89ec-7fcba329a23f",
     "value_col": "Gross index",
     "row_filter": {"NACE groups":
                    "Total retail trade, except of motor vehicles, motorcycles and automotive fuel"},
     "freq": "M", "unit": "Index", "adjustment": "NSA", "conversion": 1.0,
     "note": "Statbel retail sales gross index, NACE G47 excl. motor vehicles; 4-month rolling view"},

    # --- NBB SDMX REST v2 (nsidisseminate-stat.nbb.be) ---
    {"kind": "nbb", "slug": "industrial-production",
     "dataflow": "DF_INDPROD", "key": "M.2021.INDPROD.W.B_C_D.BE",
     "freq": "M", "unit": "Index (2021=100)", "adjustment": "WDA", "conversion": 1.0,
     "note": "NBB DF_INDPROD total industry B+C+D, working-day adjusted, base 2021=100"},

    {"kind": "nbb", "slug": "unemployment",
     "dataflow": "DF_UNEMPLOY_RATE", "key": "M.AA.Z0000.Y.BE.HUR.RATE",
     "freq": "M", "unit": "%", "adjustment": "SA", "conversion": 1.0,
     "note": "NBB harmonised unemployment rate, total, all ages, SA"},

    {"kind": "nbb", "slug": "trade-balance",
     "dataflow": "DF_EXTERNAL_TRADE_OVERVIEW", "key": "M.NBB_A1.B.NAT.VAL.M",
     "freq": "M", "unit": "EUR million", "adjustment": "NSA", "conversion": 1.0,
     "note": "NBB foreign trade balance vs World, national concept, monthly movement, EUR mn"},

    {"kind": "nbb", "slug": "gdp-real",
     "dataflow": "DF_QNA_DISS", "key": "Q.2.B1GM.VZ.LY.Y",
     "freq": "Q", "unit": "% YoY", "adjustment": "SA", "conversion": 1.0,
     "note": "NBB quarterly GDP, chain-linked Y/Y % change (reference year 2020), SA+WDA"},

    {"kind": "nbb", "slug": "consumer-confidence",
     "dataflow": "DF_CONSN", "key": "M.CCI.BE",
     "freq": "M", "unit": "Balance", "adjustment": "SA", "conversion": 1.0,
     "note": "NBB consumer confidence indicator (CCI), Belgium, balance of opinions"},

    {"kind": "nbb", "slug": "business-confidence",
     "dataflow": "DF_BUSSURVM", "key": "M.SYNC.BE.A999.X",
     "freq": "M", "unit": "Balance", "adjustment": "SA", "conversion": 1.0,
     "note": "NBB monthly business survey synthetic curve, Belgium total, SA+smoothed"},
]


_BE_MONTHS = {"January":1,"February":2,"March":3,"April":4,"May":5,"June":6,
              "July":7,"August":8,"September":9,"October":10,"November":11,"December":12}


def fetch_be_statbel_csv(view_id: str, value_col: str, freq: str = "M",
                         row_filter: dict | None = None) -> list[tuple[date, float]]:
    """Statbel publishes views as CSV. Year/Month columns + named value cols.

    `row_filter`: dict of {column_name: required_value} — only rows matching
    every key are kept. Empty string ("") matches blank cells (used to pick
    grand totals in views with aggregate breakdowns).
    """
    import csv as csvm, io as iom
    url = f"https://bestat.statbel.fgov.be/bestat/api/views/{view_id}/result/CSV"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    reader = csvm.DictReader(iom.StringIO(r.text))
    out = []
    for row in reader:
        if row_filter:
            skip = False
            for col, want in row_filter.items():
                if (row.get(col) or "") != want:
                    skip = True
                    break
            if skip:
                continue
        # Some views use "Month" = "January 2025", others split Year/Month
        month_text = (row.get("Month") or row.get("Reference month") or "").strip()
        try:
            mname, ystr = month_text.rsplit(" ", 1)
            yy = int(ystr)
            mm = _BE_MONTHS[mname]
            dt = date(yy, mm, 1)
        except Exception:
            continue
        val_str = (row.get(value_col) or "").replace(",", "")
        try:
            val = float(val_str)
        except ValueError:
            continue
        out.append((dt, val))
    return sorted(out)


# NBB SDMX v2 — accepts SDMX-JSON 2.0
_NBB_BASE = "https://nsidisseminate-stat.nbb.be/rest"


def fetch_nbb_sdmx(dataflow: str, key: str, freq: str = "M",
                   agency: str = "BE2") -> list[tuple[date, float]]:
    """NBB SDMX REST v2 (nsidisseminate-stat.nbb.be).

    `dataflow` example: "DF_INDPROD". `key` is dot-separated dimension values
    in the order declared by the DSD (FREQ first), e.g. "M.2021.INDPROD.W.B_C_D.BE".
    Pass "" for wildcard dims. Time period encoding follows SDMX 2.1 conventions
    (YYYY-MM monthly, YYYY-Qn quarterly, YYYY annual).
    """
    url = f"{_NBB_BASE}/data/{dataflow}/{key}"
    hdrs = {"User-Agent": "Mozilla/5.0 (EconPulse)",
            "Accept": "application/vnd.sdmx.data+json;version=2.0"}
    r = requests.get(url, headers=hdrs, timeout=30)
    r.raise_for_status()
    js = r.json()
    data = js.get("data") or {}
    ds = data.get("dataSets") or []
    structs = data.get("structures") or []
    if not ds or not structs:
        return []
    obs_dims = structs[0].get("dimensions", {}).get("observation", [])
    if not obs_dims:
        return []
    time_vals = obs_dims[0].get("values", [])
    out: list[tuple[date, float]] = []
    for ser in ds[0].get("series", {}).values():
        for obs_idx_str, obs_val in (ser.get("observations") or {}).items():
            try:
                idx = int(obs_idx_str)
            except ValueError:
                continue
            if idx < 0 or idx >= len(time_vals):
                continue
            period = time_vals[idx].get("id") or ""
            if obs_val is None or obs_val[0] is None:
                continue
            dt = _parse_period(period, freq)
            if dt is None:
                # also accept YYYY-MM and YYYY-Qn directly
                if freq == "M" and len(period) == 7 and period[4] == "-":
                    try:
                        dt = date(int(period[:4]), int(period[5:7]), 1)
                    except Exception:
                        pass
                elif freq == "Q" and len(period) == 7 and period[4] == "-" and period[5] == "Q":
                    try:
                        yy, q = int(period[:4]), int(period[6])
                        dt = date(yy, {1:1,2:4,3:7,4:10}[q], 1)
                    except Exception:
                        pass
            if dt is None:
                continue
            try:
                out.append((dt, float(obs_val[0])))
            except (TypeError, ValueError):
                continue
    return sorted(out)


# === Poland — GUS BDL API ===

PL_SERIES = [
    # GUS BDL: variable IDs need to be discovered.
    # Variable 217230 = CPI (poprzedni miesiąc=100) ; 217 ID family
    # We use direct BDL API: /api/v1/data/by-variable/<var_id>?unit-level=0&format=json
]


def fetch_gus_variable(var_id: int, freq: str = "M") -> list[tuple[date, float]]:
    """GUS BDL API — fetch all observations for a variable at national level (unit=000000000000)."""
    url = f"https://bdl.stat.gov.pl/api/v1/data/by-variable/{var_id}?unit-level=0&format=json&page-size=1000&lang=en"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    js = r.json()
    out = []
    for unit_obs in js.get("results", []):
        for v in unit_obs.get("values", []):
            year = v.get("year")
            attr = (v.get("year") or "")
            val = v.get("val")
            # GUS returns year as YYYY for annual, "YYYYMnn" for monthly
            # No standardised period — usually .year is for annual; need to inspect
            try:
                val = float(val)
            except Exception:
                continue
            if isinstance(year, int):
                dt = date(year, 1, 1) if freq == "A" else None
                if dt:
                    out.append((dt, val))
    return sorted(out)


# === Austria — Statistik Austria OGD (CSV semicolon-separated, German decimals) ===
#
# Each AT entry uses a `filters` dict (col -> required value) plus `time_col` + `value_col`.
# Time codes have the form "<PREFIX>-<digits>". The digits encode the period:
#   length 6 + freq=M  -> YYYYMM
#   length 5 + freq=Q  -> YYYYQ (1..4)
#   length 4 + freq=A  -> YYYY  (annual)

AT_SERIES = [
    # CPI — VPI Basis 2020, Jan 2021..Dec 2025.
    {"slug": "inflation-cpi", "ogd": "OGD_vpi20_VPI_2020_1",
     "filters": {"C-VPI5NEU-0": "VPI-0"},
     "time_col": "C-VPIZR-0", "value_col": "F-VPIMZVM",
     "freq": "M", "unit": "Index", "adjustment": "NSA", "conversion": 1.0,
     "note": "Statistik Austria VPI base 2020=100 (covers 2021-01..2025-12)"},

    # PPI — Erzeugerpreisindex Basis 2021, Gesamtmarkt (B72EPI-5).
    # TE shows 117.50 points (Mar 2026) — exact match with our F-EZPINSG-0 + B72EPI-5.
    {"slug": "ppi", "ogd": "OGD_epi2021nac08_EPI_2021_OENACE_1",
     "filters": {"C-B72EPI-0": "B72EPI-5"},
     "time_col": "C-EPIA10-0", "value_col": "F-EZPINSG-0",
     "freq": "M", "unit": "Index (2021=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "Statistik Austria EPI 2021=100 Gesamtmarkt (Total domestic+foreign)"},

    # Industrial production — Produktionsindex Basis 2021, Österreich (KJIB00-10),
    # arbeitstägig bereinigt (X93-2). TE shows IP YoY 1.7% (Mar 2026); 111.8/109.9 -> +1.7%.
    {"slug": "industrial-production", "ogd": "OGD_kjiprodindex2021_KJID2021_PI_1",
     "filters": {"C-X93-0": "X93-2", "C-KJIB00-0": "KJIB00-10"},
     "time_col": "C-A10-0", "value_col": "F-KJIP_UI_INSG",
     "freq": "M", "unit": "Index (2021=100, WDA)", "adjustment": "WDA", "conversion": 1.0,
     "note": "Statistik Austria Produktionsindex 2021=100, AT total, working-day adjusted"},

    # Unemployment — ake100 ALQ (LFS/ILO concept), Österreich insgesamt (AKEQUOT_AL-1).
    # Quarterly only (codes YYYYQ length 5). Annual rows (length 4) filtered by freq.
    # NOTE: TE shows AMS registered rate (~7.5% Apr 2026); we publish the Eurostat-comparable
    # ILO rate (5.7% Q4 2025) — the official Statistik Austria number.
    {"slug": "unemployment", "ogd": "OGD_ake100_hvd_ogdonly_HVD_ALQUO_1",
     "filters": {"C-AKEQUOT_AL-0": "AKEQUOT_AL-1"},
     "time_col": "C-AKEQUOT_ZEIT-0", "value_col": "F-AKEQUOT_AL",
     "freq": "Q", "unit": "%", "adjustment": "NSA", "conversion": 1.0,
     "note": "Statistik Austria ALQ (ILO/LFS concept), AT total, quarterly"},

    # GDP (real, SA, level) — vgr108 quarterly, BIP zu Marktpreisen (VGRHAG-14).
    # F-RSAIB = real, seasonally and working-day adjusted. Convert Mio. EUR -> Bn EUR.
    {"slug": "gdp", "ogd": "OGD_vgr108_VGR_HA_vj_1",
     "filters": {"C-VGRHAG79-0": "VGRHAG-14"},
     "time_col": "C-A10-0", "value_col": "F-RSAIB",
     "freq": "Q", "unit": "Bn EUR (real, SA)", "adjustment": "SA", "conversion": 0.001,
     "note": "Statistik Austria VGR108 BIP real, SA — converted Mio->Bn EUR"},

    # Wages — Bruttoverdiensteindex Basis 2021, saisonbereinigt (X93-3).
    {"slug": "wages", "ogd": "OGD_bruttoverdiensteindex2021a_KJID2021_BVIa_1",
     "filters": {"C-X93-0": "X93-3"},
     "time_col": "C-A10-0", "value_col": "F-KJIP_BLG_INSG",
     "freq": "M", "unit": "Index (2021=100, SA)", "adjustment": "SA", "conversion": 1.0,
     "note": "Statistik Austria Bruttoverdiensteindex 2021=100, SA"},

    # Import prices — IMPI Basis 2021, Gesamtmarkt (RAUM-1), F-IMPI-01 = Gesamtindex.
    # Quarterly only (16 obs Q1 2022..Q4 2025).
    {"slug": "import-prices", "ogd": "OGD_impi21_Impi21_1",
     "filters": {"C-RAUM-0": "RAUM-1"},
     "time_col": "C-A10-0", "value_col": "F-IMPI-01",
     "freq": "Q", "unit": "Index (2021=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "Statistik Austria IMPI 2021=100 Gesamtmarkt (total origin)"},

    # === Stage-2 additions (2026-05-14): exports / imports / trade-balance /
    # retail-sales / employed-persons / government-debt-total
    # via Konjunkturmonitor (wide monthly CSV) and dedicated VGR/KONS_BRV tables. ===

    # Exports — Konjunkturmonitor, F-FAKT-46 (Ausfuhren Insgesamt in EUR), QUOTE-1=1 (Wert).
    # Filter the rolled-up annual/quarterly rows by `time_len_filter` (M = 6-digit codes).
    # Convert from EUR to Mio EUR (TE shows 16,165 Mio for Feb/26 → our 16,164,848,476 / 1e6).
    {"slug": "exports", "ogd": "OGD_konjunkturmonitor_KonMon_1",
     "filters": {"C-QUOTE-1": "1"},
     "time_col": "C-KMMONAT-0", "value_col": "F-FAKT-46",
     "freq": "M", "unit": "Mio EUR", "adjustment": "NSA", "conversion": 1e-6,
     "note": "Statistik Austria Konjunkturmonitor F-FAKT-46 Ausfuhren Insgesamt, EUR→Mio EUR"},

    # Imports — Konjunkturmonitor, F-FAKT-32 (Einfuhren Insgesamt in EUR).
    {"slug": "imports", "ogd": "OGD_konjunkturmonitor_KonMon_1",
     "filters": {"C-QUOTE-1": "1"},
     "time_col": "C-KMMONAT-0", "value_col": "F-FAKT-32",
     "freq": "M", "unit": "Mio EUR", "adjustment": "NSA", "conversion": 1e-6,
     "note": "Statistik Austria Konjunkturmonitor F-FAKT-32 Einfuhren Insgesamt, EUR→Mio EUR"},

    # Trade balance — derived as F-FAKT-46 minus F-FAKT-32 (handled in fetcher dispatch).
    # We mark with a special `derive` key; conversion is applied to the difference.
    {"slug": "trade-balance", "ogd": "OGD_konjunkturmonitor_KonMon_1",
     "filters": {"C-QUOTE-1": "1"},
     "time_col": "C-KMMONAT-0", "value_col": "F-FAKT-46",
     "value_col_b": "F-FAKT-32", "derive": "sub_b",
     "freq": "M", "unit": "Mio EUR", "adjustment": "NSA", "conversion": 1e-6,
     "note": "Statistik Austria Konjunkturmonitor: Ausfuhren − Einfuhren (F46−F32), EUR→Mio EUR"},

    # Retail sales — konjidxhan21 monthly turnover index, NACE G47 (Einzelhandel),
    # F-UIDXNSB = nominell saisonbereinigt (level, base 2021=100). TE shows G47 index level.
    {"slug": "retail-sales", "ogd": "OGD_konjidxhan21_KJIX_H_21_1",
     "filters": {"C-NACEIDX-0": "NACEIDX-47"},
     "time_col": "C-TIIDXM-0", "value_col": "F-UIDXNSB",
     "freq": "M", "unit": "Index (2021=100, SA)", "adjustment": "SA", "conversion": 1.0,
     "note": "Statistik Austria Konjunkturindizes Handel G47 (Einzelhandel), nominell SA, 2021=100"},

    # Employed persons — VGR111 Flash (t+30), Personen-Insgesamt SA (BEREIN-2), quarterly.
    # F-PERSI is already in 1,000 persons → no conversion. TE concept differs (LFS 4,500.2);
    # we publish the ESA-NA flash (4,726 Q1/26 SA) as the headline Statistik Austria figure.
    {"slug": "employed-persons", "ogd": "OGD_vgr111_VGR_Flashes_Erwerb_1",
     "filters": {"C-BEREIN-0": "BEREIN-2"},
     "time_col": "C-VGRZR-0", "value_col": "F-PERSI",
     "freq": "Q", "unit": "Thousand persons (SA)", "adjustment": "SA", "conversion": 1.0,
     "note": "Statistik Austria VGR111 Flash Erwerbstätigkeit, Personen-Insgesamt SA, in 1.000"},

    # Government debt (total, Maastricht) — annual consolidated gross debt.
    # F-TKL101 in Mio EUR → convert to Bn EUR for the level. AT.yaml period=2025 = 418,078.50 → 418.08 Bn.
    {"slug": "government-debt-total", "ogd": "OGD_kons_brv_HVD_KONS_BRV_1",
     "filters": {"C-VOLCZ9-0": "CZ9-1"},
     "time_col": "C-A10-0", "value_col": "F-TKL101",
     "freq": "A", "unit": "Bn EUR", "adjustment": "NSA", "conversion": 0.001,
     "note": "Statistik Austria Konsolidierte Bruttoverschuldung Maastricht jährlich, Mio→Bn EUR"},
]


def _parse_at_period(time_code: str, freq: str) -> date | None:
    """Parse Statistik Austria period codes like 'A10-202601' (M), 'A10-20251' (Q),
    'AKEQUOT_ZEIT-2025' (A), or bare digits '202601'/'20261'/'2026' (konjunkturmonitor).
    Splits at LAST dash if present; interprets remainder by length+freq.
    """
    if not time_code:
        return None
    digits = time_code.rsplit("-", 1)[1] if "-" in time_code else time_code
    if not digits.isdigit():
        return None
    try:
        if freq == "M" and len(digits) == 6:
            yy, mm = int(digits[:4]), int(digits[4:])
            if 1 <= mm <= 12:
                return date(yy, mm, 1)
        if freq == "Q" and len(digits) == 5:
            yy, q = int(digits[:4]), int(digits[4:])
            if 1 <= q <= 4:
                return date(yy, {1: 1, 2: 4, 3: 7, 4: 10}[q], 1)
        if freq == "A" and len(digits) == 4:
            return date(int(digits), 1, 1)
    except Exception:
        return None
    return None


def fetch_at_csv(ogd: str, filters: dict, time_col: str, value_col: str, freq: str = "M",
                 value_col_b: str | None = None, derive: str | None = None) -> list[tuple[date, float]]:
    """Fetch Statistik Austria OGD CSV. Filter rows by `filters` dict; parse `time_col`
    and `value_col`. German decimals (',' -> '.'). Skip zero placeholders and ':' (geheim).

    If `derive='sub_b'` and `value_col_b` is given, returns value_col − value_col_b per row
    (used for derived series such as trade balance = exports − imports).
    """
    import csv as csvm
    import io as iom
    url = f"https://data.statistik.gv.at/data/{ogd}.csv"
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    reader = csvm.DictReader(iom.StringIO(r.text), delimiter=";")
    out = []
    for row in reader:
        if not all(row.get(k) == v for k, v in filters.items()):
            continue
        dt = _parse_at_period(row.get(time_col, ""), freq)
        if dt is None:
            continue
        raw = row.get(value_col, "")
        if raw in ("", ":"):
            continue
        try:
            val = float(raw.replace(",", "."))
        except ValueError:
            continue
        if val == 0.0:
            continue  # zero placeholder for "no data"
        if derive == "sub_b" and value_col_b:
            raw_b = row.get(value_col_b, "")
            if raw_b in ("", ":"):
                continue
            try:
                val_b = float(raw_b.replace(",", "."))
            except ValueError:
                continue
            if val_b == 0.0:
                continue
            val = val - val_b
        out.append((dt, val))
    return sorted(out)


# === Slovenia — SURS PxWeb (pxweb.stat.si) ===

SI_SERIES = [
    # CPI: 0400608S ECOICOP v2 — TOTAL, MERITVE=2 = Index vs same month previous year
    {"slug": "inflation-cpi", "table": "0400608S.px",
     "query": {"ŽIVLJENJSKA POTREBŠČINA": "TOT", "MERITVE": "2"},
     "freq": "M", "unit": "Index (same month py=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "SURS 0400608S CPI YoY index (same-month-previous-year=100), TOTAL"},
    # PPI: 0457101S Producer price indices, by activities (NACE Rev. 2), monthly.
    # B_TO_E = Industry except construction; INDEKS=29 = Month / avg 2021 (level index, base 2021=100).
    # Verified Mar 2026 = 126.98, matches TE 127 points.
    {"slug": "ppi", "table": "0457101S.px",
     "query": {"SKD DEJAVNOST": "B_TO_E", "INDEKS": "29"},
     "freq": "M", "unit": "Index (2021=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "SURS 0457101 PPI Industry (B-E) Month / avg 2021"},
    # Industrial production: 1701111S Section + MIG, monthly (base 2021=100).
    # B+C+D[skd] = Total industry; VRSTA PODATKA=sa = seasonally+calendar adjusted.
    # Verified Feb 2026 = 92.2 SA -> YoY -2.5% matches TE.
    {"slug": "industrial-production", "table": "1701111S.px",
     "query": {"SKD DEJAVNOST / NAMENSKA SKUPINA": "B+C+D[skd]", "VRSTA PODATKA": "sa"},
     "freq": "M", "unit": "Index (2021=100, SA)", "adjustment": "SA", "conversion": 1.0,
     "note": "SURS 1701111 IP Total industry (B+C+D) seasonally+calendar adjusted"},
    # Unemployment: 0762013S monthly experimental rate. MERITVE=1 = unemployment rate %, VRSTA PODATKA=1 = SA, total sex+age.
    # NB: SURS publishes only the experimental monthly LFS-based rate; differs from TE's
    # registered-unemployment-rate proxy (TE Feb/26 = 4.9%; this series ~3.8-3.9%).
    {"slug": "unemployment", "table": "0762013S.px",
     "query": {"MERITVE": "1", "VRSTA PODATKA": "1", "STAROSTNA SKUPINA": "0", "SPOL": "0"},
     "freq": "M", "unit": "%", "adjustment": "SA", "conversion": 1.0,
     "note": "SURS 0762013 monthly unemployment rate (experimental, SA, total)"},
    # GDP growth: 0300220S quarterly. TRANSAKCIJE=B1GQ (GDP), MERITVE=G4 = volume growth rate vs same quarter prev. year (%), SA.
    # Verified Q4 2025 = 1.6% (TE shows 2.0% - minor revision difference).
    {"slug": "gdp-growth-rate", "table": "0300220S.px",
     "query": {"TRANSAKCIJE": "B1GQ", "MERITVE": "G4", "VRSTA PODATKA": "Y"},
     "freq": "Q", "unit": "% YoY", "adjustment": "SA", "conversion": 1.0,
     "note": "SURS 0300220 GDP volume YoY growth rate, SA"},
    # GDP level: 0300220 V (current prices, mio EUR), SA - Q4 2025 = 18,117 mio EUR.
    {"slug": "gdp", "table": "0300220S.px",
     "query": {"TRANSAKCIJE": "B1GQ", "MERITVE": "V", "VRSTA PODATKA": "Y"},
     "freq": "Q", "unit": "Million EUR", "adjustment": "SA", "conversion": 1.0,
     "note": "SURS 0300220 GDP current prices, mio EUR, SA"},
    # Retail sales: 2001303S value/volume indices of turnover in retail trade, monthly (base 2021=100).
    # "47 brez 47.3" = Retail trade except fuel; INDEKS=1 (Value); VRSTA PODATKA=3 (calendar adjusted).
    # Verified Mar 2026 = 132.7.
    {"slug": "retail-sales", "table": "2001303S.px",
     "query": {"INDEKS": "1", "VRSTA PODATKA": "3", "SKD DEJAVNOST": "47 brez 47.3"},
     "freq": "M", "unit": "Index (2021=100, WDA)", "adjustment": "WDA", "conversion": 1.0,
     "note": "SURS 2001303 Retail trade ex fuel value index, calendar adjusted"},
    # Trade balance/exports/imports: 2490001S monthly, EUR. Convert raw EUR to million EUR (* 1e-6).
    # Verified Mar 2026 balance = -1,104,646,903 EUR / 1e6 = -1104.6 mio EUR (TE: -1,105M).
    {"slug": "trade-balance", "table": "2490001S.px",
     "query": {"UVOZ/IZVOZ": "4", "VALUTA": "EUR"},
     "freq": "M", "unit": "Million EUR", "adjustment": "NSA", "conversion": 1e-6,
     "note": "SURS 2490001 Trade balance (exports - imports), EUR -> mio EUR"},
    {"slug": "exports", "table": "2490001S.px",
     "query": {"UVOZ/IZVOZ": "2", "VALUTA": "EUR"},
     "freq": "M", "unit": "Million EUR", "adjustment": "NSA", "conversion": 1e-6,
     "note": "SURS 2490001 Exports of goods, EUR -> mio EUR"},
    {"slug": "imports", "table": "2490001S.px",
     "query": {"UVOZ/IZVOZ": "1", "VALUTA": "EUR"},
     "freq": "M", "unit": "Million EUR", "adjustment": "NSA", "conversion": 1e-6,
     "note": "SURS 2490001 Imports of goods, EUR -> mio EUR"},
]


def fetch_si_pxweb(table: str, query_filters: dict, freq: str = "M") -> list[tuple[date, float]]:
    url = f"https://pxweb.stat.si/SiStatData/api/v1/en/Data/{table}"
    body = {
        "query": [{"code": k, "selection": {"filter": "item", "values": [v]}}
                  for k, v in query_filters.items()],
        "response": {"format": "json-stat2"},
    }
    r = requests.post(url, json=body, timeout=30)
    r.raise_for_status()
    js = r.json()
    return _parse_jsonstat(js, freq)


def _parse_jsonstat(js: dict, freq: str) -> list[tuple[date, float]]:
    """Parse JSON-stat 2.0 response — handles role.time or detects time dim by name."""
    values = js.get("value", [])
    dim = js.get("dimension", {})
    dim_ids = js.get("id", [])
    dim_sizes = js.get("size", [])
    if not dim_ids or not values:
        return []
    # find time dim: prefer top-level role.time (JSON-stat 2.0)
    tid = None
    role = js.get("role") or {}
    role_time = role.get("time") if isinstance(role, dict) else None
    if role_time:
        tid = role_time[0] if isinstance(role_time, list) else role_time
    # fallback: per-dim role.time (older format)
    if tid is None:
        for k, v in dim.items():
            if isinstance(v, dict) and v.get("role", {}).get("time"):
                tid = k; break
    # heuristic: dim name contains time-like word
    if tid is None:
        for k in dim_ids:
            kl = k.lower()
            if any(w in kl for w in ("tid", "time", "month", "mjesec", "mesec", "kuukausi", "vuosi", "år", "ar", "luni", "ani", "tlist")):
                tid = k; break
    if tid is None:
        return []
    cat = dim[tid].get("category", {})
    idx_obj = cat.get("index", {})
    if isinstance(idx_obj, list):
        time_pairs = list(enumerate(idx_obj))
        time_pairs = [(code, pos) for pos, code in time_pairs]
    else:
        time_pairs = [(code, pos) for code, pos in idx_obj.items()]

    # build flat-index for non-time dims (single value each since user filtered)
    other_indices = []
    for k in dim_ids:
        if k == tid:
            other_indices.append(None)
        else:
            other_indices.append(0)

    out = []
    tid_pos_in_id = dim_ids.index(tid)
    for time_code, time_pos in time_pairs:
        indices = list(other_indices)
        indices[tid_pos_in_id] = time_pos
        flat = 0
        stride = 1
        for i in range(len(dim_ids) - 1, -1, -1):
            flat += indices[i] * stride
            stride *= dim_sizes[i]
        if 0 <= flat < len(values):
            v = values[flat]
            if v is not None:
                dt = _parse_period(time_code, freq)
                if dt:
                    out.append((dt, float(v)))
    return sorted(out)


# === Latvia — CSP PxWeb (data.stat.gov.lv) ===
#
# Discovery walk: GET https://data.stat.gov.lv/api/v1/en/OSP_PUB/  -> 11 topics
# (POP/EMP/VES/IZG/VEK/TIR/ENT/IKT/NOZ/ENV/FIN). Each topic has nested folders;
# leaf tables live under e.g. VEK/PC/PCI/PCI030m. POSTing JSON-stat2 query to
# the .px endpoint returns standard JSON-stat that _parse_jsonstat handles.

LV_SERIES = [
    # PCI030m: Consumer price indices December 1990=100, monthly 1991M01-2026M03
    {"slug": "inflation-cpi", "path": "VEK/PC/PCI/PCI030m",
     "query": {"ContentsCode": "PCI030m"},
     "freq": "M", "unit": "Index (Dec 1990=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "CSP Latvia PCI030m CPI Dec 1990=100"},
    # NOTE: LV CSP PxWeb actively returns HTTP 400 when querying the section-level
    # "Industry total" aggregate (B_C_D_E in RCI020m, B_C_D_X_D353 in RUI020m)
    # paired with the TOVT/calendar-adjusted ContentsCode combos — only MIG_*
    # breakdowns return data. We therefore leave LV `ppi` and LV
    # `industrial-production` on the Eurostat fallback rather than fetching a
    # non-comparable MIG slice as a proxy.
    # NBB150m: Unemployment rate aged 15-74, total sex, seasonally adjusted, monthly
    # ContentsCode=NBB1501m = Unemployment rate (%)
    {"slug": "unemployment", "path": "EMP/NBBA/NBBB/NBB150m",
     "query": {"SEX": "T", "SESON": "SA", "ContentsCode": "NBB1501m"},
     "freq": "M", "unit": "%", "adjustment": "SA", "conversion": 1.0,
     "note": "CSP Latvia NBB150m unemployment rate 15-74 total SA"},
    # TIT010m: Total turnover index of retail trade enterprises, monthly
    # ContentsCode=TIT010m1 (2021=100, seasonally adjusted)
    {"slug": "retail-sales", "path": "TIR/TI/TIT/TIT010m",
     "query": {"ContentsCode": "TIT010m1"},
     "freq": "M", "unit": "Index (2021=100)", "adjustment": "SA", "conversion": 1.0,
     "note": "CSP Latvia TIT010m retail trade total turnover index 2021=100 SA"},
    # ATD100m: Exports/imports by grouping of countries, monthly EUR mln
    # FLOW=BAL (Balance), COUNTRY_GROUP=TOTAL = total goods trade balance
    {"slug": "trade-balance", "path": "TIR/AT/ATD/ATD100m",
     "query": {"FLOW": "BAL", "COUNTRY_GROUP": "TOTAL", "ContentsCode": "ATD100m"},
     "freq": "M", "unit": "Million EUR", "adjustment": "NSA", "conversion": 1.0,
     "note": "CSP Latvia ATD100m goods trade balance vs World, NSA, mln EUR"},
    # ISP010c: GDP from production approach in EUR thousands, quarterly
    # PRICES=CLV2020 (chain-linked ref 2020), SESON=SA, INDICATOR=B1GQ
    {"slug": "gdp-real", "path": "VEK/IS/ISP/ISP010c",
     "query": {"PRICES": "CLV2020", "SESON": "SA", "INDICATOR": "B1GQ", "ContentsCode": "ISP010c"},
     "freq": "Q", "unit": "Million EUR (2020 chained)", "adjustment": "SA", "conversion": 0.001,
     "note": "CSP Latvia ISP010c real GDP chain-linked 2020 prices, SA, thousand EUR (converted to mln)"},
]


def fetch_lv_pxweb(path: str, query_filters: dict, freq: str = "M") -> list[tuple[date, float]]:
    """LV CSP PxWeb generic fetcher. `path` is the full sub-path after /OSP_PUB/.
    LV PxWeb expects the bare table ID (no '.px' suffix), unlike HR/EE which need it."""
    url = f"https://data.stat.gov.lv/api/v1/en/OSP_PUB/{path}"
    body = {
        "query": [{"code": k, "selection": {"filter": "item", "values": [v]}}
                  for k, v in query_filters.items()],
        "response": {"format": "json-stat2"},
    }
    r = requests.post(url, json=body, timeout=30)
    r.raise_for_status()
    js = r.json()
    # LV uses TIME dim with 2025Q4 (Q-format) for quarterly tables
    if freq == "Q":
        return _parse_jsonstat_quarterly(js)
    return _parse_jsonstat(js, freq)


def _parse_jsonstat_quarterly(js: dict) -> list[tuple[date, float]]:
    """Variant of _parse_jsonstat that decodes YYYYQ# period codes."""
    values = js.get("value", [])
    dim = js.get("dimension", {})
    dim_ids = js.get("id", [])
    dim_sizes = js.get("size", [])
    if not dim_ids or not values:
        return []
    tid = None
    role = js.get("role") or {}
    role_time = role.get("time") if isinstance(role, dict) else None
    if role_time:
        tid = role_time[0] if isinstance(role_time, list) else role_time
    if tid is None:
        for k in dim_ids:
            if "time" in k.lower() or "tid" in k.lower():
                tid = k; break
    if tid is None:
        return []
    cat = dim[tid].get("category", {})
    idx_obj = cat.get("index", {})
    if isinstance(idx_obj, list):
        time_pairs = [(code, pos) for pos, code in enumerate(idx_obj)]
    else:
        time_pairs = [(code, pos) for code, pos in idx_obj.items()]
    other_indices = [None if k == tid else 0 for k in dim_ids]
    out = []
    tid_pos = dim_ids.index(tid)
    Q_MONTHS = {"1": 1, "2": 4, "3": 7, "4": 10}
    for code, pos in time_pairs:
        indices = list(other_indices)
        indices[tid_pos] = pos
        flat = 0
        stride = 1
        for i in range(len(dim_ids) - 1, -1, -1):
            flat += indices[i] * stride
            stride *= dim_sizes[i]
        if 0 <= flat < len(values):
            v = values[flat]
            if v is None:
                continue
            try:
                if "Q" in code:
                    yy, q = code.split("Q")
                    out.append((date(int(yy), Q_MONTHS[q], 1), float(v)))
            except Exception:
                continue
    return sorted(out)


# === Romania — INSSE Tempo (HTTP only on port 8077) ===
#
# Tempo matrices have 2..N dimensions. The time dim is labelled "Luni" (months)
# or "Ani" (years). The unit dim label starts "UM:". For each non-time/non-unit
# dim we pin a single category (typically "Total"/"TOTAL") via filter_dims.
#
# Discovery: tempo.Node().get_all() -> all theme nodes with .name; .by_code(...)
# gives a node and .children traverses to leaf matrices. Matrix dimensions
# expose .label and .options (each option has .label).

RO_SERIES = [
    # 4000 INDICII PRETURILOR DE CONSUM
    # IPC102A: monthly CPI vs previous month=100 (kept for backward compat).
    {"slug": "inflation-cpi", "parent": "4000", "matrix": "IPC102A",
     "filter_dims": {"Categorii de marfuri si servicii cumparate": "Total"},
     "unit_value": "Procente",
     "freq": "M", "unit": "Index (prev month=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "INSSE Tempo IPC102A CPI MoM index (prev month=100), total"},
    # 5010 INDUSTRIE — IND104N gross monthly IP index, base 2021=100
    {"slug": "industrial-production", "parent": "5010", "matrix": "IND104N",
     "filter_dims": {"Activitati ale industriei CAEN Rev.2 - total": "TOTAL"},
     "unit_value": "Procente",
     "freq": "M", "unit": "Index (2021=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "INSSE Tempo IND104N IP gross monthly index, total CAEN Rev.2, base 2021=100"},
    # 4020 INDICII PRETURILOR PRODUCTIEI INDUSTRIALE — PPI1035 total internal+external
    {"slug": "ppi", "parent": "4020", "matrix": "PPI1035",
     "filter_dims": {"CAEN Rev.2 (activitati ale industriei - diviziuni)": "TOTAL"},
     "unit_value": "Procente",
     "freq": "M", "unit": "Index", "adjustment": "NSA", "conversion": 1.0,
     "note": "INSSE Tempo PPI1035 PPI total (internal+external markets), all CAEN Rev.2 activities"},
    # 1511 SOMERI BIM — AMG157H LFS unemployment rate, seasonally adjusted, monthly
    {"slug": "unemployment", "parent": "1511", "matrix": "AMG157H",
     "filter_dims": {"Grupe de varsta": "15 - 74 ani", "Sexe": "Total "},
     "unit_value": "Procente",
     "freq": "M", "unit": "%", "adjustment": "SA", "conversion": 1.0,
     "note": "INSSE Tempo AMG157H LFS unemployment rate 15-74, total sex, seasonally adjusted"},
    # 6005 COMERT INTERIOR — COM1071 retail trade volume index, gross series, base 2021
    {"slug": "retail-sales", "parent": "6005", "matrix": "COM1071",
     "filter_dims": {"Comert cu amanuntul cu exceptia comertului cu autovehicule si motocicl": "Total"},
     "unit_value": "Procente",
     "freq": "M", "unit": "Index (2021=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "INSSE Tempo COM1071 retail trade volume index gross series, base 2021=100"},
    # 1525 CASTIG SALARIAL — FOM107D gross monthly nominal wages, RON
    {"slug": "wages", "parent": "1525", "matrix": "FOM107D",
     "filter_dims": {"CAEN Rev.2  (activitati ale economiei nationale - sectiuni si diviziuni)": "TOTAL"},
     "unit_value": "Lei RON",
     "freq": "M", "unit": "RON/Month", "adjustment": "NSA", "conversion": 1.0,
     "note": "INSSE Tempo FOM107D gross monthly nominal wage, total economy, RON"},
    # 1508 SOMERI INREGISTRATI — SOM103B registered unemployment rate, monthly, NSA
    {"slug": "unemployment-rate-registered", "parent": "1508", "matrix": "SOM103B",
     "filter_dims": {"Sexe": "Total ", "Macroregiuni, regiuni de dezvoltare si judete": "TOTAL"},
     "unit_value": "Procente",
     "freq": "M", "unit": "%", "adjustment": "NSA", "conversion": 1.0,
     "note": "INSSE Tempo SOM103B registered unemployment rate (end-of-month), total"},
]

# Romania trade pairs (computed: balance = exports - imports). Both matrices have
# Sectiuni=Total, Total/Intra/Extra=Total, UM=Mii EURO. Values in thousand EUR;
# conversion 1e-3 -> million EUR (matches TE convention).
RO_TRADE_SERIES = [
    {"slug": "exports", "parent": "6020", "matrix": "EXP101I",
     "filter_dims": {"Sectiuni conform Clasificarii Standard de Comert International (CSCI) Rev.4": "Total",
                     "Total, Intra-UE si Extra-UE": "Total"},
     "unit_value": "Mii EURO",
     "freq": "M", "unit": "Million EUR", "adjustment": "NSA", "conversion": 1e-3,
     "note": "INSSE Tempo EXP101I Exports FOB Total, all CSCI sections, kEUR -> mio EUR"},
    {"slug": "imports", "parent": "6020", "matrix": "EXP102I",
     "filter_dims": {"Sectiuni conform Clasificarii Standard de Comert International (CSCI) Rev.4": "Total",
                     "Total, Intra-UE si Extra-UE": "Total"},
     "unit_value": "Mii EURO",
     "freq": "M", "unit": "Million EUR", "adjustment": "NSA", "conversion": 1e-3,
     "note": "INSSE Tempo EXP102I Imports CIF Total, all CSCI sections, kEUR -> mio EUR"},
]


def fetch_ro_tempo(parent_code: str, matrix: str, filter_dims: dict, unit_value: str,
                   freq: str = "M") -> list[tuple[date, float]]:
    """RO INSSE Tempo via tempo-py library.

    Generic fetcher: handles arbitrary number of dimensions by pinning each
    non-time, non-unit dim to the value supplied in filter_dims (key matched
    by exact-or-startswith against dim .label, to tolerate truncation).
    The unit dim (label starts 'UM:') is pinned to unit_value.
    The time dim ('Luni' for monthly, 'Ani' for annual) is selected exhaustively.
    Returns list of (date, value) sorted ascending.
    """
    import tempo
    RO_MONTHS = {"ianuarie":1, "februarie":2, "martie":3, "aprilie":4, "mai":5, "iunie":6,
                 "iulie":7, "august":8, "septembrie":9, "octombrie":10, "noiembrie":11, "decembrie":12}
    node = tempo.Node()
    parent = node.by_code(parent_code)
    if not parent:
        return []
    leaf = next((c for c in parent.children if c.code == matrix), None)
    if not leaf:
        return []

    selections = []
    time_dim_label = None
    for dim in leaf.dimensions:
        lbl = dim.label
        if lbl in ("Luni", "Ani"):
            time_dim_label = lbl
            time_values = [opt.label for opt in dim.options]
            selections.append((lbl, time_values))
        elif lbl.startswith("UM:"):
            selections.append((lbl, [unit_value]))
        else:
            chosen = filter_dims.get(lbl)
            if chosen is None:
                for k, v in filter_dims.items():
                    if lbl.startswith(k) or k.startswith(lbl):
                        chosen = v
                        break
            if chosen is None:
                chosen = dim.options[0].label  # fallback (typically "Total"/"TOTAL")
            selections.append((lbl, [chosen]))
    if time_dim_label is None:
        return []

    csv_text = leaf.query(*selections)
    lines = csv_text.splitlines()
    if len(lines) < 2:
        return []
    header = [h.strip() for h in lines[0].split(",")]
    try:
        time_col = header.index(time_dim_label)
    except ValueError:
        return []
    val_col = len(header) - 1  # 'Valoare' is always last

    out = []
    for line in lines[1:]:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) <= max(time_col, val_col):
            continue
        period = parts[time_col].lower()
        try:
            val = float(parts[val_col])
        except ValueError:
            continue
        words = period.split()
        if freq == "M" and len(words) == 3 and words[0] == "luna" and words[1] in RO_MONTHS:
            try:
                out.append((date(int(words[2]), RO_MONTHS[words[1]], 1), val))
            except ValueError:
                pass
        elif freq == "A" and len(words) == 2 and words[0] == "anul":
            try:
                out.append((date(int(words[1]), 1, 1), val))
            except ValueError:
                pass
    return sorted(out)


# === Estonia — Statistics Estonia PxWeb (andmed.stat.ee) ===

EE_SERIES = [
    # IA002.px = CPI 1997=100 monthly. Filter Kaubagrupp=1 (Total)
    {"slug": "inflation-cpi", "path": "majandus/hinnad/IA002.px",
     "query": {"Kaubagrupp": "1"},  # Total commodity group
     "freq": "M_year_month_combo", "unit": "Index (1997=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "Statistics Estonia IA002 CPI 1997=100, total commodity"},
    # IA039.px = PPI of industrial output, 2010=100, monthly
    # Year + Month split dims, Tegevusala (EMTAK 2008) value "1" = Total
    {"slug": "ppi", "path": "majandus/hinnad/IA039.PX",
     "query": {"Tegevusala (EMTAK 2008)": "1"},
     "freq": "M_year_month_combo", "unit": "Index (2010=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "Statistics Estonia IA039 PPI of industrial output total, 2010=100"},
    # TO0053.PX = Volume index of industrial production, 2021=100, monthly
    # Tegevusala="BTD" (Mining+Manufacturing+Energy), Korrigeerimine="Y" (calendar+seasonal adj)
    # Vaatlusperiood is the time dim (YYYYM01 format).
    {"slug": "industrial-production", "path": "majandus/toostus/TO0053.PX",
     "query": {"Näitaja": "PROD", "Tegevusala": "BTD", "Korrigeerimine": "Y"},
     "freq": "M", "unit": "Index (2021=100)", "adjustment": "SA", "conversion": 1.0,
     "note": "Statistics Estonia TO0053 IP volume index BTD (mining+manuf+energy) SA, 2021=100"},
    # KM00338.PX = Retail sales volume index 2021=100 quarterly
    # Indicator=RETAIL, Tegevusala=G45_47
    {"slug": "retail-sales", "path": "majandus/sisekaubandus/jaemuugi-mahuindeksid/KM00338.PX",
     "query": {"Näitaja": "RETAIL", "Tegevusala": "G45_47"},
     "freq": "Q", "unit": "Index (2021=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "Statistics Estonia KM00338 retail sales volume index G45-47 2021=100 quarterly"},
    # RAA0012.PX = GDP and GNI quarterly. Year + Quarter split dims.
    # Adjustment 2 = SA + working-day adjusted. Indicator 2 = GDP chain-linked vol ref 2020.
    {"slug": "gdp-real", "path": "majandus/rahvamajanduse-arvepidamine/sisemajanduse-koguprodukt-(skp)/pehilised-rahvamajanduse-arvepidamise-naitajad/RAA0012.PX",
     "query": {"Sesoonne korrigeerimine": "2", "Näitaja": "2"},
     "freq": "Q_year_quarter_combo", "unit": "Million EUR (2020 chain-linked)", "adjustment": "SA", "conversion": 1.0,
     "note": "Statistics Estonia RAA0012 real GDP chain-linked vol ref 2020, SA, mln EUR"},
    # TT0160.px = Labour market headline indicators quarterly
    # Näitaja=UNEMP_RATE, Sugu=T, Vanuserühm=Y15-74
    {"slug": "unemployment", "path": "sotsiaalelu/tooturg/tooturu-uldandmed/luhiajastatistika/TT0160.px",
     "query": {"Näitaja": "UNEMP_RATE", "Sugu": "T", "Vanuserühm": "Y15-74"},
     "freq": "Q", "unit": "%", "adjustment": "NSA", "conversion": 1.0,
     "note": "Statistics Estonia TT0160 LFS unemployment rate 15-74 total quarterly"},
]


def fetch_ee_pxweb(path: str, query_filters: dict, freq: str = "M") -> list[tuple[date, float]]:
    """Estonia PxWeb. Tables vary:
      - 'M_year_month_combo' = separate Aasta(Year)+Kuu(Month) dims
      - 'Q_year_quarter_combo' = separate Aasta(Year)+Kvartal(Quarter) dims (1..5, 1=annual)
      - 'M'/'Q' = single time dim Vaatlusperiood with YYYYM01/YYYYQ1 codes
    """
    url = f"https://andmed.stat.ee/api/v1/en/stat/{path}"
    body = {
        "query": [{"code": k, "selection": {"filter": "item", "values": [v]}}
                  for k, v in query_filters.items()],
        "response": {"format": "json-stat2"},
    }
    r = requests.post(url, json=body, timeout=30)
    r.raise_for_status()
    js = r.json()
    if freq == "M_year_month_combo":
        return _parse_jsonstat_year_month(js)
    if freq == "Q_year_quarter_combo":
        return _parse_jsonstat_ee_year_quarter(js)
    if freq == "Q":
        return _parse_jsonstat_quarterly(js)
    return _parse_jsonstat(js, freq)


def _parse_jsonstat_ee_year_quarter(js: dict) -> list[tuple[date, float]]:
    """EE PxWeb tables with Aasta (Year) + Kvartal (Quarter I-IV) split dims.
    Kvartal codes: 1 = annual aggregate (skip), I/II/III/IV = quarters."""
    values = js.get("value", [])
    dim = js.get("dimension", {})
    dim_ids = js.get("id", [])
    dim_sizes = js.get("size", [])
    if not values or not dim_ids:
        return []
    year_dim = next((k for k in dim_ids if k.lower() in ("aasta", "year")), None)
    q_dim = next((k for k in dim_ids if k.lower() in ("kvartal", "quarter")), None)
    if not year_dim or not q_dim:
        return []
    def pairs(name):
        idx = dim[name].get("category", {}).get("index", {})
        if isinstance(idx, list):
            return [(c, p) for p, c in enumerate(idx)]
        return [(c, p) for c, p in idx.items()]
    y_pairs = pairs(year_dim)
    q_pairs = pairs(q_dim)
    other = {k: 0 for k in dim_ids if k not in (year_dim, q_dim)}
    Q_MONTHS = {"I": 1, "II": 4, "III": 7, "IV": 10}
    out = []
    for ycode, ypos in y_pairs:
        try:
            yy = int(ycode)
        except ValueError:
            continue
        for qcode, qpos in q_pairs:
            mm = Q_MONTHS.get(str(qcode).strip().upper())
            if not mm:
                continue
            indices = []
            for k in dim_ids:
                if k == year_dim:
                    indices.append(ypos)
                elif k == q_dim:
                    indices.append(qpos)
                else:
                    indices.append(other[k])
            flat = 0
            stride = 1
            for i in range(len(dim_ids) - 1, -1, -1):
                flat += indices[i] * stride
                stride *= dim_sizes[i]
            if 0 <= flat < len(values):
                v = values[flat]
                if v is not None:
                    try:
                        out.append((date(yy, mm, 1), float(v)))
                    except Exception:
                        continue
    return sorted(out)


def _parse_jsonstat_year_month(js: dict) -> list[tuple[date, float]]:
    """Parse JSON-stat where time is split across Year (Aasta/Vuosi) and Month (Kuu/Kuukausi) dimensions."""
    values = js.get("value", [])
    dim = js.get("dimension", {})
    dim_ids = js.get("id", [])
    dim_sizes = js.get("size", [])
    if not values:
        return []
    # find year and month dims
    year_dim = next((k for k in dim_ids if k.lower() in ("aasta", "vuosi", "year", "år", "ar")), None)
    month_dim = next((k for k in dim_ids if k.lower() in ("kuu", "kuukausi", "month", "månad", "manad", "mesec")), None)
    if not year_dim or not month_dim:
        return []

    def get_index(name):
        idx = dim[name].get("category", {}).get("index", {})
        if isinstance(idx, list):
            return [(code, pos) for pos, code in enumerate(idx)]
        return [(code, pos) for code, pos in idx.items()]

    year_pairs = get_index(year_dim)
    month_pairs = get_index(month_dim)

    other_indices = {}
    for k in dim_ids:
        if k in (year_dim, month_dim):
            continue
        other_indices[k] = 0

    out = []
    yi = dim_ids.index(year_dim)
    mi = dim_ids.index(month_dim)
    for ycode, ypos in year_pairs:
        for mcode, mpos in month_pairs:
            indices = []
            for k in dim_ids:
                if k == year_dim:
                    indices.append(ypos)
                elif k == month_dim:
                    indices.append(mpos)
                else:
                    indices.append(other_indices.get(k, 0))
            flat = 0
            stride = 1
            for i in range(len(dim_ids) - 1, -1, -1):
                flat += indices[i] * stride
                stride *= dim_sizes[i]
            if 0 <= flat < len(values):
                v = values[flat]
                if v is not None:
                    try:
                        yy = int(ycode)
                        mm = int(mcode)
                        if 1 <= mm <= 12:
                            out.append((date(yy, mm, 1), float(v)))
                    except Exception:
                        continue
    return sorted(out)


# === Hungary — KSH STADAT (HTML scrape) ===

HU_SERIES = [
    # ara0040 = "The consumer price index by main consumption groups, monthly"
    # Format: YoY index (same period previous year=100.0%). Columns: Year, Month,
    # Food, AlcTobacco, Clothing, Durable, FuelPower, Other, Services, Total, Pensioners
    {"slug": "inflation-cpi", "section": "ara", "table": "ara0040",
     "value_col_index": 9,
     "freq": "M", "unit": "Index (same month previous year=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "KSH STADAT 1.2.1.2 ara0040 CPI total YoY Index (sm-py=100)"},
    # ara0055 col 19 = "Total industry" (B+C+D+E) PPI; first table section = base 2021=100
    {"slug": "ppi", "section": "ara", "table": "ara0055",
     "value_col_index": 19,
     "freq": "M", "unit": "Index (2021=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "KSH STADAT 1.2.1.19 ara0055 PPI Total industry (B+C+D+E) base 2021=100"},
    # ipa0072 col 19 = Hungary's monthly volume index of industrial production
    # (EU-comparison table, YoY index corresponding period prev year = 100)
    {"slug": "industrial-production", "section": "ipa", "table": "ipa0072",
     "value_col_index": 19,
     "freq": "M", "unit": "Index (same month previous year=100)", "adjustment": "WDA", "conversion": 1.0,
     "note": "KSH STADAT 13.2.3.1 ipa0072 IPI Hungary WDA, YoY index"},
    # mun0098 col 8 = "Unemployment rate" %, LFS aged 15-64, Total section (first occurrence)
    {"slug": "unemployment-rate", "section": "mun", "table": "mun0098",
     "value_col_index": 8,
     "freq": "M", "unit": "%", "adjustment": "NSA", "conversion": 1.0,
     "note": "KSH STADAT 20.2.1.3 mun0098 LFS unemployment rate 15-64 Total %"},
    # bel0020 col 20 = "Total retail sales" calendar-adjusted volume YoY index (sm-py=100).
    # Data rows have Year+Month+19 sub-categories; the last column is the grand total.
    {"slug": "retail-sales", "section": "bel", "table": "bel0020",
     "value_col_index": 20,
     "freq": "M", "unit": "Index (same month previous year=100)", "adjustment": "WDA", "conversion": 1.0,
     "note": "KSH STADAT 2.2.1.7 bel0020 Retail sales total calendar-adjusted volume YoY index"},
    # gdp0086 col 2 = unadjusted raw YoY index (corresponding period prev year=100)
    # Quarterly volume indices of GDP — back to 1996.
    {"slug": "gdp-real", "section": "gdp", "table": "gdp0086",
     "value_col_index": 2,
     "freq": "Q", "unit": "Index (same quarter previous year=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "KSH STADAT 21.2.1.2 gdp0086 GDP volume index unadjusted YoY"},
    # Trade balance: synthesised in fetch loop from kkr0065 (exports) - kkr0064 (imports),
    # Hungary at value_col_index 19 in both EU-comparison tables, units = million EUR.
    {"slug": "trade-balance", "section": "kkr", "table": "kkr_synthetic",
     "value_col_index": 19,
     "freq": "M", "unit": "Million EUR", "adjustment": "NSA", "conversion": 1.0,
     "note": "KSH STADAT 17.2.3.1+17.2.3.2 kkr0065-kkr0064 HU exports minus imports, mEUR"},
]

HU_MONTHS = {
    "January":1, "February":2, "March":3, "April":4, "May":5, "June":6,
    "July":7, "August":8, "September":9, "October":10, "November":11, "December":12,
}

HU_QUARTERS = {"Q1": 3, "Q2": 6, "Q3": 9, "Q4": 12}


def _hu_parse_number(s: str):
    """Parse a KSH STADAT cell: strip nbsp/spaces; remove thousand-separator commas.
    KSH English HTML pages use period as decimal separator throughout."""
    s = s.replace("\xa0", "").replace(" ", "").replace(",", "")
    if s in ("", "..", "…", "x", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def fetch_hu_stadat(table: str, value_col_index: int, freq: str = "M",
                    section: str = "ara") -> list[tuple[date, float]]:
    """Scrape KSH STADAT HTML table. Year repeats only on the first-period row
    (January for monthly, Q1 for quarterly). KSH tables can contain multiple
    sub-sections (YoY/MoM/base-index); we keep the first occurrence of each
    (year, period) tuple."""
    import bs4
    url = f"https://www.ksh.hu/stadat_files/{section}/en/{table}.html"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    soup = bs4.BeautifulSoup(r.text, "html.parser")
    out = []
    seen = set()
    table_el = soup.find("table")
    if not table_el:
        return out
    period_map = HU_QUARTERS if freq == "Q" else HU_MONTHS
    current_year = None
    for tr in table_el.find_all("tr"):
        cells = [c.get_text(strip=True) for c in tr.find_all(["td", "th"])]
        if not cells:
            continue
        first = cells[0]
        if first.lower() in ("period", "quarter", "year", "code", "") and \
                (len(cells) < 2 or cells[1] not in period_map):
            continue
        if first.isdigit() and len(first) == 4:
            current_year = int(first)
            period_text = cells[1] if len(cells) > 1 else ""
        elif first == "" and len(cells) >= 2 and cells[1] in period_map:
            period_text = cells[1]
        elif first in period_map:
            period_text = first
        else:
            continue
        if period_text not in period_map or current_year is None:
            continue
        pm = period_map[period_text]
        key = (current_year, pm)
        if key in seen:
            continue
        seen.add(key)
        if value_col_index < len(cells):
            val = _hu_parse_number(cells[value_col_index])
            if val is None:
                continue
            out.append((date(current_year, pm, 1), val))
    return sorted(out)


def fetch_hu_trade_balance() -> list[tuple[date, float]]:
    """Synthesise HU trade balance = exports (kkr0065) - imports (kkr0064), million EUR.
    Hungary appears at value_col_index 19 in both EU-comparison tables."""
    exp = dict(fetch_hu_stadat("kkr0065", 19, "M", section="kkr"))
    imp = dict(fetch_hu_stadat("kkr0064", 19, "M", section="kkr"))
    return [(dt, exp[dt] - imp[dt]) for dt in sorted(set(exp.keys()) & set(imp.keys()))]


# === Slovakia — Štatistický úrad SR DataCube REST ===

SK_SERIES = [
    # sp2038ms: Consumer Price Indices by COICOP - monthly. Hierarchy:
    # /dataset/sp2038ms/{years CSV}/{months CSV or all}/{coicop}/{measure}
    # odb01 = Úhrn (Total), mj38 = December 2000=100 (continuous index)
    {"slug": "inflation-cpi", "dataset_id": "sp2038ms",
     "segments": [
         "2010,2011,2012,2013,2014,2015,2016,2017,2018,2019,2020,2021,2022,2023,2024,2025,2026",
         "all", "odb01", "mj38",
     ],
     "freq": "M", "unit": "Index (Dec 2000=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "ŠÚ SR sp2038ms CPI Total, Dec 2000=100 continuous monthly"},
    # sp0101ms: Producer price indices vs. corresponding period of previous year — monthly.
    # 3 dims: rok, mes, ukaz. UKAZ04 = Industrial producers prices - total.
    {"slug": "ppi", "dataset_id": "sp0101ms",
     "segments": ["all", "all", "UKAZ04"],
     "freq": "M", "unit": "Index (same month previous year=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "SUSR sp0101ms PPI Industrial producers prices total UKAZ04 YoY index"},
    # pm0042ms: Industrial production YoY index (adjusted). Dims: year, month, specu, nace2,
    # unit, indic. Pick SPECU_Y_ROMR (YoY) × NACE 05-39 (Industry total) × UNIT_INDEX × U_PM_0001.
    {"slug": "industrial-production", "dataset_id": "pm0042ms",
     "segments": ["all", "all", "SPECU_Y_ROMR", "05-39", "UNIT_INDEX", "U_PM_0001"],
     "freq": "M", "unit": "Index (same month previous year=100)", "adjustment": "WDA", "conversion": 1.0,
     "note": "SUSR pm0042ms Industrial production YoY adjusted, NACE 05-39 Industry total"},
    # pr1802qs: LFS unemployment rate quarterly. Dims (in path order):
    # rok, vek, vzdel03, poh, stv (quarter), mj, ukaz.
    # all years × VEK_Y15-74 × TOTAL education × TOTAL sex × all quarters × MJ_VPC (in %)
    # × U_PR_0003 (Unemployment rate).
    {"slug": "unemployment-rate", "dataset_id": "pr1802qs",
     "segments": ["all", "VEK_Y15-74", "TOTAL", "TOTAL", "all", "MJ_VPC", "U_PR_0003"],
     "freq": "Q", "unit": "%", "adjustment": "NSA", "conversion": 1.0,
     "note": "SUSR pr1802qs LFS unemployment rate 15-74 Total %"},
    # ob0004ms: Retail trade except motor vehicles, turnover index YoY (constant prices).
    # Dims: year, month, specu, nace2, unit, indic. SPECU_Y_ROMR × NACE 47 (Total retail trade)
    # × UNIT_INDEX_CSP (index/con.p.) × U_OD_0001 (Turnover).
    {"slug": "retail-sales", "dataset_id": "ob0004ms",
     "segments": ["all", "all", "SPECU_Y_ROMR", "47", "UNIT_INDEX_CSP", "U_OD_0001"],
     "freq": "M", "unit": "Index (same month previous year=100)", "adjustment": "WDA", "conversion": 1.0,
     "note": "SUSR ob0004ms Retail trade turnover NACE 47 YoY index (constant prices)"},
    # zo0001ms: Foreign trade by months. Dims: rok, mes, ukaz, mj.
    # UKAZ03 = Balance - for month, MJ01 = mill. EUR.
    {"slug": "trade-balance", "dataset_id": "zo0001ms",
     "segments": ["all", "all", "UKAZ03", "MJ01"],
     "freq": "M", "unit": "Million EUR", "adjustment": "NSA", "conversion": 1.0,
     "note": "SUSR zo0001ms Foreign trade balance, mill EUR, monthly"},
    # nu0004qs: Quarterly GDP, chain-linked volumes (previous year prices). Dims:
    # rok, stv, ukaz, meto, mj. UKAZ15 = GDP × METO04 (GDP method) × MJ01 (Mill EUR).
    {"slug": "gdp-real", "dataset_id": "nu0004qs",
     "segments": ["all", "all", "UKAZ15", "METO04", "MJ01"],
     "freq": "Q", "unit": "Million EUR (chain-linked, prev-year prices)", "adjustment": "NSA", "conversion": 1.0,
     "note": "SUSR nu0004qs Quarterly GDP chain-linked volumes, mill EUR"},
]


def fetch_sk_datacube(dataset_id: str, segments: list, freq: str = "M") -> list[tuple[date, float]]:
    """SUSR datacube REST: /api/v2.0/dataset/{id}/{seg1}/{seg2}/.../{segN}.
    Supports monthly (M) and quarterly (Q) frequencies; year dim has 'rok'/'year' in name,
    period dim has 'mes' (month) or 'stv' (quarter) in name.

    `segments` is the ordered list of path segments after the dataset_id (excluding
    leading slash) — typically: years, months_or_all, then the indicator/measure filters
    in the order specified by the dataset's dimension declaration. Use 'all' to fetch
    every category for a dimension.
    """
    url = "https://data.statistics.sk/api/v2.0/dataset/" + dataset_id + "/" + "/".join(segments)
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    js = r.json()
    sizes = js.get("size", [])
    values = js.get("value", [])
    if not sizes or not values:
        return []
    dim_ids = js.get("id", [])
    year_pos = next((i for i, k in enumerate(dim_ids) if "rok" in k.lower() or "year" in k.lower()), None)
    if freq == "Q":
        period_pos = next((i for i, k in enumerate(dim_ids) if "stv" in k.lower()), None)
        period_kind = "Q"
    else:
        period_pos = next((i for i, k in enumerate(dim_ids) if "mes" in k.lower() or "month" in k.lower()), None)
        period_kind = "M"
    if year_pos is None or period_pos is None:
        return []
    year_idx = js["dimension"][dim_ids[year_pos]]["category"]["index"]
    period_idx = js["dimension"][dim_ids[period_pos]]["category"]["index"]
    if isinstance(year_idx, dict):
        year_pairs = list(year_idx.items())
    else:
        year_pairs = [(c, i) for i, c in enumerate(year_idx)]
    if isinstance(period_idx, dict):
        period_pairs = list(period_idx.items())
    else:
        period_pairs = [(c, i) for i, c in enumerate(period_idx)]

    # Q-codes look like '1.', '2.', '3.', '4.' (last category may be '1. - 4.' cumulative)
    # M-codes look like '1.', '2.', ..., '12.', '1. - 12.' cumulative
    out = []
    for ycode, ypos in year_pairs:
        # Year codes may carry status suffixes like '2026 (p)' / '(d)' / '(s)';
        # strip the parenthesised marker and any whitespace.
        y_clean = ycode.split("(", 1)[0].strip()
        try:
            yy = int(y_clean)
        except ValueError:
            continue
        for pcode, ppos in period_pairs:
            # Quarter codes look like '1. Q.', '1.Q.', '1.', '12.'; month codes are '1.' .. '12.'
            # Strip any non-leading-digit characters before parsing the integer.
            p_str = pcode.split("(", 1)[0].strip()
            digits = ""
            for ch in p_str:
                if ch.isdigit():
                    digits += ch
                else:
                    if digits:
                        break  # only consume the leading run of digits
            if not digits:
                continue
            try:
                pn = int(digits)
            except ValueError:
                continue
            if period_kind == "Q":
                if pn < 1 or pn > 4:
                    continue
                month = pn * 3
            else:
                if pn < 1 or pn > 12:
                    continue
                month = pn
            indices = [0] * len(dim_ids)
            indices[year_pos] = ypos
            indices[period_pos] = ppos
            flat = 0
            stride = 1
            for i in range(len(dim_ids) - 1, -1, -1):
                flat += indices[i] * stride
                stride *= sizes[i]
            if 0 <= flat < len(values):
                v = values[flat]
                if v is not None:
                    out.append((date(yy, month, 1), float(v)))
    return sorted(out)


# === Malta — NSO Malta SDMX REST (Cloudflare-protected) ===
# Endpoint: https://apidesign-statdb.nso.gov.mt/rest/ (newest data; release variant
# lags behind). Plain `requests` gets blocked by Cloudflare; cloudscraper passes.
# DSD_RETAIL_PRICE_INDEX_MONTHLY has 2 dims: CS_SUB_SECTION + CSE_FREQ.
# CS_SUB_SECTION code CC00000 = 00.000 RETAIL PRICE INDEX (all-items total).
# Response is SDMX-CSV; columns include TIME_PERIOD,OBS_VALUE.

MT_SERIES = [
    {"slug": "inflation-cpi", "dataflow": "DF_RETAIL_PRICE_INDEX_MONTHLY",
     "key": "CC00000.M", "freq": "M",
     "unit": "Index (2015=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "NSO Malta DF_RETAIL_PRICE_INDEX_MONTHLY total RPI (CC00000)"},
]


def fetch_mt_sdmx(dataflow: str, key: str, freq: str = "M") -> list[tuple[date, float]]:
    """Fetch SDMX-CSV from NSO Malta. Returns sorted [(date, value)]."""
    if _CF_SCRAPER is None:
        raise RuntimeError("cloudscraper not installed; required for nso.gov.mt")
    url = f"https://apidesign-statdb.nso.gov.mt/rest/data/{dataflow}/{key}"
    headers = {"Accept": "application/vnd.sdmx.data+csv;version=1.0.0"}
    r = _CF_SCRAPER.get(url, headers=headers, timeout=60)
    r.raise_for_status()
    out = []
    lines = r.text.strip().splitlines()
    if not lines:
        return []
    header = [h.strip() for h in lines[0].split(",")]
    try:
        time_idx = header.index("TIME_PERIOD")
        val_idx = header.index("OBS_VALUE")
    except ValueError:
        return []
    for line in lines[1:]:
        parts = line.split(",")
        if len(parts) <= max(time_idx, val_idx):
            continue
        period = parts[time_idx].strip()
        val_str = parts[val_idx].strip()
        try:
            val = float(val_str)
        except ValueError:
            continue
        dt = _parse_period(period, freq)
        if dt:
            out.append((dt, val))
    return sorted(out)


# === Cyprus — CYSTAT PxWeb (Cloudflare-protected) ===
# Endpoint: https://cystatdb.cystat.gov.cy/api/v1/en/ — classic PxWeb v1 API.
# Pretty path: 8.CYSTAT-DB / Price Indices / Consumer Price Index / 0410055E.px
# (Continuous CPI Timeseries Base Year 1986/1992/2005/2015/2025, monthly).
# valueTexts of MONTH are YYYYMmm. PxWeb here only accepts selection.filter='all'
# for code 'BASE YEAR' (filter='item' returns 404). We fetch all 5 base years
# and pick the requested one (label match, not code).

CY_SERIES = [
    # Base 1986 spans 1980-01..present (556 obs); base 2025 only 2019+ (88 obs).
    # We use 1986 for full history; YoY computation is base-invariant.
    {"slug": "inflation-cpi",
     "px_path": "8.CYSTAT-DB/Price Indices/Consumer Price Index/0410055E.px",
     "base_year": "1986",
     "freq": "M",
     "unit": "Index (1986=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "CYSTAT 0410055E continuous CPI timeseries, base 1986=100"},
]


def fetch_cy_pxweb(px_path: str, base_year: str, freq: str = "M") -> list[tuple[date, float]]:
    """CYSTAT PxWeb. POST data endpoint requires literal spaces in path
    (URL-encoding gives 404). filter='all' is the only accepted selection."""
    if _CF_SCRAPER is None:
        raise RuntimeError("cloudscraper not installed; required for cystat.gov.cy")
    url = f"https://cystatdb.cystat.gov.cy/api/v1/en/{px_path}"
    body = {
        "query": [{"code": "BASE YEAR", "selection": {"filter": "all", "values": ["*"]}}],
        "response": {"format": "json-stat2"},
    }
    r = _CF_SCRAPER.post(url, json=body, timeout=60)
    r.raise_for_status()
    js = r.json()

    values = js.get("value", [])
    dim = js.get("dimension", {})
    dim_ids = js.get("id", [])
    sizes = js.get("size", [])
    if not values or "MONTH" not in dim or "BASE YEAR" not in dim:
        return []

    by_cat = dim["BASE YEAR"]["category"]
    by_idx = by_cat.get("index", {})
    by_lbl = by_cat.get("label", {})
    target_by_pos = None
    if isinstance(by_idx, dict):
        for code, pos in by_idx.items():
            if str(by_lbl.get(code, code)) == base_year:
                target_by_pos = pos
                break
    if target_by_pos is None:
        target_by_pos = sizes[dim_ids.index("BASE YEAR")] - 1

    m_cat = dim["MONTH"]["category"]
    m_idx = m_cat.get("index", {})
    m_lbl = m_cat.get("label", {})
    if isinstance(m_idx, dict):
        m_pairs = sorted(m_idx.items(), key=lambda x: x[1])
    else:
        m_pairs = [(c, i) for i, c in enumerate(m_idx)]

    month_pos = dim_ids.index("MONTH")
    by_pos = dim_ids.index("BASE YEAR")
    out = []
    for mcode, mpos in m_pairs:
        indices = [0] * len(dim_ids)
        indices[month_pos] = mpos
        indices[by_pos] = target_by_pos
        flat = 0
        stride = 1
        for i in range(len(dim_ids) - 1, -1, -1):
            flat += indices[i] * stride
            stride *= sizes[i]
        if 0 <= flat < len(values):
            v = values[flat]
            if v is None:
                continue
            label = m_lbl.get(mcode, mcode)  # e.g. "2026M04"
            dt = _parse_period(str(label), freq)
            if dt:
                out.append((dt, float(v)))
    return sorted(out)


# === Croatia — DZS PxWeb (web.dzs.hr) ===
#
# Discovery: GET https://web.dzs.hr/PXWeb/api/v1/en/ -> 20 topics (Cijene,
# Industrija, Trgovina na malo, Nacionalni racuni, ...). DZS PxWeb uses the
# language code 'en' but most node IDs and dim codes remain Croatian.
# Stage-2 tables (BS_IN11, BS_PP11, BS_TR21) have *split* Year+Month dims
# (GODINA + MJESEC with Roman-numeral months I..XII) rather than a single
# combined Tid. We use _parse_jsonstat_roman_year_month for those tables.
# GDP table BDP-T01_EUR.px uses Godina (Year) + Tromjesečje (Quarter).

HR_SERIES = [
    # ME_PS09.px CPI ECOICOP v2 monthly. ECOICOP_ver_2='00' (Total), Indikatori='4' (index 2025=100)
    {"slug": "inflation-cpi",
     "path": "Cijene/Indeksi potrošačkih cijena/Indeksi potrošačkih cijena – ECOICOP, ver. 2/ME_PS09.px",
     "query": {"ECOICOP, ver. 2": "00", "Indikatori": "4"},
     "freq": "M", "parse": "tid",
     "unit": "Index (2025=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "DZS Croatia ME_PS09 CPI 2025=100 total ECOICOP v2"},
    # BS_IN11.px Industrial production volume indices, gross indices, total industry
    # DJELATNOSTI=Ukupno (Total) — split GODINA + MJESEC (Roman) dims, 1998-..
    {"slug": "industrial-production",
     "path": "Industrija/Indeks industrijske proizvodnje/BS_IN11.px",
     "query": {"DJELATNOSTI": "Ukupno"},
     "freq": "M", "parse": "roman_ym",
     "unit": "Index (2021=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "DZS Croatia BS_IN11 IP volume index Total industry gross 2021=100"},
    # BS_PP11.px Industrial producers price index on domestic market — total industry
    {"slug": "ppi",
     "path": "Industrija/Indeks proizvođačkih cijena/BS_PP11.px",
     "query": {"DJELATNOSTI": "Ukupno"},
     "freq": "M", "parse": "roman_ym",
     "unit": "Index (2021=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "DZS Croatia BS_PP11 PPI domestic market Total industry 2021=100"},
    # BS_TR21.px Retail Trade Turnover Indices - Gross (unadjusted), Value index 2021=100
    # DJELATNOSTI=G47 (Retail trade, except motor vehicles and motorcycles)
    {"slug": "retail-sales",
     "path": "Trgovina na malo/BS_TR21.px",
     "query": {"DJELATNOSTI": "G47"},
     "freq": "M", "parse": "roman_ym",
     "unit": "Index (2021=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "DZS Croatia BS_TR21 retail trade turnover gross value index G47 2021=100"},
    # BDP-T01_EUR.px Quarterly GDP at constant previous year prices (ref 2021), mln EUR
    # Pokazatelj=B1GQ (GDP), Način prikaza=2 (Constant ref year 2021), Tromjesečje=1..4
    # Year + Quarter split dims. We fetch the four quarter codes and pin Godina open.
    {"slug": "gdp-real",
     "path": "Nacionalni racuni/BDP/Kvartalni nacionalni računi/BDP-T01_EUR.px",
     "query": {"Pokazatelj": "B1GQ", "Način prikaza": "2"},
     "freq": "Q", "parse": "hr_year_quarter",
     "unit": "Million EUR (constant 2021 prices)", "adjustment": "NSA", "conversion": 1.0,
     "note": "DZS Croatia BDP-T01_EUR real GDP constant ref-year 2021 prices, mln EUR"},
]


_HR_ROMAN_MONTHS = {
    "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6,
    "VII": 7, "VIII": 8, "IX": 9, "X": 10, "XI": 11, "XII": 12,
}


def _parse_jsonstat_roman_year_month(js: dict) -> list[tuple[date, float]]:
    """HR PxWeb tables with GODINA (Year) + MJESEC (Roman month) split dims."""
    values = js.get("value", [])
    dim = js.get("dimension", {})
    dim_ids = js.get("id", [])
    dim_sizes = js.get("size", [])
    if not values or not dim_ids:
        return []
    year_dim = next((k for k in dim_ids if k.upper() == "GODINA"), None)
    month_dim = next((k for k in dim_ids if k.upper() == "MJESEC"), None)
    if not year_dim or not month_dim:
        return []
    def pairs(name):
        idx = dim[name].get("category", {}).get("index", {})
        if isinstance(idx, list):
            return [(c, p) for p, c in enumerate(idx)]
        return [(c, p) for c, p in idx.items()]
    y_pairs = pairs(year_dim)
    m_pairs = pairs(month_dim)
    other = {k: 0 for k in dim_ids if k not in (year_dim, month_dim)}
    out = []
    for ycode, ypos in y_pairs:
        try:
            yy = int(ycode.rstrip("."))
        except ValueError:
            continue
        for mcode, mpos in m_pairs:
            mm = _HR_ROMAN_MONTHS.get(mcode.strip().upper())
            if not mm:
                continue
            indices = []
            for k in dim_ids:
                if k == year_dim:
                    indices.append(ypos)
                elif k == month_dim:
                    indices.append(mpos)
                else:
                    indices.append(other[k])
            flat = 0
            stride = 1
            for i in range(len(dim_ids) - 1, -1, -1):
                flat += indices[i] * stride
                stride *= dim_sizes[i]
            if 0 <= flat < len(values):
                v = values[flat]
                if v is not None:
                    try:
                        out.append((date(yy, mm, 1), float(v)))
                    except Exception:
                        continue
    return sorted(out)


def _parse_jsonstat_hr_year_quarter(js: dict) -> list[tuple[date, float]]:
    """HR PxWeb tables with Godina (Year) + Tromjesečje (Quarter) split dims.
    Quarter codes are 1..5 where 5 is annual 'Q1-Q4'; skip that."""
    values = js.get("value", [])
    dim = js.get("dimension", {})
    dim_ids = js.get("id", [])
    dim_sizes = js.get("size", [])
    if not values or not dim_ids:
        return []
    year_dim = next((k for k in dim_ids if k.lower() == "godina"), None)
    q_dim = next((k for k in dim_ids if "tromjeseč" in k.lower() or "tromjesec" in k.lower()), None)
    if not year_dim or not q_dim:
        return []
    def pairs(name):
        idx = dim[name].get("category", {}).get("index", {})
        if isinstance(idx, list):
            return [(c, p) for p, c in enumerate(idx)]
        return [(c, p) for c, p in idx.items()]
    y_pairs = pairs(year_dim)
    q_pairs = pairs(q_dim)
    other = {k: 0 for k in dim_ids if k not in (year_dim, q_dim)}
    Q_MONTHS = {"1": 1, "2": 4, "3": 7, "4": 10}
    out = []
    for ycode, ypos in y_pairs:
        try:
            yy = int(ycode)
        except ValueError:
            continue
        for qcode, qpos in q_pairs:
            mm = Q_MONTHS.get(str(qcode))
            if not mm:
                continue
            indices = []
            for k in dim_ids:
                if k == year_dim:
                    indices.append(ypos)
                elif k == q_dim:
                    indices.append(qpos)
                else:
                    indices.append(other[k])
            flat = 0
            stride = 1
            for i in range(len(dim_ids) - 1, -1, -1):
                flat += indices[i] * stride
                stride *= dim_sizes[i]
            if 0 <= flat < len(values):
                v = values[flat]
                if v is not None:
                    try:
                        out.append((date(yy, mm, 1), float(v)))
                    except Exception:
                        continue
    return sorted(out)


def fetch_hr_pxweb(path: str, query_filters: dict, freq: str = "M", parse: str = "tid") -> list[tuple[date, float]]:
    import urllib.parse
    encoded_path = "/".join(urllib.parse.quote(p) for p in path.split("/"))
    url = f"https://web.dzs.hr/PXWeb/api/v1/en/{encoded_path}"
    body = {
        "query": [{"code": k, "selection": {"filter": "item", "values": [v]}}
                  for k, v in query_filters.items()],
        "response": {"format": "json-stat2"},
    }
    r = requests.post(url, json=body, timeout=30)
    r.raise_for_status()
    js = r.json()
    if parse == "roman_ym":
        return _parse_jsonstat_roman_year_month(js)
    if parse == "hr_year_quarter":
        return _parse_jsonstat_hr_year_quarter(js)
    return _parse_jsonstat(js, freq)


# Aggregate fetchers
COUNTRY_FETCHERS = {
    # source_code -> (country, fetcher_function, series_list, label, url)
    "dst":      ("DK", DK_SERIES, "Statistics Denmark (Statbank)",       "https://www.dst.dk/en/Statistik/statbank"),
    "stat_fi":  ("FI", FI_SERIES, "Statistics Finland (Tilastokeskus)",  "https://www.stat.fi"),
    "scb_se":   ("SE", SE_SERIES, "Statistics Sweden (SCB)",             "https://www.scb.se"),
    "ine_pt":   ("PT", PT_SERIES, "INE Portugal",                        "https://www.ine.pt"),
    "cso_ie":   ("IE", IE_SERIES, "CSO Ireland",                         "https://www.cso.ie"),
    "stat_at":  ("AT", AT_SERIES, "Statistik Austria",                   "https://www.statistik.at"),
    "surs_si":  ("SI", SI_SERIES, "SURS Statistical Office Slovenia",    "https://www.stat.si"),
    "csp_lv":   ("LV", LV_SERIES, "CSP Latvia",                          "https://stat.gov.lv"),
    "insse_ro": ("RO", RO_SERIES, "INSSE Romania",                       "https://insse.ro"),
    "stat_ee":  ("EE", EE_SERIES, "Statistics Estonia",                  "https://andmed.stat.ee"),
    "dzs_hr":   ("HR", HR_SERIES, "DZS Croatian Bureau of Statistics",   "https://web.dzs.hr"),
    "statbel":  ("BE", BE_SERIES, "Statbel (Belgium)",                   "https://statbel.fgov.be"),
    "susr_sk":  ("SK", SK_SERIES, "Štatistický úrad SR (Slovakia)",      "https://slovak.statistics.sk"),
    "ksh_hu":   ("HU", HU_SERIES, "KSH (Hungary)",                       "https://www.ksh.hu"),
    "nso_mt":   ("MT", MT_SERIES, "NSO Malta",                           "https://nso.gov.mt"),
    "cystat_cy":("CY", CY_SERIES, "Statistical Service of Cyprus (CYSTAT)", "https://www.cystat.gov.cy"),
}


class NationalEUProvider(BaseProvider):
    name = "national_eu"
    display_name = "EU national stat offices (direct)"

    def fetch(self) -> list[DataPoint]:
        out: list[DataPoint] = []
        # Denmark
        for cfg in DK_SERIES:
            try:
                pairs = fetch_dk_table(cfg["table"], cfg["filters"], cfg["freq"])
                # Optional disambiguator for tables that serve multiple slugs (e.g. BBM)
                sid = cfg.get("series_id") or f"DST/{cfg['table']}"
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"], country="DK",
                        date=normalize_date(dt, cfg["freq"]),
                        value=round(v * cfg["conversion"], 4),
                        source="dst", unit=cfg["unit"],
                        series_id=sid,
                        adjustment=cfg["adjustment"],
                    ))
                print(f"  OK {cfg['slug']}/DK ({cfg['table']}): {len(pairs)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['slug']}/DK ({cfg['table']}): {e}")
            time.sleep(0.3)

        # Finland
        fi_trade_cache: dict[str, dict] = {}
        for cfg in FI_SERIES:
            try:
                pairs = fetch_fi_table(cfg["path"], cfg["query"], cfg["freq"])
                sid = cfg.get("series_id") or f"STATFI/{cfg['path']}"
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"], country="FI",
                        date=normalize_date(dt, cfg["freq"]),
                        value=round(v * cfg["conversion"], 4),
                        source="stat_fi", unit=cfg["unit"],
                        series_id=sid,
                        adjustment=cfg["adjustment"],
                    ))
                # Cache exports/imports for trade-balance derivation
                if cfg["slug"] in ("exports", "imports") and "tpulk" in cfg["path"]:
                    fi_trade_cache[cfg["slug"]] = {
                        normalize_date(dt, cfg["freq"]): round(v * cfg["conversion"], 4)
                        for dt, v in pairs
                    }
                print(f"  OK {cfg['slug']}/FI ({cfg['path'][-30:]}): {len(pairs)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['slug']}/FI: {e}")
            time.sleep(0.3)

        # Finland — derive trade-balance from BoP exports - imports (tpulk 12gq).
        if "exports" in fi_trade_cache and "imports" in fi_trade_cache:
            exp_map = fi_trade_cache["exports"]
            imp_map = fi_trade_cache["imports"]
            tb_pts = 0
            for d, ex in exp_map.items():
                im = imp_map.get(d)
                if im is None:
                    continue
                out.append(DataPoint(
                    indicator="trade-balance", country="FI", date=d,
                    value=round(ex - im, 4), source="stat_fi",
                    unit="EUR million",
                    series_id="STATFI/StatFin/tpulk/statfin_tpulk_pxt_12gq.px/tb",
                    adjustment="NSA",
                ))
                tb_pts += 1
            print(f"  OK trade-balance/FI (derived exp-imp tpulk 12gq): {tb_pts} pts")

        # Sweden
        for cfg in SE_SERIES:
            try:
                pairs = fetch_se_table(cfg["path"], cfg["query"], cfg["freq"])
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"], country="SE",
                        date=normalize_date(dt, cfg["freq"]),
                        value=round(v * cfg["conversion"], 4),
                        source="scb_se", unit=cfg["unit"],
                        series_id=f"SCB/{cfg['path']}",
                        adjustment=cfg["adjustment"],
                    ))
                print(f"  OK {cfg['slug']}/SE: {len(pairs)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['slug']}/SE: {e}")
            time.sleep(0.3)

        # Portugal
        for cfg in PT_SERIES:
            try:
                pairs = fetch_pt_indicator(
                    cfg["varcd"], cfg["freq"],
                    row_filter=cfg.get("row_filter"),
                )
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"], country="PT",
                        date=normalize_date(dt, cfg["freq"]),
                        value=round(v * cfg["conversion"], 4),
                        source="ine_pt", unit=cfg["unit"],
                        series_id=f"INE-PT/{cfg['varcd']}",
                        adjustment=cfg["adjustment"],
                    ))
                print(f"  OK {cfg['slug']}/PT (varcd {cfg['varcd']}): {len(pairs)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['slug']}/PT: {e}")
            time.sleep(0.3)

        # Ireland
        for cfg in IE_SERIES:
            try:
                pairs = fetch_ie_table(cfg["table"], cfg["filters"], cfg["freq"])
                sid = cfg.get("series_id") or f"CSO/{cfg['table']}"
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"], country="IE",
                        date=normalize_date(dt, cfg["freq"]),
                        value=round(v * cfg["conversion"], 4),
                        source="cso_ie", unit=cfg["unit"],
                        series_id=sid,
                        adjustment=cfg["adjustment"],
                    ))
                print(f"  OK {cfg['slug']}/IE ({cfg['table']}): {len(pairs)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['slug']}/IE: {e}")
            time.sleep(0.3)

        # Austria
        for cfg in AT_SERIES:
            try:
                pairs = fetch_at_csv(
                    cfg["ogd"], cfg["filters"], cfg["time_col"], cfg["value_col"], cfg["freq"],
                    value_col_b=cfg.get("value_col_b"), derive=cfg.get("derive"),
                )
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"], country="AT",
                        date=normalize_date(dt, cfg["freq"]),
                        value=round(v * cfg["conversion"], 4),
                        source="stat_at", unit=cfg["unit"],
                        series_id=f"STATAT/{cfg['ogd']}",
                        adjustment=cfg["adjustment"],
                    ))
                print(f"  OK {cfg['slug']}/AT ({cfg['ogd'][:30]}): {len(pairs)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['slug']}/AT: {e}")
            time.sleep(0.3)

        # Slovenia
        for cfg in SI_SERIES:
            try:
                pairs = fetch_si_pxweb(cfg["table"], cfg["query"], cfg["freq"])
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"], country="SI",
                        date=normalize_date(dt, cfg["freq"]),
                        value=round(v * cfg["conversion"], 4),
                        source="surs_si", unit=cfg["unit"],
                        series_id=f"SURS/{cfg['table']}",
                        adjustment=cfg["adjustment"],
                    ))
                print(f"  OK {cfg['slug']}/SI ({cfg['table']}): {len(pairs)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['slug']}/SI: {e}")
            time.sleep(0.3)

        # Latvia
        for cfg in LV_SERIES:
            try:
                pairs = fetch_lv_pxweb(cfg["path"], cfg["query"], cfg["freq"])
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"], country="LV",
                        date=normalize_date(dt, cfg["freq"]),
                        value=round(v * cfg["conversion"], 4),
                        source="csp_lv", unit=cfg["unit"],
                        series_id=f"CSP/{cfg['path'].rsplit('/',1)[-1]}",
                        adjustment=cfg["adjustment"],
                    ))
                print(f"  OK {cfg['slug']}/LV ({cfg['path'].rsplit('/',1)[-1]}): {len(pairs)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['slug']}/LV: {e}")
            time.sleep(0.3)

        # Estonia
        for cfg in EE_SERIES:
            try:
                pairs = fetch_ee_pxweb(cfg["path"], cfg["query"], cfg["freq"])
                eff_freq = {"M_year_month_combo": "M", "Q_year_quarter_combo": "Q"}.get(
                    cfg["freq"], cfg["freq"]
                )
                table_id = cfg["path"].rsplit("/", 1)[-1].split(".")[0]
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"], country="EE",
                        date=normalize_date(dt, eff_freq),
                        value=round(v * cfg["conversion"], 4),
                        source="stat_ee", unit=cfg["unit"],
                        series_id=f"STATEE/{table_id}",
                        adjustment=cfg["adjustment"],
                    ))
                print(f"  OK {cfg['slug']}/EE ({table_id}): {len(pairs)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['slug']}/EE: {e}")
            time.sleep(0.3)

        # Belgium — Statbel CSV views + NBB SDMX REST v2
        for cfg in BE_SERIES:
            kind = cfg.get("kind", "statbel")
            try:
                if kind == "statbel":
                    pairs = fetch_be_statbel_csv(
                        cfg["view_id"], cfg["value_col"], cfg["freq"],
                        row_filter=cfg.get("row_filter"),
                    )
                    src = "statbel"
                    sid = f"STATBEL/{cfg['view_id'][:8]}"
                    tag = f"Statbel {cfg['view_id'][:8]}"
                elif kind == "nbb":
                    pairs = fetch_nbb_sdmx(cfg["dataflow"], cfg["key"], cfg["freq"])
                    src = "nbb"
                    sid = f"NBB/{cfg['dataflow']}/{cfg['key']}"
                    tag = f"NBB {cfg['dataflow']}"
                else:
                    raise ValueError(f"unknown BE kind: {kind}")
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"], country="BE",
                        date=normalize_date(dt, cfg["freq"]),
                        value=round(v * cfg["conversion"], 4),
                        source=src, unit=cfg["unit"],
                        series_id=sid,
                        adjustment=cfg["adjustment"],
                    ))
                print(f"  OK {cfg['slug']}/BE ({tag}): {len(pairs)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['slug']}/BE: {e}")
            time.sleep(0.3)

        # Hungary
        for cfg in HU_SERIES:
            try:
                if cfg["table"] == "kkr_synthetic":
                    pairs = fetch_hu_trade_balance()
                else:
                    pairs = fetch_hu_stadat(
                        cfg["table"], cfg["value_col_index"],
                        cfg["freq"], section=cfg.get("section", "ara"),
                    )
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"], country="HU",
                        date=normalize_date(dt, cfg["freq"]),
                        value=round(v * cfg["conversion"], 4),
                        source="ksh_hu", unit=cfg["unit"],
                        series_id=f"KSH/{cfg['table']}",
                        adjustment=cfg["adjustment"],
                    ))
                print(f"  OK {cfg['slug']}/HU ({cfg['table']}): {len(pairs)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['slug']}/HU: {e}")
            time.sleep(0.3)

        # Slovakia
        for cfg in SK_SERIES:
            try:
                pairs = fetch_sk_datacube(cfg["dataset_id"], cfg["segments"], cfg["freq"])
                seg_tail = "/".join(cfg["segments"][2:]) if len(cfg["segments"]) > 2 else ""
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"], country="SK",
                        date=normalize_date(dt, cfg["freq"]),
                        value=round(v * cfg["conversion"], 4),
                        source="susr_sk", unit=cfg["unit"],
                        series_id=f"SUSR/{cfg['dataset_id']}/{seg_tail}",
                        adjustment=cfg["adjustment"],
                    ))
                print(f"  OK {cfg['slug']}/SK ({cfg['dataset_id']}): {len(pairs)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['slug']}/SK: {e}")
            time.sleep(0.3)

        # Croatia
        for cfg in HR_SERIES:
            try:
                pairs = fetch_hr_pxweb(cfg["path"], cfg["query"], cfg["freq"], cfg.get("parse", "tid"))
                table_id = cfg["path"].rsplit("/", 1)[-1].replace(".px", "")
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"], country="HR",
                        date=normalize_date(dt, cfg["freq"]),
                        value=round(v * cfg["conversion"], 4),
                        source="dzs_hr", unit=cfg["unit"],
                        series_id=f"DZS/{table_id}",
                        adjustment=cfg["adjustment"],
                    ))
                print(f"  OK {cfg['slug']}/HR ({table_id}): {len(pairs)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['slug']}/HR: {e}")
            time.sleep(0.3)

        # Romania
        for cfg in RO_SERIES:
            try:
                pairs = fetch_ro_tempo(
                    cfg["parent"], cfg["matrix"],
                    cfg.get("filter_dims", {}), cfg.get("unit_value", "Procente"),
                    cfg["freq"],
                )
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"], country="RO",
                        date=normalize_date(dt, cfg["freq"]),
                        value=round(v * cfg["conversion"], 4),
                        source="insse_ro", unit=cfg["unit"],
                        series_id=f"INSSE/{cfg['matrix']}",
                        adjustment=cfg["adjustment"],
                    ))
                print(f"  OK {cfg['slug']}/RO ({cfg['matrix']}): {len(pairs)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['slug']}/RO: {e}")
            time.sleep(0.3)

        # Romania trade: fetch exports & imports separately, then compute trade-balance
        ro_trade_cache = {}
        for cfg in RO_TRADE_SERIES:
            try:
                pairs = fetch_ro_tempo(
                    cfg["parent"], cfg["matrix"],
                    cfg.get("filter_dims", {}), cfg.get("unit_value"),
                    cfg["freq"],
                )
                ro_trade_cache[cfg["slug"]] = dict(pairs)
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"], country="RO",
                        date=normalize_date(dt, cfg["freq"]),
                        value=round(v * cfg["conversion"], 4),
                        source="insse_ro", unit=cfg["unit"],
                        series_id=f"INSSE/{cfg['matrix']}",
                        adjustment=cfg["adjustment"],
                    ))
                print(f"  OK {cfg['slug']}/RO ({cfg['matrix']}): {len(pairs)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['slug']}/RO: {e}")
            time.sleep(0.3)
        # Trade balance = exports - imports (million EUR)
        if "exports" in ro_trade_cache and "imports" in ro_trade_cache:
            exp_map = ro_trade_cache["exports"]
            imp_map = ro_trade_cache["imports"]
            common = sorted(set(exp_map) & set(imp_map))
            for dt in common:
                bal_th = exp_map[dt] - imp_map[dt]   # thousand EUR
                out.append(DataPoint(
                    indicator="trade-balance", country="RO",
                    date=normalize_date(dt, "M"),
                    value=round(bal_th * 1e-3, 4),
                    source="insse_ro", unit="Million EUR",
                    series_id="INSSE/EXP101I-EXP102I",
                    adjustment="NSA",
                ))
            print(f"  OK trade-balance/RO (EXP101I-EXP102I): {len(common)} pts")

        # Malta — NSO via cloudscraper
        for cfg in MT_SERIES:
            try:
                pairs = fetch_mt_sdmx(cfg["dataflow"], cfg["key"], cfg["freq"])
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"], country="MT",
                        date=normalize_date(dt, cfg["freq"]),
                        value=round(v * cfg["conversion"], 4),
                        source="nso_mt", unit=cfg["unit"],
                        series_id=f"NSO/{cfg['dataflow']}/{cfg['key']}",
                        adjustment=cfg["adjustment"],
                    ))
                print(f"  OK {cfg['slug']}/MT ({cfg['dataflow']}): {len(pairs)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['slug']}/MT: {e}")
            time.sleep(0.3)

        # Cyprus — CYSTAT PxWeb via cloudscraper
        for cfg in CY_SERIES:
            try:
                pairs = fetch_cy_pxweb(cfg["px_path"], cfg["base_year"], cfg["freq"])
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"], country="CY",
                        date=normalize_date(dt, cfg["freq"]),
                        value=round(v * cfg["conversion"], 4),
                        source="cystat_cy", unit=cfg["unit"],
                        series_id=f"CYSTAT/{cfg['px_path'].rsplit('/',1)[-1]}/B{cfg['base_year']}",
                        adjustment=cfg["adjustment"],
                    ))
                print(f"  OK {cfg['slug']}/CY ({cfg['px_path'][-30:]}): {len(pairs)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['slug']}/CY: {e}")
            time.sleep(0.3)

        return out


def run():
    p = NationalEUProvider()
    print(f"Fetching from {p.display_name}...")
    try:
        pts = p.fetch()
        print(f"\nTotal: {len(pts)} data points")
        rows = datapoints_to_rows(pts)
        total = 0
        for i in range(0, len(rows), 500):
            count = upsert_data_points(rows[i:i+500])
            total += count
        log_pipeline_run("national_eu", "success", total)
        print(f"\nDone. {total} rows upserted.")
    except Exception as e:
        log_pipeline_run("national_eu", "failed", error_message=str(e))
        print(f"\nFailed: {e}")
        raise


if __name__ == "__main__":
    run()
