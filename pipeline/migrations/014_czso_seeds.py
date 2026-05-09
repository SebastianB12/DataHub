"""Promote CZSO (Czech Statistical Office) as primary source for CZ indicators.

Seeds 4 series per CZ country:
  inflation-cpi         CEN0101E  monthly index 2025=100
  ppi                   CEN0201A  monthly index 2015=100
  industrial-production PRU01D    monthly index 2021=100
  unemployment          ZAM01     quarterly ILO unemployment rate %

Demotes any existing eurostat/dbnomics/curated rows for these CZ slugs to fallback.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb

# (country, slug, src, series_id, freq, unit, adjustment, conversion, note)
SEEDS = [
    ("CZ", "inflation-cpi",         "czso", "CZSO/CEN0101E", "M", "Index (2025=100)",  "NSA", 1.0,
     "CZSO CEN0101E CPI total all-items, base 2025=100, monthly"),
    ("CZ", "ppi",                   "czso", "CZSO/CEN0201A", "M", "Index (2015=100)",  "NSA", 1.0,
     "CZSO CEN0201A PPI total industry (BTE36), base 2015=100, monthly"),
    ("CZ", "industrial-production", "czso", "CZSO/PRU01D",   "M", "Index (2021=100)",  "NSA", 1.0,
     "CZSO PRU01D Industrial Production total industry, base 2021=100, monthly"),
    ("CZ", "unemployment",          "czso", "CZSO/ZAM01",    "Q", "%",                 "NSA", 1.0,
     "CZSO ZAM01 ILO unemployment rate (Obecná míra nezaměstnanosti), quarterly"),
]


def main():
    inserted = 0
    for country, slug, src, series_id, freq, unit, adj, conv, note in SEEDS:
        # Delete same-source row if any (idempotent rerun)
        sb.table("indicator_sources").delete().eq(
            "indicator", slug
        ).eq("country", country).eq("source", src).execute()
        # Demote any prior default for this (slug, country) — eurostat/dbnomics/curated/etc.
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
        print(f"  + {country}/{slug:<22} | {src:<6} | {series_id}")
    print(f"\n{inserted} CZSO rows promoted; existing CZ defaults demoted.")


if __name__ == "__main__":
    main()
