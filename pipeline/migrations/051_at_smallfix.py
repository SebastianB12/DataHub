"""AT TE-conformity small fixes (2026-05-14):

1. gdp -> promote `worldbank` (NY.GDP.MKTP.CD annual nominal USD), demote stat_at.
   TE attributes AT `gdp` to "World Bank"; the existing stat_at row was actually
   serving real-SA quarterly data labelled under `gdp`. Provider re-labelled to
   `gdp-real`; this migration repoints the `gdp` default at worldbank.

2. gdp-real -> promote `stat_at` (vgr108 BIP real SA, converted Mio->Bn EUR),
   demote eurostat namq_10_gdp:CLV10_MEUR. TE attributes AT `gdp-real` to
   "Statistics Austria".

3. retail-sales -> promote `eurostat` (sts_trtu_m:G47:I21), demote stat_at
   (OGD_konjidxhan21 G47 nominal SA index). TE attributes AT `retail-sales` to
   EUROSTAT (0.1 % m/m volume reading for 2026-03 is the eurostat headline).
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb


# (country, slug, src, series_id, freq, unit, adjustment, conversion, note)
SEEDS = [
    ("AT", "gdp", "worldbank", "NY.GDP.MKTP.CD", "A",
     "Billion USD", "NSA", 1.0,
     "AT World Bank NY.GDP.MKTP.CD annual GDP, current USD (TE source)"),
    ("AT", "gdp-real", "stat_at", "STATAT/OGD_vgr108_VGR_HA_vj_1", "Q",
     "Bn EUR (real, SA)", "SA", 0.001,
     "AT Statistik Austria VGR108 BIP real SA, Mio->Bn EUR (TE source)"),
    ("AT", "retail-sales", "eurostat", "sts_trtu_m:G47:I21", "M",
     "Index (2021=100)", "SA", 1.0,
     "AT Eurostat sts_trtu_m retail trade G47 index (TE source)"),
]


def main():
    inserted = 0
    for country, slug, src, series_id, freq, unit, adj, conv, note in SEEDS:
        sb.table("indicator_sources").delete().eq(
            "indicator", slug
        ).eq("country", country).eq("source", src).execute()
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
        print(f"  + {country}/{slug:<14} | {src:<10} | {series_id}")
    print(f"\n{inserted} AT TE-conformity small fixes applied; conflicting defaults demoted.")


if __name__ == "__main__":
    main()
