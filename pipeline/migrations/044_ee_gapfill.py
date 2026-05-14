"""Promote Statistics Estonia (Statistikaamet, andmed.stat.ee PxWeb) as default
source for the TE-conformity gap-fill batch (17 indicators).

Indicators promoted to stat_ee:
  - cpi-food, cpi-clothing, cpi-housing-utilities, cpi-transportation,
    cpi-recreation-and-culture, cpi-education       (IA002 CPI by Kaubagrupp)
  - consumer-spending, government-spending,
    gross-fixed-capital-formation, exports, imports (RAA0061 chain-linked)
  - changes-in-inventories                          (RAA0061 current-prices)
  - manufacturing-production, mining-production     (TO0053 NACE C, B, SA)
  - employed-persons                                (TT0130 LFS quarterly)
  - employment-rate                                 (TT0160 EMPRATE Y20-64)
  - labor-force-participation-rate                  (TT0160 LABOUR_RATE Y15-74)
  - population                                      (RV021 at 1 January)

Not seeded for EE (kept on Eurostat fallback):
  - business-confidence, consumer-confidence
    (Estonian Institute of Economic Research surveys, not via PxWeb)
  - food-inflation
    (no separate national rate slug; YoY derivable from cpi-food)
  - unemployed-persons
    (not in this gap-fill batch)

Demotes existing eurostat rows for the same (indicator, country) tuples.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb


SEEDS = [
    # (slug, src, series_id, freq, unit, adjustment, conversion, note)
    ("cpi-food",                       "stat_ee", "STATEE/IA002/K2",            "M",
     "Index (1997=100)", "NSA", 1.0,
     "Stat Estonia IA002 CPI Food and non-alcoholic beverages"),
    ("cpi-clothing",                   "stat_ee", "STATEE/IA002/K4",            "M",
     "Index (1997=100)", "NSA", 1.0,
     "Stat Estonia IA002 CPI Clothing and footwear"),
    ("cpi-housing-utilities",          "stat_ee", "STATEE/IA002/K5",            "M",
     "Index (1997=100)", "NSA", 1.0,
     "Stat Estonia IA002 CPI Housing"),
    ("cpi-transportation",             "stat_ee", "STATEE/IA002/K8",            "M",
     "Index (1997=100)", "NSA", 1.0,
     "Stat Estonia IA002 CPI Transport"),
    ("cpi-recreation-and-culture",     "stat_ee", "STATEE/IA002/K10",           "M",
     "Index (1997=100)", "NSA", 1.0,
     "Stat Estonia IA002 CPI Recreation, sport and culture"),
    ("cpi-education",                  "stat_ee", "STATEE/IA002/K11",           "M",
     "Index (1997=100)", "NSA", 1.0,
     "Stat Estonia IA002 CPI Education services"),
    ("consumer-spending",              "stat_ee", "STATEE/RAA0061/K1",          "Q",
     "Million EUR (2020 chain-linked)", "NSA", 1.0,
     "Stat Estonia RAA0061 private consumption expenditure, chain-linked vol ref 2020"),
    ("government-spending",            "stat_ee", "STATEE/RAA0061/K2",          "Q",
     "Million EUR (2020 chain-linked)", "NSA", 1.0,
     "Stat Estonia RAA0061 general government final consumption expenditure, chain-linked"),
    ("gross-fixed-capital-formation",  "stat_ee", "STATEE/RAA0061/K4",          "Q",
     "Million EUR (2020 chain-linked)", "NSA", 1.0,
     "Stat Estonia RAA0061 gross fixed capital formation + valuables, chain-linked"),
    ("changes-in-inventories",         "stat_ee", "STATEE/RAA0061/K5",          "Q",
     "Million EUR (current prices)", "NSA", 1.0,
     "Stat Estonia RAA0061 change in inventories, current prices (chain-linked not published)"),
    ("exports",                        "stat_ee", "STATEE/RAA0061/K7",          "Q",
     "Million EUR (2020 chain-linked)", "NSA", 1.0,
     "Stat Estonia RAA0061 exports of goods and services, chain-linked"),
    ("imports",                        "stat_ee", "STATEE/RAA0061/K10",         "Q",
     "Million EUR (2020 chain-linked)", "NSA", 1.0,
     "Stat Estonia RAA0061 imports of goods and services, chain-linked"),
    ("manufacturing-production",       "stat_ee", "STATEE/TO0053/C",            "M",
     "Index (2021=100)", "SA", 1.0,
     "Stat Estonia TO0053 manufacturing C volume index SA, 2021=100"),
    ("mining-production",              "stat_ee", "STATEE/TO0053/B",            "M",
     "Index (2021=100)", "SA", 1.0,
     "Stat Estonia TO0053 mining and quarrying B volume index SA, 2021=100"),
    ("employed-persons",               "stat_ee", "STATEE/TT0130",              "Q",
     "Thousand persons", "NSA", 1.0,
     "Stat Estonia TT0130 employed persons 15-74, both sexes, full+part time"),
    ("employment-rate",                "stat_ee", "STATEE/TT0160/EMPRATE",      "Q",
     "%", "NSA", 1.0,
     "Stat Estonia TT0160 employment rate Y20-64, total"),
    ("labor-force-participation-rate", "stat_ee", "STATEE/TT0160/LABOUR_RATE",  "Q",
     "%", "NSA", 1.0,
     "Stat Estonia TT0160 labour force participation rate Y15-74"),
    ("population",                     "stat_ee", "STATEE/RV021",               "A",
     "Million persons", "NSA", 0.000001,
     "Stat Estonia RV021 population at 1 January, total -> million"),
]


def main():
    inserted = 0
    for slug, src, series_id, freq, unit, adj, conv, note in SEEDS:
        sb.table("indicator_sources").delete().eq(
            "indicator", slug
        ).eq("country", "EE").eq("source", src).execute()
        sb.table("indicator_sources").update({"is_default": False}).eq(
            "indicator", slug
        ).eq("country", "EE").execute()
        row = {
            "indicator": slug,
            "country": "EE",
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
        print(f"  + EE/{slug:<32} | {src:<8} | {series_id}")

    print(f"\n{inserted} stat_ee-direct rows promoted; eurostat counterparts demoted.")


if __name__ == "__main__":
    main()
