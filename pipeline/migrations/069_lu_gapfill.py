"""LU gap-fill (2026-05-15) — close all `suggested_source: statec_lu` mismatches.

Major STATEC expansion: previously only inflation-cpi/ppi/unemployment/IP/population
were sourced from STATEC directly (1 → 24 series wired in pipeline/providers/statec.py).

This migration promotes STATEC as the default source for:
  CPI sub-indices  : cpi-food, cpi-clothing, cpi-housing-utilities,
                     cpi-transportation, cpi-recreation-and-culture, cpi-education
                     (all via DSD_ECOICOP_PRIX@DF_E5405 ECOICOP_2018=CP0n,
                      NCPI base 2025=100)
  CPI special aggs : core-cpi, food-inflation, energy-inflation, services-inflation
                     (DSD_ECOICOP_PRIX@DF_E5409 TOT_X_NRG_FOOD / FOOD / NRG / SERV
                      — level indices; frontend computes YoY)
  Quarterly NA     : gdp-real, consumer-spending, government-spending,
                     gross-fixed-capital-formation
                     (DF_E2504 chain-linked vol 2015, SA; LABELS r33/r13/r15/r16)
  Government       : budget-deficit (DF_E3101 L03 % of GDP),
                     government-debt-total (DF_E3101 L12 mln EUR)
  Retail sales     : retail-sales (DF_D5108 G47 TOVV SEASONAL_ADJUST=Y base 2021)

Smoke-tested 2026-05-15 (latest period):
  cpi-food                       2026-04 = 102.07
  cpi-clothing                   2026-04 = 102.85
  cpi-housing-utilities          2026-04 = 103.91   matches TE 103.91
  cpi-transportation             2026-04 = 106.05   matches TE 106.05
  cpi-recreation-and-culture     2026-04 = 101.87   matches TE 101.87
  cpi-education                  2026-04 = 104.03   matches TE 104.03
  core-cpi                       2026-04 = 101.35   (level; TE displays 5.17% YoY)
  food-inflation                 2026-04 = 102.26   (level; TE 13.27% YoY)
  energy-inflation               2026-04 = 116.65   (level)
  services-inflation             2026-04 = 101.43   (level)
  gdp-real                       2025-Q4 = 16,105.6 mln EUR chain-linked SA
  consumer-spending              2025-Q4 = 5,576.4 mln EUR
  government-spending            2025-Q4 = 3,242.4 mln EUR
  gross-fixed-capital-formation  2025-Q4 = 2,248.1 mln EUR
  budget-deficit                 2025    = -1.96 % of GDP (TE shows 2.0 — sign convention)
  government-debt-total          2025    = 23,695 mln EUR
  retail-sales                   2026-03 = 143.66   (Index 2021=100, SA)

Existing eurostat siblings are demoted (is_default=False).
"""
import sys

sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb


SEEDS = [
    # (slug, series_id, freq, unit, adjustment, conversion, note)
    ("cpi-food", "STATEC/LU1,DSD_ECOICOP_PRIX@DF_E5405,1.0#CP01", "M",
     "Index (2025=100)", "NSA", 1.0,
     "STATEC NCPI CP01 Food & non-alc beverages"),
    ("cpi-clothing", "STATEC/LU1,DSD_ECOICOP_PRIX@DF_E5405,1.0#CP03", "M",
     "Index (2025=100)", "NSA", 1.0,
     "STATEC NCPI CP03 Clothing & footwear"),
    ("cpi-housing-utilities", "STATEC/LU1,DSD_ECOICOP_PRIX@DF_E5405,1.0#CP04", "M",
     "Index (2025=100)", "NSA", 1.0,
     "STATEC NCPI CP04 Housing/water/electricity/gas"),
    ("cpi-transportation", "STATEC/LU1,DSD_ECOICOP_PRIX@DF_E5405,1.0#CP07", "M",
     "Index (2025=100)", "NSA", 1.0,
     "STATEC NCPI CP07 Transport"),
    ("cpi-recreation-and-culture", "STATEC/LU1,DSD_ECOICOP_PRIX@DF_E5405,1.0#CP09", "M",
     "Index (2025=100)", "NSA", 1.0,
     "STATEC NCPI CP09 Recreation & culture"),
    ("cpi-education", "STATEC/LU1,DSD_ECOICOP_PRIX@DF_E5405,1.0#CP10", "M",
     "Index (2025=100)", "NSA", 1.0,
     "STATEC NCPI CP10 Education"),

    ("core-cpi", "STATEC/LU1,DSD_ECOICOP_PRIX@DF_E5409,1.0#TOT_X_NRG_FOOD", "M",
     "Index (2025=100)", "NSA", 1.0,
     "STATEC NCPI special agg core (excl. energy & food)"),
    ("food-inflation", "STATEC/LU1,DSD_ECOICOP_PRIX@DF_E5409,1.0#FOOD", "M",
     "Index (2025=100)", "NSA", 1.0,
     "STATEC NCPI special agg FOOD (level); frontend computes YoY"),
    ("energy-inflation", "STATEC/LU1,DSD_ECOICOP_PRIX@DF_E5409,1.0#NRG", "M",
     "Index (2025=100)", "NSA", 1.0,
     "STATEC NCPI special agg NRG energy (level)"),
    ("services-inflation", "STATEC/LU1,DSD_ECOICOP_PRIX@DF_E5409,1.0#SERV", "M",
     "Index (2025=100)", "NSA", 1.0,
     "STATEC NCPI special agg SERV services (level)"),

    ("gdp-real", "STATEC/LU1,DF_E2504,1.0#r33", "Q",
     "Million EUR (chain-linked, SA)", "SA", 1.0,
     "STATEC DF_E2504 r33 GDP B1*G chain-linked vol SA"),
    ("consumer-spending", "STATEC/LU1,DF_E2504,1.0#r13", "Q",
     "Million EUR (chain-linked, SA)", "SA", 1.0,
     "STATEC DF_E2504 r13 HH consumption chain-linked vol SA"),
    ("government-spending", "STATEC/LU1,DF_E2504,1.0#r15", "Q",
     "Million EUR (chain-linked, SA)", "SA", 1.0,
     "STATEC DF_E2504 r15 Government consumption chain-linked vol SA"),
    ("gross-fixed-capital-formation", "STATEC/LU1,DF_E2504,1.0#r16", "Q",
     "Million EUR (chain-linked, SA)", "SA", 1.0,
     "STATEC DF_E2504 r16 Gross capital formation chain-linked vol SA"),

    ("budget-deficit", "STATEC/LU1,DF_E3101,1.0#L03", "A",
     "% of GDP", "NSA", 1.0,
     "STATEC DF_E3101 L03 GG net lending/borrowing % of GDP"),
    ("government-debt-total", "STATEC/LU1,DF_E3101,1.0#L12", "A",
     "Million EUR", "NSA", 1.0,
     "STATEC DF_E3101 L12 Consolidated gross general government debt"),

    ("retail-sales", "STATEC/LU1,DF_D5108,1.1#G47-TOVV-Y", "M",
     "Index (2021=100, SA)", "SA", 1.0,
     "STATEC DF_D5108 G47 retail trade turnover-value SA, base 2021"),
]


def main():
    inserted = 0
    country = "LU"
    src = "statec_lu"
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
        print(f"  + {country}/{slug:<35} | {src} | {series_id}")
    print(f"\n{inserted} LU statec_lu rows promoted; eurostat siblings demoted.")


if __name__ == "__main__":
    main()
