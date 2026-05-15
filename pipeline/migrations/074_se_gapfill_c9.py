"""TE-conformity gap-fill (cycle 9) for Sweden — promote SCB (Statistics Sweden)
as default for 8 remaining gaps still on eurostat.

Series added to SE_SERIES in providers/national_eu.py (Migration 074 block).

TE-conformity smoke values (verified 2026-05-15):
  capacity-utilization            2025Q4 = 87.7 %                  (SCB actual; TE 20.0 = EC survey balance, different metric)
  core-cpi (CPIF-XE YoY%)         2026-04 = 0.0 %                  (SCB CPIF-XE; TE 11.6 outdated)
  current-account                 2025Q4 = 78.1 SEK billion        (FM0001 net CA)
  disposable-personal-income      2025Q4 = 773,762 SEK mn          (TE: 773,762 EXACT, S14 B6n)
  house-price-index               2026Q1 = 953.0 (Idx 1981=100)    (TE: 953 EXACT)
  labor-force-participation-rate  2026-03 = 75.9 %                 (TE: 75.9 EXACT for 2026-02)
  manufacturing-production        2026-03 = 122.5 (Idx 2021)       (SNI C, WDA)
  mining-production               2026-03 = 96.3 (Idx 2021)        (SNI B, WDA)

Run order:
    python -m pipeline.migrations.074_se_gapfill_c9
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb


SEEDS = [
    ("SE", "capacity-utilization", "scb_se", "SCB/NV0701A/capacity-util", "Q",
     "%", "NSA", 1.0,
     "SE SCB NV0701A Industrial capacity utilisation NACE B+C, NSA %"),
    ("SE", "core-cpi", "scb_se", "SCB/PR0101J/core-cpi-yoy", "M",
     "% YoY", "NSA", 1.0,
     "SE SCB PR0101J CPIF exclusive energy (core-CPI) annual change %"),
    ("SE", "current-account", "scb_se", "SCB/FM0001A/current-account", "Q",
     "SEK billion", "NSA", 1.0,
     "SE SCB FM0001BetBalKv BoP current account net, SEK billions quarterly"),
    ("SE", "disposable-personal-income", "scb_se", "SCB/NR0103C/disposable-S14", "Q",
     "SEK million", "NSA", 1.0,
     "SE SCB NR0103C Household (S14) disposable income net, SEK mn quarterly"),
    ("SE", "house-price-index", "scb_se", "SCB/BO0501A/house-price", "Q",
     "Index (1981=100)", "NSA", 1.0,
     "SE SCB BO0501A Real estate price index, one- and two-dwelling buildings, Sweden"),
    ("SE", "labor-force-participation-rate", "scb_se", "SCB/AM0401A/lfp-rate", "M",
     "%", "NSA", 1.0,
     "SE SCB AM0401A LFS labour-force participation rate 15-74 NSA (IAKRP/O_DATA)"),
    ("SE", "manufacturing-production", "scb_se", "SCB/NV0402A/manufacturing", "M",
     "Index (2021=100)", "WDA", 1.0,
     "SE SCB NV0402A IPI Manufacturing index level (SNI C), WDA"),
    ("SE", "mining-production", "scb_se", "SCB/NV0402A/mining", "M",
     "Index (2021=100)", "WDA", 1.0,
     "SE SCB NV0402A IPI Mining and quarrying index level (SNI B), WDA"),
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
    print(f"\n{inserted} SE TE-conformity rows promoted (cycle 9); eurostat demoted.")
    print("Run `pipeline/.venv/Scripts/python -m pipeline.providers.national_eu` to ingest.")


if __name__ == "__main__":
    main()
