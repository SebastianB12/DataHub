"""TE-conformity gap-fill (cycle 9) for Finland — promote Tilastokeskus
(Statistics Finland) as default for 8 remaining gaps still on eurostat.

Series added to FI_SERIES in providers/national_eu.py (Migration 073 block).

TE-conformity smoke values (verified 2026-05-15):
  budget-deficit                  2025    = -3.4 -> 3.4 % GDP   (sign-flipped, TE: 3.4 EXACT)
  current-account                 2026-03 = 250 EUR mn          (mata 12gf monthly net CA)
  labor-force-participation-rate  2026-03 = 68.0 %              (TE: 68.0 EXACT for 2026-02)
  manufacturing-production        2026-03 = 114.0 (Idx 2021)    (ttvi 14mh NACE C, NSA)
  mining-production               2026-03 = 102.6 (Idx 2021)    (ttvi 14mh NACE B, NSA)
  population                      2025    = 5.653 M             (vaerak 11ra 31 Dec)
  unemployed-persons              2026-03 = 315 thousand        (TE: 315 EXACT)
  youth-unemployment-rate         2026-03 = 24.3 %              (TE: 24.3 EXACT for 2026-02)

Run order:
    python -m pipeline.migrations.073_fi_gapfill_c9
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb


SEEDS = [
    ("FI", "budget-deficit", "stat_fi", "STATFI/vtp/129d/budget-deficit", "A",
     "% of GDP", "NSA", -1.0,
     "FI Tilastokeskus 129d B.9 net lending, % of GDP (sign-flipped to deficit)"),
    ("FI", "current-account", "stat_fi", "STATFI/mata/12gf/current-account", "M",
     "EUR million", "NSA", 1.0,
     "FI Tilastokeskus 12gf Current account net (CA, Tiedot B), monthly EUR mn"),
    ("FI", "labor-force-participation-rate", "stat_fi", "STATFI/tyti/135y/lfp-rate", "M",
     "%", "NSA", 1.0,
     "FI Tilastokeskus 135y LFS labour-force participation rate 15-74 (Tyovoimaosuus)"),
    ("FI", "manufacturing-production", "stat_fi", "STATFI/ttvi/14mh/manufacturing", "M",
     "Index (2021=100)", "NSA", 1.0,
     "FI Tilastokeskus 14mh Industrial Output Manufacturing (TOL C), NSA"),
    ("FI", "mining-production", "stat_fi", "STATFI/ttvi/14mh/mining", "M",
     "Index (2021=100)", "NSA", 1.0,
     "FI Tilastokeskus 14mh Industrial Output Mining and quarrying (TOL B), NSA"),
    ("FI", "population", "stat_fi", "STATFI/vaerak/11ra/population", "A",
     "Million", "NSA", 1e-6,
     "FI Tilastokeskus 11ra Population 31 Dec whole country (persons -> million)"),
    ("FI", "unemployed-persons", "stat_fi", "STATFI/tyti/135y/unemp-persons", "M",
     "Thousand", "NSA", 1.0,
     "FI Tilastokeskus 135y LFS Unemployed persons 15-74 (Tyottomat), thousands NSA"),
    ("FI", "youth-unemployment-rate", "stat_fi", "STATFI/tyti/135y/youth-unemp", "M",
     "%", "NSA", 1.0,
     "FI Tilastokeskus 135y LFS Youth unemployment rate 15-24, NSA"),
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
        print(f"  + {country}/{slug:<32} | {src:<8} | {series_id}")
    print(f"\n{inserted} FI TE-conformity rows promoted (cycle 9); eurostat demoted.")
    print("Run `pipeline/.venv/Scripts/python -m pipeline.providers.national_eu` to ingest.")


if __name__ == "__main__":
    main()
