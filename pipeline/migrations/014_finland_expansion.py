"""Promote stat_fi as default for FI core indicators (PPI, IP, UE, GDP, Retail).

Tilastokeskus PxWeb tables verified 2026-05-09 against TE:
  - PPI 13m8: 2026M03 = 120.6 (matches TE 120.6)
  - IP 14mh: 2026M03 = 116.7 NSA original (implies +7.3% YoY, matches TE)
  - LFS 135y: 2026M03 = 11.1% unemployment rate (matches TE 11.10%)
  - Retail 14kr: 2026M03 = 91.5 G47 volume WDA
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb

# (country, slug, src, series_id, freq, unit, adjustment, conversion, note)
SEEDS = [
    ("FI", "ppi",                   "stat_fi",
     "STATFI/StatFin/thi/statfin_thi_pxt_13m8.px", "M",
     "Index (2021=100)", "NSA", 1.0,
     "FI Tilastokeskus 13m8 PPI manufactured products total 2021=100"),
    ("FI", "industrial-production", "stat_fi",
     "STATFI/StatFin/ttvi/statfin_ttvi_pxt_14mh.px", "M",
     "Index (2021=100)", "NSA", 1.0,
     "FI Tilastokeskus 14mh Industrial Output BCD total original NSA 2021=100"),
    ("FI", "unemployment",          "stat_fi",
     "STATFI/StatFin/tyti/statfin_tyti_pxt_135y.px", "M",
     "%", "NSA", 1.0,
     "FI Tilastokeskus 135y Labour Force Survey unemployment rate 15-74 monthly NSA"),
    # NOTE: GDP intentionally NOT seeded — catalog `gdp` slug is annual USD (World Bank).
    # Tilastokeskus QNA 132h is quarterly EUR mn and would mismatch the indicator schema.
    ("FI", "retail-sales",          "stat_fi",
     "STATFI/StatFin/klv/statfin_klv_pxt_14kr.px", "M",
     "Index (2021=100)", "WDA", 1.0,
     "FI Tilastokeskus 14kr Retail trade G47 volume index 2021=100 WDA"),
]


def main():
    inserted = 0
    for country, slug, src, series_id, freq, unit, adj, conv, note in SEEDS:
        # Delete same-source row if any (idempotent rerun)
        sb.table("indicator_sources").delete().eq(
            "indicator", slug
        ).eq("country", country).eq("source", src).execute()
        # Demote any other default for this (country, slug)
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
        print(f"  + {country}/{slug:<22} | {src:<8} | {series_id}")
    print(f"\n{inserted} FI national-source rows promoted; previous defaults demoted.")


if __name__ == "__main__":
    main()
