"""Promote Statistics Denmark (Statbank) as default source for stage-2 DK indicators.

Migration 014_dk_statbank_expand.py already promoted DST for:
  ppi, gdp, gdp-real, trade-balance, exports, imports, employed-persons.

This migration extends to TE-aligned consumer-confidence, business-confidence and
unemployed-persons (registered) — currently served by eurostat — and demotes the
eurostat siblings.

Series:
  consumer-confidence -> DST/FORV1   (INDIKATOR=F1 headline)
  business-confidence -> DST/ETILLID (INDIKATOR=KBI industry; matches TE 100.7 Apr 2026)
  unemployed-persons  -> DST/AUS09   (YDELSESTYPE=LDM, SAESONFAK=24 NSA, in thousands)

TE-conformity (verified 2026-05-14):
  consumer-confidence  : DK FORV1 F1   2026M04 = -18.6  (TE: -18.6) MATCH
  business-confidence  : DK ETILLID KBI 2026M04 = 100.7 (TE: 100.7) MATCH
  unemployed-persons   : DK AUS09 LDM/24 2026M03 = 82.0k (TE: 80.9k, NSA vintage)

Not seeded (kept on eurostat or already DST-default):
  industrial-production, retail-sales, ppi, gdp-real, trade-balance,
  exports, imports, employed-persons -> already DST (migrations 012 + 014).
  cpi-* sub-components: TE pulls PRIS117 (HICP, ENHED=100). Out of scope for
  Stage-2 (would expand indicator catalog; revisit in CPI-subcomponent batch).
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb


SEEDS = [
    # (country, slug, src, series_id, freq, unit, adjustment, conversion, note)
    ("DK", "consumer-confidence", "dst", "DST/FORV1",   "M",
     "Balance", "NSA", 1.0,
     "DK Statbank FORV1 consumer confidence indicator (F1 headline)"),
    ("DK", "business-confidence", "dst", "DST/ETILLID", "M",
     "Index (2015=100)", "SA", 1.0,
     "DK Statbank ETILLID business sentiment, industry KBI (TE headline)"),
    ("DK", "unemployed-persons",  "dst", "DST/AUS09",   "M",
     "Thousand", "NSA", 0.001,
     "DK Statbank AUS09 registered unemployed (LDM, NSA, in 1000s)"),
]


def main():
    inserted = 0
    for country, slug, src, series_id, freq, unit, adj, conv, note in SEEDS:
        # Delete same-source row if any (idempotent re-runs)
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
    print(f"\n{inserted} DK Statbank stage-2 rows promoted; eurostat siblings demoted.")


if __name__ == "__main__":
    main()
