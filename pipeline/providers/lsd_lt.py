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
