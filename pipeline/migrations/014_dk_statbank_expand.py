"""Promote Statistics Denmark (Statbank) as default source for additional DK indicators.

Adds 7 new TE-aligned series to the existing DK coverage (inflation-cpi, IP, unemployment,
retail-sales already seeded by 012_national_eu_seeds.py):

  ppi              -> DST/PRIS4221  (Producer price index, BC mining+manufacturing, Index)
  gdp              -> DST/NAN1      (Annual GDP, current prices, bn DKK)
  gdp-real         -> DST/NKHO2     (Quarterly real GDP, 2020 chained, SA)
  trade-balance    -> DST/BBM       (Monthly Goods FOB trade balance, SA, mio DKK)
  exports          -> DST/BBM       (Monthly Goods FOB exports, SA, mio DKK)
  imports          -> DST/BBM       (Monthly Goods FOB imports, SA, mio DKK)
  employed-persons -> DST/LBESK104  (Monthly employees all sectors, SA, in 1000s)

Demotes existing eurostat / worldbank rows for the same (indicator, country) tuples.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb

SEEDS = [
    # (country, slug, src, series_id, freq, unit, adjustment, conversion, note)
    ("DK", "ppi",              "dst", "DST/PRIS4221",  "M", "Index",                       "NSA", 1.0,   "DK Statbank PRIS4221 PPI BC mining+manufacturing index"),
    ("DK", "gdp",              "dst", "DST/NAN1",      "A", "Billion DKK",                 "NSA", 1.0,   "DK Statbank NAN1 GDP at market prices, current prices, bn DKK"),
    ("DK", "gdp-real",         "dst", "DST/NKHO2",     "Q", "Million DKK (2020 chained)",  "SA",  1.0,   "DK Statbank NKHO2 quarterly real GDP chained 2020 prices, SA"),
    ("DK", "trade-balance",    "dst", "DST/BBM",       "M", "Million DKK",                 "SA",  1.0,   "DK Statbank BBM Goods FOB trade balance vs World, SA, mio DKK"),
    ("DK", "exports",          "dst", "DST/BBM/exp",   "M", "Million DKK",                 "SA",  1.0,   "DK Statbank BBM Goods FOB exports vs World, SA, mio DKK"),
    ("DK", "imports",          "dst", "DST/BBM/imp",   "M", "Million DKK",                 "SA",  1.0,   "DK Statbank BBM Goods FOB imports vs World, SA, mio DKK"),
    ("DK", "employed-persons", "dst", "DST/LBESK104",  "M", "Thousand",                    "SA",  0.001, "DK Statbank LBESK104 employees all sectors SA, thousands"),
]


def main():
    inserted = 0
    for country, slug, src, series_id, freq, unit, adj, conv, note in SEEDS:
        # Delete same-source row if any
        sb.table("indicator_sources").delete().eq(
            "indicator", slug
        ).eq("country", country).eq("source", src).execute()
        # Demote any existing default row from other sources for this (slug, country)
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
        print(f"  + {country}/{slug:<22} | {src:<8} | {series_id}")
    print(f"\n{inserted} DK Statbank rows promoted as default; sibling sources demoted.")


if __name__ == "__main__":
    main()
