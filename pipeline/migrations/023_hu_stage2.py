"""Promote KSH (Hungary) as default source for 6 additional Tier-1 indicators.

Stage 1 (012_national_eu_seeds.py) seeded only inflation-cpi from KSH; the
remaining HU indicators relied on Eurostat / WorldBank. This migration
expands KSH coverage to PPI, industrial-production, unemployment-rate,
retail-sales, trade-balance, and gdp-real, all scraped directly from
www.ksh.hu/stadat_files/ HTML tables (NationalEUProvider).

Tables used (KSH STADAT IDs):

  ppi                    -> ara0055 "Producer price indices of industry,
                            monthly" — Total industry (B+C+D+E) base 2021=100.
  industrial-production  -> ipa0072 "Volume index of industrial production
                            monthly" — Hungary column in EU comparison table.
  unemployment-rate      -> mun0098 "Economic activity of population aged
                            15-64 by sex, monthly" — LFS unemployment rate %.
  retail-sales           -> bel0020 "Calendar effect adjusted volume indices
                            on retail sales by type of shop, monthly" — Total.
  trade-balance          -> kkr0065 - kkr0064 (exports minus imports, mEUR);
                            derived in fetch_hu_trade_balance().
  gdp-real               -> gdp0086 "Quarterly volume indices of GDP" —
                            unadjusted raw YoY index.

All entries demote prior defaults (eurostat / worldbank) for the same
(indicator, country) tuple.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb

# (country, slug, src, series_id, freq, unit, adjustment, conversion, note)
SEEDS = [
    ("HU", "ppi",                   "ksh_hu", "KSH/ara0055",
     "M", "Index (2021=100)", "NSA", 1.0,
     "KSH STADAT 1.2.1.19 ara0055 PPI Total industry (B+C+D+E) base 2021=100"),
    ("HU", "industrial-production", "ksh_hu", "KSH/ipa0072",
     "M", "Index (same month previous year=100)", "WDA", 1.0,
     "KSH STADAT 13.2.3.1 ipa0072 IPI Hungary WDA, YoY index"),
    ("HU", "unemployment-rate",     "ksh_hu", "KSH/mun0098",
     "M", "%", "NSA", 1.0,
     "KSH STADAT 20.2.1.3 mun0098 LFS unemployment rate 15-64 Total %"),
    ("HU", "retail-sales",          "ksh_hu", "KSH/bel0020",
     "M", "Index (same month previous year=100)", "WDA", 1.0,
     "KSH STADAT 2.2.1.7 bel0020 Retail sales total calendar-adjusted YoY"),
    ("HU", "trade-balance",         "ksh_hu", "KSH/kkr_synthetic",
     "M", "Million EUR", "NSA", 1.0,
     "KSH STADAT 17.2.3.1+17.2.3.2 kkr0065-kkr0064 HU exports minus imports, mEUR"),
    ("HU", "gdp-real",              "ksh_hu", "KSH/gdp0086",
     "Q", "Index (same quarter previous year=100)", "NSA", 1.0,
     "KSH STADAT 21.2.1.2 gdp0086 GDP volume index unadjusted YoY"),
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
        print(f"  + {country}/{slug:<22} | {src:<7} | {series_id}")
    print(f"\n{inserted} KSH Hungary rows promoted; existing HU defaults demoted.")


if __name__ == "__main__":
    main()
