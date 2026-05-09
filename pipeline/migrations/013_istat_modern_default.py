"""ISTAT modern Esploradati endpoint replaces DBnomics-gateway rows for IT.

Removes 6 IT rows that were going through DBnomics ISTAT-mirror, replaces with
direct ISTAT calls. Resulting `series_id` = ISTAT/IT1,<dataflow>,1.0
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb

ISTAT_SEEDS = [
    # (slug, dataflow, freq, unit, adjustment, conversion, note)
    ("inflation-cpi",         "CPI", "M", "Index",     "NSA", 1.0,  "ISTAT Esploradati CPI base 2025=100"),
    ("ppi",                   "PPI", "M", "Index",     "NSA", 1.0,  "ISTAT Esploradati PPI base 2021=100"),
    ("industrial-production", "IND", "M", "Index",     "SA",  1.0,  "ISTAT Esploradati IPI seasonally adjusted"),
    ("unemployed-persons",    "UEM", "Q", "Thousand",  "SA",  1.0,  "ISTAT Esploradati unemployed persons (thousand)"),
    ("employed-persons",      "EMP", "Q", "Thousand",  "SA",  1.0,  "ISTAT Esploradati employed persons (thousand)"),
    ("population",            "POP", "A", "Million",   "NSA", 1e-6, "ISTAT Esploradati population (annual, scaled to millions)"),
]


def main():
    inserted = 0
    for slug, df, freq, unit, adj, conv, note in ISTAT_SEEDS:
        # Wipe any existing istat row (DBnomics-based)
        sb.table("indicator_sources").delete().eq("indicator", slug).eq("country", "IT").eq("source", "istat").execute()
        # Demote eurostat
        sb.table("indicator_sources").update({"is_default": False}).eq(
            "indicator", slug
        ).eq("country", "IT").eq("source", "eurostat").execute()
        # Insert new ISTAT-direct row
        sb.table("indicator_sources").insert({
            "indicator": slug,
            "country": "IT",
            "source": "istat",
            "series_id": f"ISTAT/IT1,{df},1.0",
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
        print(f"  + IT/{slug:<22} | istat | ISTAT/IT1,{df},1.0")
    print(f"\n{inserted} ISTAT-direct rows promoted (was via DBnomics gateway).")


if __name__ == "__main__":
    main()
