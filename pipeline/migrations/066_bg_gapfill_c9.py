"""Promote NSI Bulgaria (via BNB SDDS Plus) as default for additional BG slugs.

Migration 045 already wired nsi_bg for inflation-cpi (PCPI_IX), ppi (PPPI_IX),
industrial-production (AIP_IX), employed-persons (LE_PE_NUM), and the NAG
expenditure aggregates (consumer-spending P31, government-spending P3,
gross-fixed-capital-formation P51G, changes-in-inventories P5M, exports P6,
imports P7) plus BOP current-account.

This migration extends to two further mismatches where TE attributes "National
Statistical Institute, Bulgaria" / "Bulgarian National Bank" but the DB still
serves Eurostat:

  gdp-real         NAG file, STO=B1GQ PRICES=Y      Chain-linked volume GDP
                   (reference year 2020), quarterly, mln BGN. TE prints
                   gdp-real as YoY%; the frontend computes YoY on-the-fly.
  budget-deficit   CGO file, INDICATOR=GBXCCB_G01_CA_XDC    Central Government
                   Cash Balance (net lending/borrowing position, mln BGN),
                   monthly — official Ministry of Finance via BNB.

Both new series come from the existing BNB SDDS Plus SDMX-ML files at
https://www.bnb.bg/bnbweb/groups/public/documents/bnb_sdmx/{nag,cgo}.xml so no
new endpoint/credentials needed; provider config in
``pipeline/providers/nsi_bg.py`` (NAG_SERIES extended; new CGO_SERIES block).

TE-conformity smoke (verified 2026-05-15):
  gdp-real         2025-Q4 = 31,096.22 mln BGN chain-linked (real volume)
                   → ~6.4% YoY when computed against 2024-Q4 (matches TE 6.4)
  budget-deficit   2026-03 = -1,036.81 mln BGN  (cash deficit)

BG slugs still served by eurostat (deferred to next cycle):
  business/consumer-confidence -> DG ECFIN survey, not NSI
  cpi-* sub-components         -> NSI publishes via Excel only; pindica/SDMX
                                  channel does not expose COICOP breakdowns
  retail-sales, manufacturing/mining-production -> need NSI Excel scrape
  job-vacancies, labor-force-participation-rate -> NSI quarterly LFS tables
  population                   -> NSI annual demographic publication
  food-inflation               -> YoY of cpi-food; frontend computes on-the-fly
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb


SEEDS = [
    # (slug, series_id, freq, unit, adjustment, conversion, note)
    ("gdp-real", "NSI-BG/NAG/B1GQ_Y", "Q",
     "Million BGN (chain-linked, 2020 prices)", "NSA", 1.0,
     "NSI Bulgaria NAG B1GQ Gross domestic product chain-linked volumes (ref. 2020), quarterly, mln BGN"),
    ("budget-deficit", "NSI-BG/CGO/GBXCCB_G01_CA_XDC", "M",
     "Million BGN", "NSA", 1.0,
     "BNB Bulgaria CGO Central Government Cash Balance (GBXCCB) monthly, mln BGN — TE budget-deficit"),
]


def main():
    inserted = 0
    country = "BG"
    src = "nsi_bg"
    for slug, series_id, freq, unit, adj, conv, note in SEEDS:
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
        print(f"  + {country}/{slug:<32} | {src} | {series_id}")
    print(f"\n{inserted} BG NSI cycle-9 rows promoted; eurostat siblings demoted.")


if __name__ == "__main__":
    main()
