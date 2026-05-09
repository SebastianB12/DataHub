"""Promote INE-direct as default for additional ES slugs.

Extends the original 010_ine_es_default.py with 8 additional indicators:
  gdp-growth-rate, employed-persons, unemployed-persons, youth-unemployment-rate,
  wages, business-confidence, house-price-index, construction-output.

INE COD discovered 2026-05-09 via Tempus3 endpoints
(OPERACIONES_DISPONIBLES -> TABLAS_OPERACION -> SERIES_TABLA).

Verified value-match against tradingeconomics.com/spain/<indicator>.
"""
import sys

sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb

INE_SLUGS = [
    # (slug, series_id, unit, adjustment, freq, conversion, note)
    ("gdp-growth-rate",         "INE:CNTR6654",  "% YoY",     "SA",  "Q", 1.0,
     "INE CNTR2010 GDP at market prices YoY growth, SA, chain-linked"),
    ("employed-persons",        "INE:EPA387796", "Thousand",  "NSA", "Q", 1.0,
     "INE EPA Employed persons absolute (thousands), both genders, 16+"),
    ("unemployed-persons",      "INE:EPA387800", "Thousand",  "NSA", "Q", 1.0,
     "INE EPA Unemployed persons absolute (thousands), both genders, 16+"),
    ("youth-unemployment-rate", "INE:EPA452436", "%",         "NSA", "Q", 1.0,
     "INE EPA Unemployment rate, both genders, under 25, national"),
    ("wages",                   "INE:ETCL67",    "EUR/Month", "NSA", "Q", 1.0,
     "INE ETCL Total wage cost per worker, sections B-S, EUR/month"),
    ("business-confidence",     "INE:ICE1",      "Points",    "NSA", "Q", 1.0,
     "INE ICE Business Confidence Index, national, base 2013=100"),
    ("house-price-index",       "INE:IPV769",    "Index",     "NSA", "Q", 1.0,
     "INE IPV House Price Index, national general"),
    ("construction-output",     "INE:IPCO3",     "Index",     "NSA", "M", 1.0,
     "INE IPCO Construction production index, base 2021=100, NSA"),
]


def main():
    rows = []
    for slug, series_id, unit, adj, freq, conv, note in INE_SLUGS:
        # Delete existing INE row to avoid PK collision on re-run
        sb.table("indicator_sources").delete().eq(
            "indicator", slug
        ).eq("country", "ES").eq("source", "ine_es").execute()
        # Demote eurostat for this slug if present (so INE becomes default)
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
    print(f"Inserted {len(res.data)} INE-ES rows for extension slugs")
    for r in res.data:
        print(f"  + ES/{r['indicator']:<26} | {r['series_id']}")


if __name__ == "__main__":
    main()
