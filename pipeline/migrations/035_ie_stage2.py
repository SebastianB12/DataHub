"""Stage-2 expansion: Promote cso_ie as default for IE exports, imports, and
employed-persons. CPI/PPI/IP/unemployment/retail-sales/trade-balance/gdp-real/
housing-index already on cso_ie (seeded in 012_national_eu_seeds.py).

CSO PxStat tables verified 2026-05-14 against TE:
  - employed-persons QLF18C03 (15+ both sexes): 2025Q4 = 2833.1 thousand
  - exports TSM01C2 (Total Exports, NSA): 2026M02 = 15,894,938 EUR thousand
  - imports TSM01C1 (Total Imports, NSA): 2026M02 = 11,291,776 EUR thousand
  - (trade-balance TSM01C3 already published via cso_ie, series_id refined to
     CSO/TSM01/tb so the three TSM01 slices have distinct series_ids.)

Demotes any prior eurostat defaults for the same (indicator, IE) tuples.

Run order:
    python -m pipeline.migrations.035_ie_stage2
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb


# (country, slug, src, series_id, freq, unit, adjustment, conversion, note)
SEEDS = [
    ("IE", "exports", "cso_ie",
     "CSO/TSM01/exp", "M",
     "EUR thousand", "NSA", 1.0,
     "CSO Ireland TSM01 Total Exports of Goods NSA, EUR thousand"),
    ("IE", "imports", "cso_ie",
     "CSO/TSM01/imp", "M",
     "EUR thousand", "NSA", 1.0,
     "CSO Ireland TSM01 Total Imports of Goods NSA, EUR thousand"),
    ("IE", "employed-persons", "cso_ie",
     "CSO/QLF18", "Q",
     "Thousand", "NSA", 1.0,
     "CSO Ireland QLF18 LFS persons in employment 15+ both sexes (thousand)"),
    # Refresh existing trade-balance row to align series_id with new disambiguator
    ("IE", "trade-balance", "cso_ie",
     "CSO/TSM01/tb", "M",
     "EUR thousand", "NSA", 1.0,
     "CSO Ireland TSM01 Merchandise Trade Surplus (Exports-Imports) NSA"),
]


def main():
    inserted = 0
    for country, slug, src, series_id, freq, unit, adj, conv, note in SEEDS:
        # Idempotent: clear any existing same-source row for this (slug, country)
        sb.table("indicator_sources").delete().eq(
            "indicator", slug
        ).eq("country", country).eq("source", src).execute()
        # Demote any other defaults for this (slug, country)
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
    print(f"\n{inserted} IE stage-2 rows promoted; eurostat counterparts demoted.")


if __name__ == "__main__":
    main()
