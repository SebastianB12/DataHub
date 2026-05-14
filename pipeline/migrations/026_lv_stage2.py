"""Promote CSP Latvia (Centrala statistikas parvalde) as default source for
stage-2 indicators: unemployment, retail-sales, trade-balance, gdp-real.

CPI (inflation-cpi) is already seeded by 012_national_eu_seeds.py.

Discovery via https://data.stat.gov.lv/api/v1/en/OSP_PUB/ — PxWeb API.
LV PxWeb endpoint expects the bare table ID (no .px suffix), unlike HR/EE.

Not seeded for LV (CSP PxWeb actively returns HTTP 400 for the section-level
"Industry total" aggregate paired with TOVT/calendar-adjusted ContentsCode
combos; only MIG_* breakdowns work, which are not comparable totals):
  - ppi                     (kept on Eurostat fallback)
  - industrial-production   (kept on Eurostat fallback)

Demotes existing eurostat rows for the same (indicator, country) tuples.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb


SEEDS = [
    # (country, slug, src, series_id, freq, unit, adjustment, conversion, note)
    ("LV", "unemployment",  "csp_lv", "CSP/NBB150m", "M",
     "%", "SA", 1.0,
     "CSP Latvia NBB150m unemployment rate 15-74 total SA"),
    ("LV", "retail-sales",  "csp_lv", "CSP/TIT010m", "M",
     "Index (2021=100)", "SA", 1.0,
     "CSP Latvia TIT010m retail trade total turnover index 2021=100 SA"),
    ("LV", "trade-balance", "csp_lv", "CSP/ATD100m", "M",
     "Million EUR", "NSA", 1.0,
     "CSP Latvia ATD100m goods trade balance vs World, NSA, mln EUR"),
    ("LV", "gdp-real",      "csp_lv", "CSP/ISP010c", "Q",
     "Million EUR (2020 chained)", "SA", 0.001,
     "CSP Latvia ISP010c real GDP chain-linked 2020 prices, SA, thousand EUR -> mln EUR"),
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

    print(f"\n{inserted} CSP-direct rows promoted; eurostat counterparts demoted.")


if __name__ == "__main__":
    main()
