"""Seed indicator_sources rows for national stat-office data via DBnomics.

For each country, we pick TE-source-conform DBnomics paths and demote the
corresponding Eurostat rows to is_default=False.

Coverage (as of 2026-05-09):
- IT (ISTAT): industrial-production, ppi, retail-sales, inflation-cpi (lag),
              manufacturing-production, mining-production
- IE (CSO):   inflation-cpi (CPM01)
- BE (NBB):   to be added
- GR (ELSTAT): to be added
- PT (INEPT): to be added
- SE (SCB):   to be added — direct PxWeb preferred
- PL (STATPOL): to be added
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb

# (country, slug, source_code, dbnomics_provider, dataset, series, freq, unit, adjustment, conversion, note)
SEEDS = [
    # === Italy (ISTAT via DBnomics — fresh through Mar 2026 for IP/PPI/retail) ===
    ("IT", "industrial-production", "istat", "ISTAT",
     "115_333_DF_DCSC_INDXPRODIND_1_6", "M.IT.IND_PROD_21.N.0020",
     "M", "Index", "NSA", 1.0,
     "ISTAT IP base 2021=100, total industry excl. construction"),
    ("IT", "manufacturing-production", "istat", "ISTAT",
     "115_333_DF_DCSC_INDXPRODIND_1_6", "M.IT.IND_PROD_21.N.0040",
     "M", "Index", "NSA", 1.0,
     "ISTAT IP intermediate goods (proxy for manufacturing detail)"),
    ("IT", "ppi", "istat", "ISTAT",
     "145_360_DF_DCSC_PREZZPIND_1_4", "M.IT.IND_PRIC_2021.N.D.0020",
     "M", "Index", "NSA", 1.0,
     "ISTAT IPRI base 2021=100"),
    ("IT", "retail-sales", "istat", "ISTAT",
     "120_337_DF_DCSC_COMMDET_1_15", "M.IT.RTD_TURN_VOL_21.N.1.9.TOTAL",
     "M", "Index", "NSA", 1.0,
     "ISTAT retail trade sales volume base 2021=100"),
    ("IT", "inflation-cpi", "istat", "ISTAT",
     "167_744_DF_DCSP_NIC1B2015_1", "M.IT.39.4.00",
     "M", "Index", "NSA", 1.0,
     "ISTAT NIC all-items base 2015=100 (some lag vs Eurostat HICP)"),

    # === Ireland (CSO via DBnomics) ===
    ("IE", "inflation-cpi", "cso_ie", "CSO",
     "CPM01", "CPM01C01.-",
     "M", "Index", "NSA", 1.0,
     "CSO CPI all-items base Dec 2016=100"),
]


def main():
    rows_inserted = 0
    for country, slug, src, prov, ds, ser, freq, unit, adj, conv, note in SEEDS:
        # Delete any existing same-source row first
        sb.table("indicator_sources").delete().eq(
            "indicator", slug
        ).eq("country", country).eq("source", src).execute()
        # Demote Eurostat for this slug+country
        sb.table("indicator_sources").update({"is_default": False}).eq(
            "indicator", slug
        ).eq("country", country).eq("source", "eurostat").execute()
        # Insert new national-source row
        row = {
            "indicator": slug,
            "country": country,
            "source": src,
            "series_id": f"{prov}/{ds}/{ser}",
            "is_default": True,
            "transform": "raw",
            "conversion": conv,
            "unit": unit,
            "adjustment": adj,
            "freq_hint": freq,
            "extra_params": {"provider": prov, "dataset": ds, "series": ser, "freq": freq},
            "active": True,
            "note": note,
        }
        sb.table("indicator_sources").insert(row).execute()
        rows_inserted += 1
        print(f"  + {country}/{slug:<22} | {src:<10} | {prov}/{ds}/{ser}")
    print(f"\nInserted {rows_inserted} national-source rows; demoted corresponding Eurostat rows.")


if __name__ == "__main__":
    main()
