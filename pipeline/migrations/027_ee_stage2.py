"""Promote Statistics Estonia (Stat-EE / andmed.stat.ee) as default source for
stage-2 indicators: ppi, industrial-production, retail-sales, gdp-real, unemployment.

CPI (inflation-cpi) is already seeded by 012_national_eu_seeds.py.

Discovery via https://andmed.stat.ee/api/v1/en/stat/ — PxWeb API.
EE PxWeb uses different time conventions per table:
  - IA002 / IA039 use *separate* Aasta (Year) + Kuu (Month) dims
  - RAA0012 uses *separate* Aasta + Kvartal (Quarter I-IV) dims (skip code "1"=annual)
  - TO0053 / KM00338 / TT0160 use a single combined Vaatlusperiood time dim

Not seeded for EE (kept on Eurostat fallback):
  - trade-balance  (the /majandus/valiskaubandus/kaupade_valiskaubandus PxWeb
                    sub-node returns HTTP 400 from the API even when listed in
                    the parent folder)

Demotes existing eurostat rows for the same (indicator, country) tuples.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb


SEEDS = [
    # (country, slug, src, series_id, freq, unit, adjustment, conversion, note)
    ("EE", "ppi",                   "stat_ee", "STATEE/IA039",   "M",
     "Index (2010=100)", "NSA", 1.0,
     "Statistics Estonia IA039 PPI of industrial output total, 2010=100"),
    ("EE", "industrial-production", "stat_ee", "STATEE/TO0053",  "M",
     "Index (2021=100)", "SA", 1.0,
     "Statistics Estonia TO0053 IP volume index BTD seasonally and calendar adjusted, 2021=100"),
    ("EE", "retail-sales",          "stat_ee", "STATEE/KM00338", "Q",
     "Index (2021=100)", "NSA", 1.0,
     "Statistics Estonia KM00338 retail sales volume index G45-47 2021=100 quarterly"),
    ("EE", "gdp-real",              "stat_ee", "STATEE/RAA0012", "Q",
     "Million EUR (2020 chain-linked)", "SA", 1.0,
     "Statistics Estonia RAA0012 real GDP chain-linked vol ref 2020, SA, mln EUR"),
    ("EE", "unemployment",          "stat_ee", "STATEE/TT0160",  "Q",
     "%", "NSA", 1.0,
     "Statistics Estonia TT0160 LFS unemployment rate 15-74 total quarterly"),
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
        print(f"  + {country}/{slug:<22} | {src:<8} | {series_id}")

    print(f"\n{inserted} Stat-EE-direct rows promoted; eurostat counterparts demoted.")


if __name__ == "__main__":
    main()
