"""Promote NSI Bulgaria as primary source for BG indicators.

NSI = National Statistical Institute (Национален статистически институт).
Source label: ``nsi_bg``. Data is fetched via BNB's SDDS Plus dissemination
endpoint (BNB hosts the standardised SDMX-ML files on behalf of NSI):

  https://www.bnb.bg/bnbweb/groups/public/documents/bnb_sdmx/<topic>.xml

Three indicators promoted (2026-05-09):
  inflation-cpi     PCPI_IX  monthly index 2025=100   (375 obs back to 1995-01)
  ppi               PPPI_IX  monthly index 2021=100   (255 obs back to 2005-01)
  employed-persons  LE_PE_NUM quarterly (thousand persons, NA basis)

TE labels these "National Statistical Institute, Bulgaria" — exact match.

Why not NSI's own SDMX endpoint?
  * www.nsi.bg/sdmxwebclient/ exposes only ~20 dataflows (Tourism, Agriculture,
    Structural Business, NA_MAIN). No CPI/PPI/LFS dataflows are published.
  * www.nsi.bg/restsdmx/sdmx.ashx is behind an F5 WAF that rejects all calls.
  * BNB's bnb_sdmx/ files are the canonical SDDS Plus disclosures and contain
    the same NSI-produced numbers in a fully-documented IMF format
    (ECOFIN_DSD), so the source label still maps to NSI.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb

# (country, slug, src, series_id, freq, unit, adjustment, conversion, note)
SEEDS = [
    ("BG", "inflation-cpi",    "nsi_bg", "NSI-BG/PCPI_IX",  "M", "Index (2025=100)", "NSA", 1.0,
     "NSI Bulgaria CPI (PCPI_IX), base 2025=100, monthly, via BNB SDDS Plus SDMX"),
    ("BG", "ppi",              "nsi_bg", "NSI-BG/PPPI_IX",  "M", "Index (2021=100)", "NSA", 1.0,
     "NSI Bulgaria PPI (PPPI_IX), base 2021=100, monthly, via BNB SDDS Plus SDMX"),
    ("BG", "employed-persons", "nsi_bg", "NSI-BG/LE_PE_NUM", "Q", "Thousand",        "NSA", 1.0,
     "NSI Bulgaria Employed Persons (LE_PE_NUM), thousand persons, quarterly (NA basis), via BNB SDDS Plus SDMX"),
]


def main():
    inserted = 0
    for country, slug, src, series_id, freq, unit, adj, conv, note in SEEDS:
        # Idempotent: drop existing nsi_bg row for this slug
        sb.table("indicator_sources").delete().eq(
            "indicator", slug
        ).eq("country", country).eq("source", src).execute()
        # Demote any prior default for this (slug, country) — eurostat/dbnomics/etc.
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
    print(f"\n{inserted} NSI Bulgaria rows promoted; existing BG defaults demoted.")


if __name__ == "__main__":
    main()
