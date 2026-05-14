"""TE-conformity gap-fill for Sweden — promote Statistics Sweden (SCB) as default
for CPI subcomponents (KPI by COICOP 2-digit), national-accounts expenditure
components (NR0103B), food-inflation YoY%, LFS employment-rate (AKURLBefM SYSP),
and labour-cost index for salaried employees (AKITM07).

NOT promoted (kept on eurostat or external):
  - services-inflation, energy-inflation: SCB KPI by COICOP doesn't expose direct
    services / energy aggregates. Eurostat ei_cphi_m covers these via CP-HIS/HIE.
  - consumer/business-confidence: published by NIER (Konjunkturinstitutet), not SCB.
    Will be wired via a future konj_se provider; left on eurostat fallback.
  - job-vacancies: SE Public Employment Service (Arbetsförmedlingen), out of scope.
  - government-debt(-total): Riksgälden (Swedish National Debt Office), out of scope.
  - disposable-personal-income, current-account, mining/manufacturing-production,
    population, labor-force-participation-rate, exports/imports goods-only: covered
    or deferred separately.

TE-conformity smoke values (verified 2026-05-14):
  cpi-food                        2026-04 = 125.14  (TE: 125.14)
  cpi-clothing                    2026-04 = 124.95  (TE: 124.95)
  cpi-housing-utilities           2026-04 = 134.93  (TE: 134.93)
  cpi-transportation              2026-04 = 124.89  (TE: 124.89)
  cpi-recreation-and-culture      2026-04 = 119.51
  cpi-education                   2026-04 = 125.47
  food-inflation                  2026-04 = -5.7 %
  employment-rate                 2026-03 = 68.5 %  (TE: 68.5)
  consumer-spending               2025Q4  = 744,967 SEK mn  (TE: 744,967 EXACT)
  changes-in-inventories          2025Q4  = -2,909 SEK mn SA
  government-spending             2025Q4  = 437,456 SEK mn  (TE: 437,456 EXACT)
  gross-fixed-capital-formation   2025Q4  = 421,627 SEK mn  (TE: 421,627 EXACT)
  labour-costs                    2026-02 = 169.2          (TE: 169.2)

Run order:
    python -m pipeline.migrations.049_se_gapfill
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb


SEEDS = [
    ("SE", "cpi-food", "scb_se", "SCB/PR0101A/KPI2020COICOP2M/cpi-food", "M",
     "Index (2020=100)", "NSA", 1.0,
     "SE SCB KPI 2020=100 by COICOP, Food & non-alc beverages (01)"),
    ("SE", "cpi-clothing", "scb_se", "SCB/PR0101A/KPI2020COICOP2M/cpi-clothing", "M",
     "Index (2020=100)", "NSA", 1.0,
     "SE SCB KPI 2020=100 by COICOP, Clothing & footwear (03)"),
    ("SE", "cpi-housing-utilities", "scb_se", "SCB/PR0101A/KPI2020COICOP2M/cpi-housing", "M",
     "Index (2020=100)", "NSA", 1.0,
     "SE SCB KPI 2020=100 by COICOP, Housing/utilities (04)"),
    ("SE", "cpi-transportation", "scb_se", "SCB/PR0101A/KPI2020COICOP2M/cpi-transport", "M",
     "Index (2020=100)", "NSA", 1.0,
     "SE SCB KPI 2020=100 by COICOP, Transport (07)"),
    ("SE", "cpi-recreation-and-culture", "scb_se", "SCB/PR0101A/KPI2020COICOP2M/cpi-recreation", "M",
     "Index (2020=100)", "NSA", 1.0,
     "SE SCB KPI 2020=100 by COICOP, Recreation & culture (09)"),
    ("SE", "cpi-education", "scb_se", "SCB/PR0101A/KPI2020COICOP2M/cpi-education", "M",
     "Index (2020=100)", "NSA", 1.0,
     "SE SCB KPI 2020=100 by COICOP, Education services (10)"),
    ("SE", "food-inflation", "scb_se", "SCB/PR0101A/KPI2020COICOP2M/food-yoy", "M",
     "% YoY", "NSA", 1.0,
     "SE SCB KPI by COICOP Food YoY% (01, ContentsCode 00000809)"),
    ("SE", "employment-rate", "scb_se", "SCB/AM0401A/empl-rate", "M",
     "%", "NSA", 1.0,
     "SE SCB AM0401A LFS Employment Rate 15-74 NSA (SYSP/O_DATA)"),
    ("SE", "consumer-spending", "scb_se", "SCB/NR0103B/consumer-spending", "Q",
     "SEK million (ref 2024)", "SA", 1.0,
     "SE SCB NR0103B Household consumption (KHUS), constant ref 2024 SA, SEK mn"),
    ("SE", "changes-in-inventories", "scb_se", "SCB/NR0103B/inventories", "Q",
     "SEK million (ref 2024)", "SA", 1.0,
     "SE SCB NR0103B Changes in inventories (LA), constant ref 2024 SA, SEK mn"),
    ("SE", "government-spending", "scb_se", "SCB/NR0103B/gov-spending", "Q",
     "SEK million (ref 2024)", "SA", 1.0,
     "SE SCB NR0103B Government consumption (KOFF), constant ref 2024 SA, SEK mn"),
    ("SE", "gross-fixed-capital-formation", "scb_se", "SCB/NR0103B/gfcf", "Q",
     "SEK million (ref 2024)", "SA", 1.0,
     "SE SCB NR0103B GFCF (FBINV), constant ref 2024 SA, SEK mn"),
    ("SE", "labour-costs", "scb_se", "SCB/AM0301A/AKITM07/labour-costs", "M",
     "Index (2008M01=100)", "NSA", 1.0,
     "SE SCB AKITM07 LCI for salaried employees, B-S exkl.O, preliminary (2008M01=100)"),
]


def main():
    inserted = 0
    for country, slug, src, series_id, freq, unit, adj, conv, note in SEEDS:
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
        print(f"  + {country}/{slug:<32} | {src:<8} | {series_id}")
    print(f"\n{inserted} SE TE-conformity rows promoted; eurostat counterparts demoted.")


if __name__ == "__main__":
    main()
