"""Promote CSP Latvia (Centrala statistikas parvalde) as default source for
the TE-conformity gap-fill batch (21 indicators).

Indicators promoted to csp_lv:
  - exports, imports                          (CSP ATD100m, FLOW=EXP/IMP)
  - consumer-spending                         (CSP ISP050c P31_S14 chain-linked)
  - government-spending                       (CSP ISP050c P3_S13 chain-linked)
  - gross-fixed-capital-formation             (CSP ISP050c P51G chain-linked)
  - cpi-food, cpi-clothing, cpi-housing-utilities, cpi-transportation,
    cpi-recreation-and-culture, cpi-education (CSP PCI021m by COICOP)
  - food-inflation                            (CSP PCI021m6 YoY % COICOP 01)
  - business-confidence, consumer-confidence  (CSP KRE020m DG-ECFIN, SA)
  - employed-persons                          (CSP NBL010m)
  - employment-rate                           (CSP NBL020c 15-64)
  - labor-force-participation-rate            (CSP NBA050c4 15-64)
  - population                                (CSP IRS010m thousand -> million)
  - government-debt                           (CSP VFV040c quarterly mln EUR)

Not seeded for LV (kept on Eurostat fallback) — TE inventory verified gaps:
  - industrial-production, manufacturing-production, mining-production
    (CSP RUI020m HTTP 400 for section-level NACE codes B/C/B_C_D_X_D353)
  - changes-in-inventories
    (CSP ISP050c P52 chain-linked series is all-null in current publication)

Demotes existing eurostat rows for the same (indicator, country) tuples.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb


SEEDS = [
    # (slug, src, series_id, freq, unit, adjustment, conversion, note)
    ("exports",                       "csp_lv", "CSP/ATD100m/EXP",         "M",
     "Million EUR", "NSA", 1.0,
     "CSP Latvia ATD100m total goods exports vs World, NSA, mln EUR"),
    ("imports",                       "csp_lv", "CSP/ATD100m/IMP",         "M",
     "Million EUR", "NSA", 1.0,
     "CSP Latvia ATD100m total goods imports vs World, NSA, mln EUR"),
    ("consumer-spending",             "csp_lv", "CSP/ISP050c/P31_S14",     "Q",
     "Million EUR (2020 chained)", "SA", 0.001,
     "CSP Latvia ISP050c household final consumption (P31_S14) chain-linked 2020 SA, kEUR -> mln"),
    ("government-spending",           "csp_lv", "CSP/ISP050c/P3_S13",      "Q",
     "Million EUR (2020 chained)", "SA", 0.001,
     "CSP Latvia ISP050c government final consumption (P3_S13) chain-linked 2020 SA, kEUR -> mln"),
    ("gross-fixed-capital-formation", "csp_lv", "CSP/ISP050c/P51G",        "Q",
     "Million EUR (2020 chained)", "SA", 0.001,
     "CSP Latvia ISP050c gross fixed capital formation (P51G) chain-linked 2020 SA, kEUR -> mln"),
    ("cpi-food",                      "csp_lv", "CSP/PCI021m/CP01",        "M",
     "Index (2025=100)", "NSA", 1.0,
     "CSP Latvia PCI021m COICOP 01 Food and non-alcoholic beverages, 2025=100"),
    ("cpi-clothing",                  "csp_lv", "CSP/PCI021m/CP03",        "M",
     "Index (2025=100)", "NSA", 1.0,
     "CSP Latvia PCI021m COICOP 03 Clothing and footwear, 2025=100"),
    ("cpi-housing-utilities",         "csp_lv", "CSP/PCI021m/CP04",        "M",
     "Index (2025=100)", "NSA", 1.0,
     "CSP Latvia PCI021m COICOP 04 Housing, water, electricity, gas, 2025=100"),
    ("cpi-transportation",            "csp_lv", "CSP/PCI021m/CP07",        "M",
     "Index (2025=100)", "NSA", 1.0,
     "CSP Latvia PCI021m COICOP 07 Transport, 2025=100"),
    ("cpi-recreation-and-culture",    "csp_lv", "CSP/PCI021m/CP09",        "M",
     "Index (2025=100)", "NSA", 1.0,
     "CSP Latvia PCI021m COICOP 09 Recreation and culture, 2025=100"),
    ("cpi-education",                 "csp_lv", "CSP/PCI021m/CP10",        "M",
     "Index (2025=100)", "NSA", 1.0,
     "CSP Latvia PCI021m COICOP 10 Education, 2025=100"),
    ("food-inflation",                "csp_lv", "CSP/PCI021m6/CP01",       "M",
     "%", "NSA", 1.0,
     "CSP Latvia PCI021m6 YoY %, COICOP 01 Food and non-alcoholic beverages"),
    ("business-confidence",           "csp_lv", "CSP/KRE020m/CI_IND",      "M",
     "Net balance, %", "SA", 1.0,
     "CSP Latvia KRE020m Industrial Confidence Indicator (DG ECFIN), SA"),
    ("consumer-confidence",           "csp_lv", "CSP/KRE020m/CI_CONSUM",   "M",
     "Net balance, %", "SA", 1.0,
     "CSP Latvia KRE020m Consumer Confidence Indicator (DG ECFIN), SA"),
    ("employed-persons",              "csp_lv", "CSP/NBL010m",             "M",
     "Thousand persons", "SA", 1.0,
     "CSP Latvia NBL010m employed persons aged 15-74, SA, thousand"),
    ("employment-rate",               "csp_lv", "CSP/NBL020c/Y15-64",      "Q",
     "%", "NSA", 1.0,
     "CSP Latvia NBL020c employment rate aged 15-64, total, quarterly"),
    ("labor-force-participation-rate","csp_lv", "CSP/NBA050c/Y15-64",      "Q",
     "%", "NSA", 1.0,
     "CSP Latvia NBA050c activity rate aged 15-64, total, quarterly"),
    ("population",                    "csp_lv", "CSP/IRS010m",             "M",
     "Million persons", "NSA", 0.001,
     "CSP Latvia IRS010m population, thousand -> million"),
    ("government-debt",               "csp_lv", "CSP/VFV040c",             "Q",
     "Million EUR", "NSA", 1.0,
     "CSP Latvia VFV040c general government gross debt quarterly, mln EUR"),
]


def main():
    inserted = 0
    for slug, src, series_id, freq, unit, adj, conv, note in SEEDS:
        sb.table("indicator_sources").delete().eq(
            "indicator", slug
        ).eq("country", "LV").eq("source", src).execute()
        sb.table("indicator_sources").update({"is_default": False}).eq(
            "indicator", slug
        ).eq("country", "LV").execute()
        row = {
            "indicator": slug,
            "country": "LV",
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
        print(f"  + LV/{slug:<32} | {src:<8} | {series_id}")

    print(f"\n{inserted} CSP-direct rows promoted; eurostat counterparts demoted.")


if __name__ == "__main__":
    main()
