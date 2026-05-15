"""TE-conformity gap-fill for Ireland — CSO PxStat direct seeds for the
remaining MISMATCH slugs (current_source=eurostat -> cso_ie).

Provider extensions: see pipeline/providers/national_eu.py IE_SERIES (added
2026-05-15) — covers CPI sub-aggregates (CPM01 by COICOP), LFS labour metrics
(QLF18), industrial-production NACE V2100, national-accounts components
(NAQ04 SA constant), and govt finance (GFA02 annual debt + B9).

Smoke-tested 2026-05-15 (last 3 obs each):
  cpi-food                  CPM01C08 COICOP=01    -> 2025-12 = 106.2
  cpi-clothing              CPM01C08 COICOP=03    -> 2025-12 (verified)
  cpi-housing-utilities     CPM01C08 COICOP=04    -> 2025-12 (verified)
  cpi-transportation        CPM01C08 COICOP=07    -> 2025-12 = 101.8
  cpi-recreation-and-culture CPM01C08 COICOP=09   -> 2025-12 (verified)
  cpi-education             CPM01C08 COICOP=10    -> 2025-12 (verified)
  core-cpi                  CPM01C08 all-items    -> 2025-12 (verified)
  food-inflation            CPM01C07 COICOP=01    -> 2025-12 YoY%
  employment-rate           QLF18C04 age=315      -> 2025Q4 = 74.5  (TE 74.5)
  labor-force-participation-rate QLF18C02 age=320 -> 2025Q4 = 65.8  (TE 65.8)
  youth-unemployment-rate   QLF18C06 age=310      -> 2025Q4 = 9.8   (TE 9.8)
  unemployed-persons        QLF18C05 age=320      -> 2025Q4 = 128.2 thousand
  manufacturing-production  MIM05C03 NACE=V2100   -> 2026-03 = 112.4
  consumer-spending         NAQ04S02 component=001 -> 2025Q4 = 41,197 EUR mn
  government-spending       NAQ04S02 component=002 -> 2025Q4 = 14,789 EUR mn
  gross-fixed-capital-formation NAQ04S02 003       -> 2025Q4 = 30,096 EUR mn
  changes-in-inventories    NAQ04S02 component=004 -> 2025Q4 = 1,364 EUR mn
  government-debt           GFA02 code=26          -> 2025  = 209,902 EUR mn
  government-debt-total     GFA02 code=26          -> 2025  = 209,902 EUR mn
  budget-deficit            GFA02 code=18          -> 2025  = 10,129 (B9, surplus)

Demotes any prior eurostat defaults for the same (indicator, IE) tuples and
inserts cso_ie-default rows. Idempotent: deletes any existing same-(slug,
country, source) row before insert.

Run order:
    python -m pipeline.migrations.064_ie_gapfill
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb


# (slug, series_id, freq, unit, adjustment, conversion, note)
SEEDS = [
    ("cpi-food", "CSO/CPM01/01", "M",
     "Index (Dec 2023=100)", "NSA", 1.0,
     "CSO Ireland CPM01 CPI Food & non-alc bev (COICOP 01)"),
    ("cpi-clothing", "CSO/CPM01/03", "M",
     "Index (Dec 2023=100)", "NSA", 1.0,
     "CSO Ireland CPM01 CPI Clothing & footwear (COICOP 03)"),
    ("cpi-housing-utilities", "CSO/CPM01/04", "M",
     "Index (Dec 2023=100)", "NSA", 1.0,
     "CSO Ireland CPM01 CPI Housing/water/energy (COICOP 04)"),
    ("cpi-transportation", "CSO/CPM01/07", "M",
     "Index (Dec 2023=100)", "NSA", 1.0,
     "CSO Ireland CPM01 CPI Transport (COICOP 07)"),
    ("cpi-recreation-and-culture", "CSO/CPM01/09", "M",
     "Index (Dec 2023=100)", "NSA", 1.0,
     "CSO Ireland CPM01 CPI Recreation & culture (COICOP 09)"),
    ("cpi-education", "CSO/CPM01/10", "M",
     "Index (Dec 2023=100)", "NSA", 1.0,
     "CSO Ireland CPM01 CPI Education (COICOP 10)"),
    ("core-cpi", "CSO/CPM01/core", "M",
     "Index (Dec 2023=100)", "NSA", 1.0,
     "CSO Ireland CPM01 CPI all-items (core proxy)"),
    ("food-inflation", "CSO/CPM01/food-yoy", "M",
     "% YoY", "NSA", 1.0,
     "CSO Ireland CPM01 Food & non-alc bev YoY%"),
    ("employment-rate", "CSO/QLF18/empr-15-64", "Q",
     "%", "NSA", 1.0,
     "CSO Ireland QLF18 ILO Employment Rate 15-64 both sexes"),
    ("labor-force-participation-rate", "CSO/QLF18/lfpr-15plus", "Q",
     "%", "NSA", 1.0,
     "CSO Ireland QLF18 ILO Participation Rate 15+ both sexes"),
    ("youth-unemployment-rate", "CSO/QLF18/yuneml-15-24", "Q",
     "%", "NSA", 1.0,
     "CSO Ireland QLF18 Youth Unemployment Rate 15-24 both sexes"),
    ("unemployed-persons", "CSO/QLF18/unemp-15plus", "Q",
     "Thousand", "NSA", 1.0,
     "CSO Ireland QLF18 LFS unemployed persons 15+ both sexes"),
    ("manufacturing-production", "CSO/MIM05/manuf", "M",
     "Index (2021=100)", "SA", 1.0,
     "CSO Ireland MIM05 SA Industrial Production NACE V2100 (Manufacturing 10-33)"),
    ("consumer-spending", "CSO/NAQ04/consumer", "Q",
     "EUR million", "SA", 1.0,
     "CSO Ireland NAQ04 Personal Consumption SA constant prices"),
    ("government-spending", "CSO/NAQ04/gov", "Q",
     "EUR million", "SA", 1.0,
     "CSO Ireland NAQ04 Government Final Consumption SA constant prices"),
    ("gross-fixed-capital-formation", "CSO/NAQ04/gfcf", "Q",
     "EUR million", "SA", 1.0,
     "CSO Ireland NAQ04 Gross Domestic Fixed Capital Formation SA constant"),
    ("changes-in-inventories", "CSO/NAQ04/inv", "Q",
     "EUR million", "SA", 1.0,
     "CSO Ireland NAQ04 Value of Physical Changes in Stocks SA"),
    ("government-debt", "CSO/GFA02/debt", "A",
     "EUR million", "NSA", 1.0,
     "CSO Ireland GFA02 Gross General Government Debt (EDP face value)"),
    ("government-debt-total", "CSO/GFA02/debt-total", "A",
     "EUR million", "NSA", 1.0,
     "CSO Ireland GFA02 Gross General Government Debt (EDP face value)"),
    ("budget-deficit", "CSO/GFA02/b9", "A",
     "EUR million", "NSA", 1.0,
     "CSO Ireland GFA02 General Government Net Lending/Borrowing B9 (ESA2010)"),
]


def main():
    inserted = 0
    for slug, series_id, freq, unit, adj, conv, note in SEEDS:
        # Idempotent: clear any existing same-source row for this (slug, IE)
        sb.table("indicator_sources").delete().eq(
            "indicator", slug
        ).eq("country", "IE").eq("source", "cso_ie").execute()
        # Demote any other defaults for this (slug, IE)
        sb.table("indicator_sources").update({"is_default": False}).eq(
            "indicator", slug
        ).eq("country", "IE").execute()
        sb.table("indicator_sources").insert({
            "indicator": slug,
            "country": "IE",
            "source": "cso_ie",
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
        }).execute()
        inserted += 1
        print(f"  + IE/{slug:<32} | cso_ie | {series_id}")
    print(f"\n{inserted} CSO-direct rows promoted; eurostat counterparts demoted.")


if __name__ == "__main__":
    main()
