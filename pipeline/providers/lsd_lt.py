"""LSD Lithuania (Lietuvos statistikos departamentas) direct provider.

Trading Economics names the Lithuanian Statistics Office (LSD) as the primary
source for Lithuania's inflation/PPI etc. The LSD's user-facing portals
(osp.stat.gov.lt, www.lb.lt) sit behind Cloudflare Turnstile, but Lithuania's
official open-data gateway data.gov.lt re-publishes the same LSD datasets
through a stable, cookie-less REST API:

    https://get.data.gov.lt/datasets/gov/lsd/<namespace>/<table_id>?<query>

The API is documented at https://get.data.gov.lt/ and uses a small RQL-like
query language: ?select(col1,col2)&col="value"&sort(-col)&limit(N).
The data is the official LSD publication (we verified field-for-field that
laikotarpis (date) + verte (value) match the LSD's own SVKI / pramones tables).

Indicators implemented (M = monthly):
  inflation-cpi  -- SVKI (HICP) total, 2015=100, all-items (ecoicop_id="00")
                   covers 1996-01..present, ~360+ obs
  ppi            -- Pramones produkcijos kainu indeksai, total industry B_TO_E,
                   total market (rinka_id="1"), 2015=100, ~300+ obs

Both index series are published as raw index levels — no transform needed.
TE shows YoY rates for both; the frontend computes those from the index.
"""
from __future__ import annotations

import os
import re
import time
from datetime import date
from typing import Any

import requests
from dotenv import load_dotenv

from pipeline.base_provider import BaseProvider, DataPoint
from pipeline.transforms import normalize_date
from pipeline.db import upsert_data_points, log_pipeline_run, datapoints_to_rows

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))


GET_BASE = "https://get.data.gov.lt/datasets/gov/lsd/statistika"
HTTP_HEADERS = {
    "User-Agent": "EconPulse/1.0 (data.gov.lt official open-data API)",
    "Accept": "application/json",
}

# Official LSD SDMX REST v2.1 endpoint (no Cloudflare unlike osp.stat.gov.lt).
# Sample: https://osp-rs.stat.gov.lt/rest_xml/data/<DATAFLOW_ID>
# Dataflow IDs (S<NNN>R<NNN>_M<digits>) discovered via
# /rest_xml/dataflow/LSD/all/latest. Used here for indicators the
# data.gov.lt /datasets endpoint does NOT republish (industrial production
# index, labour cost index, DG-ECFIN confidence, monthly food-CPI YoY,
# quarterly LFS unemployed-persons / LFP / long-term unemp-rate).
SDMX_BASE = "https://osp-rs.stat.gov.lt/rest_xml/data"
SDMX_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; EconPulse/1.0)",
    "Accept": "application/xml",
}


# Series catalogue — keep self-describing config close to fetch logic.
# Each entry produces one indicator/country DataPoint stream.
LT_SERIES: list[dict[str, Any]] = [
    {
        "slug": "inflation-cpi",
        "ns": "svki",
        "table_id": "S7R246M2020217",
        "filter": {"ecoicop_id": "00"},  # Total HICP all-items
        "freq": "M",
        "unit": "Index (2015=100)",
        "adjustment": "NSA",
        "conversion": 1.0,
        "note": "LSD SVKI (HICP) all-items total, 2015=100",
    },
    {
        "slug": "ppi",
        "ns": "pramones_produk_kainu_indeksai",
        "table_id": "S7R259M2020327",
        "filter": {"evrk_id": "B_TO_E", "rinka_id": "1"},  # Industry total, total market
        "freq": "M",
        "unit": "Index (2015=100)",
        "adjustment": "NSA",
        "conversion": 1.0,
        "note": "LSD Pramones produkcijos kainu indeksai, B_TO_E total industry, visa rinka",
    },
    # Retail trade turnover index (constant prices, 2015=100), monthly.
    # evrk_2_id="G47" = retail trade except motor vehicles/motorcycles;
    # islyginimas_id="sezon" = SA; lyginimas_id="palyg_2021" = 2021 index level
    {
        "slug": "retail-sales",
        "ns": "mazmen_prekyb_imoniu_apyvartos_indeksai",
        "table_id": "S8R838M40701035",
        "filter": {"evrk_2_id": "G47", "islyginimas_id": "sezon", "lyginimas_id": "palyg_2021"},
        "freq": "M",
        "unit": "Index (2021=100)",
        "adjustment": "SA",
        "conversion": 1.0,
        "note": "LSD Mazmenines prekybos apyvartos indeksai G47 SA 2021=100",
    },
    # GDP at comparable prices (chain-linked), quarterly mln EUR.
    # islyginimas_id="darbo" = working-day adjusted (only available; no NSA)
    {
        "slug": "gdp-real",
        "ns": "bvp_palyginamosiomis_kainomis",
        "table_id": "S7R203M21101011",
        "filter": {"islyginimas_id": "darbo"},
        "freq": "Q",
        "unit": "Million EUR (chain-linked)",
        "adjustment": "CA",
        "conversion": 1.0,
        "note": "LSD BVP palyginamosiomis kainomis (chain-linked), working-day adj, mln EUR",
    },
    # Annual unemployment rate (LFS, ages 15+), national total, both sexes.
    # teritorija_id="00" = Lietuvos Respublika (national); lytis_id="0" = Both sexes;
    # amzius_15_24_ir_vyresni_id="15_ir_daugiau" = age 15+.
    {
        "slug": "unemployment",
        "ns": "metinis_nedarbo_lygis",
        "table_id": "S3R347M3030903",
        "filter": {"teritorija_id": "00", "lytis_id": "0", "amzius_15_24_ir_vyresni_id": "15_ir_daugiau"},
        "freq": "A",
        "unit": "%",
        "adjustment": "NSA",
        "conversion": 1.0,
        "note": "LSD Metinis nedarbo lygis age 15+ both sexes LT national annual %",
    },
    # === gapfill batch (043_lt_gapfill) ===
    # SVKI HICP by COICOP top-level groups (01..12), monthly, 2015=100
    {"slug": "cpi-food", "ns": "svki", "table_id": "S7R246M2020217",
     "filter": {"ecoicop_id": "01"},
     "freq": "M", "unit": "Index (2015=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "LSD SVKI HICP COICOP 01 Food and non-alcoholic beverages, 2015=100"},
    {"slug": "cpi-clothing", "ns": "svki", "table_id": "S7R246M2020217",
     "filter": {"ecoicop_id": "03"},
     "freq": "M", "unit": "Index (2015=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "LSD SVKI HICP COICOP 03 Clothing and footwear"},
    {"slug": "cpi-housing-utilities", "ns": "svki", "table_id": "S7R246M2020217",
     "filter": {"ecoicop_id": "04"},
     "freq": "M", "unit": "Index (2015=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "LSD SVKI HICP COICOP 04 Housing, water, electricity, gas"},
    {"slug": "cpi-transportation", "ns": "svki", "table_id": "S7R246M2020217",
     "filter": {"ecoicop_id": "07"},
     "freq": "M", "unit": "Index (2015=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "LSD SVKI HICP COICOP 07 Transport"},
    {"slug": "cpi-recreation-and-culture", "ns": "svki", "table_id": "S7R246M2020217",
     "filter": {"ecoicop_id": "09"},
     "freq": "M", "unit": "Index (2015=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "LSD SVKI HICP COICOP 09 Recreation and culture"},
    {"slug": "cpi-education", "ns": "svki", "table_id": "S7R246M2020217",
     "filter": {"ecoicop_id": "10"},
     "freq": "M", "unit": "Index (2015=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "LSD SVKI HICP COICOP 10 Education"},
    # GDP by expenditure approach, chain-linked (reference year 2020), quarterly mln EUR, SA
    {"slug": "consumer-spending", "ns": "bvp_grandininiu_susiejimu", "table_id": "S7R208M21101072",
     "filter": {"islaidu_rusis_id": "p31_S14", "matavimo_vienetai_id": "mln_euru", "islyginimas_id": "sezon"},
     "freq": "Q", "unit": "Million EUR (2020 chain-linked)", "adjustment": "SA", "conversion": 1.0,
     "note": "LSD chain-linked GDP household final consumption (P31_S14), SA"},
    {"slug": "government-spending", "ns": "bvp_grandininiu_susiejimu", "table_id": "S7R208M21101072",
     "filter": {"islaidu_rusis_id": "p3_S13", "matavimo_vienetai_id": "mln_euru", "islyginimas_id": "sezon"},
     "freq": "Q", "unit": "Million EUR (2020 chain-linked)", "adjustment": "SA", "conversion": 1.0,
     "note": "LSD chain-linked GDP government final consumption (P3_S13), SA"},
    {"slug": "gross-fixed-capital-formation", "ns": "bvp_grandininiu_susiejimu", "table_id": "S7R208M21101072",
     "filter": {"islaidu_rusis_id": "p51g", "matavimo_vienetai_id": "mln_euru", "islyginimas_id": "sezon"},
     "freq": "Q", "unit": "Million EUR (2020 chain-linked)", "adjustment": "SA", "conversion": 1.0,
     "note": "LSD chain-linked GDP gross fixed capital formation (P51G), SA"},
    {"slug": "exports", "ns": "bvp_grandininiu_susiejimu", "table_id": "S7R208M21101072",
     "filter": {"islaidu_rusis_id": "p6", "matavimo_vienetai_id": "mln_euru", "islyginimas_id": "sezon"},
     "freq": "Q", "unit": "Million EUR (2020 chain-linked)", "adjustment": "SA", "conversion": 1.0,
     "note": "LSD chain-linked GDP exports of goods and services (P6), SA"},
    {"slug": "imports", "ns": "bvp_grandininiu_susiejimu", "table_id": "S7R208M21101072",
     "filter": {"islaidu_rusis_id": "p7", "matavimo_vienetai_id": "mln_euru", "islyginimas_id": "sezon"},
     "freq": "Q", "unit": "Million EUR (2020 chain-linked)", "adjustment": "SA", "conversion": 1.0,
     "note": "LSD chain-linked GDP imports of goods and services (P7), SA"},
    # changes-in-inventories: chain-linked is null; fall back to current prices table (bvp_islaidu_metodu)
    {"slug": "changes-in-inventories", "ns": "bvp_islaidu_metodu", "table_id": "S7R192M21101071",
     "filter": {"islaidu_rusis_id": "p52", "matavimo_vienetai_id": "mln_euru", "islyginimas_id": "sezon"},
     "freq": "Q", "unit": "Million EUR (current prices)", "adjustment": "SA", "conversion": 1.0,
     "note": "LSD GDP changes in inventories (P52), current prices, SA"},
    # uzimtumas_ess2010: ESA 2010 employment, quarterly, total economy ('TOTAL'), persons (empl), SA
    {"slug": "employed-persons", "ns": "uzimtumas_ess2010", "table_id": "S7R219M2110133",
     "filter": {"ekonomines_veiklos_rusis_id": "TOTAL", "uzimtuju_klasifikacija_id": "empl",
                "matavimo_vienetai_id": "tukst_asmenu", "islyginimas_id": "sezon"},
     "freq": "Q", "unit": "Thousand persons", "adjustment": "SA", "conversion": 1.0,
     "note": "LSD ESA2010 employment total economy, persons, SA"},
    # Population at year start (annual)
    {"slug": "population", "ns": "nuolatiniai_gyventojai", "table_id": "S3R167M3010202",
     "filter": {"administracine_teritorija_id": "00", "amzius_id": "g000g999", "lytis_id": "0"},
     "freq": "A", "unit": "Million persons", "adjustment": "NSA", "conversion": 0.000001,
     "note": "LSD permanent population at 1 January, total LT"},
    # Maastricht government debt (gross debt at face value), quarterly mln EUR
    {"slug": "government-debt", "ns": "valdzios_sektoriaus_mastrichto_skola", "table_id": "S7R267M2040215",
     "filter": {"institucinis_sektorius_id": "S13", "skolos_rodikliai_id": "GD",
                "matavimo_vienetai_id": "mln_euru"},
     "freq": "Q", "unit": "Million EUR", "adjustment": "NSA", "conversion": 1.0,
     "note": "LSD General government Maastricht (gross) debt, mln EUR"},
]


# === Stage-3 SDMX series ===
# Series fetched via SDMX REST (osp-rs.stat.gov.lt) for indicators not exposed
# through data.gov.lt. Filter dict pins all non-time dimensions to a single
# code; the SDMX parser keeps observations matching every (dim, value) pair.
LT_SDMX_SERIES: list[dict[str, Any]] = [
    # Industrial production index 2021=100, SA (seasonally adjusted).
    # Dataflow S8R918_M4050113_5: "Indexes of industrial production (VAT and excises excluded) (2021 - 100)".
    # EVRKM4050107=B_TO_E_NOT_C19 -> total industry excl. refined petroleum (TE/Eurostat convention),
    # LYGINIMAS=palyg_2021 (index 2021=100), Islyginimas_indeksai=sezon (SA).
    {"slug": "industrial-production", "flow": "S8R918_M4050113_5",
     "filter": {"EVRKM4050107": "B_TO_E_NOT_C19", "LYGINIMAS": "palyg_2021",
                "Islyginimas_indeksai": "sezon"},
     "freq": "M", "unit": "Index (2021=100)", "adjustment": "SA", "conversion": 1.0,
     "note": "LSD S8R918 IP index total industry excl. refined petroleum, 2021=100, SA"},
    # Manufacturing (NACE C) IP index 2021=100, SA
    {"slug": "manufacturing-production", "flow": "S8R918_M4050113_5",
     "filter": {"EVRKM4050107": "C", "LYGINIMAS": "palyg_2021",
                "Islyginimas_indeksai": "sezon"},
     "freq": "M", "unit": "Index (2021=100)", "adjustment": "SA", "conversion": 1.0,
     "note": "LSD S8R918 manufacturing (C) IP index, 2021=100, SA"},
    # Mining and quarrying (NACE B) IP index 2021=100, SA
    {"slug": "mining-production", "flow": "S8R918_M4050113_5",
     "filter": {"EVRKM4050107": "B", "LYGINIMAS": "palyg_2021",
                "Islyginimas_indeksai": "sezon"},
     "freq": "M", "unit": "Index (2021=100)", "adjustment": "SA", "conversion": 1.0,
     "note": "LSD S8R918 mining and quarrying (B) IP index, 2021=100, SA"},
    # Food inflation YoY %: S7R250_M2020120 "Changes in prices of food and non-alcoholic beverages".
    # maistasM2020120=01 (COICOP CP01 food & non-alcoholic beverages aggregate),
    # LYGINIMAS=palyg_pm (vs corresponding month prev year, YoY %).
    {"slug": "food-inflation", "flow": "S7R250_M2020120",
     "filter": {"maistasM2020120": "01", "LYGINIMAS": "palyg_pm"},
     "freq": "M", "unit": "%", "adjustment": "NSA", "conversion": 1.0,
     "note": "LSD S7R250 food & non-alcoholic beverages YoY % (COICOP 01)"},
    # Labour cost index 2020=100, NSA, total industry (B_TO_S, all costs).
    # S3R0452_M3060508_1: "Indexes of labour costs per hour worked (2020 = 100)"
    # IslyginimasM3060501=NSA, darboM2040601=TOT (total labour cost), EVRK2M3060503=B_TO_S (private+public total).
    # Returns quarterly (Lithuanian "K" = ketvirtis).
    {"slug": "labour-costs", "flow": "S3R0452_M3060508_1",
     "filter": {"IslyginimasM3060501": "NSA", "darboM2040601": "TOT",
                "EVRK2M3060503": "B_TO_S"},
     "freq": "Q", "unit": "Index (2020=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "LSD S3R0452 LCI total labour cost per hour worked, B-S total, 2020=100, NSA"},
    # Job vacancies (quarterly), total economy, NSA. S3R275_M3040102_1.
    # darbuotojuSKM2020201=total, EVRK2M3140605=TOTAL (sum across all NACE incl. T,U missing),
    # Islyginimas_indeksai=bendras (NSA — TE reports unadjusted value 30528 for 2025Q4).
    {"slug": "job-vacancies", "flow": "S3R275_M3040102_1",
     "filter": {"darbuotojuSKM2020201": "total", "EVRK2M3140605": "TOTAL",
                "Islyginimas_indeksai": "bendras"},
     "freq": "Q", "unit": "Number of vacancies", "adjustment": "NSA", "conversion": 1.0,
     "note": "LSD S3R275 total job vacancies all NACE TOTAL, NSA, quarterly"},
    # Long-term unemployment rate (12+ months), LFS, total persons.
    # S3R196_M3030102: "Long-term unemployment rate". lytis=0 (Both sexes), vietove=0 (Total).
    {"slug": "long-term-unemployment-rate", "flow": "S3R196_M3030102",
     "filter": {"lytis": "0", "vietove": "0"},
     "freq": "Q", "unit": "%", "adjustment": "NSA", "conversion": 1.0,
     "note": "LSD S3R196 LFS long-term unemployment rate (>=12mo) total, quarterly"},
    # Labor force participation rate (LFS activity rate), total population 15+.
    # S3R003_M3030101_1: "Activity rate". AmziusM2111=0 -> all ages 15+ (matches TE 62.6).
    # (Codes: 0=15+, 1=15-24, 2=25-54, 3=15-64, 4=55-64, 1g/2g/3g auxiliary aggregates).
    {"slug": "labor-force-participation-rate", "flow": "S3R003_M3030101_1",
     "filter": {"AmziusM2111": "0", "Vietove": "0", "Lytis": "0"},
     "freq": "Q", "unit": "%", "adjustment": "NSA", "conversion": 1.0,
     "note": "LSD S3R003 LFS activity rate 15+ total, quarterly"},
    # Unemployed persons (LFS, thousands), total 15+, quarterly. S3R050_M3030101_2.
    # AmziusM2111=0 (Total), Vietove=0, Lytis=0; MATVNT=tukst (thousand persons).
    {"slug": "unemployed-persons", "flow": "S3R050_M3030101_2",
     "filter": {"AmziusM2111": "0", "Vietove": "0", "Lytis": "0"},
     "freq": "Q", "unit": "Thousand persons", "adjustment": "NSA", "conversion": 1.0,
     "note": "LSD S3R050 LFS unemployed persons 15+ total, thousand, quarterly"},
    # DG-ECFIN BCS consumer confidence balance, monthly. S3R0180_M3230101.
    # Vietove=0 (national total). Balance, percentage points.
    {"slug": "consumer-confidence", "flow": "S3R0180_M3230101",
     "filter": {"Vietove": "0"},
     "freq": "M", "unit": "Net balance, %", "adjustment": "SA", "conversion": 1.0,
     "note": "LSD S3R0180 DG-ECFIN BCS consumer confidence indicator (balance)"},
    # DG-ECFIN BCS industrial confidence indicator, monthly. S8R394_M4020216.
    # Single dim only (MATVNT=procentai). No filter beyond pinning of nothing.
    {"slug": "business-confidence", "flow": "S8R394_M4020216",
     "filter": {},
     "freq": "M", "unit": "Net balance, %", "adjustment": "SA", "conversion": 1.0,
     "note": "LSD S8R394 DG-ECFIN BCS industrial confidence indicator (balance)"},
]


def _build_query(filter_: dict[str, str], limit: int = 5000) -> str:
    """Build the data.gov.lt RQL-style query string.

    Format: ?select(...)&col="val"&sort(laikotarpis)&limit(N)
    Quotes around string values are required (otherwise 500 from server).
    """
    parts = [f'{k}="{v}"' for k, v in filter_.items()]
    parts.append("select(laikotarpis,verte)")
    parts.append("sort(laikotarpis)")
    parts.append(f"limit({limit})")
    return "?" + "&".join(parts)


_SDMX_OBS_RE = re.compile(
    r"<g:ObsKey>(.*?)</g:ObsKey>\s*<g:ObsValue value=\"([^\"]+)\"", re.S
)
_SDMX_DIM_RE = re.compile(r"id=\"([^\"]+)\" value=\"([^\"]+)\"")


def _parse_sdmx_period(p: str, freq: str) -> date | None:
    """LSD SDMX uses YYYYMm (monthly) and YYYYKn (quarterly, K=ketvirtis), YYYY annual."""
    try:
        if freq == "M" and "M" in p:
            yy, mm = p.split("M")
            return date(int(yy), int(mm), 1)
        if freq == "Q":
            if "K" in p:
                yy, q = p.split("K")
                m = {"1": 1, "2": 4, "3": 7, "4": 10}[q]
                return date(int(yy), m, 1)
            if "Q" in p:
                yy, q = p.split("Q")
                m = {"1": 1, "2": 4, "3": 7, "4": 10}[q]
                return date(int(yy), m, 1)
        if freq == "A" and len(p) == 4:
            return date(int(p), 1, 1)
    except Exception:
        return None
    return None


def fetch_sdmx_series(flow: str, filter_: dict[str, str], freq: str) -> list[tuple[date, float]]:
    """Fetch an LSD SDMX 2.1 dataflow and filter observations client-side.

    LSD does not support partial-key filtering in the URL; the full dataset
    is returned and we filter (dim_id, value) tuples in Python.  Each <g:Obs>
    block has flat <g:ObsKey><g:Value id=... value=.../>...</g:ObsKey> and a
    sibling <g:ObsValue value=.../>. We keep observations whose dim values
    match every key in `filter_` (plus a freq-aware LAIKOTARPIS parse).
    """
    url = f"{SDMX_BASE}/{flow}"
    r = requests.get(url, headers=SDMX_HEADERS, timeout=60)
    r.raise_for_status()
    text = r.text
    out: list[tuple[date, float]] = []
    for ok_inner, val_s in _SDMX_OBS_RE.findall(text):
        dims = dict(_SDMX_DIM_RE.findall(ok_inner))
        # apply user filter
        if not all(dims.get(k) == v for k, v in filter_.items()):
            continue
        period = dims.get("LAIKOTARPIS")
        if not period:
            continue
        dt = _parse_sdmx_period(period, freq)
        if dt is None:
            continue
        try:
            out.append((dt, float(val_s)))
        except ValueError:
            continue
    return sorted(out)


def fetch_lsd_series(ns: str, table_id: str, filter_: dict[str, str], limit: int = 5000) -> list[tuple[date, float]]:
    """Fetch one filtered series from data.gov.lt LSD bucket.

    Paginates via increasing limit + page query if there are >limit rows;
    in practice limit=5000 covers all current LSD monthly indices (max ~360).
    """
    url = f"{GET_BASE}/{ns}/{table_id}{_build_query(filter_, limit)}"
    r = requests.get(url, headers=HTTP_HEADERS, timeout=30)
    r.raise_for_status()
    js = r.json()
    out: list[tuple[date, float]] = []
    for d in js.get("_data", []):
        v = d.get("verte")
        per = d.get("laikotarpis")
        if v is None or per is None:
            continue
        try:
            yy, mm, dd = per.split("-")
            dt = date(int(yy), int(mm), int(dd))
            out.append((dt, float(v)))
        except (ValueError, TypeError):
            continue
    return sorted(out)


class LsdLtProvider(BaseProvider):
    name = "lsd_lt"
    display_name = "LSD Lithuania (Statistikos departamentas, via data.gov.lt)"

    def fetch(self) -> list[DataPoint]:
        out: list[DataPoint] = []
        for cfg in LT_SERIES:
            try:
                pairs = fetch_lsd_series(cfg["ns"], cfg["table_id"], cfg["filter"])
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"],
                        country="LT",
                        date=normalize_date(dt, cfg["freq"]),
                        value=round(v * cfg["conversion"], 4),
                        source="lsd_lt",
                        unit=cfg["unit"],
                        series_id=f"LSD/{cfg['ns']}/{cfg['table_id']}",
                        adjustment=cfg["adjustment"],
                    ))
                print(f"  OK {cfg['slug']}/LT ({cfg['ns'][:30]}): {len(pairs)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['slug']}/LT ({cfg['ns']}): {e}")
            time.sleep(0.3)
        # SDMX REST series (osp-rs.stat.gov.lt) — IP, LCI, confidence, LFS, food-inflation
        for cfg in LT_SDMX_SERIES:
            try:
                pairs = fetch_sdmx_series(cfg["flow"], cfg["filter"], cfg["freq"])
                sid_filter = "/".join(f"{k}={v}" for k, v in cfg["filter"].items()) or "TOTAL"
                series_id = f"LSD/SDMX/{cfg['flow']}/{sid_filter}"
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"],
                        country="LT",
                        date=normalize_date(dt, cfg["freq"]),
                        value=round(v * cfg["conversion"], 4),
                        source="lsd_lt",
                        unit=cfg["unit"],
                        series_id=series_id,
                        adjustment=cfg["adjustment"],
                    ))
                print(f"  OK {cfg['slug']}/LT (SDMX {cfg['flow']}): {len(pairs)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['slug']}/LT (SDMX {cfg['flow']}): {e}")
            time.sleep(0.3)
        return out


def run():
    p = LsdLtProvider()
    print(f"Fetching from {p.display_name}...")
    try:
        pts = p.fetch()
        print(f"\nTotal: {len(pts)} data points")
        rows = datapoints_to_rows(pts)
        total = 0
        for i in range(0, len(rows), 500):
            count = upsert_data_points(rows[i:i+500])
            total += count
        log_pipeline_run("lsd_lt", "success", total)
        print(f"\nDone. {total} rows upserted.")
    except Exception as e:
        log_pipeline_run("lsd_lt", "failed", error_message=str(e))
        print(f"\nFailed: {e}")
        raise


if __name__ == "__main__":
    run()
