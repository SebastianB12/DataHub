"""Promote NSO Malta direct as default source for stage-2 MT indicators.

Migration 015 / earlier already seeded MT for inflation-cpi via DF_RETAIL_PRICE_INDEX_MONTHLY
(NSO Malta SDMX, Cloudflare-protected — cloudscraper).

This migration extends to TE-aligned series currently served by eurostat:
  CPI sub-components: cpi-clothing, cpi-education, cpi-food, cpi-housing-utilities,
                      cpi-recreation-and-culture, cpi-transportation
                      (via DF_CPI HICP, base 2025=100 — same dataset Eurostat
                      receives from NSO; source-label change only.)
  Quarterly NA:       consumer-spending, government-spending,
                      gross-fixed-capital-formation, changes-in-inventories, gdp-real
                      (DF_NA_NAMQ10GDP)
  Trade:              exports, imports, trade-balance
                      (DF_ITGS_D_HS / DF_ITGS_A_HS — sums across HS PRODUCT codes,
                      trade-balance derived as exports − imports in fetcher)
  Population:         population (DF_TOT_POP_BY_SEX_SINGLE_YEARS_AGE — annual,
                      summed across ages for sex=T)
  Labour:             unemployment-rate, employed-persons
                      (DF_LABOUR_STATUS_FOR_PERSONS_AGED_15_PLUSS_YEARS — sex
                      summed M+F since dataflow has no Total code)

All tables sit under https://apidesign-statdb.nso.gov.mt/rest/ ; fetcher passes
Cloudflare via cloudscraper. See pipeline/providers/national_eu.py section
"Malta — NSO Malta SDMX REST" for dataflow/key conventions.

TE-conformity smoke (verified 2026-05-15 — current scrapes match TE inventory
within revision lag):
  cpi-clothing                 2026-03 = 98.41   (TE 98.41 2026-02) MATCH
  cpi-education                2026-03 = 102.41  (TE 102.41)        MATCH
  cpi-food                     2026-03 = 101.69  (TE 101.69)        MATCH
  cpi-housing-utilities        2026-03 = 102.01  (TE 102.01)        MATCH
  cpi-recreation-and-culture   2026-03 = 100.97  (TE 100.97)        MATCH
  cpi-transportation           2026-03 = 98.72   (TE 98.72)         MATCH
  consumer-spending            2025Q4 = 2,246.72 mln EUR (real NSA chained)  TE 2,246,723 MATCH
  government-spending          2025Q4 = 945.27 mln EUR (real NSA chained)    TE 945,270  MATCH
  gross-fixed-capital-formation 2025Q4 = 1,140.87 mln EUR (current NSA)      TE 1,140,869 MATCH
  changes-in-inventories       2025Q4 = 42.97 mln EUR (current NSA)
  gdp-real                     2025Q4 = 5,231.14 mln EUR (chained L,Y SA)
  exports                      2026-03 = 404,515.8 thousand EUR    TE 404,516 MATCH
  imports                      2026-03 = 664,063.3 thousand EUR    TE 664,053 MATCH (rounding)
  trade-balance                2026-03 = -259,547.5 thousand EUR (exp − imp)
  population                   2024    = 574,250 persons          TE pop 2025
  unemployment-rate            2024Q4 = 2.85%  (LFS LSUNEMP/(LSEMP+LSUNEMP) sum M+F)
  employed-persons             2024Q4 = 325.6  thousand (LSEMP sum M+F → 1000)

Not seeded (kept on eurostat or other):
  industrial-production — DF_STBS_INDUSTRIAL_INDICATORS_MONTHLY ends 2019-06
                          (stale by ~7 years); deferred → te_coverage_gaps.
  retail-sales          — NSO Malta has no monthly retail-sales index dataflow
                          in current API catalog; deferred.
  food-inflation        — YoY of cpi-food; Frontend computes on-the-fly.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb


SEEDS = [
    # (slug, series_id, freq, unit, adjustment, conversion, note)
    ("cpi-clothing", "NSO/DF_CPI/M.MT.2025.CP03", "M",
     "Index (2025=100)", "NSA", 1.0,
     "NSO Malta DF_CPI HICP CP03 Clothing & footwear, base 2025=100"),
    ("cpi-education", "NSO/DF_CPI/M.MT.2025.CP10", "M",
     "Index (2025=100)", "NSA", 1.0,
     "NSO Malta DF_CPI HICP CP10 Education, base 2025=100"),
    ("cpi-food", "NSO/DF_CPI/M.MT.2025.CP01", "M",
     "Index (2025=100)", "NSA", 1.0,
     "NSO Malta DF_CPI HICP CP01 Food & non-alc bev, base 2025=100"),
    ("cpi-housing-utilities", "NSO/DF_CPI/M.MT.2025.CP04", "M",
     "Index (2025=100)", "NSA", 1.0,
     "NSO Malta DF_CPI HICP CP04 Housing/water/electricity/gas, base 2025=100"),
    ("cpi-recreation-and-culture", "NSO/DF_CPI/M.MT.2025.CP09", "M",
     "Index (2025=100)", "NSA", 1.0,
     "NSO Malta DF_CPI HICP CP09 Recreation & culture, base 2025=100"),
    ("cpi-transportation", "NSO/DF_CPI/M.MT.2025.CP07", "M",
     "Index (2025=100)", "NSA", 1.0,
     "NSO Malta DF_CPI HICP CP07 Transport, base 2025=100"),

    ("consumer-spending", "NSO/DF_NA_NAMQ10GDP/Q.P31_S14_W0.L.N.EUR.", "Q",
     "Million EUR (chain-linked, NSA)", "NSA", 0.001,
     "NSO Malta DF_NA_NAMQ10GDP P31_S14_W0 households+NPISH chained vol NSA (EUR k → mln)"),
    ("government-spending", "NSO/DF_NA_NAMQ10GDP/Q.P3_S13.L.N.EUR.", "Q",
     "Million EUR (chain-linked, NSA)", "NSA", 0.001,
     "NSO Malta DF_NA_NAMQ10GDP P3_S13 general government chained vol NSA (EUR k → mln)"),
    ("gross-fixed-capital-formation", "NSO/DF_NA_NAMQ10GDP/Q.P51G.V.N.EUR.", "Q",
     "Million EUR (current, NSA)", "NSA", 0.001,
     "NSO Malta DF_NA_NAMQ10GDP P51G gross fixed capital formation current NSA (EUR k → mln)"),
    ("changes-in-inventories", "NSO/DF_NA_NAMQ10GDP/Q.P52.V.N.EUR.", "Q",
     "Million EUR (current, NSA)", "NSA", 0.001,
     "NSO Malta DF_NA_NAMQ10GDP P52 changes in inventories current NSA (EUR k → mln)"),
    ("gdp-real", "NSO/DF_NA_NAMQ10GDP/Q.B1GQ.L.Y.EUR.", "Q",
     "Million EUR (chain-linked, SA)", "SA", 0.001,
     "NSO Malta DF_NA_NAMQ10GDP B1GQ GDP chained vol working-day & seasonally adjusted (EUR k → mln)"),

    ("exports", "NSO/DF_ITGS_D_HS/M..X.", "M",
     "Thousand EUR", "NSA", 0.001,
     "NSO Malta DF_ITGS_D_HS dispatches (exports), sum across HS products (EUR → thousand EUR)"),
    ("imports", "NSO/DF_ITGS_A_HS/M..M.", "M",
     "Thousand EUR", "NSA", 0.001,
     "NSO Malta DF_ITGS_A_HS arrivals (imports), sum across HS products (EUR → thousand EUR)"),
    ("trade-balance", "NSO/DF_ITGS_X_MINUS_M/derived", "M",
     "Thousand EUR", "NSA", 1.0,
     "NSO Malta DF_ITGS_D_HS − DF_ITGS_A_HS (exports − imports), thousand EUR"),

    ("population", "NSO/DF_TOT_POP_BY_SEX_SINGLE_YEARS_AGE/T..A", "A",
     "Million", "NSA", 1.0,
     "NSO Malta DF_TOT_POP_BY_SEX_SINGLE_YEARS_AGE sex=Total summed across single-year ages (Million)"),

    ("unemployment", "NSO/DF_LABOUR_STATUS_FOR_PERSONS_AGED_15_PLUSS_YEARS/..Q", "Q",
     "%", "NSA", 1.0,
     "NSO Malta LFS unemployment rate = LSUNEMP/(LSEMP+LSUNEMP) summed across M+F sex (canonical slug=unemployment)"),
    ("employed-persons", "NSO/DF_LABOUR_STATUS_FOR_PERSONS_AGED_15_PLUSS_YEARS/LSEMP..Q", "Q",
     "Thousand persons", "NSA", 0.001,
     "NSO Malta LFS LSEMP summed M+F sex (Total), converted to thousands"),
]


def main():
    inserted = 0
    country = "MT"
    src = "nso_mt"
    for slug, series_id, freq, unit, adj, conv, note in SEEDS:
        sb.table("indicator_sources").delete().eq(
            "indicator", slug
        ).eq("country", country).eq("source", src).execute()
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
    print(f"\n{inserted} MT NSO stage-2 rows promoted; eurostat siblings demoted.")


if __name__ == "__main__":
    main()
