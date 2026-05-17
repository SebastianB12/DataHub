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
  NL — datasets.cbs.nl REACHABLE since 2026-05-16 (was previously TCP-timeout).
       Per NL re-audit (docs/_audit_nl_reaudit.yaml), 17 slugs where TE attributes
       Statistics Netherlands could be migrated from Eurostat → CBS OData v1
       (datasets.cbs.nl/odata/v1/CBS or opendata.cbs.nl/ODataApi). Honest label
       policy: current source='eurostat' is correct because we fetch Eurostat.
       Future work: implement NlCbsProvider and switch defaults where CBS gives
       a closer value-match to TE.
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
            # Half-year (SURS POLLETJE: 2025H1 / 2025H2) — map H1->Jan, H2->Jul
            if "H" in p:
                yy, h = p.split("H")
                return date(int(yy), {"1": 1, "2": 7}[h], 1)
        if freq == "Q":
            if "K" in p:  # Danish Kvartal
                yy, q = p.split("K")
                return date(int(yy), {"1":1,"2":4,"3":7,"4":10}[q], 1)
            if "Q" in p:
                # Accept both '2025Q4' and '2025-Q4' (NSO Malta SDMX) and similar.
                yy_part, q = p.split("Q", 1)
                yy = yy_part.rstrip("-")
                return date(int(yy), {"1":1,"2":4,"3":7,"4":10}[q], 1)
        if freq == "A":
            if len(p) == 4:
                return date(int(p), 1, 1)
            # NSO Malta annual time codes carry suffix '-A1' (e.g. '2024-A1')
            if "-A" in p:
                yy = p.split("-A")[0]
                if yy.isdigit() and len(yy) == 4:
                    return date(int(yy), 1, 1)
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
    # Unemployment rate (TE-aligned net unemployment, SA % of labour force).
    # AUS07 YD=NET, SAESONFAK=9 (SA % of labour force) — matches TE 2.7% headline.
    # Verified 2026-05-17: 2026M03 NET SA% = 2.7 (TE: 2.7 exact match).
    # (Previously used AUP01 which is GROSS registered SA% ~3.2 — not what TE displays.)
    {"slug": "unemployment", "table": "AUS07",
     "filters": {"YD": "NET", "SAESONFAK": "9"},
     "freq": "M", "unit": "%", "adjustment": "SA", "conversion": 1.0,
     "note": "DK Statbank AUS07 NET unemployment SA % of labour force (TE headline)"},
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

    # === Migration 048 (2026-05-14): TE-conformity gap-fill, DST national CPI subs ===
    # PRIS01 = Consumer price index by commodity group (national CPI by COICOP),
    # ENHED=100 (level index). All TE values verified 2026-05-14 (period offset by
    # one month vs inventory in some cases, but series matches TE labels).
    {"slug": "cpi-food", "table": "PRIS01", "series_id": "DST/PRIS01/cpi-food",
     "filters": {"VAREGR": "01", "ENHED": "100"},
     "freq": "M", "unit": "Index", "adjustment": "NSA", "conversion": 1.0,
     "note": "DK Statbank PRIS01 CPI Food & non-alcoholic beverages (COICOP 01) index"},
    {"slug": "cpi-clothing", "table": "PRIS01", "series_id": "DST/PRIS01/cpi-clothing",
     "filters": {"VAREGR": "03", "ENHED": "100"},
     "freq": "M", "unit": "Index", "adjustment": "NSA", "conversion": 1.0,
     "note": "DK Statbank PRIS01 CPI Clothing & footwear (COICOP 03) index"},
    {"slug": "cpi-housing-utilities", "table": "PRIS01", "series_id": "DST/PRIS01/cpi-housing",
     "filters": {"VAREGR": "04", "ENHED": "100"},
     "freq": "M", "unit": "Index", "adjustment": "NSA", "conversion": 1.0,
     "note": "DK Statbank PRIS01 CPI Housing, water, electricity, gas & other fuels (COICOP 04) index"},
    {"slug": "cpi-transportation", "table": "PRIS01", "series_id": "DST/PRIS01/cpi-transport",
     "filters": {"VAREGR": "07", "ENHED": "100"},
     "freq": "M", "unit": "Index", "adjustment": "NSA", "conversion": 1.0,
     "note": "DK Statbank PRIS01 CPI Transport (COICOP 07) index"},
    {"slug": "cpi-recreation-and-culture", "table": "PRIS01", "series_id": "DST/PRIS01/cpi-recreation",
     "filters": {"VAREGR": "09", "ENHED": "100"},
     "freq": "M", "unit": "Index", "adjustment": "NSA", "conversion": 1.0,
     "note": "DK Statbank PRIS01 CPI Recreation & culture (COICOP 09) index"},
    {"slug": "cpi-education", "table": "PRIS01", "series_id": "DST/PRIS01/cpi-education",
     "filters": {"VAREGR": "10", "ENHED": "100"},
     "freq": "M", "unit": "Index", "adjustment": "NSA", "conversion": 1.0,
     "note": "DK Statbank PRIS01 CPI Education (COICOP 10) index"},
    # food-inflation: PRIS01 VAREGR=01, ENHED=300 (% YoY change). TE shows 0.7% for 2026-04.
    {"slug": "food-inflation", "table": "PRIS01", "series_id": "DST/PRIS01/food-yoy",
     "filters": {"VAREGR": "01", "ENHED": "300"},
     "freq": "M", "unit": "% YoY", "adjustment": "NSA", "conversion": 1.0,
     "note": "DK Statbank PRIS01 CPI Food YoY % (COICOP 01, ENHED 300)"},
    # consumer-spending: NKN1 P31S14D (household consumption) chained 2020 SA, bn DKK.
    # Verified 2026-05-14: 2025Q4 = 276.7 bn (TE: 274.9, vintage diff ~0.7%).
    {"slug": "consumer-spending", "table": "NKN1", "series_id": "DST/NKN1/consumer-spending",
     "filters": {"TRANSAKT": "P31S14D", "PRISENHED": "LKV_M", "SÆSON": "Y"},
     "freq": "Q", "unit": "Billion DKK (2020 chained)", "adjustment": "SA", "conversion": 1.0,
     "note": "DK Statbank NKN1 P.31 Household consumption expenditure, chained 2020, SA, bn DKK"},
    # changes-in-inventories: NKN1 P52D current prices SA.
    {"slug": "changes-in-inventories", "table": "NKN1", "series_id": "DST/NKN1/inventories",
     "filters": {"TRANSAKT": "P52D", "PRISENHED": "V_M", "SÆSON": "Y"},
     "freq": "Q", "unit": "Billion DKK", "adjustment": "SA", "conversion": 1.0,
     "note": "DK Statbank NKN1 P.52 Changes in inventories, current prices SA, bn DKK"},
    # government-spending: NKN1 P3S13D chained 2020 SA bn DKK. 2025Q4=158.4 (TE 157.6).
    {"slug": "government-spending", "table": "NKN1", "series_id": "DST/NKN1/gov-spending",
     "filters": {"TRANSAKT": "P3S13D", "PRISENHED": "LKV_M", "SÆSON": "Y"},
     "freq": "Q", "unit": "Billion DKK (2020 chained)", "adjustment": "SA", "conversion": 1.0,
     "note": "DK Statbank NKN1 P.3 Government consumption expenditure, chained 2020 SA, bn DKK"},
    # gross-fixed-capital-formation: NKN1 P51GD chained 2020 SA bn DKK.
    {"slug": "gross-fixed-capital-formation", "table": "NKN1", "series_id": "DST/NKN1/gfcf",
     "filters": {"TRANSAKT": "P51GD", "PRISENHED": "LKV_M", "SÆSON": "Y"},
     "freq": "Q", "unit": "Billion DKK (2020 chained)", "adjustment": "SA", "conversion": 1.0,
     "note": "DK Statbank NKN1 P.51g Gross fixed capital formation, chained 2020 SA, bn DKK"},
    # employment-rate: AKU121K (LFS employment rate %), OMRÅDE=000 (All Denmark), SA quarterly.
    # 2025Q4 = 76.2 (TE: 76.6, ~0.4pp vintage diff).
    {"slug": "employment-rate", "table": "AKU121K", "series_id": "DST/AKU121K",
     "filters": {"BESKSTATUS": "BFK", "OMRÅDE": "000"},
     "freq": "Q", "unit": "%", "adjustment": "SA", "conversion": 1.0,
     "note": "DK Statbank AKU121K LFS employment rate (BFK), All DK, SA, quarterly"},

    # === Migration 071 (2026-05-15): TE-conformity gap-fill — DST national sources ===
    # core-cpi: PRIS04 VAREGR=151N (Net price excl. energy and unprocessed food),
    # ENHED=300 (YoY %). Verified 2026-05-15: 2026-04 = 1.6% (TE: 1.6% exact match).
    {"slug": "core-cpi", "table": "PRIS04", "series_id": "DST/PRIS04/core-yoy",
     "filters": {"VAREGR": "151N", "ENHED": "300"},
     "freq": "M", "unit": "% YoY", "adjustment": "NSA", "conversion": 1.0,
     "note": "DK Statbank PRIS04 Net price index excl. energy and unprocessed food YoY % (151N)"},
    # services-inflation: PRIS04 VAREGR=142 (Services total), ENHED=300 YoY %.
    # Verified 2026-05-15: 2026-04 = 2.2% (TE: 2.2% for 2026-03 exact-ish match).
    {"slug": "services-inflation", "table": "PRIS04", "series_id": "DST/PRIS04/services-yoy",
     "filters": {"VAREGR": "142", "ENHED": "300"},
     "freq": "M", "unit": "% YoY", "adjustment": "NSA", "conversion": 1.0,
     "note": "DK Statbank PRIS04 Services (142) YoY % inflation"},
    # budget-deficit: EDP1 LAND=DK, FUNKTION=SALDO, ENHED=PCT (% of GDP, annual).
    # Verified 2026-05-15: 2025 = 2.9 (TE: 2.9 exact match).
    {"slug": "budget-deficit", "table": "EDP1", "series_id": "DST/EDP1/deficit-pct-gdp",
     "filters": {"LAND": "DK", "FUNKTION": "SALDO", "ENHED": "PCT"},
     "freq": "A", "unit": "% of GDP", "adjustment": "NSA", "conversion": 1.0,
     "note": "DK Statbank EDP1 Government EMU surplus/deficit, % of GDP (annual)"},
    # current-account: BBM POST=1 (Current Account), INDUDBOP=N (Net), LAND=W1, ENHED=93 (mil DKK), SA.
    # Verified 2026-05-15: 2026-03 = 38,339.6 mil DKK SA.
    {"slug": "current-account", "table": "BBM", "series_id": "DST/BBM/current-account",
     "filters": {"POST": "1", "INDUDBOP": "N", "LAND": "W1", "ENHED": "93", "SÆSON": "2"},
     "freq": "M", "unit": "Million DKK", "adjustment": "SA", "conversion": 1.0,
     "note": "DK Statbank BBM Current account net, vs World, SA, mio DKK monthly"},
    # disposable-personal-income: INDKP106 ENHED=110 (Amount DKK 1.000), KOEN=MOK, ALDER1=00, INDKINTB=000.
    # Verified 2026-05-15: 2024 = 1,431,342,035 (units of 1000 DKK = 1,431,342 mil DKK).
    {"slug": "disposable-personal-income", "table": "INDKP106", "series_id": "DST/INDKP106",
     "filters": {"ENHED": "110", "KOEN": "MOK", "ALDER1": "00", "INDKINTB": "000"},
     "freq": "A", "unit": "Million DKK", "adjustment": "NSA", "conversion": 0.001,
     "note": "DK Statbank INDKP106 Disposable income, total, all ages, both sexes (DKK 1000 -> mio DKK)"},
    # job-vacancies: LSK03 ENHED=LS (number), SÆSON=20 (actual figures, NSA).
    # Verified 2026-05-15: 2025Q4 = 45,766 (TE: 45,766 exact match).
    {"slug": "job-vacancies", "table": "LSK03", "series_id": "DST/LSK03",
     "filters": {"ENHED": "LS", "SÆSON": "20"},
     "freq": "Q", "unit": "Number", "adjustment": "NSA", "conversion": 1.0,
     "note": "DK Statbank LSK03 Job vacancies (number), NSA, quarterly"},
    # labor-force-participation-rate: AKU121K BESKSTATUS=EFK (Economic activity rate).
    # Verified 2026-05-15: 2025Q4 = 81.5% (TE: 81.9% for 2025Q4, ~0.4pp vintage diff).
    {"slug": "labor-force-participation-rate", "table": "AKU121K", "series_id": "DST/AKU121K/EFK",
     "filters": {"BESKSTATUS": "EFK", "OMRÅDE": "000"},
     "freq": "Q", "unit": "%", "adjustment": "SA", "conversion": 1.0,
     "note": "DK Statbank AKU121K LFS Economic activity rate (EFK) = labour force participation rate"},
    # manufacturing-production: IPOP21 BRANCHEDB25UDVALG=C (Manufacturing), SA.
    # Verified 2026-05-15: 2026-03 = 154.5 (Index 2021=100, SA).
    {"slug": "manufacturing-production", "table": "IPOP21", "series_id": "DST/IPOP21/C",
     "filters": {"SÆSON": "SÆSON", "BRANCHEDB25UDVALG": "C"},
     "freq": "M", "unit": "Index (2021=100)", "adjustment": "SA", "conversion": 1.0,
     "note": "DK Statbank IPOP21 Manufacturing production index (NACE C), SA"},
    # mining-production: IPOP21 BRANCHEDB25UDVALG=B (Mining and quarrying), SA.
    # Verified 2026-05-15: 2026-03 = 164.9.
    {"slug": "mining-production", "table": "IPOP21", "series_id": "DST/IPOP21/B",
     "filters": {"SÆSON": "SÆSON", "BRANCHEDB25UDVALG": "B"},
     "freq": "M", "unit": "Index (2021=100)", "adjustment": "SA", "conversion": 1.0,
     "note": "DK Statbank IPOP21 Mining and quarrying production index (NACE B), SA"},
    # population: FOLK1A KØN=TOT, ALDER=IALT, CIVILSTAND=TOT, OMRÅDE=000 (All Denmark), quarterly thousands.
    # Verified 2026-05-15: 2026Q2 = 6,031,247 persons -> 6.031 million.
    {"slug": "population", "table": "FOLK1A", "series_id": "DST/FOLK1A",
     "filters": {"KØN": "TOT", "ALDER": "IALT", "CIVILSTAND": "TOT", "OMRÅDE": "000"},
     "freq": "Q", "unit": "Million", "adjustment": "NSA", "conversion": 1e-6,
     "note": "DK Statbank FOLK1A Population at first day of quarter, total (persons -> million)"},
    # productivity: NP23 BRANCHE=PIALT (Total), PRISENHED=LPR_I (Index 2020=100, annual).
    # Verified 2026-05-15: 2025 = 105.09 (TE shows 119.31 for 2025Q4 — different base/freq).
    # We publish the annual DST series for source-conformity; consumers can compare to
    # Eurostat quarterly. NOTE: TE value mismatch logged — different methodology.
    {"slug": "productivity", "table": "NP23", "series_id": "DST/NP23/PIALT",
     "filters": {"BRANCHE": "PIALT", "PRISENHED": "LPR_I"},
     "freq": "A", "unit": "Index (2020=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "DK Statbank NP23 Labour productivity index, total economy (PIALT), 2020=100, annual"},

    # === Migration 089 (2026-05-17): DK re-audit — DST government-debt + debt-total ===
    # government-debt (TE: % of GDP, "Government Debt to GDP"): EDP1 GAELD ENHED=PCT, LAND=DK.
    # Verified 2026-05-17: 2025 = 27.9% of GDP (TE: 27.90 exact match).
    # TE labels source as "Statistics Denmark"; we fetch from DST -> source='dst'.
    {"slug": "government-debt", "table": "EDP1", "series_id": "DST/EDP1/debt-pct-gdp",
     "filters": {"LAND": "DK", "FUNKTION": "GAELD", "ENHED": "PCT"},
     "freq": "A", "unit": "% of GDP", "adjustment": "NSA", "conversion": 1.0,
     "note": "DK Statbank EDP1 Government EMU-debt, % of GDP (annual, general govt)"},
    # government-debt-total (TE: "Government Debt" central govt, DKK Billion).
    # DST DNSOSB INSTRUMENT=2000 (Gross debt - Total), monthly central-government debt.
    # Verified 2026-05-17: 2026M03 = 592.729 DKK bn (TE: 592.73 exact match).
    # TE labels source "Danmarks Nationalbank" (debt manager), but the table is published
    # via DST Statbank — honest source label is 'dst'.
    {"slug": "government-debt-total", "table": "DNSOSB", "series_id": "DST/DNSOSB/debt-total",
     "filters": {"INSTRUMENT": "2000"},
     "freq": "M", "unit": "Billion DKK", "adjustment": "NSA", "conversion": 1.0,
     "note": "DK Statbank DNSOSB Central government gross debt total (DKK bn, monthly)"},
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

    # === Migration 050 (2026-05-14): TE-conformity gap-fill ===
    # CPI by COICOP (15b5), 2025=100; Hyödyke=top-level COICOP code, Tiedot=ip_khi (index).
    {"slug": "cpi-food", "path": "StatFin/khi/statfin_khi_pxt_15b5.px",
     "query": {"Hyödyke": "01", "Tiedot": "ip_khi"},
     "series_id": "STATFI/khi/15b5/cpi-food",
     "freq": "M", "unit": "Index (2025=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "FI Tilastokeskus 15b5 CPI Food & non-alcoholic beverages (COICOP 01)"},
    {"slug": "cpi-clothing", "path": "StatFin/khi/statfin_khi_pxt_15b5.px",
     "query": {"Hyödyke": "03", "Tiedot": "ip_khi"},
     "series_id": "STATFI/khi/15b5/cpi-clothing",
     "freq": "M", "unit": "Index (2025=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "FI Tilastokeskus 15b5 CPI Clothing & footwear (COICOP 03)"},
    {"slug": "cpi-housing-utilities", "path": "StatFin/khi/statfin_khi_pxt_15b5.px",
     "query": {"Hyödyke": "04", "Tiedot": "ip_khi"},
     "series_id": "STATFI/khi/15b5/cpi-housing",
     "freq": "M", "unit": "Index (2025=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "FI Tilastokeskus 15b5 CPI Housing/utilities (COICOP 04)"},
    {"slug": "cpi-transportation", "path": "StatFin/khi/statfin_khi_pxt_15b5.px",
     "query": {"Hyödyke": "07", "Tiedot": "ip_khi"},
     "series_id": "STATFI/khi/15b5/cpi-transport",
     "freq": "M", "unit": "Index (2025=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "FI Tilastokeskus 15b5 CPI Transport (COICOP 07)"},
    {"slug": "cpi-recreation-and-culture", "path": "StatFin/khi/statfin_khi_pxt_15b5.px",
     "query": {"Hyödyke": "09", "Tiedot": "ip_khi"},
     "series_id": "STATFI/khi/15b5/cpi-recreation",
     "freq": "M", "unit": "Index (2025=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "FI Tilastokeskus 15b5 CPI Recreation & culture (COICOP 09)"},
    {"slug": "cpi-education", "path": "StatFin/khi/statfin_khi_pxt_15b5.px",
     "query": {"Hyödyke": "10", "Tiedot": "ip_khi"},
     "series_id": "STATFI/khi/15b5/cpi-education",
     "freq": "M", "unit": "Index (2025=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "FI Tilastokeskus 15b5 CPI Education (COICOP 10)"},
    # food-inflation: 15b5 COICOP 01, vm_khi = Annual change %.
    {"slug": "food-inflation", "path": "StatFin/khi/statfin_khi_pxt_15b5.px",
     "query": {"Hyödyke": "01", "Tiedot": "vm_khi"},
     "series_id": "STATFI/khi/15b5/food-yoy",
     "freq": "M", "unit": "% YoY", "adjustment": "NSA", "conversion": 1.0,
     "note": "FI Tilastokeskus 15b5 CPI Food YoY % (COICOP 01, vm_khi)"},
    # Employment-rate: tyti 135y, Tyollisyysaste %, 15-64 age, both sexes.
    # Verified 2026-05-14: 2026M03 = 69.2 (TE: 69.2 exact match for 2026-02).
    {"slug": "employment-rate", "path": "StatFin/tyti/statfin_tyti_pxt_135y.px",
     "query": {"Sukupuoli": "SSS", "Ikäluokka": "15-64", "Tiedot": "Tyollisyysaste"},
     "series_id": "STATFI/tyti/135y/empl-rate",
     "freq": "M", "unit": "%", "adjustment": "NSA", "conversion": 1.0,
     "note": "FI Tilastokeskus 135y LFS Employment Rate 15-64 both sexes, monthly NSA"},
    # National-accounts expenditure components: ntp 132h, Tiedot=kausitvv2015 (SA chained ref 2015 EUR mn).
    # consumer-spending = P3KS14_S15 (Private consumption S14+S15). 2025Q4 = 29614 (exact TE).
    {"slug": "consumer-spending", "path": "StatFin/ntp/statfin_ntp_pxt_132h.px",
     "query": {"Taloustoimi": "P3KS14_S15", "Tiedot": "kausitvv2015"},
     "series_id": "STATFI/ntp/132h/consumer",
     "freq": "Q", "unit": "EUR million (chained 2015)", "adjustment": "SA", "conversion": 1.0,
     "note": "FI Tilastokeskus 132h Private consumption (S14+S15), chained 2015 SA, EUR mn"},
    # changes-in-inventories = P52K (Change in inventories, expenditure).
    # NOTE: chained 2015 (kausitvv2015) is published as zero for this transaction;
    # use kausitcp (current prices SA) which carries actual flows.
    {"slug": "changes-in-inventories", "path": "StatFin/ntp/statfin_ntp_pxt_132h.px",
     "query": {"Taloustoimi": "P52K", "Tiedot": "kausitcp"},
     "series_id": "STATFI/ntp/132h/inventories",
     "freq": "Q", "unit": "EUR million (current prices)", "adjustment": "SA", "conversion": 1.0,
     "note": "FI Tilastokeskus 132h Change in inventories (P52K), current prices SA, EUR mn"},
    # government-spending: TE displays % of GDP (general government total expenditure / GDP).
    # Switched 2026-05-17 from ntp 132h P3KS13 EUR level to vtp 129d OTES bkt_suhde % GDP.
    # Verified: 2025 = 57.5% (exact TE match).
    {"slug": "government-spending", "path": "StatFin/vtp/statfin_vtp_pxt_129d.px",
     "query": {"Sektori": "S13", "Taloustoimi": "OTES", "Tiedot": "bkt_suhde"},
     "series_id": "STATFI/vtp/129d/gov-spending-pct-gdp",
     "freq": "A", "unit": "% of GDP", "adjustment": "NSA", "conversion": 1.0,
     "note": "FI Tilastokeskus 129d S13 OTES Total expenditure consolidated, % of GDP"},
    # gross-fixed-capital-formation = P51K.
    {"slug": "gross-fixed-capital-formation", "path": "StatFin/ntp/statfin_ntp_pxt_132h.px",
     "query": {"Taloustoimi": "P51K", "Tiedot": "kausitvv2015"},
     "series_id": "STATFI/ntp/132h/gfcf",
     "freq": "Q", "unit": "EUR million (chained 2015)", "adjustment": "SA", "conversion": 1.0,
     "note": "FI Tilastokeskus 132h Gross fixed capital formation (P51K), chained 2015 SA, EUR mn"},
    # === Migration 061 (2026-05-15): TE-conformity, consumer-confidence ===
    # Consumer confidence indicator (CCI) — Tilastokeskus kbar 11cc, Tiedot=CCI_A1
    # ("A1 Consumer confidence indicator, CCI = (B1+B2+B4+E1)/4").
    # Verified 2026-05-15: 2026M04 = -12.5 (exact TE match for consumer-confidence
    # https://tradingeconomics.com/finland/consumer-confidence).
    # Note: TE attributes this to Tilastokeskus (Statistics Finland) directly — same
    # publisher, same series, fully primary-source-conform.
    {"slug": "consumer-confidence", "path": "StatFin/kbar/statfin_kbar_pxt_11cc.px",
     "query": {"Tiedot": "CCI_A1"},
     "series_id": "STATFI/kbar/11cc/CCI_A1",
     "freq": "M", "unit": "Balance (%)", "adjustment": "NSA", "conversion": 1.0,
     "note": "FI Tilastokeskus 11cc Consumer Confidence Indicator A1 (composite balance %)"},

    # === Migration 073 (2026-05-15): TE-conformity gap-fill — stat_fi national sources ===
    # budget-deficit: vtp 129d Sektori=S13 (General gov), Taloustoimi=B9 (Net lending), Tiedot=bkt_suhde (% GDP).
    # Verified 2026-05-15: 2025 = -3.4% (TE: 3.4% absolute value, exact match).
    # Conversion -1.0: TE displays deficit as positive percentage (absolute value).
    {"slug": "budget-deficit", "path": "StatFin/vtp/statfin_vtp_pxt_129d.px",
     "query": {"Sektori": "S13", "Taloustoimi": "B9", "Tiedot": "bkt_suhde"},
     "series_id": "STATFI/vtp/129d/budget-deficit",
     "freq": "A", "unit": "% of GDP", "adjustment": "NSA", "conversion": -1.0,
     "note": "FI Tilastokeskus 129d General government B.9 net lending/borrowing, % of GDP (sign-flipped to deficit)"},
    # current-account: mata 12gf Maksutase-erä=CA, Tiedot=B (net), monthly EUR mn.
    # Verified 2026-05-15: 2026-03 = 250 EUR mn (net CA balance).
    {"slug": "current-account", "path": "StatFin/mata/statfin_mata_pxt_12gf.px",
     "query": {"Maksutase-erä": "CA", "Tiedot": "B"},
     "series_id": "STATFI/mata/12gf/current-account",
     "freq": "M", "unit": "EUR million", "adjustment": "NSA", "conversion": 1.0,
     "note": "FI Tilastokeskus 12gf Current account net (Maksutase-erä CA, Tiedot B), monthly EUR mn"},
    # labor-force-participation-rate: tyti 135y Sukupuoli=SSS, Ikäluokka=15-74, Tiedot=Tyovoimaosuus.
    # Verified 2026-05-15: 2026-03 = 68.0% (TE: 68.0% for 2026-02 exact match).
    {"slug": "labor-force-participation-rate", "path": "StatFin/tyti/statfin_tyti_pxt_135y.px",
     "query": {"Sukupuoli": "SSS", "Ikäluokka": "15-74", "Tiedot": "Tyovoimaosuus"},
     "series_id": "STATFI/tyti/135y/lfp-rate",
     "freq": "M", "unit": "%", "adjustment": "NSA", "conversion": 1.0,
     "note": "FI Tilastokeskus 135y LFS labour-force participation rate 15-74 (Tyovoimaosuus)"},
    # manufacturing-production: ttvi 14mh Toimiala=C (Manufacturing), Tiedot=Alkuperainen (NSA original).
    # Verified 2026-05-15: 2026-03 = 114.0 (Index 2021=100, NSA).
    {"slug": "manufacturing-production", "path": "StatFin/ttvi/statfin_ttvi_pxt_14mh.px",
     "query": {"Toimiala (TOL 2008)": "C", "Tiedot": "Alkuperainen"},
     "series_id": "STATFI/ttvi/14mh/manufacturing",
     "freq": "M", "unit": "Index (2021=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "FI Tilastokeskus 14mh Industrial Output, Manufacturing (TOL 2008 C), NSA"},
    # mining-production: ttvi 14mh Toimiala=B (Mining and quarrying).
    # Verified 2026-05-15: 2026-03 = 102.6.
    {"slug": "mining-production", "path": "StatFin/ttvi/statfin_ttvi_pxt_14mh.px",
     "query": {"Toimiala (TOL 2008)": "B", "Tiedot": "Alkuperainen"},
     "series_id": "STATFI/ttvi/14mh/mining",
     "freq": "M", "unit": "Index (2021=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "FI Tilastokeskus 14mh Industrial Output, Mining and quarrying (TOL 2008 B), NSA"},
    # population: vaerak 11ra Alue=SSS (Whole country), Tiedot=vaesto (Pop 31 Dec), annual.
    # Verified 2026-05-15: 2025 = 5,652,881 persons -> 5.653 million.
    {"slug": "population", "path": "StatFin/vaerak/statfin_vaerak_pxt_11ra.px",
     "query": {"Alue": "SSS", "Tiedot": "vaesto"},
     "series_id": "STATFI/vaerak/11ra/population",
     "freq": "A", "unit": "Million", "adjustment": "NSA", "conversion": 1e-6,
     "note": "FI Tilastokeskus 11ra Population 31 Dec, whole country (persons -> million)"},
    # unemployed-persons: tyti 135y Tiedot=Tyottomat (Unemployed, 1000 persons).
    # Verified 2026-05-15: 2026-03 = 315 thousand (TE: 315 exact match).
    {"slug": "unemployed-persons", "path": "StatFin/tyti/statfin_tyti_pxt_135y.px",
     "query": {"Sukupuoli": "SSS", "Ikäluokka": "15-74", "Tiedot": "Tyottomat"},
     "series_id": "STATFI/tyti/135y/unemp-persons",
     "freq": "M", "unit": "Thousand", "adjustment": "NSA", "conversion": 1.0,
     "note": "FI Tilastokeskus 135y LFS Unemployed persons 15-74 (Tyottomat), thousands NSA"},
    # youth-unemployment-rate: tyti 135y Tiedot=Tyottomyysaste, Ikäluokka=15-24.
    # Verified 2026-05-15: 2026-03 = 24.3% (TE: 24.3% for 2026-02 exact match).
    {"slug": "youth-unemployment-rate", "path": "StatFin/tyti/statfin_tyti_pxt_135y.px",
     "query": {"Sukupuoli": "SSS", "Ikäluokka": "15-24", "Tiedot": "Tyottomyysaste"},
     "series_id": "STATFI/tyti/135y/youth-unemp",
     "freq": "M", "unit": "%", "adjustment": "NSA", "conversion": 1.0,
     "note": "FI Tilastokeskus 135y LFS Youth unemployment rate 15-24, NSA"},
    # === FI re-audit 2026-05-17 ===
    # government-debt: jali 122g Sektori=S13, Tiedot=Ratio_D (EDP debt % GDP), annual.
    # Verified 2026-05-17: 2025 = 88.5% (matches TE 88.50% exact). Source-conformity:
    # TE attributes to Statistics Finland; this aligns truth.yaml stat_fi target.
    {"slug": "government-debt", "path": "StatFin/jali/statfin_jali_pxt_122g.px",
     "query": {"Sektori": "S13", "Tiedot": "Ratio_D"},
     "series_id": "STATFI/jali/122g/edp-debt-ratio",
     "freq": "A", "unit": "% of GDP", "adjustment": "NSA", "conversion": 1.0,
     "note": "FI Tilastokeskus 122g EDP general government debt ratio (Ratio_D, % of GDP)"},
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
    # Arbetskraftstillh=ALÖSP (rate %), TypData=O_DATA (NSA original; matches TE headline).
    # Kon=1+2 (both sexes), Alder=tot15-74, ContentsCode=000007L9.
    # Verified 2026-05-17: 2026M03 = 9.7 (matches TE 9.7 exactly).
    {"slug": "unemployment", "path": "AM/AM0401/AM0401A/AKURLBefM",
     "query": {"Arbetskraftstillh": "ALÖSP", "TypData": "O_DATA",
               "Kon": "1+2", "Alder": "tot15-74", "ContentsCode": "000007L9"},
     "freq": "M", "unit": "%", "adjustment": "NSA", "conversion": 1.0,
     "note": "SE SCB AM0401A LFS unemployment rate 15-74 NSA (ALÖSP/O_DATA)"},
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

    # === Migration 049 (2026-05-14): TE-conformity gap-fill, SE national CPI subs ===
    # KPI2020COICOP2M = CPI by COICOP 2-digit. ContentsCode=0000080C (index, 2020=100).
    {"slug": "cpi-food", "path": "PR/PR0101/PR0101A/KPI2020COICOP2M",
     "query": {"VaruTjanstegrupp": "01", "ContentsCode": "0000080C"},
     "series_id": "SCB/PR0101A/KPI2020COICOP2M/cpi-food",
     "freq": "M", "unit": "Index (2020=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "SE SCB KPI by COICOP, Food & non-alcoholic beverages (01)"},
    {"slug": "cpi-clothing", "path": "PR/PR0101/PR0101A/KPI2020COICOP2M",
     "query": {"VaruTjanstegrupp": "03", "ContentsCode": "0000080C"},
     "series_id": "SCB/PR0101A/KPI2020COICOP2M/cpi-clothing",
     "freq": "M", "unit": "Index (2020=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "SE SCB KPI by COICOP, Clothing & footwear (03)"},
    {"slug": "cpi-housing-utilities", "path": "PR/PR0101/PR0101A/KPI2020COICOP2M",
     "query": {"VaruTjanstegrupp": "04", "ContentsCode": "0000080C"},
     "series_id": "SCB/PR0101A/KPI2020COICOP2M/cpi-housing",
     "freq": "M", "unit": "Index (2020=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "SE SCB KPI by COICOP, Housing/utilities (04)"},
    {"slug": "cpi-transportation", "path": "PR/PR0101/PR0101A/KPI2020COICOP2M",
     "query": {"VaruTjanstegrupp": "07", "ContentsCode": "0000080C"},
     "series_id": "SCB/PR0101A/KPI2020COICOP2M/cpi-transport",
     "freq": "M", "unit": "Index (2020=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "SE SCB KPI by COICOP, Transport (07)"},
    {"slug": "cpi-recreation-and-culture", "path": "PR/PR0101/PR0101A/KPI2020COICOP2M",
     "query": {"VaruTjanstegrupp": "09", "ContentsCode": "0000080C"},
     "series_id": "SCB/PR0101A/KPI2020COICOP2M/cpi-recreation",
     "freq": "M", "unit": "Index (2020=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "SE SCB KPI by COICOP, Recreation & culture (09)"},
    {"slug": "cpi-education", "path": "PR/PR0101/PR0101A/KPI2020COICOP2M",
     "query": {"VaruTjanstegrupp": "10", "ContentsCode": "0000080C"},
     "series_id": "SCB/PR0101A/KPI2020COICOP2M/cpi-education",
     "freq": "M", "unit": "Index (2020=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "SE SCB KPI by COICOP, Education services (10)"},
    # food-inflation: KPI by COICOP, ContentsCode=00000809 (Annual change %).
    {"slug": "food-inflation", "path": "PR/PR0101/PR0101A/KPI2020COICOP2M",
     "query": {"VaruTjanstegrupp": "01", "ContentsCode": "00000809"},
     "series_id": "SCB/PR0101A/KPI2020COICOP2M/food-yoy",
     "freq": "M", "unit": "% YoY", "adjustment": "NSA", "conversion": 1.0,
     "note": "SE SCB KPI by COICOP, Food YoY % (01, 00000809)"},
    # employment-rate: AKURLBefM SYSP O_DATA NSA, both sexes 15-74. 2026M03=68.5 (TE match).
    {"slug": "employment-rate", "path": "AM/AM0401/AM0401A/AKURLBefM",
     "query": {"Arbetskraftstillh": "SYSP", "TypData": "O_DATA",
               "Kon": "1+2", "Alder": "tot15-74", "ContentsCode": "000007L9"},
     "series_id": "SCB/AM0401A/empl-rate",
     "freq": "M", "unit": "%", "adjustment": "NSA", "conversion": 1.0,
     "note": "SE SCB AM0401A LFS Employment Rate 15-74 NSA % (SYSP/O_DATA)"},
    # National-accounts expenditure: NR0103B, ContentsCode=NR0103CE (constant prices ref 2024 SA, SEK mn).
    # consumer-spending = KHUS (household consumption incl NPISH). 2025Q4=744,967 (exact TE match).
    {"slug": "consumer-spending", "path": "NR/NR0103/NR0103B/NR0103ENS2010T10SKv",
     "query": {"Anvandningstyp": "KHUS", "ContentsCode": "NR0103CE"},
     "series_id": "SCB/NR0103B/consumer-spending",
     "freq": "Q", "unit": "SEK million (ref 2024)", "adjustment": "SA", "conversion": 1.0,
     "note": "SE SCB NR0103B Household consumption (KHUS), constant ref 2024 SA, SEK mn"},
    # changes-in-inventories = LA.
    {"slug": "changes-in-inventories", "path": "NR/NR0103/NR0103B/NR0103ENS2010T10SKv",
     "query": {"Anvandningstyp": "LA", "ContentsCode": "NR0103CE"},
     "series_id": "SCB/NR0103B/inventories",
     "freq": "Q", "unit": "SEK million (ref 2024)", "adjustment": "SA", "conversion": 1.0,
     "note": "SE SCB NR0103B Changes in inventories (LA), constant ref 2024 SA, SEK mn"},
    # government-spending = KOFF (general government final consumption). 2025Q4=437,456 (exact TE).
    {"slug": "government-spending", "path": "NR/NR0103/NR0103B/NR0103ENS2010T10SKv",
     "query": {"Anvandningstyp": "KOFF", "ContentsCode": "NR0103CE"},
     "series_id": "SCB/NR0103B/gov-spending",
     "freq": "Q", "unit": "SEK million (ref 2024)", "adjustment": "SA", "conversion": 1.0,
     "note": "SE SCB NR0103B Government final consumption (KOFF), constant ref 2024 SA, SEK mn"},
    # gross-fixed-capital-formation = FBINV.
    {"slug": "gross-fixed-capital-formation", "path": "NR/NR0103/NR0103B/NR0103ENS2010T10SKv",
     "query": {"Anvandningstyp": "FBINV", "ContentsCode": "NR0103CE"},
     "series_id": "SCB/NR0103B/gfcf",
     "freq": "Q", "unit": "SEK million (ref 2024)", "adjustment": "SA", "conversion": 1.0,
     "note": "SE SCB NR0103B Gross fixed capital formation (FBINV), constant ref 2024 SA, SEK mn"},
    # labour-costs: AKITM07 = AKI for salaried employees, B-S exkl.O total, AM0301AC preliminary
    # at 2008M01=100. 2026M02 = 169.2 (TE: 169.2 exact match, period offset by one month).
    {"slug": "labour-costs", "path": "AM/AM0301/AM0301A/AKITM07",
     "query": {"SNI2007": "B-S exkl.O", "ContentsCode": "AM0301AC"},
     "series_id": "SCB/AM0301A/AKITM07/labour-costs",
     "freq": "M", "unit": "Index (2008M01=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "SE SCB AKITM07 LCI for salaried employees, all industry B-S exkl.O, preliminary"},

    # === Migration 074 (2026-05-15): TE-conformity gap-fill — SCB national sources ===
    # capacity-utilization: NV0701A IndKaputnBCKv, ContentsCode=000001H6 (NSA actual %).
    # Verified 2026-05-15: 2025Q4 = 87.7% (SCB actual; TE 20.0 is EC survey balance — different metric).
    {"slug": "capacity-utilization", "path": "NV/NV0701/NV0701A/IndKaputnBCKv",
     "query": {"ContentsCode": "000001H6"},
     "series_id": "SCB/NV0701A/capacity-util",
     "freq": "Q", "unit": "%", "adjustment": "NSA", "conversion": 1.0,
     "note": "SE SCB NV0701A Industrial capacity utilisation, NACE B+C, not calendar adjusted %"},
    # core-cpi: PR0101J KPIFXE2020, ContentsCode=000007ZV (annual changes, CPIF-XE).
    # Verified 2026-05-15: 2026-04 = 0.0% YoY (CPIF-XE).
    {"slug": "core-cpi", "path": "PR/PR0101/PR0101J/KPIFXE2020",
     "query": {"ContentsCode": "000007ZV"},
     "series_id": "SCB/PR0101J/core-cpi-yoy",
     "freq": "M", "unit": "% YoY", "adjustment": "NSA", "conversion": 1.0,
     "note": "SE SCB PR0101J CPIF exclusive energy (core-CPI) annual change %"},
    # current-account: FM0001BetBalKv, Kontopost=A1 (Current account net), SEK billions.
    {"slug": "current-account", "path": "FM/FM0001/FM0001A/FM0001BetBalKv",
     "query": {"Kontopost": "A1", "ContentsCode": "FM0001AQ"},
     "series_id": "SCB/FM0001A/current-account",
     "freq": "Q", "unit": "SEK billion", "adjustment": "NSA", "conversion": 1.0,
     "note": "SE SCB FM0001BetBalKv BoP current account net, SEK billions, quarterly"},
    # disposable-personal-income: NR0103C HusDispInkENS2010Kv, S14 B6n, NR0103DV.
    # Verified 2026-05-15: 2025Q4 = 773,762 SEK mn (TE: 773,762 exact match).
    {"slug": "disposable-personal-income", "path": "NR/NR0103/NR0103C/HusDispInkENS2010Kv",
     "query": {"Transaktionspost": "B6n", "ContentsCode": "NR0103DV"},
     "series_id": "SCB/NR0103C/disposable-S14",
     "freq": "Q", "unit": "SEK million", "adjustment": "NSA", "conversion": 1.0,
     "note": "SE SCB NR0103C Household (S14) disposable income net, SEK mn, quarterly"},
    # house-price-index: BO0501A FastpiPSRegKv, Region=00 (Sweden).
    # Verified 2026-05-15: 2026Q1 = 953.0 (TE: 953 exact match).
    {"slug": "house-price-index", "path": "BO/BO0501/BO0501A/FastpiPSRegKv",
     "query": {"Region": "00", "ContentsCode": "BO0501K2"},
     "series_id": "SCB/BO0501A/house-price",
     "freq": "Q", "unit": "Index (1981=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "SE SCB BO0501A Real estate price index, one- and two-dwelling buildings, Sweden"},
    # labor-force-participation-rate: AKURLBefM Arbetskraftstillh=IAKRP.
    # Verified 2026-05-15: 2026-03 = 75.9% (TE: 75.9 exact match for 2026-02).
    {"slug": "labor-force-participation-rate", "path": "AM/AM0401/AM0401A/AKURLBefM",
     "query": {"Arbetskraftstillh": "IAKRP", "TypData": "O_DATA",
               "Kon": "1+2", "Alder": "tot15-74", "ContentsCode": "000007L9"},
     "series_id": "SCB/AM0401A/lfp-rate",
     "freq": "M", "unit": "%", "adjustment": "NSA", "conversion": 1.0,
     "note": "SE SCB AM0401A LFS labour-force participation rate 15-74 NSA (IAKRP/O_DATA)"},
    # manufacturing-production: IPI2010KedjM, SNI2007=C, calendar adjusted.
    # Verified 2026-05-15: 2026-03 = 122.5 (Index 2021=100).
    {"slug": "manufacturing-production", "path": "NV/NV0402/NV0402A/IPI2010KedjM",
     "query": {"SNI2007": "C", "ContentsCode": "NV0402AJ"},
     "series_id": "SCB/NV0402A/manufacturing",
     "freq": "M", "unit": "Index (2021=100)", "adjustment": "WDA", "conversion": 1.0,
     "note": "SE SCB NV0402A IPI Manufacturing index level (SNI C), WDA"},
    # mining-production: IPI2010KedjM, SNI2007=B.
    # Verified 2026-05-15: 2026-03 = 96.3.
    {"slug": "mining-production", "path": "NV/NV0402/NV0402A/IPI2010KedjM",
     "query": {"SNI2007": "B", "ContentsCode": "NV0402AJ"},
     "series_id": "SCB/NV0402A/mining",
     "freq": "M", "unit": "Index (2021=100)", "adjustment": "WDA", "conversion": 1.0,
     "note": "SE SCB NV0402A IPI Mining and quarrying index level (SNI B), WDA"},
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
    # NOTE 2026-05-15: inflation-cpi REMOVED from INE-PT pindica.
    # The legacy varcd 0008273 was mis-mapped to "Resident population". A full
    # sweep of pindica.jsp varcds 0007000-0014000 only located the old IPC
    # Base-2012 family (0007320 / 0007324 / 0008351 / 0008352), all frozen at
    # Dezembro de 2024. INE migrated current IPC publication (Base 2017+) off
    # pindica into a separate dissemination channel that is not yet exposed
    # via JSON. Until that endpoint is identified, PT inflation-cpi is sourced
    # from Eurostat HICP (see migration 054_pt_cpifix.py).

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

    # Labour-force participation rate (Taxa de atividade 16-74), monthly, %.
    # dim_3='T' is both sexes (HM). TE quotes this exact series.
    # Verified 2026-05-15: 2026-03 = 69.7 % (TE: 69.7 %).
    {"slug": "labor-force-participation-rate", "varcd": "0010060", "freq": "M",
     "unit": "%", "adjustment": "NSA", "conversion": 1.0,
     "row_filter": {"geocod": "PT", "dim_3": "T"},
     "note": "INE PT 0010060 Taxa de atividade da populacao residente 16-74 (both sexes), monthly"},
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
    # ---- TE-conformity gap-fill (added 2026-05-15) -------------------------------
    # CPI sub-aggregates — CPM01 by COICOP, STATISTIC=CPM01C08 = Index Base Dec2023=100.
    # COICOP codes: 01=Food, 03=Clothing, 04=Housing/utilities, 07=Transport,
    # 09=Recreation, 10=Education.
    {"slug": "cpi-food", "table": "CPM01",
     "filters": {"STATISTIC": "CPM01C08", "C01779V03424": "01"},
     "series_id": "CSO/CPM01/01",
     "freq": "M", "unit": "Index (Dec 2023=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "CSO Ireland CPM01 CPI Food & non-alc bev (COICOP 01)"},
    {"slug": "cpi-clothing", "table": "CPM01",
     "filters": {"STATISTIC": "CPM01C08", "C01779V03424": "03"},
     "series_id": "CSO/CPM01/03",
     "freq": "M", "unit": "Index (Dec 2023=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "CSO Ireland CPM01 CPI Clothing & footwear (COICOP 03)"},
    {"slug": "cpi-housing-utilities", "table": "CPM01",
     "filters": {"STATISTIC": "CPM01C08", "C01779V03424": "04"},
     "series_id": "CSO/CPM01/04",
     "freq": "M", "unit": "Index (Dec 2023=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "CSO Ireland CPM01 CPI Housing/water/energy (COICOP 04)"},
    {"slug": "cpi-transportation", "table": "CPM01",
     "filters": {"STATISTIC": "CPM01C08", "C01779V03424": "07"},
     "series_id": "CSO/CPM01/07",
     "freq": "M", "unit": "Index (Dec 2023=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "CSO Ireland CPM01 CPI Transport (COICOP 07)"},
    {"slug": "cpi-recreation-and-culture", "table": "CPM01",
     "filters": {"STATISTIC": "CPM01C08", "C01779V03424": "09"},
     "series_id": "CSO/CPM01/09",
     "freq": "M", "unit": "Index (Dec 2023=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "CSO Ireland CPM01 CPI Recreation & culture (COICOP 09)"},
    {"slug": "cpi-education", "table": "CPM01",
     "filters": {"STATISTIC": "CPM01C08", "C01779V03424": "10"},
     "series_id": "CSO/CPM01/10",
     "freq": "M", "unit": "Index (Dec 2023=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "CSO Ireland CPM01 CPI Education (COICOP 10)"},
    # Core CPI — STATISTIC CPM01C08 on all items (-). CSO does not publish a true
    # core (ex-food/energy) series; we use overall CPI index from CSO as source
    # attribution proxy. TE attributes "core inflation" to CSO too.
    {"slug": "core-cpi", "table": "CPM01",
     "filters": {"STATISTIC": "CPM01C08", "C01779V03424": "-"},
     "series_id": "CSO/CPM01/core",
     "freq": "M", "unit": "Index (Dec 2023=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "CSO Ireland CPM01 CPI all-items (core proxy; CSO does not publish core)"},
    # Food inflation YoY — CPM01C07 (12-month % change) for COICOP=01.
    {"slug": "food-inflation", "table": "CPM01",
     "filters": {"STATISTIC": "CPM01C07", "C01779V03424": "01"},
     "series_id": "CSO/CPM01/food-yoy",
     "freq": "M", "unit": "% YoY", "adjustment": "NSA", "conversion": 1.0,
     "note": "CSO Ireland CPM01 Food & non-alc bev YoY%"},
    # Labour Force Survey — QLF18, both sexes ('-').
    # Employment rate 15-64 (C04, age=315).
    {"slug": "employment-rate", "table": "QLF18",
     "filters": {"STATISTIC": "QLF18C04", "C02076V02508": "315", "C02199V02655": "-"},
     "series_id": "CSO/QLF18/empr-15-64",
     "freq": "Q", "unit": "%", "adjustment": "NSA", "conversion": 1.0,
     "note": "CSO Ireland QLF18 ILO Employment Rate 15-64 both sexes"},
    # Labor force participation rate 15+ (C02, age=320). 15-64 isn't published here.
    {"slug": "labor-force-participation-rate", "table": "QLF18",
     "filters": {"STATISTIC": "QLF18C02", "C02076V02508": "320", "C02199V02655": "-"},
     "series_id": "CSO/QLF18/lfpr-15plus",
     "freq": "Q", "unit": "%", "adjustment": "NSA", "conversion": 1.0,
     "note": "CSO Ireland QLF18 ILO Participation Rate 15+ both sexes"},
    # Youth unemployment 15-24 (C06, age=310).
    {"slug": "youth-unemployment-rate", "table": "QLF18",
     "filters": {"STATISTIC": "QLF18C06", "C02076V02508": "310", "C02199V02655": "-"},
     "series_id": "CSO/QLF18/yuneml-15-24",
     "freq": "Q", "unit": "%", "adjustment": "NSA", "conversion": 1.0,
     "note": "CSO Ireland QLF18 Youth Unemployment Rate 15-24 both sexes"},
    # Unemployed persons — TE uses CSO MUM01 Monthly Unemployment count SA
    # (15-74 yrs, both sexes). Verified 2026-05-17: 2026-04 = 140.3 thousand (matches TE).
    {"slug": "unemployed-persons", "table": "MUM01",
     "filters": {"STATISTIC": "MUM01C01", "C02076V02508": "316", "C02199V02655": "-"},
     "series_id": "CSO/MUM01/unemp-month",
     "freq": "M", "unit": "Thousand", "adjustment": "SA", "conversion": 1.0,
     "note": "CSO Ireland MUM01 SA Monthly Unemployment count, 15-74 both sexes"},
    # Manufacturing-production — MIM05C03 SA Industrial Production NACE V2100 (mfg 10-33).
    {"slug": "manufacturing-production", "table": "MIM05",
     "filters": {"STATISTIC": "MIM05C03", "C02576V03125": "V2100"},
     "series_id": "CSO/MIM05/manuf",
     "freq": "M", "unit": "Index (2021=100)", "adjustment": "SA", "conversion": 1.0,
     "note": "CSO Ireland MIM05 SA Industrial Production NACE V2100 (Manufacturing 10-33)"},
    # National Accounts components — NAQ04, SA constant prices (S02), by C03331V04018:
    #   001  = Personal Consumption (full Personal Expenditure incl. NPISH)
    #   0012 = Household Final Consumption Expenditure only (TE consumer-spending uses this; matches 37778 for 2025Q4)
    #   002  = Government Final Consumption (government-spending)
    #   003  = Gross Domestic Fixed Capital Formation
    #   004  = Value of Physical Changes in Stocks (changes-in-inventories)
    {"slug": "consumer-spending", "table": "NAQ04",
     "filters": {"STATISTIC": "NAQ04S02", "C03331V04018": "0012"},
     "series_id": "CSO/NAQ04/consumer-0012",
     "freq": "Q", "unit": "EUR million", "adjustment": "SA", "conversion": 1.0,
     "note": "CSO Ireland NAQ04 Household FCE SA constant prices (sector 0012; matches TE 37778)"},
    {"slug": "government-spending", "table": "NAQ04",
     "filters": {"STATISTIC": "NAQ04S02", "C03331V04018": "002"},
     "series_id": "CSO/NAQ04/gov",
     "freq": "Q", "unit": "EUR million", "adjustment": "SA", "conversion": 1.0,
     "note": "CSO Ireland NAQ04 Government Final Consumption SA constant prices"},
    {"slug": "gross-fixed-capital-formation", "table": "NAQ04",
     "filters": {"STATISTIC": "NAQ04S02", "C03331V04018": "003"},
     "series_id": "CSO/NAQ04/gfcf",
     "freq": "Q", "unit": "EUR million", "adjustment": "SA", "conversion": 1.0,
     "note": "CSO Ireland NAQ04 Gross Domestic Fixed Capital Formation SA constant"},
    {"slug": "changes-in-inventories", "table": "NAQ04",
     "filters": {"STATISTIC": "NAQ04S02", "C03331V04018": "004"},
     "series_id": "CSO/NAQ04/inv",
     "freq": "Q", "unit": "EUR million", "adjustment": "SA", "conversion": 1.0,
     "note": "CSO Ireland NAQ04 Value of Physical Changes in Stocks SA"},
    # Government finance — GFA02 annual: Gross GG Debt (code 26), Net lending/B9 (code 18).
    {"slug": "government-debt", "table": "GFA02",
     "filters": {"STATISTIC": "GFA02", "C03145V03797": "26"},
     "series_id": "CSO/GFA02/debt",
     "freq": "A", "unit": "EUR million", "adjustment": "NSA", "conversion": 1.0,
     "note": "CSO Ireland GFA02 Gross General Government Debt (EDP face value)"},
    {"slug": "government-debt-total", "table": "GFA02",
     "filters": {"STATISTIC": "GFA02", "C03145V03797": "26"},
     "series_id": "CSO/GFA02/debt-total",
     "freq": "A", "unit": "EUR million", "adjustment": "NSA", "conversion": 1.0,
     "note": "CSO Ireland GFA02 Gross General Government Debt (EDP face value)"},
    {"slug": "budget-deficit", "table": "GFA02",
     "filters": {"STATISTIC": "GFA02", "C03145V03797": "18"},
     "series_id": "CSO/GFA02/b9",
     "freq": "A", "unit": "EUR million", "adjustment": "NSA", "conversion": 1.0,
     "note": "CSO Ireland GFA02 General Government Net Lending/Borrowing B9 (ESA2010)"},
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
    # TE attributes BE industrial-production to "Statbel" — but a 2026-05-15
    # full enumeration of https://bestat.statbel.fgov.be/bestat/api/views
    # (1341 views, all locales) found NO industrial-production volume index.
    # Statbel only publishes PPI (Erzeugerpreisindex / producer prices, 2021=100)
    # under that family; the industrial-production volume index (NACE B+C+D,
    # 2021=100, working-day adjusted) is published by Statbel and republished
    # by the NBB on Belgostat — the NBB SDMX redistribution below shares the
    # same underlying Statbel data and methodology. Keeping nbb as the
    # technical default is therefore TE-conformant.
    {"kind": "nbb", "slug": "industrial-production",
     "dataflow": "DF_INDPROD", "key": "M.2021.INDPROD.W.B_C_D.BE",
     "freq": "M", "unit": "Index (2021=100)", "adjustment": "WDA", "conversion": 1.0,
     "note": "NBB DF_INDPROD total industry B+C+D, WDA, base 2021=100 (Statbel "
             "IPI redistributed via Belgostat — Statbel REST API has no direct "
             "view for the IPI volume index as of 2026-05-15)"},

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

    # === Migration 075 (2026-05-15): TE-conformity gap-fill — BE Statbel + NBB SDMX ===
    # --- Statbel CPI by COICOP (dfc2ab6f: CPI 13 groups ECOICOP V2, last 13 months) ---
    # cpi-education: COICOP "10 Education services". Verified 2026-05-15: April 2026 = 101.79 (TE: 101.79 exact match).
    {"kind": "statbel", "slug": "cpi-education",
     "view_id": "dfc2ab6f-b5bf-4520-9645-31a5dbb2be06",
     "value_col": "Consumer price index",
     "row_filter": {"Level 1": "10 Education services"},
     "freq": "M", "unit": "Index", "adjustment": "NSA", "conversion": 1.0,
     "note": "Statbel CPI by ECOICOP V2 13 groups — Education services (10), last 13 months window"},
    # cpi-recreation-and-culture: COICOP "09 Recreation, sport and culture". Verified 2026-05-15: April 2026 = 105.54 (TE 105.33 close).
    {"kind": "statbel", "slug": "cpi-recreation-and-culture",
     "view_id": "dfc2ab6f-b5bf-4520-9645-31a5dbb2be06",
     "value_col": "Consumer price index",
     "row_filter": {"Level 1": "09 Recreation, sport and culture"},
     "freq": "M", "unit": "Index", "adjustment": "NSA", "conversion": 1.0,
     "note": "Statbel CPI by ECOICOP V2 — Recreation, sport and culture (09)"},
    # === BE re-audit 2026-05-16: TE attributes Statbel for clothing/food/housing/transport CPI subgroups ===
    # cpi-clothing: COICOP "03 Clothing and footwear". Verified 2026-05-16: April 2026 = 100.42 (TE Mar 2026 = 100.23 close).
    {"kind": "statbel", "slug": "cpi-clothing",
     "view_id": "dfc2ab6f-b5bf-4520-9645-31a5dbb2be06",
     "value_col": "Consumer price index",
     "row_filter": {"Level 1": "03 Clothing and footwear"},
     "freq": "M", "unit": "Index", "adjustment": "NSA", "conversion": 1.0,
     "note": "Statbel CPI by ECOICOP V2 — Clothing and footwear (03)"},
    # cpi-food: COICOP "01 Food and non-alcoholic beverages". Verified 2026-05-16: April 2026 = 100.93.
    {"kind": "statbel", "slug": "cpi-food",
     "view_id": "dfc2ab6f-b5bf-4520-9645-31a5dbb2be06",
     "value_col": "Consumer price index",
     "row_filter": {"Level 1": "01 Food and non-alcoholic beverages"},
     "freq": "M", "unit": "Index", "adjustment": "NSA", "conversion": 1.0,
     "note": "Statbel CPI by ECOICOP V2 — Food and non-alcoholic beverages (01)"},
    # cpi-housing-utilities: COICOP "04 Housing, water, electricity, gas and other fuels". April 2026 = 103.91.
    {"kind": "statbel", "slug": "cpi-housing-utilities",
     "view_id": "dfc2ab6f-b5bf-4520-9645-31a5dbb2be06",
     "value_col": "Consumer price index",
     "row_filter": {"Level 1": "04 Housing, water, electricity, gas and other fuels"},
     "freq": "M", "unit": "Index", "adjustment": "NSA", "conversion": 1.0,
     "note": "Statbel CPI by ECOICOP V2 — Housing, water, electricity, gas and other fuels (04)"},
    # cpi-transportation: COICOP "07 Transport". April 2026 = 106.95.
    {"kind": "statbel", "slug": "cpi-transportation",
     "view_id": "dfc2ab6f-b5bf-4520-9645-31a5dbb2be06",
     "value_col": "Consumer price index",
     "row_filter": {"Level 1": "07 Transport"},
     "freq": "M", "unit": "Index", "adjustment": "NSA", "conversion": 1.0,
     "note": "Statbel CPI by ECOICOP V2 — Transport (07)"},
    # core-cpi: 30778b36 HICP aggregates, Special aggregates="HICP excluding energy and unprocessed food".
    # Verified 2026-05-15: April 2026 = ~134.5 index. TE 8.7 appears to be old YoY%.
    {"kind": "statbel", "slug": "core-cpi",
     "view_id": "30778b36-87b4-44e7-bb37-d36adbebb2bc",
     "value_col": "HICP Index",
     "row_filter": {"Special aggregates": "HICP excluding energy and unprocessed food"},
     "freq": "M", "unit": "HICP Index", "adjustment": "NSA", "conversion": 1.0,
     "note": "Statbel HICP excluding energy and unprocessed food (core HICP), last 12 months"},
    # food-inflation YoY %: 70adacda Inflation by COICOP group. Level 1 = "01 Food and non-alcoholic beverages".
    # Statbel publishes as decimal (0.024 = 2.4%); convert to percentage.
    {"kind": "statbel", "slug": "food-inflation",
     "view_id": "70adacda-3a56-4bf9-bd59-6c241d4398db",
     "value_col": "Inflation (HICP)",
     "row_filter": {"Level 1": "01 Food and non-alcoholic beverages"},
     "freq": "M", "unit": "% YoY", "adjustment": "NSA", "conversion": 100.0,
     "note": "Statbel HICP inflation by COICOP — Food YoY % (decimal -> %)"},
    # labor-force-participation-rate (statbel 7d30d7ff quarterly Activity rate, Belgium total).
    # Verified 2026-05-15: 2025Q4 = 0.719 -> 71.9% (TE: 71.9 exact match).
    {"kind": "statbel", "slug": "labor-force-participation-rate",
     "view_id": "7d30d7ff-ab74-4047-b2af-2a0bff250647",
     "value_col": "Activity rate",
     "row_filter": {"Region": "", "Gender": "", "Total": "Total"},
     "freq": "Q", "unit": "%", "adjustment": "NSA", "conversion": 100.0,
     "note": "Statbel LFS Activity rate, Belgium total both sexes (decimal -> %), 2025 quarterly"},

    # --- NBB SDMX REST v2: National accounts, BoP, government, employment ---
    # consumer-spending: DF_QNA_DISS, Q.2.P31_S14_S15.VZ.V.Y (Private final consumption, total economy, current EUR mn, SA+WDA).
    # Verified 2026-05-15: 2025Q4 = 84,503 EUR mn.
    {"kind": "nbb", "slug": "consumer-spending",
     "dataflow": "DF_QNA_DISS", "key": "Q.2.P31_S14_S15.VZ.V.Y",
     "freq": "Q", "unit": "EUR million", "adjustment": "SA", "conversion": 1.0,
     "note": "NBB DF_QNA_DISS Private final consumption (P.31 S14+S15), VZ total economy, current EUR mn, SA+WDA"},
    # changes-in-inventories: P52 (Changes in stocks + Acquisitions less disposals of valuables).
    # Verified 2026-05-15: 2025Q4 = 3,780 EUR mn.
    {"kind": "nbb", "slug": "changes-in-inventories",
     "dataflow": "DF_QNA_DISS", "key": "Q.2.P52.VZ.V.Y",
     "freq": "Q", "unit": "EUR million", "adjustment": "SA", "conversion": 1.0,
     "note": "NBB DF_QNA_DISS P.52 Changes in stocks + acquisitions, total economy, current EUR mn, SA+WDA"},
    # gross-fixed-capital-formation: P51 total GFCF, EUR mn SA+WDA.
    # Verified 2026-05-15: 2025Q4 = 39,142 EUR mn.
    {"kind": "nbb", "slug": "gross-fixed-capital-formation",
     "dataflow": "DF_QNA_DISS", "key": "Q.2.P51.VZ.V.Y",
     "freq": "Q", "unit": "EUR million", "adjustment": "SA", "conversion": 1.0,
     "note": "NBB DF_QNA_DISS P.51 Gross fixed capital formation, total economy, current EUR mn, SA+WDA"},
    # government-spending: P3_S13 (Final consumption expenditure of general government).
    # Verified 2026-05-15: 2025Q4 = 39,161 EUR mn.
    {"kind": "nbb", "slug": "government-spending",
     "dataflow": "DF_QNA_DISS", "key": "Q.2.P3_S13..L.Y",
     "freq": "Q", "unit": "EUR million", "adjustment": "SA", "conversion": 1.0,
     "note": "NBB DF_QNA_DISS P.3 Final consumption of general government (S.13), current EUR mn, SA+WDA"},
    # government-spending-eur: alias of government-spending (TE BE re-audit 2026-05-16).
    {"kind": "nbb", "slug": "government-spending-eur",
     "dataflow": "DF_QNA_DISS", "key": "Q.2.P3_S13..L.Y",
     "freq": "Q", "unit": "EUR million", "adjustment": "SA", "conversion": 1.0,
     "note": "NBB DF_QNA_DISS P.3 (alias of government-spending), EUR mn quarterly"},
    # current-account: DF_NFQADISPINC_DISS B9 (Net lending/borrowing of nation = current account proxy), Y.
    # Verified 2026-05-15: 2025Q4 = -4,452 EUR mn.
    {"kind": "nbb", "slug": "current-account",
     "dataflow": "DF_NFQADISPINC_DISS", "key": "Q.B9.V.Y",
     "freq": "Q", "unit": "EUR million", "adjustment": "SA", "conversion": 1.0,
     "note": "NBB DF_NFQADISPINC_DISS B.9 Net lending/borrowing (current+capital account, ROW), EUR mn SA+WDA"},
    # disposable-personal-income: DF_NASECDETQ_DISS sector S1M (households+NPISH), II2U_B6G (gross disposable income).
    # Verified 2026-05-15: 2025Q4 = 96,445 EUR mn.
    {"kind": "nbb", "slug": "disposable-personal-income",
     "dataflow": "DF_NASECDETQ_DISS", "key": "Q.II2U_B6G.S1M",
     "freq": "Q", "unit": "EUR million", "adjustment": "NSA", "conversion": 1.0,
     "note": "NBB DF_NASECDETQ_DISS Gross disposable income (B.6g), Households+NPISH (S1M), quarterly EUR mn"},
    # employed-persons: DF_EMPLOY_DISS, INDICATOR=EMPLOY (employees), BRANCH=VZ, CONCEPT=D (domestic), ADJUSTMENT=Y.
    # Verified 2026-05-15: 2025Q4 = 4,210 thousand employees.
    {"kind": "nbb", "slug": "employed-persons",
     "dataflow": "DF_EMPLOY_DISS", "key": "Q.EMPLOY.VZ.D.Y",
     "freq": "Q", "unit": "Thousand", "adjustment": "SA", "conversion": 1.0,
     "note": "NBB DF_EMPLOY_DISS Number of employees, total economy domestic, thousands SA+WDA quarterly"},
    # exports: DF_EXTERNAL_TRADE_OVERVIEW, M.NBB_A1.X.NAT.VAL.M (World, exports, national concept, value, monthly).
    # Verified 2026-05-15: 2026-03 = 33,100 EUR mn.
    {"kind": "nbb", "slug": "exports",
     "dataflow": "DF_EXTERNAL_TRADE_OVERVIEW", "key": "M.NBB_A1.X.NAT.VAL.M",
     "freq": "M", "unit": "EUR million", "adjustment": "NSA", "conversion": 1.0,
     "note": "NBB DF_EXTERNAL_TRADE_OVERVIEW exports of goods vs World, national concept, value, monthly"},
    # imports: same DF, FLOW=I.
    # Verified 2026-05-15: 2026-03 = 29,816 EUR mn.
    {"kind": "nbb", "slug": "imports",
     "dataflow": "DF_EXTERNAL_TRADE_OVERVIEW", "key": "M.NBB_A1.I.NAT.VAL.M",
     "freq": "M", "unit": "EUR million", "adjustment": "NSA", "conversion": 1.0,
     "note": "NBB DF_EXTERNAL_TRADE_OVERVIEW imports of goods vs World, national concept, value, monthly"},
    # government-debt: DF_CGD Q.CGD.S1300.F (consolidated gross debt, general government, total instruments).
    # Verified 2026-05-15: 2025Q4 = 692,461 EUR mn (~ TE: gov debt EUR mn).
    {"kind": "nbb", "slug": "government-debt",
     "dataflow": "DF_CGD", "key": "Q.CGD.S1300.F",
     "freq": "Q", "unit": "EUR million", "adjustment": "NSA", "conversion": 1.0,
     "note": "NBB DF_CGD Consolidated gross debt of general government (S.1300), total instruments, quarterly EUR mn"},
    # government-debt-total: alias of government-debt (TE uses both slugs).
    {"kind": "nbb", "slug": "government-debt-total",
     "dataflow": "DF_CGD", "key": "Q.CGD.S1300.F",
     "freq": "Q", "unit": "EUR million", "adjustment": "NSA", "conversion": 1.0,
     "note": "NBB DF_CGD Consolidated gross debt (alias of government-debt)"},
    # unemployed-persons: DF_UNEMPLOY_RATE is rate only; use DF_UNEMPLOYMENT (count) — full 14-dim key.
    # Verified 2026-05-15: 2026-03 = 564,477 unemployed.
    {"kind": "nbb", "slug": "unemployed-persons",
     "dataflow": "DF_UNEMPLOYMENT", "key": "M.BE.AA.A0000.Z0000.999.BR00.000.0000.N.00.99.NHU._Z",
     "freq": "M", "unit": "Number", "adjustment": "NSA", "conversion": 1.0,
     "note": "NBB DF_UNEMPLOYMENT Belgium total all ages, persons (NHU non-harmonised), monthly NSA"},
    # manufacturing-production: DF_INDPROD NACE C (Manufacturing), WDA, base 2021=100.
    # Verified 2026-05-15: 2026-03 = 101.2 (NBB redistributes Statbel IPI; aggregation may differ from TE 62.1).
    {"kind": "nbb", "slug": "manufacturing-production",
     "dataflow": "DF_INDPROD", "key": "M.2021.INDPROD.W.C.BE",
     "freq": "M", "unit": "Index (2021=100)", "adjustment": "WDA", "conversion": 1.0,
     "note": "NBB DF_INDPROD Industrial production index, Manufacturing (NACE C), Belgium, WDA"},
    # mining-production: DF_INDPROD NACE B (Mining and quarrying).
    {"kind": "nbb", "slug": "mining-production",
     "dataflow": "DF_INDPROD", "key": "M.2021.INDPROD.W.B.BE",
     "freq": "M", "unit": "Index (2021=100)", "adjustment": "WDA", "conversion": 1.0,
     "note": "NBB DF_INDPROD Industrial production index, Mining and quarrying (NACE B), Belgium, WDA"},
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
    import csv as csvm, io as iom, re as rem
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
        dt = None
        if freq == "M":
            month_text = (row.get("Month") or row.get("Reference month") or "").strip()
            try:
                mname, ystr = month_text.rsplit(" ", 1)
                yy = int(ystr)
                mm = _BE_MONTHS[mname]
                dt = date(yy, mm, 1)
            except Exception:
                continue
        elif freq == "Q":
            q_text = (row.get("Quarter") or row.get("Trimester") or "").strip().lower()
            m = rem.match(r"(\d)(?:st|nd|rd|th)\s+(?:quarter|trimester)\s+(\d{4})", q_text)
            if not m:
                continue
            q = int(m.group(1)); yy = int(m.group(2))
            dt = date(yy, {1: 1, 2: 4, 3: 7, 4: 10}[q], 1)
        elif freq == "A":
            ystr = (row.get("Year") or "").strip()
            try:
                dt = date(int(ystr), 1, 1)
            except ValueError:
                continue
        if dt is None:
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

    # GDP-real (real, SA, level) — vgr108 quarterly, BIP zu Marktpreisen (VGRHAG-14).
    # F-RSAIB = real, seasonally and working-day adjusted. Convert Mio. EUR -> Bn EUR.
    # NOTE: previously labelled `gdp`; relabelled to `gdp-real` per TE inventory
    # (migration 051 promotes worldbank for the annual nominal USD `gdp` slug).
    {"slug": "gdp-real", "ogd": "OGD_vgr108_VGR_HA_vj_1",
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

    # === AT gap-fill (C9, 2026-05-15) — TE-source-conformity expansion ===
    # CPI sub-indices via OGD_vpi20_VPI_2020_1 (base 2020=100). COICOP at C-VPI5NEU-0.
    # F-VPIMZBM = Messzahl Berichtsmonat (level index). Coverage through 2025-12 (OGD lag).
    {"slug": "cpi-food", "ogd": "OGD_vpi20_VPI_2020_1",
     "filters": {"C-VPI5NEU-0": "VPI-01"},
     "time_col": "C-VPIZR-0", "value_col": "F-VPIMZBM",
     "freq": "M", "unit": "Index (2020=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "Statistik Austria VPI 2020 COICOP-01 Food & non-alc beverages (level)"},
    {"slug": "cpi-clothing", "ogd": "OGD_vpi20_VPI_2020_1",
     "filters": {"C-VPI5NEU-0": "VPI-03"},
     "time_col": "C-VPIZR-0", "value_col": "F-VPIMZBM",
     "freq": "M", "unit": "Index (2020=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "Statistik Austria VPI 2020 COICOP-03 Clothing & footwear (level)"},
    {"slug": "cpi-housing-utilities", "ogd": "OGD_vpi20_VPI_2020_1",
     "filters": {"C-VPI5NEU-0": "VPI-04"},
     "time_col": "C-VPIZR-0", "value_col": "F-VPIMZBM",
     "freq": "M", "unit": "Index (2020=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "Statistik Austria VPI 2020 COICOP-04 Housing, water, electricity (level)"},
    {"slug": "cpi-transportation", "ogd": "OGD_vpi20_VPI_2020_1",
     "filters": {"C-VPI5NEU-0": "VPI-07"},
     "time_col": "C-VPIZR-0", "value_col": "F-VPIMZBM",
     "freq": "M", "unit": "Index (2020=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "Statistik Austria VPI 2020 COICOP-07 Transport (level)"},
    {"slug": "cpi-recreation-and-culture", "ogd": "OGD_vpi20_VPI_2020_1",
     "filters": {"C-VPI5NEU-0": "VPI-09"},
     "time_col": "C-VPIZR-0", "value_col": "F-VPIMZBM",
     "freq": "M", "unit": "Index (2020=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "Statistik Austria VPI 2020 COICOP-09 Recreation & culture (level)"},
    {"slug": "cpi-education", "ogd": "OGD_vpi20_VPI_2020_1",
     "filters": {"C-VPI5NEU-0": "VPI-10"},
     "time_col": "C-VPIZR-0", "value_col": "F-VPIMZBM",
     "freq": "M", "unit": "Index (2020=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "Statistik Austria VPI 2020 COICOP-10 Education (level)"},
    # food-inflation: VPI-01 YoY rate column (F-VPIPZVJM = % vs. prev year same month)
    {"slug": "food-inflation", "ogd": "OGD_vpi20_VPI_2020_1",
     "filters": {"C-VPI5NEU-0": "VPI-01"},
     "time_col": "C-VPIZR-0", "value_col": "F-VPIPZVJM",
     "freq": "M", "unit": "% YoY", "adjustment": "NSA", "conversion": 1.0,
     "note": "Statistik Austria VPI 2020 COICOP-01 Food YoY (% vs prev. year)"},

    # === VGR108 quarterly national accounts components (Mio EUR -> Bn EUR) ===
    # Real, seasonally and working-day adjusted: F-RSAIB. Mapping via C-VGRHAG79-0.
    {"slug": "consumer-spending", "ogd": "OGD_vgr108_VGR_HA_vj_1",
     "filters": {"C-VGRHAG79-0": "VGRHAG-16"},
     "time_col": "C-A10-0", "value_col": "F-RSAIB",
     "freq": "Q", "unit": "Bn EUR (real, SA)", "adjustment": "SA", "conversion": 0.001,
     "note": "Statistik Austria VGR108 VGRHAG-16 HH final consumption, real SA, Mio→Bn EUR"},
    {"slug": "government-spending", "ogd": "OGD_vgr108_VGR_HA_vj_1",
     "filters": {"C-VGRHAG79-0": "VGRHAG-18"},
     "time_col": "C-A10-0", "value_col": "F-RSAIB",
     "freq": "Q", "unit": "Bn EUR (real, SA)", "adjustment": "SA", "conversion": 0.001,
     "note": "Statistik Austria VGR108 VGRHAG-18 Government final consumption, real SA"},
    {"slug": "gross-fixed-capital-formation", "ogd": "OGD_vgr108_VGR_HA_vj_1",
     "filters": {"C-VGRHAG79-0": "VGRHAG-23"},
     "time_col": "C-A10-0", "value_col": "F-RSAIB",
     "freq": "Q", "unit": "Bn EUR (real, SA)", "adjustment": "SA", "conversion": 0.001,
     "note": "Statistik Austria VGR108 VGRHAG-23 Total gross fixed capital formation, real SA"},
    {"slug": "changes-in-inventories", "ogd": "OGD_vgr108_VGR_HA_vj_1",
     "filters": {"C-VGRHAG79-0": "VGRHAG-32"},
     "time_col": "C-A10-0", "value_col": "F-NSAIB",
     "freq": "Q", "unit": "Bn EUR (nominal, SA)", "adjustment": "SA", "conversion": 0.001,
     "note": "Statistik Austria VGR108 VGRHAG-32 Changes in inventories, nominal SA (F-NSAIB)"},

    # === Industrial production sub-breakdowns (same OGD_kjiprodindex2021) ===
    # Use KJIB00-10 (Industrie gesamt, the same slice as industrial-production) but pick
    # a NACE-specific value column: F-KJIP_NAC_B = Mining, F-KJIP_NAC_C = Manufacturing.
    {"slug": "mining-production", "ogd": "OGD_kjiprodindex2021_KJID2021_PI_1",
     "filters": {"C-X93-0": "X93-2", "C-KJIB00-0": "KJIB00-10"},
     "time_col": "C-A10-0", "value_col": "F-KJIP_NAC_B",
     "freq": "M", "unit": "Index (2021=100, WDA)", "adjustment": "WDA", "conversion": 1.0,
     "note": "Statistik Austria Produktionsindex NACE B Bergbau (column F-KJIP_NAC_B), WDA"},
    {"slug": "manufacturing-production", "ogd": "OGD_kjiprodindex2021_KJID2021_PI_1",
     "filters": {"C-X93-0": "X93-2", "C-KJIB00-0": "KJIB00-10"},
     "time_col": "C-A10-0", "value_col": "F-KJIP_NAC_C",
     "freq": "M", "unit": "Index (2021=100, WDA)", "adjustment": "WDA", "conversion": 1.0,
     "note": "Statistik Austria Produktionsindex NACE C Verarbeitung (col F-KJIP_NAC_C), WDA"},
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
    # --- CPI sub-indices (ECOICOP) — base avg 2025 = 100 (MERITVE=33)
    # Verified 2026-05-14: clothing 03 2026M04 = 104.85, matches TE 104.85.
    {"slug": "cpi-clothing", "table": "0400608S.px",
     "query": {"ŽIVLJENJSKA POTREBŠČINA": "03", "MERITVE": "33"},
     "freq": "M", "unit": "Index (avg 2025=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "SURS 0400608 CPI sub-index Clothing & footwear (COICOP 03), avg-2025=100"},
    {"slug": "cpi-education", "table": "0400608S.px",
     "query": {"ŽIVLJENJSKA POTREBŠČINA": "10", "MERITVE": "33"},
     "freq": "M", "unit": "Index (avg 2025=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "SURS 0400608 CPI sub-index Education (COICOP 10), avg-2025=100"},
    {"slug": "cpi-food", "table": "0400608S.px",
     "query": {"ŽIVLJENJSKA POTREBŠČINA": "01", "MERITVE": "33"},
     "freq": "M", "unit": "Index (avg 2025=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "SURS 0400608 CPI sub-index Food & non-alc bevs (COICOP 01), avg-2025=100"},
    {"slug": "cpi-housing-utilities", "table": "0400608S.px",
     "query": {"ŽIVLJENJSKA POTREBŠČINA": "04", "MERITVE": "33"},
     "freq": "M", "unit": "Index (avg 2025=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "SURS 0400608 CPI sub-index Housing, water, electricity (COICOP 04), avg-2025=100"},
    {"slug": "cpi-recreation-and-culture", "table": "0400608S.px",
     "query": {"ŽIVLJENJSKA POTREBŠČINA": "09", "MERITVE": "33"},
     "freq": "M", "unit": "Index (avg 2025=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "SURS 0400608 CPI sub-index Recreation & culture (COICOP 09), avg-2025=100"},
    {"slug": "cpi-transportation", "table": "0400608S.px",
     "query": {"ŽIVLJENJSKA POTREBŠČINA": "07", "MERITVE": "33"},
     "freq": "M", "unit": "Index (avg 2025=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "SURS 0400608 CPI sub-index Transport (COICOP 07), avg-2025=100"},
    # food-inflation = CPI food YoY-style index (MERITVE=2: same-month-prev-year=100).
    # Verified 2026-05-14: 2026M04 = 101.0 -> 1.0% YoY, matches TE 1.0.
    {"slug": "food-inflation", "table": "0400608S.px",
     "query": {"ŽIVLJENJSKA POTREBŠČINA": "01", "MERITVE": "2"},
     "freq": "M", "unit": "Index (same-month py=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "SURS 0400608 CPI Food YoY index (same-month-prev-year=100)"},
    # --- National accounts expenditure components (0300230S, MERITVE=L constant ref 2010 prices, NSA)
    # Verified 2026-05-14 against TE: GFCF Q3/25=2614.1 (TE 2671.5 close), gov-spending Q2/25=2383.4 (TE 2411.5 close).
    {"slug": "consumer-spending", "table": "0300230S.px",
     "query": {"TRANSAKCIJE": "P31_S1M", "MERITVE": "L", "VRSTA PODATKA": "N"},
     "freq": "Q", "unit": "Million EUR (2010 constant)", "adjustment": "NSA", "conversion": 1.0,
     "note": "SURS 0300230 P31_S1M Household final consumption (constant 2010 prices, NSA, mln EUR)"},
    {"slug": "government-spending", "table": "0300230S.px",
     "query": {"TRANSAKCIJE": "P3_S13", "MERITVE": "L", "VRSTA PODATKA": "N"},
     "freq": "Q", "unit": "Million EUR (2010 constant)", "adjustment": "NSA", "conversion": 1.0,
     "note": "SURS 0300230 P3_S13 Government final consumption (constant 2010 prices, NSA, mln EUR)"},
    {"slug": "gross-fixed-capital-formation", "table": "0300230S.px",
     "query": {"TRANSAKCIJE": "P51G", "MERITVE": "L", "VRSTA PODATKA": "N"},
     "freq": "Q", "unit": "Million EUR (2010 constant)", "adjustment": "NSA", "conversion": 1.0,
     "note": "SURS 0300230 P51G Gross fixed capital formation (constant 2010 prices, NSA, mln EUR)"},
    # changes-in-inventories: constant 2010 prices return None — use Y (previous-year prices)
    {"slug": "changes-in-inventories", "table": "0300230S.px",
     "query": {"TRANSAKCIJE": "P52", "MERITVE": "Y", "VRSTA PODATKA": "N"},
     "freq": "Q", "unit": "Million EUR (prev-year prices)", "adjustment": "NSA", "conversion": 1.0,
     "note": "SURS 0300230 P52 Changes in inventories (constant prev-year prices, NSA, mln EUR)"},
    # --- Business / consumer surveys (2855901S, SA)
    # EKONOMSKI KAZALNIK = 2 (Confidence indicator in manufacturing) / 4 (Consumer confidence)
    {"slug": "business-confidence", "table": "2855901S.px",
     "query": {"EKONOMSKI KAZALNIK": "2", "VRSTA PODATKA": "2"},
     "freq": "M", "unit": "Balance", "adjustment": "SA", "conversion": 1.0,
     "note": "SURS 2855901 Business tendency survey — Confidence indicator in manufacturing (SA)"},
    {"slug": "consumer-confidence", "table": "2855901S.px",
     "query": {"EKONOMSKI KAZALNIK": "4", "VRSTA PODATKA": "2"},
     "freq": "M", "unit": "Balance", "adjustment": "SA", "conversion": 1.0,
     "note": "SURS 2855901 Consumer survey — Consumer confidence indicator (SA)"},
    # --- Manufacturing-only / Mining-only IP (1701111S)
    # Verified 2026-05-14: manufacturing C 2026M03 = 104.1, mining B 2026M03 = 94.8.
    {"slug": "manufacturing-production", "table": "1701111S.px",
     "query": {"SKD DEJAVNOST / NAMENSKA SKUPINA": "C[skd]", "VRSTA PODATKA": "sa"},
     "freq": "M", "unit": "Index (2021=100, SA)", "adjustment": "SA", "conversion": 1.0,
     "note": "SURS 1701111 IP Manufacturing C (NACE) seasonally+calendar adjusted, 2021=100"},
    {"slug": "mining-production", "table": "1701111S.px",
     "query": {"SKD DEJAVNOST / NAMENSKA SKUPINA": "B[skd]", "VRSTA PODATKA": "sa"},
     "freq": "M", "unit": "Index (2021=100, SA)", "adjustment": "SA", "conversion": 1.0,
     "note": "SURS 1701111 IP Mining & quarrying B (NACE) seasonally+calendar adjusted, 2021=100"},
    # --- Labour-force participation rate (0762003S activity rate, total all-ages both sexes)
    # Verified 2026-05-14: 2025Q4 = 58.5 — matches TE 58.5 exactly.
    {"slug": "labor-force-participation-rate", "table": "0762003S.px",
     "query": {"KOHEZIJSKA REGIJA": "0", "STAROSTNA SKUPINA": "0", "SPOL": "0", "MERITVE": "2000"},
     "freq": "Q", "unit": "%", "adjustment": "NSA", "conversion": 1.0,
     "note": "SURS 0762003 LFS Activity rate (all ages 15+, both sexes), quarterly %"},
    # --- Population (05E1004S half-yearly Basic population groups, total)
    # POLLETJE codes YYYYH1/H2 -> H1->Jan/H2->Jul (handled by extended _parse_period).
    # Convert to millions (TE displays 2.1 million; raw value ~2,130,986 -> 2.131).
    {"slug": "population", "table": "05E1004S.px",
     "query": {"STAROST": "999", "MERITVE": "1", "SPOL": "0"},
     "freq": "M", "unit": "Million", "adjustment": "NSA", "conversion": 1e-6,
     "note": "SURS 05E1004 Total resident population, half-yearly snapshots (millions)"},
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
    # PCI030m: Consumer price indices December 1990=100, monthly 1991M01-2026M04.
    # CSP encodes raw integers with decimals=2 (e.g. 29648 = 296.48). Apply 0.01.
    {"slug": "inflation-cpi", "path": "VEK/PC/PCI/PCI030m",
     "query": {"ContentsCode": "PCI030m"},
     "freq": "M", "unit": "Index (Dec 1990=100)", "adjustment": "NSA", "conversion": 0.01,
     "note": "CSP Latvia PCI030m CPI Dec 1990=100 (raw int *0.01)"},
    # NOTE: LV CSP PxWeb actively returns HTTP 400 when querying the section-level
    # "Industry total" aggregate (B_C_D_E in RCI020m, B_C_D_X_D353 in RUI020m)
    # paired with the TOVT/calendar-adjusted ContentsCode combos — only MIG_*
    # breakdowns return data. We therefore leave LV `ppi` on the Eurostat fallback.
    # Industrial / manufacturing / mining production are served from RUI030m
    # (YoY % from beginning of year, the headline TE-style YoY series), which
    # DOES accept the NACE section codes used by TE (B_C_D_X_D353, C, B).
    # RUI030m: "Volume indices of industrial production by economic activity
    #         (from the beginning of year), as % of corresponding period of
    #         previous year" — monthly 2001M01-2026M03.
    {"slug": "industrial-production", "path": "IZG/RU/RUI/RUI030m",
     "query": {"NACE": "B_C_D_X_D353", "ContentsCode": "RUI030m"},
     "series_id": "CSP/RUI030m/B_C_D_X_D353",
     "freq": "M", "unit": "% YoY (YTD)", "adjustment": "NSA", "conversion": 1.0,
     "note": "CSP Latvia RUI030m IP YoY%, total industry excl. D353, NSA"},
    {"slug": "manufacturing-production", "path": "IZG/RU/RUI/RUI030m",
     "query": {"NACE": "C", "ContentsCode": "RUI030m"},
     "series_id": "CSP/RUI030m/C",
     "freq": "M", "unit": "% YoY (YTD)", "adjustment": "NSA", "conversion": 1.0,
     "note": "CSP Latvia RUI030m IP YoY%, manufacturing (NACE C), NSA"},
    {"slug": "mining-production", "path": "IZG/RU/RUI/RUI030m",
     "query": {"NACE": "B", "ContentsCode": "RUI030m"},
     "series_id": "CSP/RUI030m/B",
     "freq": "M", "unit": "% YoY (YTD)", "adjustment": "NSA", "conversion": 1.0,
     "note": "CSP Latvia RUI030m IP YoY%, mining and quarrying (NACE B), NSA"},
    # Changes in inventories — chain-linked P52 is all-null; current-prices is
    # the only publishable LV series (TE shows EUR thousands current prices).
    # ISP050c P52 PRICES=CP NSA, quarterly thousand EUR.
    {"slug": "changes-in-inventories", "path": "VEK/IS/ISP/ISP050c",
     "query": {"PRICES": "CP", "SESON": "NSA", "INDICATOR": "P52",
               "ContentsCode": "ISP050c"},
     "series_id": "CSP/ISP050c/P52_CP_NSA",
     "freq": "Q", "unit": "Thousand EUR (current prices)", "adjustment": "NSA",
     "conversion": 1.0,
     "note": "CSP Latvia ISP050c P52 changes in inventories, current prices, NSA, kEUR"},
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
    # === gapfill batch (042_lv_gapfill) ===
    # ATD100m: monthly exports/imports of goods vs World, EUR mln
    {"slug": "exports", "path": "TIR/AT/ATD/ATD100m",
     "query": {"FLOW": "EXP", "COUNTRY_GROUP": "TOTAL", "ContentsCode": "ATD100m"},
     "series_id": "CSP/ATD100m/EXP",
     "freq": "M", "unit": "Million EUR", "adjustment": "NSA", "conversion": 1.0,
     "note": "CSP Latvia ATD100m total goods exports vs World, NSA, mln EUR"},
    {"slug": "imports", "path": "TIR/AT/ATD/ATD100m",
     "query": {"FLOW": "IMP", "COUNTRY_GROUP": "TOTAL", "ContentsCode": "ATD100m"},
     "series_id": "CSP/ATD100m/IMP",
     "freq": "M", "unit": "Million EUR", "adjustment": "NSA", "conversion": 1.0,
     "note": "CSP Latvia ATD100m total goods imports vs World, NSA, mln EUR"},
    # ISP050c: GDP by expenditure approach, chain-linked 2020, SA, thousand EUR -> mln
    {"slug": "consumer-spending", "path": "VEK/IS/ISP/ISP050c",
     "query": {"PRICES": "CLV2020", "SESON": "SA", "INDICATOR": "P31_S14", "ContentsCode": "ISP050c"},
     "series_id": "CSP/ISP050c/P31_S14",
     "freq": "Q", "unit": "Million EUR (2020 chained)", "adjustment": "SA", "conversion": 0.001,
     "note": "CSP Latvia ISP050c household final consumption expenditure (P31_S14)"},
    {"slug": "government-spending", "path": "VEK/IS/ISP/ISP050c",
     "query": {"PRICES": "CLV2020", "SESON": "SA", "INDICATOR": "P3_S13", "ContentsCode": "ISP050c"},
     "series_id": "CSP/ISP050c/P3_S13",
     "freq": "Q", "unit": "Million EUR (2020 chained)", "adjustment": "SA", "conversion": 0.001,
     "note": "CSP Latvia ISP050c government final consumption expenditure (P3_S13)"},
    # government-spending-eur: alias of government-spending (TE LV re-audit 2026-05-17).
    {"slug": "government-spending-eur", "path": "VEK/IS/ISP/ISP050c",
     "query": {"PRICES": "CLV2020", "SESON": "SA", "INDICATOR": "P3_S13", "ContentsCode": "ISP050c"},
     "series_id": "CSP/ISP050c/P3_S13",
     "freq": "Q", "unit": "Million EUR (2020 chained)", "adjustment": "SA", "conversion": 0.001,
     "note": "CSP Latvia ISP050c P3_S13 (alias of government-spending)"},
    {"slug": "gross-fixed-capital-formation", "path": "VEK/IS/ISP/ISP050c",
     "query": {"PRICES": "CLV2020", "SESON": "SA", "INDICATOR": "P51G", "ContentsCode": "ISP050c"},
     "series_id": "CSP/ISP050c/P51G",
     "freq": "Q", "unit": "Million EUR (2020 chained)", "adjustment": "SA", "conversion": 0.001,
     "note": "CSP Latvia ISP050c gross fixed capital formation (P51G)"},
    # NB: changes-in-inventories (P52) is null in chain-linked ISP050c -> kept on Eurostat
    # PCI021m: CPI by COICOP commodity group, monthly 2000M01- (Index 2025=100)
    {"slug": "cpi-food", "path": "VEK/PC/PCI/PCI021m",
     "query": {"ECOICOP_V2": "01", "ContentsCode": "PCI021m"},
     "series_id": "CSP/PCI021m/CP01",
     "freq": "M", "unit": "Index (2025=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "CSP Latvia PCI021m COICOP 01 Food and non-alcoholic beverages, 2025=100"},
    {"slug": "cpi-clothing", "path": "VEK/PC/PCI/PCI021m",
     "query": {"ECOICOP_V2": "03", "ContentsCode": "PCI021m"},
     "series_id": "CSP/PCI021m/CP03",
     "freq": "M", "unit": "Index (2025=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "CSP Latvia PCI021m COICOP 03 Clothing and footwear, 2025=100"},
    {"slug": "cpi-housing-utilities", "path": "VEK/PC/PCI/PCI021m",
     "query": {"ECOICOP_V2": "04", "ContentsCode": "PCI021m"},
     "series_id": "CSP/PCI021m/CP04",
     "freq": "M", "unit": "Index (2025=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "CSP Latvia PCI021m COICOP 04 Housing, 2025=100"},
    {"slug": "cpi-transportation", "path": "VEK/PC/PCI/PCI021m",
     "query": {"ECOICOP_V2": "07", "ContentsCode": "PCI021m"},
     "series_id": "CSP/PCI021m/CP07",
     "freq": "M", "unit": "Index (2025=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "CSP Latvia PCI021m COICOP 07 Transport, 2025=100"},
    {"slug": "cpi-recreation-and-culture", "path": "VEK/PC/PCI/PCI021m",
     "query": {"ECOICOP_V2": "09", "ContentsCode": "PCI021m"},
     "series_id": "CSP/PCI021m/CP09",
     "freq": "M", "unit": "Index (2025=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "CSP Latvia PCI021m COICOP 09 Recreation and culture, 2025=100"},
    {"slug": "cpi-education", "path": "VEK/PC/PCI/PCI021m",
     "query": {"ECOICOP_V2": "10", "ContentsCode": "PCI021m"},
     "series_id": "CSP/PCI021m/CP10",
     "freq": "M", "unit": "Index (2025=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "CSP Latvia PCI021m COICOP 10 Education, 2025=100"},
    # food-inflation: PCI021m6 = YoY % change for COICOP 01
    {"slug": "food-inflation", "path": "VEK/PC/PCI/PCI021m",
     "query": {"ECOICOP_V2": "01", "ContentsCode": "PCI021m6"},
     "series_id": "CSP/PCI021m6/CP01",
     "freq": "M", "unit": "%", "adjustment": "NSA", "conversion": 1.0,
     "note": "CSP Latvia PCI021m6 YoY %, COICOP 01 Food and non-alcoholic beverages"},
    # KRE020m: DG ECFIN BCS confidence indicators (balances %).
    # Migration 042 originally fetched VAL=SA, but TE displays the NSA series:
    #   business-confidence 2026-03 = -0.3   (CSP NSA -0.3, SA -3.0 — TE matches NSA)
    #   consumer-confidence 2026-03 = -16.1  (CSP NSA -16.1, SA -9.3 — TE matches NSA)
    # Fixed by migration 061 to use VAL=NSA.
    {"slug": "business-confidence", "path": "VEK/KR/KRE/KRE020m",
     "query": {"VAL": "NSA", "INDICATOR": "CI_IND", "ContentsCode": "KRE020m"},
     "series_id": "CSP/KRE020m/CI_IND/NSA",
     "freq": "M", "unit": "Net balance, %", "adjustment": "NSA", "conversion": 1.0,
     "note": "CSP Latvia KRE020m Industrial Confidence Indicator (DG ECFIN), NSA"},
    {"slug": "consumer-confidence", "path": "VEK/KR/KRE/KRE020m",
     "query": {"VAL": "NSA", "INDICATOR": "CI_CONSUM", "ContentsCode": "KRE020m"},
     "series_id": "CSP/KRE020m/CI_CONSUM/NSA",
     "freq": "M", "unit": "Net balance, %", "adjustment": "NSA", "conversion": 1.0,
     "note": "CSP Latvia KRE020m Consumer Confidence Indicator (DG ECFIN), NSA"},
    # NBL010m: Employed aged 15-74, SA, thousands, monthly
    {"slug": "employed-persons", "path": "EMP/NB/NBLA/NBL010m",
     "query": {"SEX": "T", "SESON": "SA", "ContentsCode": "NBL010m"},
     "series_id": "CSP/NBL010m",
     "freq": "M", "unit": "Thousand persons", "adjustment": "SA", "conversion": 1.0,
     "note": "CSP Latvia NBL010m employed persons aged 15-74, SA"},
    # NBL020c3: Employment rate aged 15-64, total, quarterly %
    {"slug": "employment-rate", "path": "EMP/NB/NBLB/NBL020c",
     "query": {"SEX": "T", "AgeGroup": "Y15-64", "ContentsCode": "NBL020c3"},
     "series_id": "CSP/NBL020c/Y15-64",
     "freq": "Q", "unit": "%", "adjustment": "NSA", "conversion": 1.0,
     "note": "CSP Latvia NBL020c employment rate aged 15-64, quarterly"},
    # NBA050c4: Activity rate (LFS) aged 15-64
    {"slug": "labor-force-participation-rate", "path": "EMP/NBB/NBA/NBA050c",
     "query": {"SEX": "T", "AgeGroup": "Y15-64", "ContentsCode": "NBA050c4"},
     "series_id": "CSP/NBA050c/Y15-64",
     "freq": "Q", "unit": "%", "adjustment": "NSA", "conversion": 1.0,
     "note": "CSP Latvia NBA050c activity rate aged 15-64, quarterly"},
    # IRS010m: Population at beginning of period, monthly, thousands
    {"slug": "population", "path": "POP/IR/IRS/IRS010m",
     "query": {"ContentsCode": "IRS010m"},
     "series_id": "CSP/IRS010m",
     "freq": "M", "unit": "Million persons", "adjustment": "NSA", "conversion": 0.001,
     "note": "CSP Latvia IRS010m population at beginning of period, thousand -> million"},
    # VFV040c: General government gross debt quarterly (mln EUR)
    {"slug": "government-debt", "path": "VEK/VF/VFV/VFV040c",
     "query": {"INDICATOR": "GROSS_DEBT", "ContentsCode": "VFV040c1"},
     "series_id": "CSP/VFV040c",
     "freq": "Q", "unit": "Million EUR", "adjustment": "NSA", "conversion": 1.0,
     "note": "CSP Latvia VFV040c general government gross debt quarterly, mln EUR"},
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
    # IPC102E: monthly CPI vs same month previous year = 100 (YoY index).
    # TE displays the YoY rate (e.g. 109.31 = +9.31% YoY) as the headline
    # inflation number, matching INSSE's published series. Use row_filter so
    # we keep only the exact 'TOTAL' aggregate (the dim pin alone is not strict
    # enough — TE returns TOTAL plus TOTAL MARFURI ALIMENTARE/NEALIMENTARE/SERVICII).
    {"slug": "inflation-cpi", "parent": "4000", "matrix": "IPC102E",
     "filter_dims": {"Categorii de marfuri si servicii cumparate": "TOTAL"},
     "row_filter": {"Categorii de marfuri si servicii cumparate": "TOTAL"},
     "unit_value": "Procente",
     "freq": "M", "unit": "Index (same month prev year=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "INSSE Tempo IPC102E CPI YoY index (same month prev year=100), TOTAL"},
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
    # 1505 FORTA DE MUNCA — FOM116A 'Rata de ocupare a resurselor de munca' (employment rate
    # of labour resources), annual, NSA, total / all regions.
    {"slug": "employment-rate", "parent": "1505", "matrix": "FOM116A",
     "filter_dims": {"Sexe": "Total ", "Macroregiuni, regiuni de dezvoltare si judete": "TOTAL"},
     "unit_value": "Procente",
     "freq": "A", "unit": "%", "adjustment": "NSA", "conversion": 1.0,
     "note": "INSSE Tempo FOM116A annual employment rate of labour resources, total"},
    # 5010 INDUSTRIE — IND104N filtered to INDUSTRIA PRELUCRATOARE (Manufacturing)
    {"slug": "manufacturing-production", "parent": "5010", "matrix": "IND104N",
     "series_id": "INSSE/IND104N/INDUSTRIA-PRELUCRATOARE",
     "filter_dims": {"Activitati ale industriei CAEN Rev.2 - total": "INDUSTRIA PRELUCRATOARE"},
     "unit_value": "Procente",
     "freq": "M", "unit": "Index (2021=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "INSSE Tempo IND104N IP monthly index, Manufacturing (CAEN Rev.2 section C), 2021=100"},
    # 5010 INDUSTRIE — IND104N filtered to INDUSTRIA EXTRACTIVA (Mining & quarrying)
    {"slug": "mining-production", "parent": "5010", "matrix": "IND104N",
     "series_id": "INSSE/IND104N/INDUSTRIA-EXTRACTIVA",
     "filter_dims": {"Activitati ale industriei CAEN Rev.2 - total": "INDUSTRIA EXTRACTIVA"},
     "unit_value": "Procente",
     "freq": "M", "unit": "Index (2021=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "INSSE Tempo IND104N IP monthly index, Mining & quarrying (CAEN Rev.2 section B), 2021=100"},
    # 1530 LOCURI DE MUNCA VACANTE — LMV102B job vacancies (number), all sections;
    # 'Perioade' dim mixes annual+quarterly — fetch_ro_tempo filters by 'trimestrul' for Q freq.
    {"slug": "job-vacancies", "parent": "1530", "matrix": "LMV102B",
     "filter_dims": {"CAEN Rev.2  (activitati ale economiei nationale)": "TOTAL",
                     "Macroregiuni si regiuni de dezvoltare": "TOTAL"},
     "unit_value": "Numar",
     "freq": "Q", "unit": "Number", "adjustment": "NSA", "conversion": 1.0,
     "note": "INSSE Tempo LMV102B Job vacancies (number), quarterly, total economy"},
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
                   freq: str = "M", row_filter: dict | None = None) -> list[tuple[date, float]]:
    """RO INSSE Tempo via tempo-py library.

    Generic fetcher: handles arbitrary number of dimensions by pinning each
    non-time, non-unit dim to the value supplied in filter_dims (key matched
    by exact-or-startswith against dim .label, to tolerate truncation).
    The unit dim (label starts 'UM:') is pinned to unit_value.
    The time dim ('Luni' for monthly, 'Ani' for annual) is selected exhaustively.
    Returns list of (date, value) sorted ascending.

    row_filter: optional {column_label: required_value} mapping applied AFTER
    the CSV is fetched, to drop rows whose category column doesn't match
    exactly. Use when the upstream Tempo query returns multiple sub-categories
    despite the dimension pin (observed for IPC102E where TOTAL also matches
    'TOTAL MARFURI ALIMENTARE' etc.).
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
        if lbl in ("Luni", "Ani", "Perioade"):
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

    # Pre-compute row_filter column indices (post-CSV filter to keep only rows
    # whose specified column exactly equals the required value).
    rf_cols: list[tuple[int, str]] = []
    if row_filter:
        for col_label, req_val in row_filter.items():
            try:
                rf_cols.append((header.index(col_label), req_val))
            except ValueError:
                pass

    out = []
    for line in lines[1:]:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) <= max(time_col, val_col):
            continue
        # Apply row_filter (exact match) if requested
        skip = False
        for ci, req in rf_cols:
            if ci >= len(parts) or parts[ci] != req:
                skip = True
                break
        if skip:
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
        elif freq == "Q" and len(words) == 3 and words[0] == "trimestrul" and words[1] in ("i","ii","iii","iv"):
            try:
                qmap = {"i": 3, "ii": 6, "iii": 9, "iv": 12}
                out.append((date(int(words[2]), qmap[words[1]], 1), val))
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
    # === gapfill batch (044_ee_gapfill) ===
    # IA002.px CPI 1997=100 monthly, by Kaubagrupp (commodity group)
    {"slug": "cpi-food", "path": "majandus/hinnad/IA002.px",
     "query": {"Kaubagrupp": "2"},
     "series_id": "STATEE/IA002/K2",
     "freq": "M_year_month_combo", "unit": "Index (1997=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "Stat Estonia IA002 CPI Food and non-alcoholic beverages"},
    {"slug": "cpi-clothing", "path": "majandus/hinnad/IA002.px",
     "query": {"Kaubagrupp": "4"},
     "series_id": "STATEE/IA002/K4",
     "freq": "M_year_month_combo", "unit": "Index (1997=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "Stat Estonia IA002 CPI Clothing and footwear"},
    {"slug": "cpi-housing-utilities", "path": "majandus/hinnad/IA002.px",
     "query": {"Kaubagrupp": "5"},
     "series_id": "STATEE/IA002/K5",
     "freq": "M_year_month_combo", "unit": "Index (1997=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "Stat Estonia IA002 CPI Housing"},
    {"slug": "cpi-transportation", "path": "majandus/hinnad/IA002.px",
     "query": {"Kaubagrupp": "8"},
     "series_id": "STATEE/IA002/K8",
     "freq": "M_year_month_combo", "unit": "Index (1997=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "Stat Estonia IA002 CPI Transport"},
    {"slug": "cpi-recreation-and-culture", "path": "majandus/hinnad/IA002.px",
     "query": {"Kaubagrupp": "10"},
     "series_id": "STATEE/IA002/K10",
     "freq": "M_year_month_combo", "unit": "Index (1997=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "Stat Estonia IA002 CPI Recreation, sport and culture"},
    {"slug": "cpi-education", "path": "majandus/hinnad/IA002.px",
     "query": {"Kaubagrupp": "11"},
     "series_id": "STATEE/IA002/K11",
     "freq": "M_year_month_combo", "unit": "Index (1997=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "Stat Estonia IA002 CPI Education services"},
    # RAA0061.PX GDP by expenditure (ESA 2010), quarterly chain-linked vol mln EUR (Näitaja=2)
    # Komponent: 1=Private consumption, 2=Government, 4=GFCF, 7=Exports, 10=Imports
    # NB: 5=Change in inventories has no chain-linked vol; pulled at current prices (Näitaja=1)
    {"slug": "consumer-spending", "path": "majandus/rahvamajanduse-arvepidamine/sisemajanduse-koguprodukt-(skp)/sisemajanduse-koguprodukt-tarbimise-meetodil/RAA0061.PX",
     "query": {"Komponent": "1", "Näitaja": "2"},
     "series_id": "STATEE/RAA0061/K1",
     "freq": "Q_year_quarter_combo", "unit": "Million EUR (2020 chain-linked)", "adjustment": "NSA", "conversion": 1.0,
     "note": "Stat Estonia RAA0061 private consumption expenditure, chain-linked vol ref 2020"},
    {"slug": "government-spending", "path": "majandus/rahvamajanduse-arvepidamine/sisemajanduse-koguprodukt-(skp)/sisemajanduse-koguprodukt-tarbimise-meetodil/RAA0061.PX",
     "query": {"Komponent": "2", "Näitaja": "2"},
     "series_id": "STATEE/RAA0061/K2",
     "freq": "Q_year_quarter_combo", "unit": "Million EUR (2020 chain-linked)", "adjustment": "NSA", "conversion": 1.0,
     "note": "Stat Estonia RAA0061 general government final consumption expenditure, chain-linked"},
    # government-spending-eur mirrors government-spending in EUR Million (TE attribution: Statistics Estonia)
    {"slug": "government-spending-eur", "path": "majandus/rahvamajanduse-arvepidamine/sisemajanduse-koguprodukt-(skp)/sisemajanduse-koguprodukt-tarbimise-meetodil/RAA0061.PX",
     "query": {"Komponent": "2", "Näitaja": "2"},
     "series_id": "STATEE/RAA0061/K2",
     "freq": "Q_year_quarter_combo", "unit": "Million EUR (2020 chain-linked)", "adjustment": "NSA", "conversion": 1.0,
     "note": "Stat Estonia RAA0061 government spending in EUR; mirrors government-spending. TE attributes Statistics Estonia."},
    {"slug": "gross-fixed-capital-formation", "path": "majandus/rahvamajanduse-arvepidamine/sisemajanduse-koguprodukt-(skp)/sisemajanduse-koguprodukt-tarbimise-meetodil/RAA0061.PX",
     "query": {"Komponent": "4", "Näitaja": "2"},
     "series_id": "STATEE/RAA0061/K4",
     "freq": "Q_year_quarter_combo", "unit": "Million EUR (2020 chain-linked)", "adjustment": "NSA", "conversion": 1.0,
     "note": "Stat Estonia RAA0061 gross fixed capital formation + valuables, chain-linked"},
    {"slug": "changes-in-inventories", "path": "majandus/rahvamajanduse-arvepidamine/sisemajanduse-koguprodukt-(skp)/sisemajanduse-koguprodukt-tarbimise-meetodil/RAA0061.PX",
     "query": {"Komponent": "5", "Näitaja": "1"},
     "series_id": "STATEE/RAA0061/K5",
     "freq": "Q_year_quarter_combo", "unit": "Million EUR (current prices)", "adjustment": "NSA", "conversion": 1.0,
     "note": "Stat Estonia RAA0061 change in inventories at current prices (chain-linked not published)"},
    {"slug": "exports", "path": "majandus/rahvamajanduse-arvepidamine/sisemajanduse-koguprodukt-(skp)/sisemajanduse-koguprodukt-tarbimise-meetodil/RAA0061.PX",
     "query": {"Komponent": "7", "Näitaja": "2"},
     "series_id": "STATEE/RAA0061/K7",
     "freq": "Q_year_quarter_combo", "unit": "Million EUR (2020 chain-linked)", "adjustment": "NSA", "conversion": 1.0,
     "note": "Stat Estonia RAA0061 exports of goods and services, chain-linked"},
    {"slug": "imports", "path": "majandus/rahvamajanduse-arvepidamine/sisemajanduse-koguprodukt-(skp)/sisemajanduse-koguprodukt-tarbimise-meetodil/RAA0061.PX",
     "query": {"Komponent": "10", "Näitaja": "2"},
     "series_id": "STATEE/RAA0061/K10",
     "freq": "Q_year_quarter_combo", "unit": "Million EUR (2020 chain-linked)", "adjustment": "NSA", "conversion": 1.0,
     "note": "Stat Estonia RAA0061 imports of goods and services, chain-linked"},
    # TO0053.PX Industrial production volume index 2021=100, monthly, SA+CA (Y)
    {"slug": "manufacturing-production", "path": "majandus/toostus/TO0053.PX",
     "query": {"Näitaja": "PROD", "Tegevusala": "C", "Korrigeerimine": "Y"},
     "series_id": "STATEE/TO0053/C",
     "freq": "M", "unit": "Index (2021=100)", "adjustment": "SA", "conversion": 1.0,
     "note": "Stat Estonia TO0053 manufacturing C volume index SA, 2021=100"},
    {"slug": "mining-production", "path": "majandus/toostus/TO0053.PX",
     "query": {"Näitaja": "PROD", "Tegevusala": "B", "Korrigeerimine": "Y"},
     "series_id": "STATEE/TO0053/B",
     "freq": "M", "unit": "Index (2021=100)", "adjustment": "SA", "conversion": 1.0,
     "note": "Stat Estonia TO0053 mining and quarrying B volume index SA, 2021=100"},
    # TT0130.px employed persons (thousands), quarterly
    {"slug": "employed-persons", "path": "sotsiaalelu/tooturg/heivatud/luhiajastatistika/TT0130.px",
     "query": {"Näitaja": "EMP_NR", "Sugu": "T", "Vanuserühm": "Y15-74", "Töötaja hõivatus": "TOTAL"},
     "series_id": "STATEE/TT0130",
     "freq": "Q", "unit": "Thousand persons", "adjustment": "NSA", "conversion": 1.0,
     "note": "Stat Estonia TT0130 employed persons 15-74, both sexes, full+part time"},
    # TT0160.px employment-rate, quarterly (Y20-64 EU std)
    {"slug": "employment-rate", "path": "sotsiaalelu/tooturg/tooturu-uldandmed/luhiajastatistika/TT0160.px",
     "query": {"Näitaja": "EMPRATE", "Sugu": "T", "Vanuserühm": "Y20-64"},
     "series_id": "STATEE/TT0160/EMPRATE",
     "freq": "Q", "unit": "%", "adjustment": "NSA", "conversion": 1.0,
     "note": "Stat Estonia TT0160 employment rate Y20-64, total"},
    # labor-force-participation-rate (LABOUR_RATE) Y15-74
    {"slug": "labor-force-participation-rate", "path": "sotsiaalelu/tooturg/tooturu-uldandmed/luhiajastatistika/TT0160.px",
     "query": {"Näitaja": "LABOUR_RATE", "Sugu": "T", "Vanuserühm": "Y15-74"},
     "series_id": "STATEE/TT0160/LABOUR_RATE",
     "freq": "Q", "unit": "%", "adjustment": "NSA", "conversion": 1.0,
     "note": "Stat Estonia TT0160 labour force participation rate Y15-74"},
    # RV021.PX population at 1 January (annual)
    {"slug": "population", "path": "rahvastik/rahvastikunaitajad-ja-koosseis/rahvaarv-ja-rahvastiku-koosseis/RV021.PX",
     "query": {"Sugu": "1", "Vanuserühm": "1"},
     "series_id": "STATEE/RV021",
     "freq": "A", "unit": "Million persons", "adjustment": "NSA", "conversion": 0.000001,
     "note": "Stat Estonia RV021 population at 1 January, total -> million"},
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
    # mun0098 col 8 = "Unemployment rate" %, LFS aged 15-64, Total section (first occurrence).
    # Canonical slug is `unemployment` (no -rate suffix); FK enforces.
    {"slug": "unemployment", "section": "mun", "table": "mun0098",
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
    # ara0042 = 'Consumer price indices by main groups of COICOP, monthly'. Row-oriented:
    # each COICOP class is one row, columns are 5 years × 12 months. YoY index (sm-py=100).
    # Row indices (0-based, within full HTML <table>): 3=Food, 4=Alc/tob, 5=Clothing,
    # 6=Housing, 7=Furn, 8=Health, 9=Transport, 10=Communication, 11=Recreation,
    # 12=Education, 13=Restaurants, 14=Misc, 15=Total. Section-header at row 2.
    {"slug": "cpi-transportation", "section": "ara", "table": "ara0042",
     "row_index": 9, "row_oriented": True, "n_years": 5, "start_year": 2022,
     "freq": "M", "unit": "Index (same month previous year=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "KSH STADAT 1.2.1.4 ara0042 row 9 (COICOP 07 Transport) YoY index"},
    # ipa0037 = 'Volume indices of industrial production by sub-sections, monthly avg 2021=100'.
    # Column 1 (0-indexed) = 'Mining and quarrying' (NACE B). Period column then 14 sub-sections.
    # value_col_index 2 = 'Period(yr)' / 'Period(mo)' / Mining=col 2 in legacy parser.
    {"slug": "mining-production", "section": "ipa", "table": "ipa0037",
     "value_col_index": 2,
     "freq": "M", "unit": "Index (monthly avg 2021=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "KSH STADAT 13.2.1.7 ipa0037 col 2 (Mining&quarrying NACE B) index 2021=100"},
    # ipa0037 col 16 = NACE C 'Manufacturing'; same 2021=100 monthly index.
    {"slug": "manufacturing-production", "section": "ipa", "table": "ipa0037",
     "value_col_index": 16,
     "freq": "M", "unit": "Index (monthly avg 2021=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "KSH STADAT 13.2.1.7 ipa0037 col 16 (Manufacturing NACE C) index 2021=100"},
    # ara0040 col 2 = Food YoY index (same month previous year=100).
    {"slug": "food-inflation", "section": "ara", "table": "ara0040",
     "value_col_index": 2,
     "freq": "M", "unit": "Index (same month previous year=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "KSH STADAT 1.2.1.2 ara0040 col 2 Food YoY index (sm-py=100)"},
    # mun0099 3-month rolling LFS, 15-74. Sub-sections Total/Males/Females are separated
    # only by year recurrence (no explicit headers). The dedicated mun0099 parser
    # tracks the first 'Total' segment and converts 'January–March' style period text
    # to date(year, last-month-of-window, 1).
    # Columns (cells[0]=year,cells[1]=period):
    #   2  Employed
    #   6  Unemployed
    #  11  Activity rate (LFP)
    #  12  Unemployment rate
    #  13  Employment rate
    {"slug": "employed-persons", "section": "mun", "table": "mun0099",
     "value_col_index": 2, "parser": "mun0099_rolling",
     "freq": "M", "unit": "Thousand persons", "adjustment": "NSA", "conversion": 1.0,
     "note": "KSH STADAT 20.2.1.4 mun0099 col 2 Employed 15-74 (3-month rolling, Total)"},
    {"slug": "employment-rate", "section": "mun", "table": "mun0099",
     "value_col_index": 13, "parser": "mun0099_rolling",
     "freq": "M", "unit": "%", "adjustment": "NSA", "conversion": 1.0,
     "note": "KSH STADAT 20.2.1.4 mun0099 col 13 Employment rate 15-74 Total (3-mo rolling)"},
    {"slug": "labor-force-participation-rate", "section": "mun", "table": "mun0099",
     "value_col_index": 11, "parser": "mun0099_rolling",
     "freq": "M", "unit": "%", "adjustment": "NSA", "conversion": 1.0,
     "note": "KSH STADAT 20.2.1.4 mun0099 col 11 Activity rate (LFP) 15-74 Total (3-mo rolling)"},
    # mun0159 col 23 = Number of job vacancies, National Economy total (A-S), quarterly.
    # Table has two sections: 'Number of job vacancies' and 'Job vacancy rate %';
    # use job_vacancies-aware parser to read only the first block.
    {"slug": "job-vacancies", "section": "mun", "table": "mun0159",
     "value_col_index": 23, "parser": "mun0159_count",
     "freq": "Q", "unit": "Persons", "adjustment": "NSA", "conversion": 1.0,
     "note": "KSH STADAT 20.2.1.53 mun0159 col 23 Job vacancies National Economy total A-S"},
    # nep0001 'Main indicators of population and vital events' — row-oriented annual.
    # Row index 4 = 'total' population, 1 January; columns are years (header row 0).
    {"slug": "population", "section": "nep", "table": "nep0001",
     "row_index": 4, "parser": "nep0001_annual",
     "freq": "A", "unit": "Persons", "adjustment": "NSA", "conversion": 0.000001,
     "note": "KSH STADAT 22.1.1.1 nep0001 row 4 (total) Population 1 January, converted to millions"},
    # gdp0094 'Final use of GDP at current prices (quarterly)'. 23 cols incl. period split.
    # col 2 = HH FC expenditure -> consumer-spending
    # col 6 = Actual FC of government -> government-spending
    # col 8 = Gross fixed capital formation -> GFCF
    # col 9 = Changes in inventories -> changes-in-inventories
    {"slug": "consumer-spending", "section": "gdp", "table": "gdp0094",
     "value_col_index": 2,
     "freq": "Q", "unit": "Million HUF", "adjustment": "NSA", "conversion": 1.0,
     "note": "KSH STADAT 21.2.1.10 gdp0094 col 2 HH FC expenditure, current prices, mHUF"},
    {"slug": "government-spending", "section": "gdp", "table": "gdp0094",
     "value_col_index": 6,
     "freq": "Q", "unit": "Million HUF", "adjustment": "NSA", "conversion": 1.0,
     "note": "KSH STADAT 21.2.1.10 gdp0094 col 6 Actual FC of government, current prices, mHUF"},
    {"slug": "gross-fixed-capital-formation", "section": "gdp", "table": "gdp0094",
     "value_col_index": 8,
     "freq": "Q", "unit": "Million HUF", "adjustment": "NSA", "conversion": 1.0,
     "note": "KSH STADAT 21.2.1.10 gdp0094 col 8 GFCF, current prices, mHUF"},
    {"slug": "changes-in-inventories", "section": "gdp", "table": "gdp0094",
     "value_col_index": 9,
     "freq": "Q", "unit": "Million HUF", "adjustment": "NSA", "conversion": 1.0,
     "note": "KSH STADAT 21.2.1.10 gdp0094 col 9 Changes in inventories, current prices, mHUF"},
    # kkr0065 col 19 = Hungary exports of goods (EU-comparison table), monthly, mEUR.
    {"slug": "exports", "section": "kkr", "table": "kkr0065",
     "value_col_index": 19,
     "freq": "M", "unit": "Million EUR", "adjustment": "NSA", "conversion": 1.0,
     "note": "KSH STADAT 17.2.3.1 kkr0065 col 19 Hungary exports of goods, monthly, mEUR"},
    # kkr0064 col 19 = Hungary imports of goods (EU-comparison table), monthly, mEUR.
    {"slug": "imports", "section": "kkr", "table": "kkr0064",
     "value_col_index": 19,
     "freq": "M", "unit": "Million EUR", "adjustment": "NSA", "conversion": 1.0,
     "note": "KSH STADAT 17.2.3.2 kkr0064 col 19 Hungary imports of goods, monthly, mEUR"},
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


def fetch_hu_stadat_row(table: str, row_index: int, n_years: int, start_year: int,
                         section: str = "ara") -> list[tuple[date, float]]:
    """Scrape a row-oriented KSH STADAT HTML table where each row corresponds to
    one category and columns are flat-laid year×month (12 × n_years values).

    Used for tables like ara0042 'CPI by COICOP main groups, monthly' where each
    COICOP class is one row spanning many year×month columns. cells[0] is the
    category code, cells[1] the label, cells[2:] are the monthly values.
    Returns sorted [(date, value)].
    """
    import bs4
    url = f"https://www.ksh.hu/stadat_files/{section}/en/{table}.html"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    soup = bs4.BeautifulSoup(r.text, "html.parser")
    table_el = soup.find("table")
    if not table_el:
        return []
    rows = table_el.find_all("tr")
    if row_index >= len(rows):
        return []
    cells = [c.get_text(strip=True) for c in rows[row_index].find_all(["td", "th"])]
    data = cells[2:2 + n_years * 12]
    out = []
    for i, raw in enumerate(data):
        val = _hu_parse_number(raw)
        if val is None:
            continue
        y = start_year + i // 12
        m = (i % 12) + 1
        out.append((date(y, m, 1), val))
    return sorted(out)


def fetch_hu_trade_balance() -> list[tuple[date, float]]:
    """Synthesise HU trade balance = exports (kkr0065) - imports (kkr0064), million EUR.
    Hungary appears at value_col_index 19 in both EU-comparison tables."""
    exp = dict(fetch_hu_stadat("kkr0065", 19, "M", section="kkr"))
    imp = dict(fetch_hu_stadat("kkr0064", 19, "M", section="kkr"))
    return [(dt, exp[dt] - imp[dt]) for dt in sorted(set(exp.keys()) & set(imp.keys()))]


def fetch_hu_mun0159_count(value_col_index: int) -> list[tuple[date, float]]:
    """Scrape mun0159 'Job vacancies, quarterly'. Table has two stacked blocks:
    'Number of job vacancies' (counts) and 'Job vacancy rate, %'. We stop after the
    first block (when we encounter the rate-block header).
    Each data row: cells = ['<year-or-empty>', 'Q1'..'Q4', 21 NACE letters values,
    National-economy-total, of-which: business, of-which: budgetary]. So
    value_col_index 23 = National economy total (A-S)."""
    import bs4
    url = "https://www.ksh.hu/stadat_files/mun/en/mun0159.html"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    soup = bs4.BeautifulSoup(r.text, "html.parser")
    table_el = soup.find("table")
    if not table_el:
        return []
    rows = table_el.find_all("tr")
    current_year = None
    in_count_block = False
    out: list[tuple[date, float]] = []
    for tr in rows:
        cells = [c.get_text(strip=True) for c in tr.find_all(["td", "th"])]
        if not cells:
            continue
        first = cells[0]
        if first.startswith("Number of job vacancies"):
            in_count_block = True
            current_year = None
            continue
        if first.startswith("Job vacancy rate"):
            # Counts block ended.
            break
        if not in_count_block:
            continue
        if first.isdigit() and len(first) == 4:
            current_year = int(first)
            quarter_text = cells[1] if len(cells) > 1 else ""
        elif first == "" and len(cells) >= 2 and cells[1] in HU_QUARTERS:
            quarter_text = cells[1]
        elif first in HU_QUARTERS:
            quarter_text = first
        else:
            continue
        if quarter_text not in HU_QUARTERS or current_year is None:
            continue
        if value_col_index < len(cells):
            val = _hu_parse_number(cells[value_col_index])
            if val is None:
                continue
            month = HU_QUARTERS[quarter_text]
            out.append((date(current_year, month, 1), val))
    return sorted(out)


def fetch_hu_nep0001_annual(row_index: int) -> list[tuple[date, float]]:
    """Scrape nep0001 'Main indicators of population and vital events'. The table is
    row-oriented: row 0 is the year header (skipping label cell), and row N (4 = total
    population, 1 January) holds one cell per year. Header includes irregular early years
    (1941, 1949, 1960, 1970, 1980, 1990, 2001, ...) plus continuous yearly entries.
    Returns sorted [(date(year, 1, 1), value)]."""
    import bs4
    url = "https://www.ksh.hu/stadat_files/nep/en/nep0001.html"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    soup = bs4.BeautifulSoup(r.text, "html.parser")
    table_el = soup.find("table")
    if not table_el:
        return []
    rows = table_el.find_all("tr")
    if row_index >= len(rows) or len(rows) == 0:
        return []
    header_cells = [c.get_text(strip=True) for c in rows[0].find_all(["td", "th"])]
    data_cells = [c.get_text(strip=True) for c in rows[row_index].find_all(["td", "th"])]
    if len(header_cells) < 2 or len(data_cells) < 2:
        return []
    # header_cells[0] = 'Denomination'; data_cells[0] = 'total'/'males'/etc label.
    # Pair year-header cells with corresponding data cells starting at index 1.
    out: list[tuple[date, float]] = []
    for i in range(1, min(len(header_cells), len(data_cells))):
        hraw = header_cells[i]
        # year strings may carry footnote markers like '1941b' - strip non-digits at end.
        digits = "".join(ch for ch in hraw if ch.isdigit())
        if len(digits) != 4:
            continue
        yy = int(digits)
        val = _hu_parse_number(data_cells[i])
        if val is None:
            continue
        out.append((date(yy, 1, 1), val))
    return sorted(out)


def fetch_hu_mun0099_rolling(value_col_index: int) -> list[tuple[date, float]]:
    """Scrape mun0099 'Economic activity of population aged 15-74, 3 months mean data'.
    Period column 1 holds text like 'January-March', 'February-April', ...,
    'November-2026. January', 'December-2026. February' (en-dash variants). We map each
    period to date(year, last_month_of_rolling_window, 1).

    The table contains three stacked sub-sections (Total, Males, Females); only the
    first ('Total') is included. Sub-section boundaries are detected by year-counter
    resets (year '2009' or any year that has already been observed within the current
    section triggers section end).
    """
    import bs4
    url = "https://www.ksh.hu/stadat_files/mun/en/mun0099.html"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    soup = bs4.BeautifulSoup(r.text, "html.parser")
    table_el = soup.find("table")
    if not table_el:
        return []
    out: list[tuple[date, float]] = []
    seen_years: set[int] = set()
    current_year: int | None = None
    section_done = False
    for tr in table_el.find_all("tr"):
        if section_done:
            break
        cells = [c.get_text(strip=True) for c in tr.find_all(["td", "th"])]
        if not cells:
            continue
        first = cells[0]
        if first.isdigit() and len(first) == 4:
            new_year = int(first)
            if new_year in seen_years:
                # Section boundary: second occurrence of an already-seen year =
                # Males/Females sub-section is starting.
                section_done = True
                break
            current_year = new_year
            seen_years.add(new_year)
            period_text = cells[1] if len(cells) > 1 else ""
        elif first == "" and len(cells) >= 2:
            period_text = cells[1]
        else:
            continue
        if current_year is None or not period_text:
            continue
        # Period text examples: 'January–March', 'November–2026. January',
        # 'December–2026. February'. Determine the *last* month of the rolling window.
        # Replace various dash characters with a uniform '-'.
        norm = period_text.replace("–", "-").replace("—", "-")
        # Split on '-' to get the right-hand part.
        if "-" not in norm:
            continue
        right = norm.split("-", 1)[1].strip()
        # If right side contains a 4-digit year like '2026. January', strip the year.
        # Extract the trailing month name.
        right_parts = right.replace(".", " ").split()
        month_word = None
        new_year_for_end = None
        for tok in right_parts:
            if tok in HU_MONTHS:
                month_word = tok
            elif tok.isdigit() and len(tok) == 4:
                new_year_for_end = int(tok)
        if month_word is None:
            continue
        # The rolling-window's end year is `new_year_for_end` if present, else current_year.
        end_year = new_year_for_end if new_year_for_end is not None else current_year
        end_month = HU_MONTHS[month_word]
        if value_col_index < len(cells):
            val = _hu_parse_number(cells[value_col_index])
            if val is None:
                continue
            out.append((date(end_year, end_month, 1), val))
    return sorted(out)


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
    # sp0107ms: Producer price indices in comparison with the basic period — monthly.
    # 5 dims (after year/month): specu (base), cpa (industry), indic.
    # SPECU_B_DEC2021 = Dec 2021=100 (matches TE PPI series).
    # UKAZ04 = Industrial producers prices - total, U_SP_0007 = Producer price indices.
    {"slug": "ppi", "dataset_id": "sp0107ms",
     "segments": ["all", "all", "SPECU_B_DEC2021", "UKAZ04", "U_SP_0007"],
     "freq": "M", "unit": "Index (Dec 2021=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "SUSR sp0107ms PPI Industrial producers prices total, Dec 2021=100 base (TE-conform)"},
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
    {"slug": "unemployment", "dataset_id": "pr1802qs",
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
    # CPI by COICOP main groups — same sp2038ms dataset, different odb codes.
    # odb01=Total (already mapped to inflation-cpi), odb02..odb12 = COICOP 01..12.
    # Mapping (KSH SUSR odb code -> TE indicator slug):
    #   odb02 (Food & non-alc bev)           -> cpi-food
    #   odb04 (Clothing & footwear)          -> cpi-clothing
    #   odb05 (Housing, water, electricity)  -> cpi-housing-utilities
    #   odb08 (Transport)                    -> cpi-transportation
    #   odb09 (Recreation & culture)         -> cpi-recreation-and-culture
    #   odb10 (Education)                    -> cpi-education
    # All measured as 'Dec 2000 = 100' continuous index (mj38); YoY/MoM derivable.
    {"slug": "cpi-food", "dataset_id": "sp2038ms",
     "segments": [
         "2010,2011,2012,2013,2014,2015,2016,2017,2018,2019,2020,2021,2022,2023,2024,2025,2026",
         "all", "odb02", "mj38",
     ],
     "freq": "M", "unit": "Index (Dec 2000=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "SUSR sp2038ms CPI COICOP 01 Food & non-alc bev, Dec 2000=100 continuous"},
    {"slug": "cpi-clothing", "dataset_id": "sp2038ms",
     "segments": [
         "2010,2011,2012,2013,2014,2015,2016,2017,2018,2019,2020,2021,2022,2023,2024,2025,2026",
         "all", "odb04", "mj38",
     ],
     "freq": "M", "unit": "Index (Dec 2000=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "SUSR sp2038ms CPI COICOP 03 Clothing & footwear, Dec 2000=100 continuous"},
    {"slug": "cpi-housing-utilities", "dataset_id": "sp2038ms",
     "segments": [
         "2010,2011,2012,2013,2014,2015,2016,2017,2018,2019,2020,2021,2022,2023,2024,2025,2026",
         "all", "odb05", "mj38",
     ],
     "freq": "M", "unit": "Index (Dec 2000=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "SUSR sp2038ms CPI COICOP 04 Housing+utilities, Dec 2000=100 continuous"},
    {"slug": "cpi-transportation", "dataset_id": "sp2038ms",
     "segments": [
         "2010,2011,2012,2013,2014,2015,2016,2017,2018,2019,2020,2021,2022,2023,2024,2025,2026",
         "all", "odb08", "mj38",
     ],
     "freq": "M", "unit": "Index (Dec 2000=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "SUSR sp2038ms CPI COICOP 07 Transport, Dec 2000=100 continuous"},
    {"slug": "cpi-recreation-and-culture", "dataset_id": "sp2038ms",
     "segments": [
         "2010,2011,2012,2013,2014,2015,2016,2017,2018,2019,2020,2021,2022,2023,2024,2025,2026",
         "all", "odb09", "mj38",
     ],
     "freq": "M", "unit": "Index (Dec 2000=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "SUSR sp2038ms CPI COICOP 09 Recreation & culture, Dec 2000=100 continuous"},
    {"slug": "cpi-education", "dataset_id": "sp2038ms",
     "segments": [
         "2010,2011,2012,2013,2014,2015,2016,2017,2018,2019,2020,2021,2022,2023,2024,2025,2026",
         "all", "odb10", "mj38",
     ],
     "freq": "M", "unit": "Index (Dec 2000=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "SUSR sp2038ms CPI COICOP 10 Education, Dec 2000=100 continuous"},
    # pm0042ms industrial production YoY adjusted: NACE 05-09 = mining,
    # 10-33 = manufacturing.
    {"slug": "manufacturing-production", "dataset_id": "pm0042ms",
     "segments": ["all", "all", "SPECU_Y_ROMR", "10 - 33", "UNIT_INDEX", "U_PM_0001"],
     "freq": "M", "unit": "Index (same month previous year=100)", "adjustment": "WDA", "conversion": 1.0,
     "note": "SUSR pm0042ms Industrial production YoY adjusted, NACE 10-33 Manufacturing"},
    {"slug": "mining-production", "dataset_id": "pm0042ms",
     "segments": ["all", "all", "SPECU_Y_ROMR", "05 - 09", "UNIT_INDEX", "U_PM_0001"],
     "freq": "M", "unit": "Index (same month previous year=100)", "adjustment": "WDA", "conversion": 1.0,
     "note": "SUSR pm0042ms Industrial production YoY adjusted, NACE 05-09 Mining & quarrying"},
    # kp0022ms Economic Sentiment Indicator (monthly), dims: year, month, indic.
    # U_KP_0002 Industrial confidence indicator -> business-confidence
    # U_KP_0006 Consumer confidence indicator   -> consumer-confidence
    {"slug": "business-confidence", "dataset_id": "kp0022ms",
     "segments": ["all", "all", "U_KP_0002"],
     "freq": "M", "unit": "Balance (NSA)", "adjustment": "NSA", "conversion": 1.0,
     "note": "SUSR kp0022ms Industrial confidence indicator (Konjunktúra survey)"},
    {"slug": "consumer-confidence", "dataset_id": "kp0022ms",
     "segments": ["all", "all", "U_KP_0006"],
     "freq": "M", "unit": "Balance (NSA)", "adjustment": "NSA", "conversion": 1.0,
     "note": "SUSR kp0022ms Consumer confidence indicator (Konjunktúra survey)"},
    # pr2035qs Employed by NACE quarterly, dims: year, quarter, sex, nace.
    # poh01 (Total persons) × nace1a (Total NACE)
    {"slug": "employed-persons", "dataset_id": "pr2035qs",
     "segments": ["all", "all", "poh01", "nace1a"],
     "freq": "Q", "unit": "Thousand persons", "adjustment": "NSA", "conversion": 1.0,
     "note": "SUSR pr2035qs Employed LFS Total × NACE Total, quarterly, thousand persons"},
    # kz1018rs 'Economic activity rate' (yearly), dims: year, sex, age.
    # POHL1 (Total persons) × VEK01 (15-64) = LFP 15-64 %
    {"slug": "labor-force-participation-rate", "dataset_id": "kz1018rs",
     "segments": ["all", "POHL1", "VEK01"],
     "freq": "A", "unit": "%", "adjustment": "NSA", "conversion": 1.0,
     "note": "SUSR kz1018rs Economic activity rate Total 15-64, yearly %"},
    # om2019rs Population (yearly), dims: year, indicator. 08dem03 = Mid-year population.
    {"slug": "population", "dataset_id": "om2019rs",
     "segments": ["all", "08dem03"],
     "freq": "A", "unit": "Persons", "adjustment": "NSA", "conversion": 0.000001,
     "note": "SUSR om2019rs Mid-year population, yearly (converted to millions)"},
    # nu1807qs GDP by expenditure components, chain-linked volumes (2020), quarterly.
    # Dims: year, quarter, ukaz, mj. mj=MJ_CLV20_MEUR
    # U_NU_P31_S14 = HH final consumption -> consumer-spending
    # U_NU_P3_S13  = Final consumption of general government -> government-spending
    # U_NU_P51G    = Gross fixed capital formation -> GFCF
    # U_NU_P7      = Imports of goods and services -> imports (quarterly EUR)
    {"slug": "consumer-spending", "dataset_id": "nu1807qs",
     "segments": ["all", "all", "U_NU_P31_S14", "MJ_CLV20_MEUR"],
     "freq": "Q", "unit": "Million EUR (chain-linked, 2020 prices)", "adjustment": "NSA", "conversion": 1.0,
     "note": "SUSR nu1807qs HH final consumption, chain-linked volumes 2020, quarterly mEUR"},
    {"slug": "government-spending", "dataset_id": "nu1807qs",
     "segments": ["all", "all", "U_NU_P3_S13", "MJ_CLV20_MEUR"],
     "freq": "Q", "unit": "Million EUR (chain-linked, 2020 prices)", "adjustment": "NSA", "conversion": 1.0,
     "note": "SUSR nu1807qs General govt final consumption, chain-linked volumes 2020, mEUR"},
    {"slug": "gross-fixed-capital-formation", "dataset_id": "nu1807qs",
     "segments": ["all", "all", "U_NU_P51G", "MJ_CLV20_MEUR"],
     "freq": "Q", "unit": "Million EUR (chain-linked, 2020 prices)", "adjustment": "NSA", "conversion": 1.0,
     "note": "SUSR nu1807qs Gross fixed capital formation, chain-linked volumes 2020, mEUR"},
    # changes-in-inventories synthesised in fetch loop = P5 (Gross capital formation) - P51G.
    {"slug": "changes-in-inventories", "dataset_id": "nu1807qs_synthetic",
     "segments": [],
     "freq": "Q", "unit": "Million EUR (chain-linked, 2020 prices)", "adjustment": "NSA", "conversion": 1.0,
     "note": "SUSR nu1807qs P5-P51G (Gross capital formation minus GFCF), chain-linked volumes 2020"},
    # zo0001ms Foreign trade monthly. UKAZ01 = Import (level), MJ01 = mill EUR.
    {"slug": "imports", "dataset_id": "zo0001ms",
     "segments": ["all", "all", "UKAZ01", "MJ01"],
     "freq": "M", "unit": "Million EUR", "adjustment": "NSA", "conversion": 1.0,
     "note": "SUSR zo0001ms Foreign trade imports, monthly mEUR"},
    # nu2063qs Generation and use of income in sector of households (quarterly).
    # 03dd13 = Gross disposable income, mj00 = Mill EUR.
    {"slug": "disposable-personal-income", "dataset_id": "nu2063qs",
     "segments": ["all", "all", "03dd13", "mj00"],
     "freq": "Q", "unit": "EUR Million", "adjustment": "NSA", "conversion": 1.0,
     "note": "SUSR nu2063qs Household gross disposable income, quarterly mEUR (current prices)"},
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
    elif freq == "A":
        # Annual datasets have no period dim — use a synthetic single-period axis.
        period_pos = None
        period_kind = "A"
    else:
        period_pos = next((i for i, k in enumerate(dim_ids) if "mes" in k.lower() or "month" in k.lower()), None)
        period_kind = "M"
    if year_pos is None:
        return []
    if period_kind != "A" and period_pos is None:
        return []
    year_idx = js["dimension"][dim_ids[year_pos]]["category"]["index"]
    if isinstance(year_idx, dict):
        year_pairs = list(year_idx.items())
    else:
        year_pairs = [(c, i) for i, c in enumerate(year_idx)]
    if period_kind == "A":
        period_pairs = [("0", 0)]
    else:
        period_idx = js["dimension"][dim_ids[period_pos]]["category"]["index"]
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
            elif period_kind == "A":
                month = 1
            else:
                if pn < 1 or pn > 12:
                    continue
                month = pn
            indices = [0] * len(dim_ids)
            indices[year_pos] = ypos
            if period_kind != "A":
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

#
# === Stage-2 additions (2026-05-15) ===
# DF_CPI = HICP (Eurostat-formatted, base 2025=100, monthly) — used for COICOP
# sub-components which match TE exactly. Keys are ".M.MT.2025.<ITEM>" using
# the 5 trailing optional dims; SDMX allows leaving dims blank.
# DF_NA_NAMQ10GDP = quarterly NA aggregates (ESA2010, EUR thousands). Codes:
#   B1GQ chained vol NSA = gdp-real; P31_S14_W0 chained vol NSA = consumer-spending;
#   P3_S13 chained vol NSA = government-spending; P51G current EUR = gfcf;
#   P52 current EUR = changes-in-inventories.
# DF_ITGS_A_HS / D_HS = monthly merchandise trade, sum across PRODUCT codes
#   (no pre-aggregated total); FLOW=M (arrivals=imports), FLOW=X (dispatches=exports).
# DF_TOT_POP_BY_SEX_SINGLE_YEARS_AGE = annual pop; sum across ages for sex=T.
# DF_LABOUR_STATUS_FOR_PERSONS_AGED_15_PLUSS_YEARS = LFS quarterly stocks; codes
#   LSEMP/LSUNEMP/LSPOP by CSE_SEX (T/M/F). TE unemployment-rate = LSUNEMP/labour-force.

MT_SERIES = [
    # CPI sub-components — HICP via DF_CPI, base 2025=100. Source: NSO Malta.
    # Keys are M.MT.2025.<ITEM>. Verified vs TE 2026-05-15: all 6 match exactly.
    {"slug": "inflation-cpi", "dataflow": "DF_RETAIL_PRICE_INDEX_MONTHLY",
     "key": "CC00000.M", "freq": "M",
     "unit": "Index (2015=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "NSO Malta DF_RETAIL_PRICE_INDEX_MONTHLY total RPI (CC00000)"},
    {"slug": "cpi-clothing", "dataflow": "DF_CPI",
     "key": "M.MT.2025.CP03", "freq": "M",
     "unit": "Index (2025=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "NSO Malta DF_CPI HICP CP03 Clothing & footwear, base 2025=100"},
    {"slug": "cpi-education", "dataflow": "DF_CPI",
     "key": "M.MT.2025.CP10", "freq": "M",
     "unit": "Index (2025=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "NSO Malta DF_CPI HICP CP10 Education, base 2025=100"},
    {"slug": "cpi-food", "dataflow": "DF_CPI",
     "key": "M.MT.2025.CP01", "freq": "M",
     "unit": "Index (2025=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "NSO Malta DF_CPI HICP CP01 Food & non-alc bev, base 2025=100"},
    {"slug": "cpi-housing-utilities", "dataflow": "DF_CPI",
     "key": "M.MT.2025.CP04", "freq": "M",
     "unit": "Index (2025=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "NSO Malta DF_CPI HICP CP04 Housing/water/electricity/gas, base 2025=100"},
    {"slug": "cpi-recreation-and-culture", "dataflow": "DF_CPI",
     "key": "M.MT.2025.CP09", "freq": "M",
     "unit": "Index (2025=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "NSO Malta DF_CPI HICP CP09 Recreation & culture, base 2025=100"},
    {"slug": "cpi-transportation", "dataflow": "DF_CPI",
     "key": "M.MT.2025.CP07", "freq": "M",
     "unit": "Index (2025=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "NSO Malta DF_CPI HICP CP07 Transport, base 2025=100"},

    # National Accounts quarterly (ESA2010) — EUR thousands → mln EUR (×0.001).
    # Verified Q4 2025: gov-spending L,N = 945,269.654 (TE 945,270); gfcf V,N =
    # 1,140,869.43 (TE 1,140,869); consumer-spending L,N = 2,246,723.08 (TE
    # 2,246,723); changes-in-inventories P52 V,N = 42,971.998.
    {"slug": "consumer-spending", "dataflow": "DF_NA_NAMQ10GDP",
     "key": "Q.P31_S14_W0.L.N.EUR.", "freq": "Q",
     "unit": "Million EUR (chain-linked, NSA)", "adjustment": "NSA", "conversion": 0.001,
     "note": "NSO Malta DF_NA_NAMQ10GDP P31_S14_W0 households+NPISH chained vol NSA"},
    {"slug": "government-spending", "dataflow": "DF_NA_NAMQ10GDP",
     "key": "Q.P3_S13.L.N.EUR.", "freq": "Q",
     "unit": "Million EUR (chain-linked, NSA)", "adjustment": "NSA", "conversion": 0.001,
     "note": "NSO Malta DF_NA_NAMQ10GDP P3_S13 general government chained vol NSA"},
    {"slug": "gross-fixed-capital-formation", "dataflow": "DF_NA_NAMQ10GDP",
     "key": "Q.P51G.V.N.EUR.", "freq": "Q",
     "unit": "Million EUR (current, NSA)", "adjustment": "NSA", "conversion": 0.001,
     "note": "NSO Malta DF_NA_NAMQ10GDP P51G gross fixed capital formation current NSA"},
    {"slug": "changes-in-inventories", "dataflow": "DF_NA_NAMQ10GDP",
     "key": "Q.P52.V.N.EUR.", "freq": "Q",
     "unit": "Million EUR (current, NSA)", "adjustment": "NSA", "conversion": 0.001,
     "note": "NSO Malta DF_NA_NAMQ10GDP P52 changes in inventories current NSA"},
    {"slug": "gdp-real", "dataflow": "DF_NA_NAMQ10GDP",
     "key": "Q.B1GQ.L.Y.EUR.", "freq": "Q",
     "unit": "Million EUR (chain-linked, SA)", "adjustment": "SA", "conversion": 0.001,
     "note": "NSO Malta DF_NA_NAMQ10GDP B1GQ GDP chained vol working-day & seasonally adjusted"},

    # Trade — merchandise monthly, sum across HS products (no pre-aggregated total).
    # DF_ITGS_D_HS = dispatches (exports), DF_ITGS_A_HS = arrivals (imports).
    # EUR raw values → divide by 1000 for thousand EUR (TE unit).
    {"slug": "exports", "dataflow": "DF_ITGS_D_HS",
     "key": "M..X.", "freq": "M",
     "unit": "Thousand EUR", "adjustment": "NSA", "conversion": 0.001,
     "aggregate": "sum_product",
     "note": "NSO Malta DF_ITGS_D_HS dispatches (exports), sum across HS products"},
    {"slug": "imports", "dataflow": "DF_ITGS_A_HS",
     "key": "M..M.", "freq": "M",
     "unit": "Thousand EUR", "adjustment": "NSA", "conversion": 0.001,
     "aggregate": "sum_product",
     "note": "NSO Malta DF_ITGS_A_HS arrivals (imports), sum across HS products"},
    # Trade balance = exports − imports, derived in dispatcher.
    {"slug": "trade-balance", "dataflow": "DF_ITGS_X_MINUS_M",
     "key": "derived", "freq": "M",
     "unit": "Thousand EUR", "adjustment": "NSA", "conversion": 1.0,
     "derive": "mt_trade_balance",
     "note": "NSO Malta DF_ITGS_D_HS − DF_ITGS_A_HS (exports − imports), thousand EUR"},

    # Population — annual total: sum across ages for sex='T' (Total).
    {"slug": "population", "dataflow": "DF_TOT_POP_BY_SEX_SINGLE_YEARS_AGE",
     "key": "T..A", "freq": "A",
     "unit": "Persons", "adjustment": "NSA", "conversion": 0.000001,
     "aggregate": "sum_product",
     "note": "NSO Malta DF_TOT_POP_BY_SEX_SINGLE_YEARS_AGE sex=Total, sum across single-year ages (Million)"},

    # Unemployment rate — LFS LSUNEMP+LSEMP summed M+F (no Total code). Derived in fetcher.
    # Uses canonical slug `unemployment` (te_slug=unemployment-rate).
    {"slug": "unemployment", "dataflow": "DF_LABOUR_STATUS_FOR_PERSONS_AGED_15_PLUSS_YEARS",
     "key": "..Q", "freq": "Q",
     "unit": "%", "adjustment": "NSA", "conversion": 1.0,
     "derive": "lfs_unemp_rate",
     "note": "NSO Malta LFS unemployment rate = LSUNEMP/(LSEMP+LSUNEMP) summed M+F"},
    # Employed persons — LSEMP summed across CSE_SEX (M+F) since dataflow has no
    # Total code. Use aggregate=sum_product.
    {"slug": "employed-persons", "dataflow": "DF_LABOUR_STATUS_FOR_PERSONS_AGED_15_PLUSS_YEARS",
     "key": "LSEMP..Q", "freq": "Q",
     "unit": "Thousand persons", "adjustment": "NSA", "conversion": 0.001,
     "aggregate": "sum_product",
     "note": "NSO Malta LFS LSEMP summed M+F sex (Total), converted to thousands"},
]


def fetch_mt_sdmx(dataflow: str, key: str, freq: str = "M",
                  aggregate: str | None = None) -> list[tuple[date, float]]:
    """Fetch SDMX-CSV from NSO Malta. Returns sorted [(date, value)].

    aggregate='sum_product' sums OBS_VALUE across all rows sharing the same
    TIME_PERIOD (used when the dataflow lacks a pre-aggregated total — e.g.
    DF_ITGS_*_HS sums across PRODUCT codes; DF_TOT_POP sums across ages).
    """
    if _CF_SCRAPER is None:
        raise RuntimeError("cloudscraper not installed; required for nso.gov.mt")
    url = f"https://apidesign-statdb.nso.gov.mt/rest/data/{dataflow}/{key}"
    headers = {"Accept": "application/vnd.sdmx.data+csv;version=1.0.0"}
    r = _CF_SCRAPER.get(url, headers=headers, timeout=60)
    r.raise_for_status()
    lines = r.text.strip().splitlines()
    if not lines:
        return []
    header = [h.strip() for h in lines[0].split(",")]
    try:
        time_idx = header.index("TIME_PERIOD")
        val_idx = header.index("OBS_VALUE")
    except ValueError:
        return []
    if aggregate == "sum_product":
        sums: dict[str, float] = {}
        for line in lines[1:]:
            parts = line.split(",")
            if len(parts) <= max(time_idx, val_idx):
                continue
            try:
                v = float(parts[val_idx].strip())
            except ValueError:
                continue
            sums[parts[time_idx].strip()] = sums.get(parts[time_idx].strip(), 0.0) + v
        out = []
        for period, total in sums.items():
            dt = _parse_period(period, freq)
            if dt:
                out.append((dt, total))
        return sorted(out)

    out = []
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


def fetch_mt_lfs_unemp_rate() -> list[tuple[date, float]]:
    """Derive MT unemployment rate from DF_LABOUR_STATUS — LSUNEMP / (LSEMP+LSUNEMP).
    The dataflow only carries CSE_SEX in {M, F}; we sum both for the Total rate.
    Returns sorted [(date, rate_pct)]."""
    if _CF_SCRAPER is None:
        raise RuntimeError("cloudscraper not installed; required for nso.gov.mt")
    url = ("https://apidesign-statdb.nso.gov.mt/rest/data/"
           "DF_LABOUR_STATUS_FOR_PERSONS_AGED_15_PLUSS_YEARS/..Q")
    r = _CF_SCRAPER.get(url, headers={"Accept": "application/vnd.sdmx.data+csv;version=1.0.0"},
                        timeout=60)
    r.raise_for_status()
    lines = r.text.strip().splitlines()
    if not lines:
        return []
    header = [h.strip() for h in lines[0].split(",")]
    try:
        status_idx = header.index("CSE_LABOUR_STATUS")
        time_idx = header.index("TIME_PERIOD")
        val_idx = header.index("OBS_VALUE")
    except ValueError:
        return []
    emp: dict[str, float] = {}
    unemp: dict[str, float] = {}
    for line in lines[1:]:
        parts = line.split(",")
        if len(parts) <= max(status_idx, time_idx, val_idx):
            continue
        try:
            v = float(parts[val_idx].strip())
        except ValueError:
            continue
        period = parts[time_idx].strip()
        status = parts[status_idx].strip()
        if status == "LSEMP":
            emp[period] = emp.get(period, 0.0) + v
        elif status == "LSUNEMP":
            unemp[period] = unemp.get(period, 0.0) + v
    out = []
    for period in sorted(set(emp.keys()) & set(unemp.keys())):
        lf = emp[period] + unemp[period]
        if lf <= 0:
            continue
        rate = 100.0 * unemp[period] / lf
        dt = _parse_period(period, "Q")
        if dt:
            out.append((dt, rate))
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

    # === Stage-2 additions (2026-05-15) — generic PxWeb tables. ===
    # CPI subcategories (base 2025=100, COICOP18) — table 0410070E.
    # Verified 2026-05-15: cpi-clothing CP03 2026M04 = 98.76 (TE 98.76);
    # cpi-transportation CP07 2026M04 = 108.87 (TE 108.87); cpi-food CP01 = 104.62;
    # cpi-housing-utilities CP04 = 101.64; cpi-recreation CP09 = 102.74;
    # cpi-education CP10 = 102.58.
    {"slug": "cpi-clothing",
     "px_path": "8.CYSTAT-DB/Price Indices/Consumer Price Index/0410070E.px",
     "pxweb_query": {"COICOP18": ["CP03"], "INDICATOR": ["0"]},
     "time_dim": "MONTH", "freq": "M",
     "unit": "Index (2025=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "CYSTAT 0410070E CPI by main categories CP03 Clothing & footwear, 2025=100"},
    {"slug": "cpi-education",
     "px_path": "8.CYSTAT-DB/Price Indices/Consumer Price Index/0410070E.px",
     "pxweb_query": {"COICOP18": ["CP10"], "INDICATOR": ["0"]},
     "time_dim": "MONTH", "freq": "M",
     "unit": "Index (2025=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "CYSTAT 0410070E CPI by main categories CP10 Education services, 2025=100"},
    {"slug": "cpi-food",
     "px_path": "8.CYSTAT-DB/Price Indices/Consumer Price Index/0410070E.px",
     "pxweb_query": {"COICOP18": ["CP01"], "INDICATOR": ["0"]},
     "time_dim": "MONTH", "freq": "M",
     "unit": "Index (2025=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "CYSTAT 0410070E CPI by main categories CP01 Food & non-alc bev, 2025=100"},
    {"slug": "cpi-housing-utilities",
     "px_path": "8.CYSTAT-DB/Price Indices/Consumer Price Index/0410070E.px",
     "pxweb_query": {"COICOP18": ["CP04"], "INDICATOR": ["0"]},
     "time_dim": "MONTH", "freq": "M",
     "unit": "Index (2025=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "CYSTAT 0410070E CPI by main categories CP04 Housing/water/electricity/gas, 2025=100"},
    {"slug": "cpi-recreation-and-culture",
     "px_path": "8.CYSTAT-DB/Price Indices/Consumer Price Index/0410070E.px",
     "pxweb_query": {"COICOP18": ["CP09"], "INDICATOR": ["0"]},
     "time_dim": "MONTH", "freq": "M",
     "unit": "Index (2025=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "CYSTAT 0410070E CPI by main categories CP09 Recreation, sport & culture, 2025=100"},
    {"slug": "cpi-transportation",
     "px_path": "8.CYSTAT-DB/Price Indices/Consumer Price Index/0410070E.px",
     "pxweb_query": {"COICOP18": ["CP07"], "INDICATOR": ["0"]},
     "time_dim": "MONTH", "freq": "M",
     "unit": "Index (2025=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "CYSTAT 0410070E CPI by main categories CP07 Transport, 2025=100"},

    # Industrial production — timeseries table 0210045E, base 2021=100. Latest
    # 2026M02 = 108.4. Single INDEX selection = '0' (Index-Monthly).
    {"slug": "industrial-production",
     "px_path": "8.CYSTAT-DB/Industry/Index of Industrial Production/0210045E.px",
     "pxweb_query": {"INDEX": ["0"]},
     "time_dim": "MONTH", "freq": "M",
     "unit": "Index (2021=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "CYSTAT 0210045E IP total index, base 2021=100, monthly"},

    # PPI — Industrial Output Prices timeseries 0230015E, base 2021=100. Latest
    # 2026M03 = 121.0 (TE 121.0 for 2026-02 — TE values lag by one release).
    {"slug": "ppi",
     "px_path": "8.CYSTAT-DB/Industry/Industrial Output Prices Index/0230015E.px",
     "pxweb_query": {"INDEX": ["0"]},
     "time_dim": "MONTH", "freq": "M",
     "unit": "Index (2021=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "CYSTAT 0230015E PPI total industry, base 2021=100, monthly"},

    # Foreign Trade Summary — table 1000010E monthly, partner=Total, goods=Total.
    # Latest 2026M03: imports 1,210,707; exports 506,861; trade balance −703,846
    # (Thousand euro). Conversion ÷1000 → Million EUR.
    {"slug": "imports",
     "px_path": "8.CYSTAT-DB/External Trade/1000010E.px",
     "pxweb_query": {"MEASURE": ["0"], "REFERENCE PEIROD": ["0"], "TYPE OF GOODS": ["0"],
                     "PARTNER COUNTRY": ["0"], "TYPE OF TRADE": ["0"]},
     "time_dim": "MONTH", "freq": "M",
     "unit": "Million EUR", "adjustment": "NSA", "conversion": 0.001,
     "note": "CYSTAT 1000010E foreign trade summary, monthly imports c.i.f. total goods/partners (thousand EUR → mln)"},
    {"slug": "exports",
     "px_path": "8.CYSTAT-DB/External Trade/1000010E.px",
     "pxweb_query": {"MEASURE": ["0"], "REFERENCE PEIROD": ["0"], "TYPE OF GOODS": ["0"],
                     "PARTNER COUNTRY": ["0"], "TYPE OF TRADE": ["1"]},
     "time_dim": "MONTH", "freq": "M",
     "unit": "Million EUR", "adjustment": "NSA", "conversion": 0.001,
     "note": "CYSTAT 1000010E foreign trade summary, monthly exports f.o.b. total goods/partners (thousand EUR → mln)"},
    {"slug": "trade-balance",
     "px_path": "8.CYSTAT-DB/External Trade/1000010E.px",
     "pxweb_query": {"MEASURE": ["0"], "REFERENCE PEIROD": ["0"], "TYPE OF GOODS": ["0"],
                     "PARTNER COUNTRY": ["0"], "TYPE OF TRADE": ["2"]},
     "time_dim": "MONTH", "freq": "M",
     "unit": "Million EUR", "adjustment": "NSA", "conversion": 0.001,
     "note": "CYSTAT 1000010E foreign trade summary, monthly net trade balance (thousand EUR → mln)"},

    # Quarterly NA expenditure approach — table 0620020E. Measure 1 (Real
    # terms), TYPE OF DATA 1 (SA/WDA). Q4 2025 SA: consumer 4490.2; gov 1298.3;
    # gfcf 1570.3 (TE: 4559.4 / 1325.7 / 1566.9 — small revision lag).
    {"slug": "consumer-spending",
     "px_path": "8.CYSTAT-DB/National Accounts/Quarterly National Accounts/0620020E.px",
     "pxweb_query": {"MEASURE": ["1"], "TYPE OF DATA": ["1"], "NA AGGREGATE": ["2"]},
     "time_dim": "QUARTER", "freq": "Q",
     "unit": "Million EUR (chain-linked, SA)", "adjustment": "SA", "conversion": 1.0,
     "note": "CYSTAT 0620020E P31 households+NPISH real terms working-day & seasonally adjusted"},
    {"slug": "government-spending",
     "px_path": "8.CYSTAT-DB/National Accounts/Quarterly National Accounts/0620020E.px",
     "pxweb_query": {"MEASURE": ["1"], "TYPE OF DATA": ["1"], "NA AGGREGATE": ["5"]},
     "time_dim": "QUARTER", "freq": "Q",
     "unit": "Million EUR (chain-linked, SA)", "adjustment": "SA", "conversion": 1.0,
     "note": "CYSTAT 0620020E P3 general government real terms working-day & seasonally adjusted"},
    {"slug": "gross-fixed-capital-formation",
     "px_path": "8.CYSTAT-DB/National Accounts/Quarterly National Accounts/0620020E.px",
     "pxweb_query": {"MEASURE": ["1"], "TYPE OF DATA": ["1"], "NA AGGREGATE": ["10"]},
     "time_dim": "QUARTER", "freq": "Q",
     "unit": "Million EUR (chain-linked, SA)", "adjustment": "SA", "conversion": 1.0,
     "note": "CYSTAT 0620020E P51G gross fixed capital formation real terms WDA & SA"},
    # Changes in inventories — only Current prices NSA exposed (Measure 0).
    {"slug": "changes-in-inventories",
     "px_path": "8.CYSTAT-DB/National Accounts/Quarterly National Accounts/0620020E.px",
     "pxweb_query": {"MEASURE": ["0"], "TYPE OF DATA": ["0"], "NA AGGREGATE": ["20"]},
     "time_dim": "QUARTER", "freq": "Q",
     "unit": "Million EUR (current, NSA)", "adjustment": "NSA", "conversion": 1.0,
     "note": "CYSTAT 0620020E P52 changes in inventories current prices NSA"},
    # GDP-real — B1GQ real-terms NSA (TE doesn't specify adjustment; matches Eurostat real).
    {"slug": "gdp-real",
     "px_path": "8.CYSTAT-DB/National Accounts/Quarterly National Accounts/0620020E.px",
     "pxweb_query": {"MEASURE": ["1"], "TYPE OF DATA": ["1"], "NA AGGREGATE": ["0"]},
     "time_dim": "QUARTER", "freq": "Q",
     "unit": "Million EUR (chain-linked, SA)", "adjustment": "SA", "conversion": 1.0,
     "note": "CYSTAT 0620020E B1GQ GDP real terms working-day & seasonally adjusted"},

    # LFS — unemployment-rate INDICATOR=53 'Unemployment 15+' MEASURE=1 (Percentage),
    # SEX=0 (Total). Q4 2025 = 4.0% (TE inventory has no unemployment-rate slug for
    # CY but the rate is widely published). Employed-persons INDICATOR=32 SEX=0 Number.
    {"slug": "unemployment",
     "px_path": "8.CYSTAT-DB/Labour Market/Labour Force Survey/0110010E.px",
     "pxweb_query": {"INDICATOR": ["53"], "MEASURE": ["1"], "SEX": ["0"]},
     "time_dim": "QUARTER", "freq": "Q",
     "unit": "%", "adjustment": "NSA", "conversion": 1.0,
     "note": "CYSTAT 0110010E LFS unemployment rate 15+ total (Eurostat-comparable concept)"},
    {"slug": "employed-persons",
     "px_path": "8.CYSTAT-DB/Labour Market/Labour Force Survey/0110010E.px",
     "pxweb_query": {"INDICATOR": ["32"], "MEASURE": ["0"], "SEX": ["0"]},
     "time_dim": "QUARTER", "freq": "Q",
     "unit": "Thousand persons", "adjustment": "NSA", "conversion": 0.001,
     "note": "CYSTAT 0110010E LFS employed persons 15+ total (Number, converted to thousands)"},
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


def fetch_cy_pxweb_generic(px_path: str, pxweb_query: dict, time_dim: str,
                           freq: str = "M") -> list[tuple[date, float]]:
    """Generic CYSTAT PxWeb fetcher. `pxweb_query` is a dict {dim_code: [values]}.
    The fetcher POSTs filter='item' with the listed value codes, then parses the
    returned json-stat2 dataset along `time_dim` (MONTH or QUARTER). All other
    dims must be reduced to a single value by `pxweb_query` for an unambiguous
    1-D timeseries. Returns sorted [(date, value)].
    """
    if _CF_SCRAPER is None:
        raise RuntimeError("cloudscraper not installed; required for cystat.gov.cy")
    url = f"https://cystatdb.cystat.gov.cy/api/v1/en/{px_path}"
    body = {
        "query": [
            {"code": code, "selection": {"filter": "item", "values": vals}}
            for code, vals in pxweb_query.items()
        ],
        "response": {"format": "json-stat2"},
    }
    # Small retry loop with exponential backoff — CYSTAT throws 429 on
    # consecutive POSTs to the same .px endpoint.
    r = None
    for attempt in range(5):
        r = _CF_SCRAPER.post(url, json=body, timeout=60)
        if r.status_code == 429:
            time.sleep(2 ** attempt)  # 1, 2, 4, 8, 16 s
            continue
        break
    r.raise_for_status()
    j = r.json()
    values = j.get("value", [])
    dim_ids = j.get("id", [])
    sizes = j.get("size", [])
    dim = j.get("dimension", {})
    if time_dim not in dim or not values:
        return []

    t_cat = dim[time_dim]["category"]
    t_idx = t_cat.get("index", {})
    t_lbl = t_cat.get("label", {})
    if isinstance(t_idx, dict):
        t_pairs = sorted(t_idx.items(), key=lambda x: x[1])
    else:
        t_pairs = [(c, i) for i, c in enumerate(t_idx)]

    time_pos = dim_ids.index(time_dim)
    # For all other dims, default to position 0 (single-value selection).
    out = []
    for tcode, tpos in t_pairs:
        indices = [0] * len(dim_ids)
        indices[time_pos] = tpos
        flat = 0
        stride = 1
        for i in range(len(dim_ids) - 1, -1, -1):
            flat += indices[i] * stride
            stride *= sizes[i]
        if not (0 <= flat < len(values)):
            continue
        v = values[flat]
        if v is None:
            continue
        label = t_lbl.get(tcode, tcode)  # MONTH "2026M04" or QUARTER "2025Q4"
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
    # --- CPI sub-indices (ECOICOP v2) — ME_PS09 Indikatori=4 (index 2025=100)
    # Verified 2026-05-14 against TE: food 01 2026M02 = 101.1 ≈ TE 101.2.
    {"slug": "cpi-clothing",
     "path": "Cijene/Indeksi potrošačkih cijena/Indeksi potrošačkih cijena – ECOICOP, ver. 2/ME_PS09.px",
     "query": {"ECOICOP, ver. 2": "03", "Indikatori": "4"},
     "freq": "M", "parse": "tid",
     "unit": "Index (2025=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "DZS Croatia ME_PS09 CPI sub-index Clothing & footwear (COICOP 03), 2025=100"},
    {"slug": "cpi-education",
     "path": "Cijene/Indeksi potrošačkih cijena/Indeksi potrošačkih cijena – ECOICOP, ver. 2/ME_PS09.px",
     "query": {"ECOICOP, ver. 2": "10", "Indikatori": "4"},
     "freq": "M", "parse": "tid",
     "unit": "Index (2025=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "DZS Croatia ME_PS09 CPI sub-index Education (COICOP 10), 2025=100"},
    {"slug": "cpi-food",
     "path": "Cijene/Indeksi potrošačkih cijena/Indeksi potrošačkih cijena – ECOICOP, ver. 2/ME_PS09.px",
     "query": {"ECOICOP, ver. 2": "01", "Indikatori": "4"},
     "freq": "M", "parse": "tid",
     "unit": "Index (2025=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "DZS Croatia ME_PS09 CPI sub-index Food & non-alc bevs (COICOP 01), 2025=100"},
    {"slug": "cpi-housing-utilities",
     "path": "Cijene/Indeksi potrošačkih cijena/Indeksi potrošačkih cijena – ECOICOP, ver. 2/ME_PS09.px",
     "query": {"ECOICOP, ver. 2": "04", "Indikatori": "4"},
     "freq": "M", "parse": "tid",
     "unit": "Index (2025=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "DZS Croatia ME_PS09 CPI sub-index Housing, water, electricity (COICOP 04), 2025=100"},
    {"slug": "cpi-recreation-and-culture",
     "path": "Cijene/Indeksi potrošačkih cijena/Indeksi potrošačkih cijena – ECOICOP, ver. 2/ME_PS09.px",
     "query": {"ECOICOP, ver. 2": "09", "Indikatori": "4"},
     "freq": "M", "parse": "tid",
     "unit": "Index (2025=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "DZS Croatia ME_PS09 CPI sub-index Recreation & culture (COICOP 09), 2025=100"},
    {"slug": "cpi-transportation",
     "path": "Cijene/Indeksi potrošačkih cijena/Indeksi potrošačkih cijena – ECOICOP, ver. 2/ME_PS09.px",
     "query": {"ECOICOP, ver. 2": "07", "Indikatori": "4"},
     "freq": "M", "parse": "tid",
     "unit": "Index (2025=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "DZS Croatia ME_PS09 CPI sub-index Transport (COICOP 07), 2025=100. Re-audit 2026-05-17 TE 112.9."},
    # food-inflation = ME_PS09 Indikatori=1 (YoY % rate). Verified 2026M03 = 3.3% matches TE 3.3.
    {"slug": "food-inflation",
     "path": "Cijene/Indeksi potrošačkih cijena/Indeksi potrošačkih cijena – ECOICOP, ver. 2/ME_PS09.px",
     "query": {"ECOICOP, ver. 2": "01", "Indikatori": "1"},
     "freq": "M", "parse": "tid",
     "unit": "% YoY", "adjustment": "NSA", "conversion": 1.0,
     "note": "DZS Croatia ME_PS09 CPI Food YoY % rate of change"},
    # --- National accounts expenditure components (BDP-T01_EUR, Način=2 constant ref-2021 prices)
    # Verified 2026-05-14 against TE: consumer-spending Q4/25=10510 matches TE 10510 exactly.
    # changes-in-inventories has no data at Način=2; use Način=1 current prices.
    {"slug": "consumer-spending",
     "path": "Nacionalni racuni/BDP/Kvartalni nacionalni računi/BDP-T01_EUR.px",
     "query": {"Pokazatelj": "P31_S14", "Način prikaza": "2"},
     "freq": "Q", "parse": "hr_year_quarter",
     "unit": "Million EUR (constant 2021 prices)", "adjustment": "NSA", "conversion": 1.0,
     "note": "DZS Croatia BDP-T01_EUR P31_S14 Household final consumption (constant ref 2021, mln EUR)"},
    {"slug": "government-spending",
     "path": "Nacionalni racuni/BDP/Kvartalni nacionalni računi/BDP-T01_EUR.px",
     "query": {"Pokazatelj": "P3_S13", "Način prikaza": "2"},
     "freq": "Q", "parse": "hr_year_quarter",
     "unit": "Million EUR (constant 2021 prices)", "adjustment": "NSA", "conversion": 1.0,
     "note": "DZS Croatia BDP-T01_EUR P3_S13 Government final consumption (constant ref 2021, mln EUR)"},
    {"slug": "gross-fixed-capital-formation",
     "path": "Nacionalni racuni/BDP/Kvartalni nacionalni računi/BDP-T01_EUR.px",
     "query": {"Pokazatelj": "P51G", "Način prikaza": "2"},
     "freq": "Q", "parse": "hr_year_quarter",
     "unit": "Million EUR (constant 2021 prices)", "adjustment": "NSA", "conversion": 1.0,
     "note": "DZS Croatia BDP-T01_EUR P51G Gross fixed capital formation (constant ref 2021, mln EUR)"},
    {"slug": "changes-in-inventories",
     "path": "Nacionalni racuni/BDP/Kvartalni nacionalni računi/BDP-T01_EUR.px",
     "query": {"Pokazatelj": "P5M", "Način prikaza": "1"},
     "freq": "Q", "parse": "hr_year_quarter",
     "unit": "Million EUR (current prices)", "adjustment": "NSA", "conversion": 1.0,
     "note": "DZS Croatia BDP-T01_EUR P5M Changes in inventories + valuables (current prices, mln EUR)"},
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
                sid = cfg.get("series_id") or f"SCB/{cfg['path']}"
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"], country="SE",
                        date=normalize_date(dt, cfg["freq"]),
                        value=round(v * cfg["conversion"], 4),
                        source="scb_se", unit=cfg["unit"],
                        series_id=sid,
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
                sid = cfg.get("series_id") or f"CSP/{cfg['path'].rsplit('/',1)[-1]}"
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"], country="LV",
                        date=normalize_date(dt, cfg["freq"]),
                        value=round(v * cfg["conversion"], 4),
                        source="csp_lv", unit=cfg["unit"],
                        series_id=sid,
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
                sid = cfg.get("series_id") or f"STATEE/{table_id}"
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"], country="EE",
                        date=normalize_date(dt, eff_freq),
                        value=round(v * cfg["conversion"], 4),
                        source="stat_ee", unit=cfg["unit"],
                        series_id=sid,
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
                parser = cfg.get("parser")
                if cfg["table"] == "kkr_synthetic":
                    pairs = fetch_hu_trade_balance()
                elif parser == "mun0159_count":
                    pairs = fetch_hu_mun0159_count(cfg["value_col_index"])
                elif parser == "mun0099_rolling":
                    pairs = fetch_hu_mun0099_rolling(cfg["value_col_index"])
                elif parser == "nep0001_annual":
                    pairs = fetch_hu_nep0001_annual(cfg["row_index"])
                elif cfg.get("row_oriented"):
                    pairs = fetch_hu_stadat_row(
                        cfg["table"], cfg["row_index"],
                        cfg.get("n_years", 5), cfg.get("start_year", 2022),
                        section=cfg.get("section", "ara"),
                    )
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
                if cfg["dataset_id"] == "nu1807qs_synthetic":
                    # changes-in-inventories = Gross capital formation (P5) - GFCF (P51G).
                    p5 = dict(fetch_sk_datacube(
                        "nu1807qs", ["all", "all", "U_NU_P5", "MJ_CLV20_MEUR"], "Q",
                    ))
                    p51g = dict(fetch_sk_datacube(
                        "nu1807qs", ["all", "all", "U_NU_P51G", "MJ_CLV20_MEUR"], "Q",
                    ))
                    pairs = [
                        (dt, p5[dt] - p51g[dt])
                        for dt in sorted(set(p5.keys()) & set(p51g.keys()))
                    ]
                else:
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
                    cfg["freq"], cfg.get("row_filter"),
                )
                sid = cfg.get("series_id") or f"INSSE/{cfg['matrix']}"
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"], country="RO",
                        date=normalize_date(dt, cfg["freq"]),
                        value=round(v * cfg["conversion"], 4),
                        source="insse_ro", unit=cfg["unit"],
                        series_id=sid,
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
                    cfg["freq"], cfg.get("row_filter"),
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
                if cfg.get("derive") == "lfs_unemp_rate":
                    pairs = fetch_mt_lfs_unemp_rate()
                elif cfg.get("derive") == "mt_trade_balance":
                    # Compute exports − imports per month, in thousand EUR
                    exp = dict(fetch_mt_sdmx("DF_ITGS_D_HS", "M..X.", "M", aggregate="sum_product"))
                    imp = dict(fetch_mt_sdmx("DF_ITGS_A_HS", "M..M.", "M", aggregate="sum_product"))
                    pairs = []
                    for dt in sorted(set(exp.keys()) & set(imp.keys())):
                        pairs.append((dt, (exp[dt] - imp[dt]) * 0.001))
                else:
                    pairs = fetch_mt_sdmx(cfg["dataflow"], cfg["key"], cfg["freq"],
                                          aggregate=cfg.get("aggregate"))
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
                if "pxweb_query" in cfg:
                    pairs = fetch_cy_pxweb_generic(
                        cfg["px_path"], cfg["pxweb_query"], cfg["time_dim"], cfg["freq"])
                    sid_tail = "/".join(sorted(cfg["pxweb_query"].keys()))
                    series_id = f"CYSTAT/{cfg['px_path'].rsplit('/',1)[-1]}/{sid_tail}"
                else:
                    pairs = fetch_cy_pxweb(cfg["px_path"], cfg["base_year"], cfg["freq"])
                    series_id = f"CYSTAT/{cfg['px_path'].rsplit('/',1)[-1]}/B{cfg['base_year']}"
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"], country="CY",
                        date=normalize_date(dt, cfg["freq"]),
                        value=round(v * cfg["conversion"], 4),
                        source="cystat_cy", unit=cfg["unit"],
                        series_id=series_id,
                        adjustment=cfg["adjustment"],
                    ))
                print(f"  OK {cfg['slug']}/CY ({cfg['px_path'][-30:]}): {len(pairs)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['slug']}/CY: {e}")
            # CYSTAT rate-limits aggressively on same-path POSTs; sleep 1.2s.
            time.sleep(1.2)

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
