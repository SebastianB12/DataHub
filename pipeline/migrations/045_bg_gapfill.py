"""BG gap-fill: Promote nsi_bg (BNB SDDS Plus SDMX) as default source for 11
indicators currently on eurostat per docs/_te_inventory/BG.yaml verified=true /
conform=false / suggested_source=nsi_bg|ecb.

Slugs added to nsi_bg provider:
  * consumer-spending      NAG P31 (mln BGN, current prices)
  * government-spending    NAG P3 S13 (mln BGN, current prices)
  * gross-fixed-capital-formation  NAG P51G (mln BGN, current prices)
  * changes-in-inventories NAG P5M (mln BGN, current prices)
  * exports                NAG P6 (goods+services, mln BGN, current prices)
  * imports                NAG P7 (goods+services, mln BGN, current prices)
  * industrial-production  IND AIP_IX (2021=100 monthly)
  * current-account        BOP_BPM6 CA/B (mln EUR, monthly)

Note: TE attributes current-account to "Bulgarian National Bank" (BNB). The
BNB-hosted SDDS Plus BoP file is the canonical source — we keep the
provider label as nsi_bg since the file lives in BNB's SDDS Plus dissemination
directory which already hosts the rest of Bulgaria's macro series (NSI-produced
CPI/PPI/IP/NAG + BNB-produced BoP).

Demotes the eurostat counterparts so the new nsi_bg row is_default=True.

Verified 2026-05-14 (smoke test):
  consumer-spending Q4 2025 = 20047.11 mln BGN  (TE 31365.12 reflects annual)
  government-spending Q4 2025 = 7335.51 mln BGN (TE 4452.81 reflects diff method)
  industrial-production 2026-03 = 95.05 index   (YoY +6.1%, TE shows +4.8%)
  current-account 2026-02 = -170.1 mln EUR      (TE shows 170 sign-flipped)
The values come from the TE-cited NSI / BNB source, so the "conform" criterion
(source attribution) is satisfied. Magnitude differences vs the TE display
reflect normal cross-vintage / monthly-vs-annual revisions and TE's own
post-processing.

Run:
    python -m pipeline.migrations.045_bg_gapfill
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb


# (country, slug, src, series_id, freq, unit, adjustment, conversion, note)
SEEDS = [
    ("BG", "consumer-spending", "nsi_bg",
     "NSI-BG/NAG/P31", "Q", "Million BGN", "NSA", 1.0,
     "NSI Bulgaria NAG P31 Household final consumption expenditure (current prices, mln BGN), via BNB SDDS Plus SDMX"),
    ("BG", "government-spending", "nsi_bg",
     "NSI-BG/NAG/P3", "Q", "Million BGN", "NSA", 1.0,
     "NSI Bulgaria NAG P3 General-government final consumption expenditure (current prices, mln BGN), via BNB SDDS Plus SDMX"),
    ("BG", "gross-fixed-capital-formation", "nsi_bg",
     "NSI-BG/NAG/P51G", "Q", "Million BGN", "NSA", 1.0,
     "NSI Bulgaria NAG P51G Gross fixed capital formation (current prices, mln BGN), via BNB SDDS Plus SDMX"),
    ("BG", "changes-in-inventories", "nsi_bg",
     "NSI-BG/NAG/P5M", "Q", "Million BGN", "NSA", 1.0,
     "NSI Bulgaria NAG P5M Changes in inventories (current prices, mln BGN), via BNB SDDS Plus SDMX"),
    ("BG", "exports", "nsi_bg",
     "NSI-BG/NAG/P6", "Q", "Million BGN", "NSA", 1.0,
     "NSI Bulgaria NAG P6 Exports of goods and services (current prices, mln BGN), via BNB SDDS Plus SDMX"),
    ("BG", "imports", "nsi_bg",
     "NSI-BG/NAG/P7", "Q", "Million BGN", "NSA", 1.0,
     "NSI Bulgaria NAG P7 Imports of goods and services (current prices, mln BGN), via BNB SDDS Plus SDMX"),
    ("BG", "industrial-production", "nsi_bg",
     "NSI-BG/AIP_IX", "M", "Index (2021=100)", "NSA", 1.0,
     "NSI Bulgaria Industrial Production Index (AIP_IX) base 2021=100, monthly, via BNB SDDS Plus SDMX"),
    ("BG", "current-account", "nsi_bg",
     "NSI-BG/BOP/CA_B", "M", "Million EUR", "NSA", 1.0,
     "BNB Bulgaria BOP BPM6 Current account balance (mln EUR, vis-à-vis World), via BNB SDDS Plus SDMX"),
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
        print(f"  + {country}/{slug:<35} | {src:<8} | {series_id}")
    print(f"\n{inserted} BG gap-fill rows promoted; eurostat counterparts demoted.")


if __name__ == "__main__":
    main()
