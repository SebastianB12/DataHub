"""Promote RO Stage-2 indicator_sources rows from INSSE Tempo (tempo-py).

Newly verified RO series (besides existing CPI/PPI/IPI/Unempl/Retail/Wages):
  - unemployment-rate-registered : INSSE/SOM103B (registered, monthly, NSA, %)
  - exports                       : INSSE/EXP101I (FOB Total, kEUR -> mio EUR)
  - imports                       : INSSE/EXP102I (CIF Total, kEUR -> mio EUR)
  - trade-balance                 : INSSE/EXP101I-EXP102I (computed, mio EUR)

This file also re-asserts the existing INSSE-default rows for the slugs the
provider already covers so that 'insse_ro' is the TE-conform primary source
for RO across the stage-2 indicators. Eurostat / DBnomics fallbacks demoted.

Run:
    python -m pipeline.migrations.021_ro_stage2
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb

# (slug, src, series_id, freq, unit, adjustment, conversion, note)
RO_SEEDS = [
    # Already covered by RO_SERIES (re-assert as default)
    ("inflation-cpi",               "insse_ro", "INSSE/IPC102A",          "M", "Index (previous month=100)", "NSA", 1.0,  "INSSE Tempo IPC102A CPI MoM index, total"),
    ("industrial-production",       "insse_ro", "INSSE/IND104N",          "M", "Index (2021=100)",          "NSA", 1.0,  "INSSE Tempo IND104N IP gross monthly index, total CAEN Rev.2, 2021=100"),
    ("ppi",                         "insse_ro", "INSSE/PPI1035",          "M", "Index (2021=100)",          "NSA", 1.0,  "INSSE Tempo PPI1035 PPI total (internal+external markets), 2021=100"),
    ("unemployment",                "insse_ro", "INSSE/AMG157H",          "M", "%",                          "SA",  1.0,  "INSSE Tempo AMG157H LFS unemployment rate 15-74 SA monthly"),
    ("retail-sales",                "insse_ro", "INSSE/COM1071",          "M", "Index (2021=100)",          "NSA", 1.0,  "INSSE Tempo COM1071 retail trade volume index (gross), 2021=100"),
    ("wages",                       "insse_ro", "INSSE/FOM107D",          "M", "RON/Month",                  "NSA", 1.0,  "INSSE Tempo FOM107D gross monthly nominal wage, total economy"),
    # New stage-2 rows
    ("unemployment-rate-registered","insse_ro", "INSSE/SOM103B",          "M", "%",                          "NSA", 1.0,  "INSSE Tempo SOM103B registered unemployment rate (end-of-month), total"),
    ("exports",                     "insse_ro", "INSSE/EXP101I",          "M", "Million EUR",                "NSA", 1e-3, "INSSE Tempo EXP101I Exports FOB Total (Mii EURO -> Mio EUR)"),
    ("imports",                     "insse_ro", "INSSE/EXP102I",          "M", "Million EUR",                "NSA", 1e-3, "INSSE Tempo EXP102I Imports CIF Total (Mii EURO -> Mio EUR)"),
    ("trade-balance",               "insse_ro", "INSSE/EXP101I-EXP102I",  "M", "Million EUR",                "NSA", 1.0,  "INSSE Tempo trade balance = Exports(EXP101I) - Imports(EXP102I), Mio EUR"),
]

DEMOTE_SOURCES = ("eurostat", "worldbank", "dbnomics", "fred")


def main():
    inserted = 0
    for slug, src, series_id, freq, unit, adj, conv, note in RO_SEEDS:
        # Delete prior insse_ro row if any (idempotent)
        sb.table("indicator_sources").delete().eq(
            "indicator", slug
        ).eq("country", "RO").eq("source", src).execute()
        # Demote other-source counterparts for this slug
        for other in DEMOTE_SOURCES:
            sb.table("indicator_sources").update({"is_default": False}).eq(
                "indicator", slug
            ).eq("country", "RO").eq("source", other).execute()
        row = {
            "indicator": slug,
            "country": "RO",
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
        print(f"  + RO/{slug:<32} | {src:<10} | {series_id}")
    print(f"\n{inserted} INSSE Romania rows promoted (is_default=true). Fallbacks demoted.")


if __name__ == "__main__":
    main()
