"""Promote LSD Lithuania (Statistikos departamentas via data.gov.lt) as default
source for the TE-conformity gap-fill batch (15 indicators).

Indicators promoted to lsd_lt:
  - cpi-food, cpi-clothing, cpi-housing-utilities, cpi-transportation,
    cpi-recreation-and-culture, cpi-education       (LSD SVKI HICP by COICOP)
  - consumer-spending                               (LSD chain-linked P31_S14)
  - government-spending                             (LSD chain-linked P3_S13)
  - gross-fixed-capital-formation                   (LSD chain-linked P51G)
  - exports, imports                                (LSD chain-linked P6/P7)
  - changes-in-inventories                          (LSD current-price P52)
  - employed-persons                                (LSD ESS2010 TOTAL empl SA)
  - population                                      (LSD nuolatiniai 1 Jan -> mln)
  - government-debt                                 (LSD Maastricht S13 GD)

Not seeded for LT (no LSD short-term tables in data.gov.lt catalog,
kept on Eurostat fallback):
  - industrial-production, manufacturing-production, mining-production
    (no pramones_produkcijos_indeksai namespace in data.gov.lt)
  - business-confidence, consumer-confidence
    (DG-ECFIN BCS data not republished by LSD via data.gov.lt)
  - food-inflation, labor-force-participation-rate,
    labour-costs, long-term-unemployment-rate, job-vacancies,
    unemployed-persons
    (not in this gap-fill batch or no national table available)

Demotes existing eurostat/worldbank rows for the same (indicator, country) tuples.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb


SEEDS = [
    # (slug, src, series_id, freq, unit, adjustment, conversion, note)
    ("cpi-food",                      "lsd_lt", "LSD/svki/S7R246M2020217/CP01", "M",
     "Index (2015=100)", "NSA", 1.0,
     "LSD SVKI HICP COICOP 01 Food and non-alcoholic beverages, 2015=100"),
    ("cpi-clothing",                  "lsd_lt", "LSD/svki/S7R246M2020217/CP03", "M",
     "Index (2015=100)", "NSA", 1.0,
     "LSD SVKI HICP COICOP 03 Clothing and footwear"),
    ("cpi-housing-utilities",         "lsd_lt", "LSD/svki/S7R246M2020217/CP04", "M",
     "Index (2015=100)", "NSA", 1.0,
     "LSD SVKI HICP COICOP 04 Housing"),
    ("cpi-transportation",            "lsd_lt", "LSD/svki/S7R246M2020217/CP07", "M",
     "Index (2015=100)", "NSA", 1.0,
     "LSD SVKI HICP COICOP 07 Transport"),
    ("cpi-recreation-and-culture",    "lsd_lt", "LSD/svki/S7R246M2020217/CP09", "M",
     "Index (2015=100)", "NSA", 1.0,
     "LSD SVKI HICP COICOP 09 Recreation and culture"),
    ("cpi-education",                 "lsd_lt", "LSD/svki/S7R246M2020217/CP10", "M",
     "Index (2015=100)", "NSA", 1.0,
     "LSD SVKI HICP COICOP 10 Education"),
    ("consumer-spending",             "lsd_lt", "LSD/bvp_grandininiu_susiejimu/S7R208M21101072/p31_S14", "Q",
     "Million EUR (2020 chain-linked)", "SA", 1.0,
     "LSD chain-linked GDP household final consumption (P31_S14), SA"),
    ("government-spending",           "lsd_lt", "LSD/bvp_grandininiu_susiejimu/S7R208M21101072/p3_S13",  "Q",
     "Million EUR (2020 chain-linked)", "SA", 1.0,
     "LSD chain-linked GDP government final consumption (P3_S13), SA"),
    ("gross-fixed-capital-formation", "lsd_lt", "LSD/bvp_grandininiu_susiejimu/S7R208M21101072/p51g",    "Q",
     "Million EUR (2020 chain-linked)", "SA", 1.0,
     "LSD chain-linked GDP gross fixed capital formation (P51G), SA"),
    ("exports",                       "lsd_lt", "LSD/bvp_grandininiu_susiejimu/S7R208M21101072/p6",      "Q",
     "Million EUR (2020 chain-linked)", "SA", 1.0,
     "LSD chain-linked GDP exports of goods and services (P6), SA"),
    ("imports",                       "lsd_lt", "LSD/bvp_grandininiu_susiejimu/S7R208M21101072/p7",      "Q",
     "Million EUR (2020 chain-linked)", "SA", 1.0,
     "LSD chain-linked GDP imports of goods and services (P7), SA"),
    ("changes-in-inventories",        "lsd_lt", "LSD/bvp_islaidu_metodu/S7R192M21101071/p52",            "Q",
     "Million EUR (current prices)", "SA", 1.0,
     "LSD GDP changes in inventories (P52), current prices, SA (chain-linked not published)"),
    ("employed-persons",              "lsd_lt", "LSD/uzimtumas_ess2010/S7R219M2110133/TOTAL",            "Q",
     "Thousand persons", "SA", 1.0,
     "LSD ESA2010 employment total economy, persons, SA"),
    ("population",                    "lsd_lt", "LSD/nuolatiniai_gyventojai/S3R167M3010202",             "A",
     "Million persons", "NSA", 0.000001,
     "LSD permanent population at 1 January, total LT, persons -> million"),
    ("government-debt",               "lsd_lt", "LSD/valdzios_sektoriaus_mastrichto_skola/S7R267M2040215", "Q",
     "Million EUR", "NSA", 1.0,
     "LSD General government Maastricht (gross) debt, mln EUR"),
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
            "indicator": slug,
            "country": "LT",
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
        print(f"  + LT/{slug:<32} | {src:<8} | {series_id}")

    print(f"\n{inserted} LSD-direct rows promoted; eurostat counterparts demoted.")


if __name__ == "__main__":
    main()
