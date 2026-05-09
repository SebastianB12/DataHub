"""Promote NSO Malta and CYSTAT (Cyprus) as default sources for inflation-cpi.

Both endpoints are Cloudflare-protected and require the `cloudscraper` package.

Sources:
  nso_mt    -> NSO Malta SDMX REST (apidesign-statdb.nso.gov.mt/rest)
  cystat_cy -> CYSTAT PxWeb (cystatdb.cystat.gov.cy/api/v1)

TE-Source-Conformity: confirmed via tradingeconomics.com/{country}/inflation-cpi
  Malta:  "National Statistics Office, Malta"
  Cyprus: "Statistical Service of the Republic of Cyprus" (cystat.gov.cy)
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb

SEEDS = [
    # Malta — NSO direct via SDMX (covers 2003-01..present, monthly)
    ("MT", "inflation-cpi", "nso_mt", "NSO/DF_RETAIL_PRICE_INDEX_MONTHLY/CC00000.M",
     "M", "Index (2015=100)", "NSA", 1.0,
     "NSO Malta DF_RETAIL_PRICE_INDEX_MONTHLY total RPI"),
    # Cyprus — CYSTAT direct via PxWeb (covers 1980-01..present, monthly, base 1986)
    ("CY", "inflation-cpi", "cystat_cy", "CYSTAT/0410055E.px/B1986",
     "M", "Index (1986=100)", "NSA", 1.0,
     "CYSTAT 0410055E continuous CPI timeseries, base 1986=100"),
]


def main():
    inserted = 0
    for country, slug, src, series_id, freq, unit, adj, conv, note in SEEDS:
        # Delete same-source row if any
        sb.table("indicator_sources").delete().eq(
            "indicator", slug
        ).eq("country", country).eq("source", src).execute()
        # Demote eurostat for this slug+country
        sb.table("indicator_sources").update({"is_default": False}).eq(
            "indicator", slug
        ).eq("country", country).eq("source", "eurostat").execute()
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
        print(f"  + {country}/{slug:<22} | {src:<10} | {series_id}")
    print(f"\n{inserted} national-source rows promoted; eurostat counterparts demoted.")


if __name__ == "__main__":
    main()
