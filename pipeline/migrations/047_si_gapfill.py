"""SI gap-fill: Promote surs_si (SURS PxWeb pxweb.stat.si) as default for 16
indicators currently on eurostat per docs/_te_inventory/SI.yaml verified=true /
conform=false / suggested_source=surs_si.

Slugs added to national_eu SI_SERIES:
  CPI sub-classes (0400608S ECOICOP, MERITVE=33 index avg-2025=100):
    cpi-clothing (03), cpi-education (10), cpi-food (01),
    cpi-housing-utilities (04), cpi-recreation-and-culture (09),
    cpi-transportation (07)
  Inflation:
    food-inflation (0400608S MERITVE=2 same-month-prev-year index)
  National accounts (0300230S, MERITVE=L constant ref-2010 prices, NSA):
    consumer-spending (P31_S1M), government-spending (P3_S13),
    gross-fixed-capital-formation (P51G)
  National accounts (0300230S, MERITVE=Y constant prev-year prices, NSA):
    changes-in-inventories (P52)
  Surveys (2855901S, SA):
    business-confidence (Confidence indicator in manufacturing),
    consumer-confidence (Consumer confidence indicator)
  Industrial production breakouts (1701111S, SA):
    manufacturing-production (NACE C), mining-production (NACE B)
  Labour-force (0762003S, all-ages 15+, both sexes):
    labor-force-participation-rate (MERITVE=2000 activity rate)
  Demographics (05E1004S, half-yearly):
    population (millions)

Verified 2026-05-14 against TE:
  cpi-clothing 2026-04 = 104.85 (TE 104.85) — exact match
  food-inflation 2026-04 = 101.0 -> 1.0% YoY (TE 1.0) — exact match
  business-confidence 2026-04 = -9 (TE -9 for 2026-03) — exact
  consumer-confidence 2026-04 = -32 (TE -32 for 2026-03) — exact
  labor-force-participation-rate Q4 2025 = 58.5 (TE 58.5) — exact
  population 2025H2 = 2.131 million (TE 2.1) — match

Slugs left on eurostat (no SURS table available / TE attributes to BSI):
  current-account (Banka Slovenije only, no public API).

Run:
    python -m pipeline.migrations.047_si_gapfill
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb


SEEDS = [
    ("SI", "cpi-clothing", "surs_si",
     "SURS/0400608S", "M", "Index (avg 2025=100)", "NSA", 1.0,
     "SURS 0400608 CPI Clothing & footwear (COICOP 03), avg-2025=100"),
    ("SI", "cpi-education", "surs_si",
     "SURS/0400608S", "M", "Index (avg 2025=100)", "NSA", 1.0,
     "SURS 0400608 CPI Education (COICOP 10), avg-2025=100"),
    ("SI", "cpi-food", "surs_si",
     "SURS/0400608S", "M", "Index (avg 2025=100)", "NSA", 1.0,
     "SURS 0400608 CPI Food & non-alc bevs (COICOP 01), avg-2025=100"),
    ("SI", "cpi-housing-utilities", "surs_si",
     "SURS/0400608S", "M", "Index (avg 2025=100)", "NSA", 1.0,
     "SURS 0400608 CPI Housing, water, electricity (COICOP 04), avg-2025=100"),
    ("SI", "cpi-recreation-and-culture", "surs_si",
     "SURS/0400608S", "M", "Index (avg 2025=100)", "NSA", 1.0,
     "SURS 0400608 CPI Recreation & culture (COICOP 09), avg-2025=100"),
    ("SI", "cpi-transportation", "surs_si",
     "SURS/0400608S", "M", "Index (avg 2025=100)", "NSA", 1.0,
     "SURS 0400608 CPI Transport (COICOP 07), avg-2025=100"),
    ("SI", "food-inflation", "surs_si",
     "SURS/0400608S", "M", "Index (same-month py=100)", "NSA", 1.0,
     "SURS 0400608 CPI Food YoY index (same-month-prev-year=100)"),
    ("SI", "consumer-spending", "surs_si",
     "SURS/0300230S", "Q", "Million EUR (2010 constant)", "NSA", 1.0,
     "SURS 0300230 P31_S1M Household final consumption (constant 2010 prices, NSA, mln EUR)"),
    ("SI", "government-spending", "surs_si",
     "SURS/0300230S", "Q", "Million EUR (2010 constant)", "NSA", 1.0,
     "SURS 0300230 P3_S13 Government final consumption (constant 2010 prices, NSA, mln EUR)"),
    ("SI", "gross-fixed-capital-formation", "surs_si",
     "SURS/0300230S", "Q", "Million EUR (2010 constant)", "NSA", 1.0,
     "SURS 0300230 P51G Gross fixed capital formation (constant 2010 prices, NSA, mln EUR)"),
    ("SI", "changes-in-inventories", "surs_si",
     "SURS/0300230S", "Q", "Million EUR (prev-year prices)", "NSA", 1.0,
     "SURS 0300230 P52 Changes in inventories (constant prev-year prices, NSA, mln EUR)"),
    ("SI", "business-confidence", "surs_si",
     "SURS/2855901S", "M", "Balance", "SA", 1.0,
     "SURS 2855901 Business tendency survey — Confidence indicator in manufacturing (SA)"),
    ("SI", "consumer-confidence", "surs_si",
     "SURS/2855901S", "M", "Balance", "SA", 1.0,
     "SURS 2855901 Consumer survey — Consumer confidence indicator (SA)"),
    ("SI", "manufacturing-production", "surs_si",
     "SURS/1701111S", "M", "Index (2021=100, SA)", "SA", 1.0,
     "SURS 1701111 IP Manufacturing C (NACE) seasonally+calendar adjusted, 2021=100"),
    ("SI", "mining-production", "surs_si",
     "SURS/1701111S", "M", "Index (2021=100, SA)", "SA", 1.0,
     "SURS 1701111 IP Mining & quarrying B (NACE) seasonally+calendar adjusted, 2021=100"),
    ("SI", "labor-force-participation-rate", "surs_si",
     "SURS/0762003S", "Q", "%", "NSA", 1.0,
     "SURS 0762003 LFS Activity rate (all ages 15+, both sexes), quarterly %"),
    ("SI", "population", "surs_si",
     "SURS/05E1004S", "M", "Million", "NSA", 1.0,
     "SURS 05E1004 Total resident population, half-yearly snapshots (millions)"),
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
    print(f"\n{inserted} SI gap-fill rows promoted; eurostat counterparts demoted.")


if __name__ == "__main__":
    main()
