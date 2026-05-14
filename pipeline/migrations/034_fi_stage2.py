"""Stage-2 expansion: Promote stat_fi as default for FI trade-balance, exports,
imports, gdp-real, employed-persons.

CPI/PPI/IP/unemployment/retail-sales already promoted in 014_finland_expansion.py.

Tilastokeskus PxWeb tables verified 2026-05-14 against TE:
  - employed-persons tyti 13gg: 2026M03 = 2524 thousand (matches TE 2524.0)
  - gdp-real ntp 132h kausitvv2015: 2025Q4 = 57249 EUR mn (chained ref 2015 SA)
  - exports tpulk 12gq ULK GS: 2026Q1 = 29495 EUR mn
  - imports tpulk 12gq ULK GS: 2026Q1 = 29952 EUR mn
  - trade-balance (derived exp-imp): 2026Q1 = -457 EUR mn

Notes:
  * Trade series are quarterly BoP (goods+services). StatFin does not expose
    monthly Tulli customs values via PxWeb; Tulli ULJAS lacks a JSON-stat REST
    endpoint, so we publish at quarterly cadence rather than mixing providers.
  * Demotes prior eurostat defaults for the same (indicator, FI) tuples.

Run order:
    python -m pipeline.migrations.034_fi_stage2
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb


# (country, slug, src, series_id, freq, unit, adjustment, conversion, note)
SEEDS = [
    ("FI", "employed-persons", "stat_fi",
     "STATFI/StatFin/tyti/statfin_tyti_pxt_13gg.px", "M",
     "Thousand", "NSA", 1.0,
     "FI Tilastokeskus 13gg LFS employed persons 15-74 monthly NSA thousand"),
    ("FI", "gdp-real", "stat_fi",
     "STATFI/StatFin/ntp/statfin_ntp_pxt_132h.px", "Q",
     "EUR million (chained 2015)", "SA", 1.0,
     "FI Tilastokeskus 132h Real GDP chained 2015 EUR mn SA+WDA (B1GMH/kausitvv2015)"),
    ("FI", "exports", "stat_fi",
     "STATFI/StatFin/tpulk/statfin_tpulk_pxt_12gq.px/exp", "Q",
     "EUR million", "NSA", 1.0,
     "FI Tilastokeskus 12gq Exports of goods+services to ROW (BoP), quarterly EUR mn"),
    ("FI", "imports", "stat_fi",
     "STATFI/StatFin/tpulk/statfin_tpulk_pxt_12gq.px/imp", "Q",
     "EUR million", "NSA", 1.0,
     "FI Tilastokeskus 12gq Imports of goods+services from ROW (BoP), quarterly EUR mn"),
    ("FI", "trade-balance", "stat_fi",
     "STATFI/StatFin/tpulk/statfin_tpulk_pxt_12gq.px/tb", "Q",
     "EUR million", "NSA", 1.0,
     "FI derived from 12gq (exports-imports) quarterly EUR mn"),
]


def main():
    inserted = 0
    for country, slug, src, series_id, freq, unit, adj, conv, note in SEEDS:
        # Idempotent: clear any existing same-source row for this (slug, country)
        sb.table("indicator_sources").delete().eq(
            "indicator", slug
        ).eq("country", country).eq("source", src).execute()
        # Demote any other defaults for this (slug, country)
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
    print(f"\n{inserted} FI stage-2 rows promoted; eurostat counterparts demoted.")


if __name__ == "__main__":
    main()
