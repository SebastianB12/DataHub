"""Promote Statistics Sweden (SCB) as default source for stage-2 SE indicators.

Migration 012_national_eu_seeds.py seeded SE for inflation-cpi, ppi,
industrial-production-yoy, unemployment, gdp-growth-rate, trade-balance,
retail-sales-yoy.

This migration extends to additional TE-aligned series currently on eurostat:
  industrial-production (level), retail-sales (level), exports, imports,
  unemployed-persons, employed-persons, gdp-real.

Tables / endpoints (SCB PxWeb https://api.scb.se/OV0104/v1/doris/en/ssd/):

  industrial-production -> NV/NV0402/NV0402A/IPI2010KedjM         (B-D, NV0402AJ, level)
  retail-sales          -> HA/HA0101/HA0101B/DetOms07N            (47exkl47.3, 000006VX SA-WDA)
  exports               -> HA/HA0201/HA0201A/ImportExportSnabbM   (ETOT, SEK mn)
  imports               -> HA/HA0201/HA0201A/ImportExportSnabbM   (ITOT, SEK mn)
  unemployed-persons    -> AM/AM0401/AM0401A/AKURLBefM            (ALOES NSA thousands)
  employed-persons      -> AM/AM0401/AM0401A/AKURLBefM            (SYS NSA thousands)
  gdp-real              -> NR/NR0103/NR0103B/NR0103ENS2010T10SKv  (BNPM NR0103CE SA, ref 2024)

TE-conformity smoke (verified 2026-05-14):
  industrial-production : 2026M03 = 119.1 idx (level, B-D calendar-adj)
  retail-sales          : 2026M03 = 99.9   idx (SA-WDA 47 ex 47.3)
  exports               : 2026M03 = 195,100 SEK mn
  imports               : 2026M03 = 185,800 SEK mn
  unemployed-persons    : 2026M03 = 564.9   k (TE: 564.9) MATCH
  employed-persons      : 2026M03 = 5,229.8 k (TE: 5.23 mn) MATCH
  gdp-real              : 2025Q4 = 1,643,113 SEK mn (SA, ref 2024)

Not seeded (kept on eurostat or external):
  consumer-confidence, business-confidence — published by NIER (Konjunkturinstitutet,
    https://www.konj.se/), NOT by SCB. Requires a new konj_se provider; deferred.
  cpi-* sub-components: TE pulls KPI by ECOICOP from SCB. Out of scope for Stage-2.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb


SEEDS = [
    # (country, slug, src, series_id, freq, unit, adjustment, conversion, note)
    ("SE", "industrial-production", "scb_se", "SCB/NV/NV0402/NV0402A/IPI2010KedjM",        "M",
     "Index (2021=100)", "WDA", 1.0,
     "SE SCB NV0402A Industrial Production Index level, B-D, WDA (NV0402AJ)"),
    ("SE", "retail-sales",          "scb_se", "SCB/HA/HA0101/HA0101B/DetOms07N",           "M",
     "Index (2021=100)", "SA",  1.0,
     "SE SCB HA0101B Retail Sales index level (excl fuel), SA-WDA constant prices (000006VX)"),
    ("SE", "exports",               "scb_se", "SCB/HA/HA0201/HA0201A/ImportExportSnabbM",  "M",
     "SEK million", "NSA", 1.0,
     "SE SCB HA0201A Total exports of goods, SEK million (ETOT/HA0201A2)"),
    ("SE", "imports",               "scb_se", "SCB/HA/HA0201/HA0201A/ImportExportSnabbM",  "M",
     "SEK million", "NSA", 1.0,
     "SE SCB HA0201A Total imports of goods, SEK million (ITOT/HA0201A2)"),
    ("SE", "unemployed-persons",    "scb_se", "SCB/AM/AM0401/AM0401A/AKURLBefM",           "M",
     "Thousand", "NSA", 1.0,
     "SE SCB AM0401A LFS unemployed persons 15-74 NSA, thousands (ALOES/O_DATA)"),
    ("SE", "employed-persons",      "scb_se", "SCB/AM/AM0401/AM0401A/AKURLBefM",           "M",
     "Thousand", "NSA", 1.0,
     "SE SCB AM0401A LFS employed persons 15-74 NSA, thousands (SYS/O_DATA)"),
    ("SE", "gdp-real",              "scb_se", "SCB/NR/NR0103/NR0103B/NR0103ENS2010T10SKv", "Q",
     "SEK million (ref 2024)", "SA", 1.0,
     "SE SCB NR0103B GDP-real SA constant prices ref 2024, SEK mn (BNPM/NR0103CE)"),
]


def main():
    inserted = 0
    for country, slug, src, series_id, freq, unit, adj, conv, note in SEEDS:
        # Delete same-source row if any (idempotent re-runs)
        sb.table("indicator_sources").delete().eq(
            "indicator", slug
        ).eq("country", country).eq("source", src).execute()
        # Demote any existing default row from other sources for this (slug, country)
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
    print(f"\n{inserted} SE SCB stage-2 rows promoted; eurostat siblings demoted.")


if __name__ == "__main__":
    main()
