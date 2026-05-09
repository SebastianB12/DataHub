"""Promote national-source rows for DK/FI/SE/IE inflation-cpi etc., demote Eurostat to fallback.

Sources:
  dst    -> Statistics Denmark (Statbank)
  stat_fi-> Statistics Finland (Tilastokeskus)
  scb_se -> Statistics Sweden (SCB PxWeb)
  cso_ie -> CSO Ireland (PxStat)
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb

# (country, slug, src, series_id, freq, unit, adjustment, conversion, note)
SEEDS = [
    # Denmark
    ("DK", "inflation-cpi",         "dst", "DST/PRIS01",   "M", "Index", "NSA", 1.0, "DK Statbank PRIS01 CPI all-items index"),
    ("DK", "industrial-production", "dst", "DST/IPOP21",   "M", "Index", "SA",  1.0, "DK Statbank IPOP21 IP manufacturing SA"),
    ("DK", "unemployment",          "dst", "DST/AUP01",    "M", "%",     "SA",  1.0, "DK Statbank AUP01 unemployment rate (registered)"),
    ("DK", "retail-sales",          "dst", "DST/DETA211A", "M", "Index", "NSA", 1.0, "DK Statbank DETA211A Retail Trade Index G47"),
    # Finland
    ("FI", "inflation-cpi",         "stat_fi", "STATFI/khi/15b5", "M", "Index", "NSA", 1.0, "FI Tilastokeskus 15b5 CPI 2025=100 monthly"),
    # Sweden
    ("SE", "inflation-cpi",         "scb_se", "SCB/PR0101A/KPI2020M", "M", "Index", "NSA", 1.0, "SE SCB shadow CPI continuous index 1980=100"),
    # Ireland
    ("IE", "inflation-cpi",         "cso_ie", "CSO/CPM01",   "M", "Index", "NSA", 1.0, "CSO Ireland CPM01 CPI Base Dec 2023=100 all items"),
    # Austria — direct from Statistik Austria OGD CSV
    ("AT", "inflation-cpi",         "stat_at", "STATAT/OGD_vpi20_VPI_2020_1", "M", "Index", "NSA", 1.0, "Statistik Austria VPI base 2020=100 (2021-01..2025-12)"),
    # Slovenia — direct from SURS PxWeb
    ("SI", "inflation-cpi",         "surs_si", "SURS/0400608S.px", "M", "Index (same month py=100)", "NSA", 1.0, "SURS 0400608S CPI Index vs same month previous year, TOTAL"),
    # Latvia — direct from CSP PxWeb
    ("LV", "inflation-cpi",         "csp_lv", "CSP/PCI030m", "M", "Index (Dec 1990=100)", "NSA", 1.0, "CSP Latvia PCI030m CPI continuous index Dec 1990=100"),
    # Estonia — direct from Statistics Estonia PxWeb
    ("EE", "inflation-cpi",         "stat_ee", "STATEE/IA002.px", "M", "Index (1997=100)", "NSA", 1.0, "Statistics Estonia IA002 CPI 1997=100, total"),
    # Croatia — direct from DZS PxWeb (web.dzs.hr)
    ("HR", "inflation-cpi",         "dzs_hr", "DZS/ME_PS09.px", "M", "Index (2025=100)", "NSA", 1.0, "DZS Croatia ME_PS09 CPI 2025=100, total ECOICOP v2"),
    # Belgium — direct from Statbel REST API
    ("BE", "inflation-cpi",         "statbel", "STATBEL/208b69bd", "M", "Index (2013=100)", "NSA", 1.0, "Statbel CPI base 2013=100 (last 13 months)"),
    # Slovakia — direct from ŠÚ SR DataCube REST
    ("SK", "inflation-cpi",         "susr_sk", "SUSR/sp2038ms/odb01/mj38", "M", "Index (Dec 2000=100)", "NSA", 1.0, "ŠÚ SR sp2038ms CPI Total, Dec 2000=100"),
]


def main():
    inserted = 0
    for country, slug, src, series_id, freq, unit, adj, conv, note in SEEDS:
        # Delete same-source row if any
        sb.table("indicator_sources").delete().eq(
            "indicator", slug
        ).eq("country", country).eq("source", src).execute()
        # Demote eurostat for this slug
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
        print(f"  + {country}/{slug:<22} | {src:<8} | {series_id}")
    print(f"\n{inserted} national-source rows promoted; eurostat counterparts demoted.")


if __name__ == "__main__":
    main()
