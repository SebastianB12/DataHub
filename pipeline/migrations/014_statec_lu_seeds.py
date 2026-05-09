"""STATEC direct rows for Luxembourg (LU) — promote to default, demote eurostat.

Source label: ``statec_lu``. Mirrors what TE shows ("STATEC, Luxembourg") for
Tier-1 macro indicators on https://tradingeconomics.com/luxembourg.

Endpoint: lustat.statec.lu/rest (.Stat Suite SDMX REST, NSI Web Service v8.x).
The STATEC dataflow IDs and filter dimensions are encoded in
``pipeline/providers/statec.py`` — this migration only writes the
indicator_sources rows so the run-all loop can pick them up.

Series promoted:
  inflation-cpi          DSD_ECOICOP_PRIX@DF_E5405 v1.0  NCPI ECOICOP v.2 CP00
  ppi                    DSD_PRIX_PPI@DF_D3202 v1.0     Industrial PPI total (_T)
  unemployment           DF_B3019 v1.0                   Unemployment rate SA (C11)
  unemployed-persons     DF_B3019 v1.0                   Unemployed SA (C09) -> thousands
  employed-persons       DF_B3019 v1.0                   Domestic employment SA (C08) -> thousands
  industrial-production  DF_D5110 v1.1                   IP index, BTD industries, WDA, base 2021
  population             DF_B1100 v1.0                   Total resident population (C01) -> millions
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb

# (slug, series_id, freq, unit, adjustment, conversion, note)
SEEDS = [
    ("inflation-cpi",         "STATEC/LU1,DSD_ECOICOP_PRIX@DF_E5405,1.0", "M",
     "Index (2025=100)",      "NSA", 1.0,
     "STATEC NCPI ECOICOP v.2 all-items (CP00), base 2025=100"),
    ("ppi",                   "STATEC/LU1,DSD_PRIX_PPI@DF_D3202,1.0",     "M",
     "Index (2021=100)",      "NSA", 1.0,
     "STATEC Industrial Producer Prices total (_T), base 2021=100"),
    ("unemployment",          "STATEC/LU1,DF_B3019,1.0",                  "M",
     "%",                     "SA",  1.0,
     "STATEC unemployment rate SA (B3019/C11)"),
    ("unemployed-persons",    "STATEC/LU1,DF_B3019,1.0",                  "M",
     "Thousand",              "SA",  1e-3,
     "STATEC number of unemployed SA (B3019/C09), persons -> thousands"),
    ("employed-persons",      "STATEC/LU1,DF_B3019,1.0",                  "M",
     "Thousand",              "SA",  1e-3,
     "STATEC domestic employment SA (B3019/C08), persons -> thousands"),
    ("industrial-production", "STATEC/LU1,DF_D5110,1.1",                  "M",
     "Index (2021=100)",      "WDA", 1.0,
     "STATEC Industrial Production index, total industry BTD, working-day adj."),
    ("population",            "STATEC/LU1,DF_B1100,1.0",                  "A",
     "Million",               "NSA", 1e-6,
     "STATEC total resident population (B1100/C01), annual -> millions"),
]


def main():
    inserted = 0
    for slug, series_id, freq, unit, adj, conv, note in SEEDS:
        # Wipe any pre-existing statec_lu row for idempotency
        sb.table("indicator_sources").delete().eq(
            "indicator", slug
        ).eq("country", "LU").eq("source", "statec_lu").execute()
        # Demote eurostat fallback (don't deactivate it — keep as backup)
        sb.table("indicator_sources").update({"is_default": False}).eq(
            "indicator", slug
        ).eq("country", "LU").eq("source", "eurostat").execute()
        # Insert the STATEC-direct row as new default
        sb.table("indicator_sources").insert({
            "indicator": slug,
            "country": "LU",
            "source": "statec_lu",
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
        }).execute()
        inserted += 1
        print(f"  + LU/{slug:<22} | statec_lu | {series_id}")
    print(f"\n{inserted} STATEC-direct rows promoted; eurostat counterparts demoted.")


if __name__ == "__main__":
    main()
