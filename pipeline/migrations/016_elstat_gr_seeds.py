"""Promote ELSTAT direct as default for GR core indicators.

ELSTAT (Hellenic Statistical Authority) is the source TE shows for Greek
inflation, industrial production, and unemployment. We download its XLS/XLSX
publication files directly from www.statistics.gr (publication codes DKT87,
DKT21, SJO02) — there is no public SDMX REST API.

Verified 2026-05-09 against TE:
  - inflation-cpi          DKT87 doc 114838 — Apr 2026 = 126.83 → YoY +5.45%
                                              (TE shows 5.40% rounded)
  - industrial-production  DKT21 doc 114474 — Feb 2026 SA index 115.88
                                              (TE Feb 2026 +1.8% YoY)
  - unemployment           SJO02 doc 116021 — Mar 2026 SA = 9.0%
                                              (TE: 9.0%)
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb

# (country, slug, src, series_id, freq, unit, adjustment, conversion, note)
SEEDS = [
    ("GR", "inflation-cpi",         "elstat",
     "ELSTAT/DKT87/114838", "M",
     "Index (2020=100)", "NSA", 1.0,
     "ELSTAT DKT87 Table IV monthly Overall CPI base 2020=100 (1959 onwards)"),
    ("GR", "industrial-production", "elstat",
     "ELSTAT/DKT21/114474", "M",
     "Index (2021=100)", "SA", 1.0,
     "ELSTAT DKT21 Seasonally Adjusted Industrial Production Index 2021=100 (2000 onwards)"),
    ("GR", "unemployment",          "elstat",
     "ELSTAT/SJO02/116021", "M",
     "%", "SA", 1.0,
     "ELSTAT SJO02 Table 1A LFS monthly unemployment rate (seasonally adjusted, 2004 onwards)"),
]


def main():
    inserted = 0
    for country, slug, src, series_id, freq, unit, adj, conv, note in SEEDS:
        # Idempotent: delete any prior elstat row
        sb.table("indicator_sources").delete().eq(
            "indicator", slug
        ).eq("country", country).eq("source", src).execute()
        # Demote any other default for this (country, slug)
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

    # Register the data_source row so scheduler can pick it up
    existing = sb.table("data_sources").select("slug").eq("slug", "elstat").execute()
    if not existing.data:
        sb.table("data_sources").insert({
            "slug": "elstat",
            "name": "Hellenic Statistical Authority (ELSTAT)",
            "schedule": "interval:6h",
            "enabled": True,
            "config": {"base_url": "https://www.statistics.gr"},
        }).execute()
        print("  + data_sources.elstat registered")
    else:
        print("  = data_sources.elstat already present")

    print(f"\n{inserted} ELSTAT-direct rows promoted; previous defaults demoted.")


if __name__ == "__main__":
    main()
