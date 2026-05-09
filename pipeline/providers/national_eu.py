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
    # PRIS4221: Producer price index for commodities
    # STANDGRP=BC (Mining+Manufacturing), TAL=100 (Index level)
    {"slug": "ppi", "table": "PRIS4221",
     "filters": {"STANDGRP": "BC", "TAL": "100"},
     "freq": "M", "unit": "Index", "adjustment": "NSA", "conversion": 1.0,
     "note": "DK Statbank PRIS4221 PPI mining+manufacturing index"},
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

PT_SERIES = [
    # IPC base 2025 (varcd 0008273 = total) — TE shows Apr 2026 = 0.4%
    # Use op=2 to get latest period as JSON
    {"slug": "inflation-cpi", "varcd": "0008273", "freq": "M",
     "unit": "Index", "adjustment": "NSA", "conversion": 1.0,
     "note": "PT INE IPC total nacional"},
]


def fetch_pt_indicator(varcd: str, freq: str = "M") -> list[tuple[date, float]]:
    """INE Portugal JSON-Indicador, last 60 obs."""
    url = f"https://www.ine.pt/ine/json_indicador/pindica.jsp?op=2&varcd={varcd}&lang=EN"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    js = r.json()
    # Structure: list of {"Sucesso": [...]} with Dados under nested keys
    out = []
    for entry in js:
        sucesso = entry.get("Sucesso", {})
        if isinstance(sucesso, dict):
            verd = sucesso.get("Verdadeiro", [])
        else:
            verd = sucesso
        for item in verd if isinstance(verd, list) else []:
            dados = item.get("Dados", {})
            if isinstance(dados, dict):
                for period_key, obs_list in dados.items():
                    if not isinstance(obs_list, list):
                        continue
                    for obs in obs_list:
                        val_str = obs.get("valor")
                        try:
                            val = float(val_str)
                        except (ValueError, TypeError):
                            continue
                        # period_key like "2026M04" or "S7A2024"
                        per = period_key.replace("S7A", "")
                        dt = _parse_period(per, freq)
                        if dt:
                            out.append((dt, val))
    return sorted(out)


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
     "freq": "M", "unit": "EUR thousand", "adjustment": "NSA", "conversion": 1.0,
     "note": "CSO Ireland TSM01 Merchandise Trade Surplus (Exports-Imports) NSA"},
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


# === Belgium — Statbel REST API (CSV) ===
# Statbel uses unique view IDs per dataset. We pre-resolve them.
# bestat.statbel.fgov.be/bestat/api/views?lang=en&format=json gives the list.
# For inflation: search "consumer price index" — view ID encoded.

BE_SERIES = [
    # Statbel API via bestat.statbel.fgov.be — view ID for "Consumer price index,
    # inflation, health index..." monthly. Gives ~13 months history.
    {"slug": "inflation-cpi", "view_id": "208b69bd-05c5-4947-b7f9-2d2300f517b8",
     "value_col": "Consumer price index",
     "freq": "M", "unit": "Index (2013=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "Statbel CPI base 2013=100, last 13 months"},
]


def fetch_be_statbel_csv(view_id: str, value_col: str, freq: str = "M") -> list[tuple[date, float]]:
    """Statbel publishes views as CSV. Year/Month columns + named value cols."""
    import csv as csvm, io as iom
    url = f"https://bestat.statbel.fgov.be/bestat/api/views/{view_id}/result/CSV"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    reader = csvm.DictReader(iom.StringIO(r.text))
    out = []
    months_map = {"January":1,"February":2,"March":3,"April":4,"May":5,"June":6,
                  "July":7,"August":8,"September":9,"October":10,"November":11,"December":12}
    for row in reader:
        month_text = row.get("Month", "")
        # "January 2025" -> 2025-01
        try:
            mname, ystr = month_text.rsplit(" ", 1)
            yy = int(ystr)
            mm = months_map[mname]
            dt = date(yy, mm, 1)
        except Exception:
            continue
        val_str = row.get(value_col, "").replace(",", "")
        try:
            val = float(val_str)
        except ValueError:
            continue
        out.append((dt, val))
    return sorted(out)


def fetch_nbb_sdmx(dataset: str, key: str, freq: str = "M") -> list[tuple[date, float]]:
    """NBB SDMX V21 endpoint."""
    url = f"https://stat.nbb.be/sdmx/V21/data/{dataset}/{key}"
    r = requests.get(url, headers={"Accept": "application/json"}, timeout=30)
    r.raise_for_status()
    js = r.json()
    # SDMX-JSON structure
    series = js.get("data", {}).get("dataSets", [{}])[0].get("series", {})
    out = []
    for ser_key, ser_data in series.items():
        observations = ser_data.get("observations", {})
        time_dim = js["data"]["structure"]["dimensions"]["observation"][0]["values"]
        for obs_idx_str, obs_value in observations.items():
            obs_idx = int(obs_idx_str)
            if obs_idx >= len(time_dim):
                continue
            period = time_dim[obs_idx]["id"]
            dt = _parse_period(period, freq)
            if dt and obs_value and obs_value[0] is not None:
                out.append((dt, float(obs_value[0])))
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
    # vpi20 (base 2020) covers 2021-01 to 2025-12 monthly. F-VPIMZVM is the index level;
    # filter VPI5NEU = VPI-0 for all-items.
    {"slug": "inflation-cpi", "ogd": "OGD_vpi20_VPI_2020_1",
     "filter_col": "C-VPI5NEU-0", "filter_val": "VPI-0",
     "value_col": "F-VPIMZVM",
     "freq": "M", "unit": "Index", "adjustment": "NSA", "conversion": 1.0,
     "note": "Statistik Austria VPI base 2020=100 (covers 2021-01..2025-12)"},
    # vpi25 (base 2025) for 2026 onwards. We'll add it as a supplementary row that data_points
    # gets merged on (date, indicator, country, source) — but use a different source code so
    # rows don't conflict. Actually keep it simple — use vpi20 for now.
]


def fetch_at_csv(ogd: str, filter_col: str, filter_val: str, value_col: str, freq: str = "M") -> list[tuple[date, float]]:
    """Fetch Statistik Austria OGD CSV, filter and parse."""
    import csv as csvm
    import io as iom
    url = f"https://data.statistik.gv.at/data/{ogd}.csv"
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    reader = csvm.DictReader(iom.StringIO(r.text), delimiter=";")
    out = []
    for row in reader:
        if row.get(filter_col) != filter_val:
            continue
        time_code = row.get("C-VPIZR-0") or row.get("C-MZR-0") or row.get("C-ZR-0") or ""
        # VPIZR-202601 -> 2026-01 (monthly), VPIZR-2025 -> 2025 (annual; skip)
        if not time_code or "-" not in time_code:
            continue
        period = time_code.split("-")[1]
        if len(period) == 6 and period.isdigit():
            try:
                yy, mm = int(period[:4]), int(period[4:6])
                dt = date(yy, mm, 1)
            except Exception:
                continue
        else:
            # annual or unsupported - skip monthly-only fetcher
            continue
        val_str = row.get(value_col, "").replace(",", ".")
        try:
            val = float(val_str)
        except ValueError:
            continue
        if val == 0.0:  # placeholder for missing data in some rows
            continue
        out.append((dt, val))
    return sorted(out)


# === Slovenia — SURS PxWeb (pxweb.stat.si) ===

SI_SERIES = [
    # 0400608S CPI ECOICOP v2 — TOT = all-items, MERITVE=2 = Index (same month previous year)
    # Better: MERITVE=3 (Index month/Dec of previous year). For our use we want the LEVEL.
    # Use MERITVE=2 which is the most-cited YoY index format. Or MERITVE=1 for month-on-month.
    # The cleanest "level" doesn't exist directly — SI publishes only relatives.
    # Use MERITVE=2 (Index vs same month previous year) — TE shows YoY rate, this is the source.
    {"slug": "inflation-cpi", "table": "0400608S.px",
     "query": {"ŽIVLJENJSKA POTREBŠČINA": "TOT", "MERITVE": "2"},
     "freq": "M", "unit": "Index (same month py=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "SURS 0400608S CPI YoY index (same-month-previous-year=100), TOTAL"},
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

LV_SERIES = [
    # PCI030m: Consumer price indices December 1990=100, monthly 1991M01-2026M03
    {"slug": "inflation-cpi", "table": "PCI030m",
     "query": {"ContentsCode": "PCI030m"},
     "freq": "M", "unit": "Index (Dec 1990=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "CSP Latvia PCI030m CPI Dec 1990=100"},
]


def fetch_lv_pxweb(table_path: str, query_filters: dict, freq: str = "M") -> list[tuple[date, float]]:
    url = f"https://data.stat.gov.lv/api/v1/en/OSP_PUB/VEK/PC/PCI/{table_path}"
    body = {
        "query": [{"code": k, "selection": {"filter": "item", "values": [v]}}
                  for k, v in query_filters.items()],
        "response": {"format": "json-stat2"},
    }
    r = requests.post(url, json=body, timeout=30)
    r.raise_for_status()
    return _parse_jsonstat(r.json(), freq)


# === Romania — INSSE Tempo (HTTP only on port 8077) ===

RO_SERIES = [
    # IPC102A: monthly CPI vs previous month=100. Via tempo-py library.
    {"slug": "inflation-cpi", "matrix": "IPC102A", "category_label": "Total",
     "freq": "M", "unit": "Index (prev month=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "INSSE Tempo IPC102A monthly CPI MoM index (prev month=100)"},
]


def fetch_ro_tempo(matrix: str, category_label: str = "Total", freq: str = "M") -> list[tuple[date, float]]:
    """RO INSSE Tempo via tempo-py library. Returns CSV-formatted text:
    'Categorii..., Luni, UM, Valoare\nTotal, Luna ianuarie 1991, Procente, 114.8\n...'
    """
    import tempo
    RO_MONTHS = {"ianuarie":1, "februarie":2, "martie":3, "aprilie":4, "mai":5, "iunie":6,
                 "iulie":7, "august":8, "septembrie":9, "octombrie":10, "noiembrie":11, "decembrie":12}
    node = tempo.Node()
    # Find leaf by code via children search
    parent_4000 = node.by_code("4000")
    leaves = [c for c in (parent_4000.children if parent_4000 else []) if c.code == matrix]
    if not leaves:
        return []
    leaf = leaves[0]
    # Get full month list from dim
    months = [opt.label for opt in leaf.dimensions[1].options]
    csv_text = leaf.query(
        (leaf.dimensions[0].label, [category_label]),
        ("Luni", months),
        ("UM: Procente", ["Procente"]),
    )
    out = []
    for line in csv_text.splitlines()[1:]:  # skip header
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            continue
        period = parts[1].lower()
        try:
            val = float(parts[3])
        except ValueError:
            continue
        # "luna ianuarie 1991" or "anul 1991"
        words = period.split()
        if len(words) == 3 and words[0] == "luna":
            month_name, year = words[1], words[2]
            if month_name in RO_MONTHS:
                try:
                    out.append((date(int(year), RO_MONTHS[month_name], 1), val))
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
]


def fetch_ee_pxweb(path: str, query_filters: dict, freq: str = "M") -> list[tuple[date, float]]:
    """Estonia PxWeb. Note: their tables often have separate Year and Month dims (not single Tid)."""
    url = f"https://andmed.stat.ee/api/v1/en/stat/{path}"
    body = {
        "query": [{"code": k, "selection": {"filter": "item", "values": [v]}}
                  for k, v in query_filters.items()],
        "response": {"format": "json-stat2"},
    }
    r = requests.post(url, json=body, timeout=30)
    r.raise_for_status()
    js = r.json()
    # If freq is 'M_year_month_combo', the table has Year and Month dims separately
    if freq == "M_year_month_combo":
        return _parse_jsonstat_year_month(js)
    return _parse_jsonstat(js, freq)


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
    {"slug": "inflation-cpi", "table": "ara0040",
     "value_col_index": 9,  # 0-indexed: Year=0, Month=1, ..., Total=9
     "freq": "M", "unit": "Index (same month previous year=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "KSH STADAT 1.2.1.2 ara0040 CPI total YoY Index (sm-py=100)"},
]

HU_MONTHS = {
    "January":1, "February":2, "March":3, "April":4, "May":5, "June":6,
    "July":7, "August":8, "September":9, "October":10, "November":11, "December":12,
}


def fetch_hu_stadat(table: str, value_col_index: int, freq: str = "M") -> list[tuple[date, float]]:
    """Scrape KSH STADAT HTML table. Year repeats only on January-row.
    KSH tables have multiple sections (YoY/MoM/base100); we keep only first occurrence
    of each (year, month) tuple — that's the YoY section which appears first."""
    import bs4
    url = f"https://www.ksh.hu/stadat_files/ara/en/{table}.html"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    soup = bs4.BeautifulSoup(r.text, "html.parser")
    out = []
    seen = set()
    table_el = soup.find("table")
    if not table_el:
        return out
    current_year = None
    for tr in table_el.find_all("tr"):
        cells = [c.get_text(strip=True) for c in tr.find_all(["td", "th"])]
        if not cells:
            continue
        # Header rows have all-text cells; data rows start with Year (4-digit) or empty
        first = cells[0]
        # Skip header rows
        if first.lower() in ("period", "") and len(cells) >= 2 and cells[1] not in HU_MONTHS:
            continue
        # Year carry-over
        if first.isdigit() and len(first) == 4:
            current_year = int(first)
            month_text = cells[1] if len(cells) > 1 else ""
        elif first == "" and len(cells) >= 2 and cells[1] in HU_MONTHS:
            # continuation row — first cell is empty, month is in cells[1]
            month_text = cells[1]
        elif first in HU_MONTHS:
            month_text = first
        else:
            continue
        if month_text not in HU_MONTHS:
            continue
        if current_year is None:
            continue
        # Get the value at value_col_index
        if value_col_index < len(cells):
            key = (current_year, HU_MONTHS[month_text])
            if key in seen:
                continue
            seen.add(key)
            val_str = cells[value_col_index].replace(",", ".").replace("\xa0", "")
            try:
                val = float(val_str)
            except ValueError:
                continue
            out.append((date(current_year, HU_MONTHS[month_text], 1), val))
    return sorted(out)


# === Slovakia — Štatistický úrad SR DataCube REST ===

SK_SERIES = [
    # sp2038ms: Consumer Price Indices by COICOP - monthly. Hierarchy:
    # /dataset/sp2038ms/{years CSV}/{months CSV or all}/{coicop}/{measure}
    # odb01 = Úhrn (Total), mj38 = December 2000=100 (continuous index)
    {"slug": "inflation-cpi", "dataset_id": "sp2038ms",
     "years": "2010,2011,2012,2013,2014,2015,2016,2017,2018,2019,2020,2021,2022,2023,2024,2025,2026",
     "coicop": "odb01", "measure": "mj38",
     "freq": "M", "unit": "Index (Dec 2000=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "ŠÚ SR sp2038ms CPI Total, Dec 2000=100 continuous monthly"},
]


def fetch_sk_datacube(dataset_id: str, years: str, coicop: str, measure: str, freq: str = "M") -> list[tuple[date, float]]:
    """SK datacube: /dataset/{id}/{years}/all/{coicop}/{measure}"""
    url = f"https://data.statistics.sk/api/v2.0/dataset/{dataset_id}/{years}/all/{coicop}/{measure}"
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    js = r.json()
    sizes = js.get("size", [])
    values = js.get("value", [])
    if not sizes or not values:
        return []
    # Find year and month dim positions
    dim_ids = js.get("id", [])
    year_pos = next((i for i, k in enumerate(dim_ids) if "rok" in k.lower()), None)
    month_pos = next((i for i, k in enumerate(dim_ids) if "mes" in k.lower()), None)
    if year_pos is None or month_pos is None:
        return []
    year_idx = js["dimension"][dim_ids[year_pos]]["category"]["index"]
    month_idx = js["dimension"][dim_ids[month_pos]]["category"]["index"]
    # idx may be list (=positional) or dict
    if isinstance(year_idx, dict):
        year_pairs = list(year_idx.items())
    else:
        year_pairs = [(c, i) for i, c in enumerate(year_idx)]
    if isinstance(month_idx, dict):
        month_pairs = list(month_idx.items())
    else:
        month_pairs = [(c, i) for i, c in enumerate(month_idx)]

    out = []
    for ycode, ypos in year_pairs:
        try:
            yy = int(ycode)
        except ValueError:
            continue
        for mcode, mpos in month_pairs:
            mm_str = mcode.rstrip(".")
            try:
                mm = int(mm_str)
            except ValueError:
                continue
            if mm < 1 or mm > 12:
                continue
            # Build flat index across all dims
            indices = [0] * len(dim_ids)
            indices[year_pos] = ypos
            indices[month_pos] = mpos
            flat = 0
            stride = 1
            for i in range(len(dim_ids) - 1, -1, -1):
                flat += indices[i] * stride
                stride *= sizes[i]
            if 0 <= flat < len(values):
                v = values[flat]
                if v is not None:
                    out.append((date(yy, mm, 1), float(v)))
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

HR_SERIES = [
    # ME_PS09.px CPI ECOICOP v2 monthly. ECOICOP_ver_2='00' (Total), Indikatori='4' (index 2025=100)
    {"slug": "inflation-cpi",
     "path": "Cijene/Indeksi potrošačkih cijena/Indeksi potrošačkih cijena – ECOICOP, ver. 2/ME_PS09.px",
     "query": {"ECOICOP, ver. 2": "00", "Indikatori": "4"},
     "freq": "M", "unit": "Index (2025=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "DZS Croatia ME_PS09 CPI 2025=100 total ECOICOP v2"},
]


def fetch_hr_pxweb(path: str, query_filters: dict, freq: str = "M") -> list[tuple[date, float]]:
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
    return _parse_jsonstat(r.json(), freq)


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
        for cfg in FI_SERIES:
            try:
                pairs = fetch_fi_table(cfg["path"], cfg["query"], cfg["freq"])
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"], country="FI",
                        date=normalize_date(dt, cfg["freq"]),
                        value=round(v * cfg["conversion"], 4),
                        source="stat_fi", unit=cfg["unit"],
                        series_id=f"STATFI/{cfg['path']}",
                        adjustment=cfg["adjustment"],
                    ))
                print(f"  OK {cfg['slug']}/FI ({cfg['path'][-30:]}): {len(pairs)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['slug']}/FI: {e}")
            time.sleep(0.3)

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
                pairs = fetch_pt_indicator(cfg["varcd"], cfg["freq"])
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
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"], country="IE",
                        date=normalize_date(dt, cfg["freq"]),
                        value=round(v * cfg["conversion"], 4),
                        source="cso_ie", unit=cfg["unit"],
                        series_id=f"CSO/{cfg['table']}",
                        adjustment=cfg["adjustment"],
                    ))
                print(f"  OK {cfg['slug']}/IE ({cfg['table']}): {len(pairs)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['slug']}/IE: {e}")
            time.sleep(0.3)

        # Austria
        for cfg in AT_SERIES:
            try:
                pairs = fetch_at_csv(cfg["ogd"], cfg["filter_col"], cfg["filter_val"], cfg["value_col"], cfg["freq"])
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
                pairs = fetch_lv_pxweb(cfg["table"], cfg["query"], cfg["freq"])
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"], country="LV",
                        date=normalize_date(dt, cfg["freq"]),
                        value=round(v * cfg["conversion"], 4),
                        source="csp_lv", unit=cfg["unit"],
                        series_id=f"CSP/{cfg['table']}",
                        adjustment=cfg["adjustment"],
                    ))
                print(f"  OK {cfg['slug']}/LV ({cfg['table']}): {len(pairs)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['slug']}/LV: {e}")
            time.sleep(0.3)

        # Estonia
        for cfg in EE_SERIES:
            try:
                pairs = fetch_ee_pxweb(cfg["path"], cfg["query"], cfg["freq"])
                eff_freq = "M" if cfg["freq"] == "M_year_month_combo" else cfg["freq"]
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"], country="EE",
                        date=normalize_date(dt, eff_freq),
                        value=round(v * cfg["conversion"], 4),
                        source="stat_ee", unit=cfg["unit"],
                        series_id=f"STATEE/{cfg['path']}",
                        adjustment=cfg["adjustment"],
                    ))
                print(f"  OK {cfg['slug']}/EE ({cfg['path'][-25:]}): {len(pairs)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['slug']}/EE: {e}")
            time.sleep(0.3)

        # Belgium
        for cfg in BE_SERIES:
            try:
                pairs = fetch_be_statbel_csv(cfg["view_id"], cfg["value_col"], cfg["freq"])
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"], country="BE",
                        date=normalize_date(dt, cfg["freq"]),
                        value=round(v * cfg["conversion"], 4),
                        source="statbel", unit=cfg["unit"],
                        series_id=f"STATBEL/{cfg['view_id'][:8]}",
                        adjustment=cfg["adjustment"],
                    ))
                print(f"  OK {cfg['slug']}/BE (Statbel): {len(pairs)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['slug']}/BE: {e}")
            time.sleep(0.3)

        # Hungary
        for cfg in HU_SERIES:
            try:
                pairs = fetch_hu_stadat(cfg["table"], cfg["value_col_index"], cfg["freq"])
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
                pairs = fetch_sk_datacube(cfg["dataset_id"], cfg["years"], cfg["coicop"], cfg["measure"], cfg["freq"])
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"], country="SK",
                        date=normalize_date(dt, cfg["freq"]),
                        value=round(v * cfg["conversion"], 4),
                        source="susr_sk", unit=cfg["unit"],
                        series_id=f"SUSR/{cfg['dataset_id']}/{cfg['coicop']}/{cfg['measure']}",
                        adjustment=cfg["adjustment"],
                    ))
                print(f"  OK {cfg['slug']}/SK ({cfg['dataset_id']}): {len(pairs)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['slug']}/SK: {e}")
            time.sleep(0.3)

        # Croatia
        for cfg in HR_SERIES:
            try:
                pairs = fetch_hr_pxweb(cfg["path"], cfg["query"], cfg["freq"])
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"], country="HR",
                        date=normalize_date(dt, cfg["freq"]),
                        value=round(v * cfg["conversion"], 4),
                        source="dzs_hr", unit=cfg["unit"],
                        series_id=f"DZS/{cfg['path'][-30:]}",
                        adjustment=cfg["adjustment"],
                    ))
                print(f"  OK {cfg['slug']}/HR (ME_PS09): {len(pairs)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['slug']}/HR: {e}")
            time.sleep(0.3)

        # Romania
        for cfg in RO_SERIES:
            try:
                pairs = fetch_ro_tempo(cfg["matrix"], cfg.get("category_label", "Total"), cfg["freq"])
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
