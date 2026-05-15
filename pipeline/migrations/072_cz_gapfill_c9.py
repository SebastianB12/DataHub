"""TE-conformity gap-fill (cycle 9) for Czech Republic — promote CZSO as default
for 2 additional series.

Series added to czso.SERIES (Migration 072 block):
  - gdp-real     : WNUC01D 9988J10 quarterly real GDP YoY % SA
  - government-debt-total: alias of government-debt (WNUC05D 600602 annual mil Kc)

NOT migrated (CZSO open-data CSV not exposed or out of scope):
  - budget-deficit, government-spending, current-account-to-gdp,
    changes-in-inventories, exports, imports, job-vacancies, population:
    CZSO open-data API does not expose these tables via /opendata/sady/.
    Probed 2026-05-15: VZO01/PRA01/OFI01/etc all return 404. CSU's modern
    publication path is via czso.cz web pages (HTML scraping) or CNB SDMX
    for BoP-related items. Deferred to a follow-up batch.

TE-conformity smoke values (verified 2026-05-15):
  gdp-real (YoY%, SA)             2025Q4 = 2.7 %  (TE: 2.5 % close, vintage diff)
  government-debt-total (mil Kc)  2025   = same as government-debt series

Run order:
    python -m pipeline.migrations.072_cz_gapfill_c9
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb


SEEDS = [
    ("CZ", "gdp-real", "czso", "CZSO/WNUC01D/9988J10", "Q",
     "% YoY", "SA", 1.0,
     "CZSO WNUC01D Quarterly real GDP, YoY % SA"),
    ("CZ", "government-debt-total", "czso", "CZSO/WNUC05D/600602:total", "A",
     "mil Kc", "NSA", 1.0,
     "CZSO WNUC05D General government gross consolidated debt (alias of government-debt)"),
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
        print(f"  + {country}/{slug:<32} | {src:<8} | {series_id}")
    print(f"\n{inserted} CZ TE-conformity rows promoted (cycle 9); eurostat demoted.")
    print("Run `pipeline/.venv/Scripts/python -m pipeline.providers.czso` to ingest.")


if __name__ == "__main__":
    main()
