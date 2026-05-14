"""Stage-2 INE-Spain promotion: extend ine_es default-source coverage.

Per TE-source-first audit (docs/_te_inventory/ES.yaml, 2026-05-14), TE attributes
the Spain inflation sub-components and national-accounts demand-side aggregates
to INE Spain. The eurostat-default rows are demoted; new ine_es rows promoted.

Slugs covered:
  CPI sub-components (monthly Index level, table 76130 special-groups):
    - services-inflation              IPC292495
    - energy-inflation                IPC292459
  National-accounts demand side (quarterly, SA, current prices, table 67823):
    - consumer-spending               CNTR6845   (Household final consumption)
    - government-spending             CNTR6860   (General-government final consumption)
    - gross-fixed-capital-formation   CNTR6875   (FBCF)
  Industrial Production split:
    - manufacturing-production        IPI13870   (CNAE Section C)

Also fixes the core-cpi series_id: previous 014_ine_es_extension.py kept INE:IPC290851,
but that COD is "Bienes y servicios mantenimiento del hogar" (COICOP05) — NOT subyacente.
Correct code is IPC292511 ("Subyacente: General sin alimentos no elaborados ni productos
energéticos"), YoY for Apr-2026 = 2.8% matching TE te_value=2.8.

Not migrated (INE doesn't publish a clean total series, eurostat remains default):
  - long-term-unemployment-rate (EPA tables only by age-split, no total 16-74 rate)
  - exports / imports / trade-balance (INE Spain doesn't publish these; ES uses
    Ministerio de Industria/DATACOMEX or eurostat ext_st_eu27_2020sitc)

Run order: after 028_lt_stage2. Idempotent (delete then insert).
"""
import sys

sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb


INE_SLUGS = [
    # (slug, series_id, unit, adjustment, freq, conversion, note)
    # --- Core CPI correction ---
    ("core-cpi",                       "INE:IPC292511", "Index",       "NSA", "M", 1.0,
     "INE IPC Subyacente (ex unprocessed food + energy), base 2025=100 (corrects "
     "previous IPC290851 mismatch)"),
    # --- CPI sub-components ---
    ("services-inflation",             "INE:IPC292495", "Index",       "NSA", "M", 1.0,
     "INE IPC Servicios Index level (special groups), base 2025=100"),
    ("energy-inflation",               "INE:IPC292459", "Index",       "NSA", "M", 1.0,
     "INE IPC Productos energéticos Index level (special groups), base 2025=100"),
    # --- National accounts demand side, SA, EUR Mn current prices ---
    ("consumer-spending",              "INE:CNTR6845",  "EUR Million", "SA",  "Q", 1.0,
     "INE CNTR Household final consumption (SA, current prices), EUR Mn"),
    ("government-spending",            "INE:CNTR6860",  "EUR Million", "SA",  "Q", 1.0,
     "INE CNTR General-government final consumption (SA, current prices), EUR Mn"),
    ("gross-fixed-capital-formation",  "INE:CNTR6875",  "EUR Million", "SA",  "Q", 1.0,
     "INE CNTR Gross fixed capital formation (FBCF, SA, current prices), EUR Mn"),
    # --- IPI breakdown ---
    ("manufacturing-production",       "INE:IPI13870",  "Index",       "NSA", "M", 1.0,
     "INE IPI Manufacturing index level (CNAE Section C), base 2021=100, NSA"),
]


def main():
    rows = []
    for slug, series_id, unit, adj, freq, conv, note in INE_SLUGS:
        # Delete any existing ine_es row for this (slug, ES) to allow idempotent re-run
        sb.table("indicator_sources").delete().eq(
            "indicator", slug
        ).eq("country", "ES").eq("source", "ine_es").execute()
        # Demote any currently-default row (typically eurostat) for the same tuple
        sb.table("indicator_sources").update({"is_default": False}).eq(
            "indicator", slug
        ).eq("country", "ES").execute()
        rows.append({
            "indicator": slug,
            "country": "ES",
            "source": "ine_es",
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
        })
    res = sb.table("indicator_sources").insert(rows).execute()
    print(f"Inserted {len(res.data)} INE-ES Stage-2 rows")
    for r in res.data:
        print(f"  + ES/{r['indicator']:<32} | {r['series_id']}")


if __name__ == "__main__":
    main()
