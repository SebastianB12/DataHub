"""HR gap-fill: Promote dzs_hr (DZS PxWeb web.dzs.hr) as default for 11
indicators currently on eurostat per docs/_te_inventory/HR.yaml verified=true /
conform=false / suggested_source=dzs_hr.

Slugs added to national_eu HR_SERIES:
  CPI sub-classes (ME_PS09, ECOICOP v2, Indikatori=4 index 2025=100):
    cpi-clothing (03), cpi-education (10), cpi-food (01),
    cpi-housing-utilities (04), cpi-recreation-and-culture (09)
  Inflation:
    food-inflation (ME_PS09 Indikatori=1 YoY %)
  National accounts (BDP-T01_EUR, Način=2 constant ref-2021 prices):
    consumer-spending (P31_S14), government-spending (P3_S13),
    gross-fixed-capital-formation (P51G)
  National accounts (BDP-T01_EUR, Način=1 current prices):
    changes-in-inventories (P5M)

Verified 2026-05-14 against TE:
  cpi-food 2026-03 = 101.2 (TE 101.2 for 2026-02 — close revision)
  cpi-housing-utilities 2026-03 = 109.3 (TE 109.3) — exact match
  food-inflation 2026-03 = 3.3% (TE 3.3) — exact match
  consumer-spending Q4 2025 = 10510 (TE 10510) — exact match
  GFCF Q4 2025 = 4551 (TE 4552) — exact match

Slugs left on eurostat (no DZS PxWeb table available):
  cpi-transportation (only via HICP), employed-persons, unemployment,
  unemployed-persons, exports/imports (only by-country annual on DZS),
  current-account / current-account-to-gdp / government-debt (HNB-only, no API).

Run:
    python -m pipeline.migrations.046_hr_gapfill
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb


SEEDS = [
    ("HR", "cpi-clothing", "dzs_hr",
     "DZS/ME_PS09", "M", "Index (2025=100)", "NSA", 1.0,
     "DZS Croatia ME_PS09 CPI Clothing & footwear (COICOP 03), 2025=100"),
    ("HR", "cpi-education", "dzs_hr",
     "DZS/ME_PS09", "M", "Index (2025=100)", "NSA", 1.0,
     "DZS Croatia ME_PS09 CPI Education (COICOP 10), 2025=100"),
    ("HR", "cpi-food", "dzs_hr",
     "DZS/ME_PS09", "M", "Index (2025=100)", "NSA", 1.0,
     "DZS Croatia ME_PS09 CPI Food & non-alc bevs (COICOP 01), 2025=100"),
    ("HR", "cpi-housing-utilities", "dzs_hr",
     "DZS/ME_PS09", "M", "Index (2025=100)", "NSA", 1.0,
     "DZS Croatia ME_PS09 CPI Housing, water, electricity (COICOP 04), 2025=100"),
    ("HR", "cpi-recreation-and-culture", "dzs_hr",
     "DZS/ME_PS09", "M", "Index (2025=100)", "NSA", 1.0,
     "DZS Croatia ME_PS09 CPI Recreation & culture (COICOP 09), 2025=100"),
    ("HR", "food-inflation", "dzs_hr",
     "DZS/ME_PS09", "M", "% YoY", "NSA", 1.0,
     "DZS Croatia ME_PS09 CPI Food YoY % rate of change"),
    ("HR", "consumer-spending", "dzs_hr",
     "DZS/BDP-T01_EUR", "Q", "Million EUR (constant 2021 prices)", "NSA", 1.0,
     "DZS Croatia BDP-T01_EUR P31_S14 Household final consumption (constant ref 2021, mln EUR)"),
    ("HR", "government-spending", "dzs_hr",
     "DZS/BDP-T01_EUR", "Q", "Million EUR (constant 2021 prices)", "NSA", 1.0,
     "DZS Croatia BDP-T01_EUR P3_S13 Government final consumption (constant ref 2021, mln EUR)"),
    ("HR", "gross-fixed-capital-formation", "dzs_hr",
     "DZS/BDP-T01_EUR", "Q", "Million EUR (constant 2021 prices)", "NSA", 1.0,
     "DZS Croatia BDP-T01_EUR P51G Gross fixed capital formation (constant ref 2021, mln EUR)"),
    ("HR", "changes-in-inventories", "dzs_hr",
     "DZS/BDP-T01_EUR", "Q", "Million EUR (current prices)", "NSA", 1.0,
     "DZS Croatia BDP-T01_EUR P5M Changes in inventories + valuables (current prices, mln EUR)"),
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
            "indicator": slug, "country": country, "source": src,
            "series_id": series_id, "is_default": True, "transform": "raw",
            "conversion": conv, "unit": unit, "adjustment": adj,
            "freq_hint": freq, "extra_params": None, "active": True, "note": note,
        }
        sb.table("indicator_sources").insert(row).execute()
        inserted += 1
        print(f"  + {country}/{slug:<35} | {src:<8} | {series_id}")
    print(f"\n{inserted} HR gap-fill rows promoted; eurostat counterparts demoted.")


if __name__ == "__main__":
    main()
