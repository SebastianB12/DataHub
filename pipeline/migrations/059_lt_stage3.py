"""LT stage-3: promote LSD direct (osp-rs.stat.gov.lt SDMX REST) as the default
source for 11 indicators currently on Eurostat per docs/_te_inventory/LT.yaml
verified=true / conform=false / suggested_source=lsd_lt.

The earlier 043_lt_gapfill batch deferred these because the data.gov.lt JSON
gateway does not republish them. They ARE available via LSD's official SDMX
2.1 REST endpoint at https://osp-rs.stat.gov.lt/rest_xml/data/<flow>, which
is cookie-less and not gated by Cloudflare. The provider (pipeline/providers/
lsd_lt.py) gained a parallel LT_SDMX_SERIES catalogue and an SDMX fetcher
(fetch_sdmx_series) in this stage.

Indicators promoted to lsd_lt:
  industrial / manufacturing / mining production
     S8R918_M4050113_5 IP index 2021=100, SA, by NACE (B_TO_E_NOT_C19 / C / B)
  food-inflation
     S7R250_M2020120 (COICOP 01 food & non-alc bev, palyg_pm = YoY %)
  labour-costs
     S3R0452_M3060508_1 LCI 2020=100, B_TO_S total, NSA, quarterly
  job-vacancies
     S3R275_M3040102_1 (TOTAL across NACE, NSA, quarterly) — exact TE match 30528
  long-term-unemployment-rate
     S3R196_M3030102 LFS LTU rate >=12mo total quarterly — exact TE match 2.4
  labor-force-participation-rate
     S3R003_M3030101_1 LFS activity rate age 15+ total quarterly (TE 62.6)
  unemployed-persons
     S3R050_M3030101_2 LFS unemployed-persons 15+ total thousand quarterly
  business-confidence
     S8R394_M4020216 DG-ECFIN industrial confidence (balance, SA, monthly) — TE -2 exact
  consumer-confidence
     S3R0180_M3230101 DG-ECFIN consumer confidence (balance, SA, monthly) — TE -3 exact

Demotes existing eurostat rows for the same (indicator, country) tuples.

Smoke-tested 2026-05-15: all 11 SDMX flows return data; latest periods range
2026M03 (IP) / 2026M04 (BCS) / 2026K1 (LFS) / 2025M12 (food-infl) / 2025K3 (LCI).

Run:
    python -m pipeline.migrations.059_lt_stage3
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb


SEEDS = [
    # (slug, src, series_id, freq, unit, adjustment, conversion, note)
    ("industrial-production", "lsd_lt",
     "LSD/SDMX/S8R918_M4050113_5/EVRKM4050107=B_TO_E_NOT_C19/LYGINIMAS=palyg_2021/Islyginimas_indeksai=sezon",
     "M", "Index (2021=100)", "SA", 1.0,
     "LSD S8R918 IP index total industry excl. refined petroleum, 2021=100, SA"),
    ("manufacturing-production", "lsd_lt",
     "LSD/SDMX/S8R918_M4050113_5/EVRKM4050107=C/LYGINIMAS=palyg_2021/Islyginimas_indeksai=sezon",
     "M", "Index (2021=100)", "SA", 1.0,
     "LSD S8R918 manufacturing (C) IP index 2021=100 SA"),
    ("mining-production", "lsd_lt",
     "LSD/SDMX/S8R918_M4050113_5/EVRKM4050107=B/LYGINIMAS=palyg_2021/Islyginimas_indeksai=sezon",
     "M", "Index (2021=100)", "SA", 1.0,
     "LSD S8R918 mining and quarrying (B) IP index 2021=100 SA"),
    ("food-inflation", "lsd_lt",
     "LSD/SDMX/S7R250_M2020120/maistasM2020120=01/LYGINIMAS=palyg_pm",
     "M", "%", "NSA", 1.0,
     "LSD S7R250 food & non-alcoholic beverages YoY % (COICOP 01)"),
    ("labour-costs", "lsd_lt",
     "LSD/SDMX/S3R0452_M3060508_1/IslyginimasM3060501=NSA/darboM2040601=TOT/EVRK2M3060503=B_TO_S",
     "Q", "Index (2020=100)", "NSA", 1.0,
     "LSD S3R0452 LCI total labour cost per hour worked, B-S total, 2020=100, NSA"),
    ("job-vacancies", "lsd_lt",
     "LSD/SDMX/S3R275_M3040102_1/darbuotojuSKM2020201=total/EVRK2M3140605=TOTAL/Islyginimas_indeksai=bendras",
     "Q", "Number of vacancies", "NSA", 1.0,
     "LSD S3R275 total job vacancies all NACE TOTAL, NSA, quarterly"),
    ("long-term-unemployment-rate", "lsd_lt",
     "LSD/SDMX/S3R196_M3030102/lytis=0/vietove=0",
     "Q", "%", "NSA", 1.0,
     "LSD S3R196 LFS long-term unemployment rate (>=12mo) total quarterly"),
    ("labor-force-participation-rate", "lsd_lt",
     "LSD/SDMX/S3R003_M3030101_1/AmziusM2111=0/Vietove=0/Lytis=0",
     "Q", "%", "NSA", 1.0,
     "LSD S3R003 LFS activity rate 15+ total quarterly"),
    ("unemployed-persons", "lsd_lt",
     "LSD/SDMX/S3R050_M3030101_2/AmziusM2111=0/Vietove=0/Lytis=0",
     "Q", "Thousand persons", "NSA", 1.0,
     "LSD S3R050 LFS unemployed persons 15+ total, thousand, quarterly"),
    ("business-confidence", "lsd_lt",
     "LSD/SDMX/S8R394_M4020216/TOTAL",
     "M", "Net balance, %", "SA", 1.0,
     "LSD S8R394 DG-ECFIN BCS industrial confidence indicator (balance)"),
    ("consumer-confidence", "lsd_lt",
     "LSD/SDMX/S3R0180_M3230101/Vietove=0",
     "M", "Net balance, %", "SA", 1.0,
     "LSD S3R0180 DG-ECFIN BCS consumer confidence indicator (balance)"),
]


def main():
    inserted = 0
    for slug, src, series_id, freq, unit, adj, conv, note in SEEDS:
        sb.table("indicator_sources").delete().eq(
            "indicator", slug
        ).eq("country", "LT").eq("source", src).execute()
        sb.table("indicator_sources").update({"is_default": False}).eq(
            "indicator", slug
        ).eq("country", "LT").execute()
        row = {
            "indicator": slug, "country": "LT", "source": src,
            "series_id": series_id, "is_default": True, "transform": "raw",
            "conversion": conv, "unit": unit, "adjustment": adj,
            "freq_hint": freq, "extra_params": None, "active": True, "note": note,
        }
        sb.table("indicator_sources").insert(row).execute()
        inserted += 1
        print(f"  + LT/{slug:<33} | {src:<8} | {series_id}")
    print(f"\n{inserted} LSD-direct rows promoted; eurostat counterparts demoted.")


if __name__ == "__main__":
    main()
