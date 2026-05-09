"""Promote INE-direct as default for ES, demote Eurostat to fallback.
Indicators: inflation-cpi, core-cpi, food-inflation, unemployment, ppi,
industrial-production, retail-sales.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb

INE_SLUGS = [
    ("inflation-cpi",         "INE:IPC290751", "Index", "NSA", "M", 1.0,
     "INE IPC base 2026=100, monthly index, all-items, national"),
    ("core-cpi",              "INE:IPC290851", "Index", "NSA", "M", 1.0,
     "INE IPC subyacente (ex. unprocessed food + energy)"),
    ("food-inflation",        "INE:IPC290755", "Index", "NSA", "M", 1.0,
     "INE IPC Food and non-alcoholic beverages"),
    ("unemployment",          "INE:EPA452434", "%",     "NSA", "Q", 1.0,
     "INE EPA Tasa de paro (both genders, national, 16+)"),
    ("ppi",                   "INE:IPR34522",  "Index", "NSA", "M", 1.0,
     "INE IPRI Industria total Index level (base 2025=100)"),
    ("industrial-production", "INE:IPI13491",  "Index", "NSA", "M", 1.0,
     "INE IPI National Total Industry index"),
    ("retail-sales",          "INE:ICM4147",   "Index", "NSA", "M", 1.0,
     "INE ICM Volume index commercial retail trade"),
]

def main():
    # Insert INE rows as default
    rows = []
    for slug, series_id, unit, adj, freq, conv, note in INE_SLUGS:
        # Delete existing INE row first
        sb.table("indicator_sources").delete().eq("indicator", slug).eq("country", "ES").eq("source", "ine_es").execute()
        # Demote eurostat for this slug
        sb.table("indicator_sources").update({"is_default": False}).eq(
            "indicator", slug
        ).eq("country", "ES").eq("source", "eurostat").execute()
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
    print(f"Inserted {len(res.data)} INE-ES rows; demoted {len(INE_SLUGS)} Eurostat-ES rows")

if __name__ == "__main__":
    main()
