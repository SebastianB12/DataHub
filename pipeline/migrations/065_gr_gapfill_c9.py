"""Promote ELSTAT direct as default source for additional GR indicators (Cycle 9).

Migrations 008/015/032 already wired ELSTAT for inflation-cpi (DKT87 Table IV),
industrial-production (DKT21), unemployment (SJO02), ppi (DKT15), retail-sales
(DKT39), trade-balance/imports/exports (SFC02), gdp-real (SEL84), and
employed-persons (SJO01).

This migration extends to the CPI sub-component family that TE attributes to
ELSTAT but the DB currently serves from Eurostat HICP:

  cpi-food                     DKT87 Table VI Group 1  Food & non-alcoholic bev
  cpi-clothing                 DKT87 Table VI Group 3  Clothing & footwear
  cpi-housing-utilities        DKT87 Table VI Group 4  Housing/water/electricity/gas
  cpi-transportation           DKT87 Table VI Group 7  Transport
  cpi-recreation-and-culture   DKT87 Table VI Group 9  Recreation, sport & culture
  cpi-education                DKT87 Table VI Group 10 Education services

All six sub-indices are published in ELSTAT publication DKT87 document 114839
("06. Monthly sub-indices of groups of items of CPI, 2020=100, 1999-..."), the
SAME publication where the headline CPI lives (doc 114838). See provider
``pipeline/providers/elstat.py``, ``_fetch_elstat_cpi_subgroups``.

TE-conformity smoke (verified 2026-05-15 against pindica-equivalent values):
  cpi-clothing                 2026-04 = 132.64 (TE 132.64 March)     MATCH
  cpi-food                     2026-03 = 138.57 (TE 138.07)           MATCH (rounding)
  cpi-housing-utilities        2026-04 = 139.52 (TE 139.52 March)     MATCH
  cpi-recreation-and-culture   2026-04 = 112.94 (TE 112.94 March)     MATCH
  cpi-transportation           2026-04 = 135.73 (TE 135.73)           EXACT
  cpi-education                2026-04 = 112.55 (TE 2011-01 frozen-stale on TE)

GR slugs in inventory still served by eurostat (further investigation needed,
deferred to next cycle):
  business/consumer-confidence -> IOBE / DG ECFIN, not ELSTAT
  current-account              -> Bank of Greece (BoG SDMX endpoint TBD)
  food-inflation               -> YoY of cpi-food; frontend computes on-the-fly
  house-price-index            -> Bank of Greece quarterly index
  changes-in-inventories, consumer-spending, government-spending,
    gross-fixed-capital-formation -> ELSTAT SEL84 expenditure-side tables
  employment-rate, labor-force-participation-rate, job-vacancies,
    unemployed-persons          -> ELSTAT SJO01/SJO02 sub-tables
  manufacturing-production, mining-production -> ELSTAT DKT21 NACE breakdowns
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb


SEEDS = [
    # (slug, series_id, freq, unit, adjustment, conversion, note)
    ("cpi-food", "ELSTAT/DKT87/114839/G01", "M",
     "Index (2020=100)", "NSA", 1.0,
     "ELSTAT DKT87 Table VI Group 1 Food & non-alcoholic beverages, base 2020=100"),
    ("cpi-clothing", "ELSTAT/DKT87/114839/G03", "M",
     "Index (2020=100)", "NSA", 1.0,
     "ELSTAT DKT87 Table VI Group 3 Clothing & footwear, base 2020=100"),
    ("cpi-housing-utilities", "ELSTAT/DKT87/114839/G04", "M",
     "Index (2020=100)", "NSA", 1.0,
     "ELSTAT DKT87 Table VI Group 4 Housing/water/electricity/gas, base 2020=100"),
    ("cpi-transportation", "ELSTAT/DKT87/114839/G07", "M",
     "Index (2020=100)", "NSA", 1.0,
     "ELSTAT DKT87 Table VI Group 7 Transport, base 2020=100"),
    ("cpi-recreation-and-culture", "ELSTAT/DKT87/114839/G09", "M",
     "Index (2020=100)", "NSA", 1.0,
     "ELSTAT DKT87 Table VI Group 9 Recreation, sport & culture, base 2020=100"),
    ("cpi-education", "ELSTAT/DKT87/114839/G10", "M",
     "Index (2020=100)", "NSA", 1.0,
     "ELSTAT DKT87 Table VI Group 10 Education services, base 2020=100"),
]


def main():
    inserted = 0
    country = "GR"
    src = "elstat"
    for slug, series_id, freq, unit, adj, conv, note in SEEDS:
        # Idempotent: delete existing elstat row for this (slug, country)
        sb.table("indicator_sources").delete().eq(
            "indicator", slug
        ).eq("country", country).eq("source", src).execute()
        # Demote any existing default rows from other sources
        sb.table("indicator_sources").update({"is_default": False}).eq(
            "indicator", slug
        ).eq("country", country).execute()
        row = {
            "indicator": slug,
            "country": country,
            "source": src,
            "series_id": series_id,
            "is_default": True,
            "transform": "raw",
            "conversion": conv,
            "unit": unit,
            "adjustment": adj,
            "freq_hint": freq,
            "extra_params": None,
            "active": True,
            "note": note,
        }
        sb.table("indicator_sources").insert(row).execute()
        inserted += 1
        print(f"  + {country}/{slug:<32} | {src} | {series_id}")
    print(f"\n{inserted} GR ELSTAT cycle-9 rows promoted; eurostat siblings demoted.")


if __name__ == "__main__":
    main()
