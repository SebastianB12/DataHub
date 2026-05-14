"""Promote ELSTAT direct as default for GR stage-2 indicators:
ppi, retail-sales, trade-balance, exports, imports, gdp-real, employed-persons.

Stage 1 (016_elstat_gr_seeds.py) already promoted inflation-cpi,
industrial-production, unemployment.

ELSTAT publishes these as XLS/XLSX press-release files through their Liferay
portal — see pipeline/providers/elstat.py for layout/parser notes.

Documented gaps (NOT seeded here — different publisher):
  - consumer-confidence  -> IOBE/DG ECFIN (TE keeps on European Commission)
  - business-confidence  -> IOBE/DG ECFIN (TE keeps on European Commission)
  - current-account      -> Bank of Greece (separate BoG SDMX provider pending)

Smoke-tested 2026-05-14 against TE inventory:
  - ppi              DKT15 doc 587776 — Mar 2026 = 136.25 (TE Feb/2026 = 136.25)
  - retail-sales     DKT39 doc 500036 — Jan 2026 SA index 127.03 (218 pts since 2000)
  - imports          SFC02 doc 115720 — Mar 2026 = 7150.43 mEUR
  - exports          SFC02 doc 115720 — Mar 2026 = 4939.80 mEUR
  - trade-balance    SFC02 doc 115720 — Mar 2026 = -2210.63 mEUR
  - gdp-real         SEL84 doc 115384 — Q4 2025 = 51622.77 mEUR (chain-linked 2020)
  - employed-persons SJO01 doc 115983 — Q4 2025 = 4352.4 thousand

Demotes existing eurostat/worldbank rows for the same (indicator, country) tuples.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb


# (country, slug, src, series_id, freq, unit, adjustment, conversion, note)
SEEDS = [
    ("GR", "ppi", "elstat",
     "ELSTAT/DKT15/587776", "M",
     "Index (2021=100)", "NSA", 1.0,
     "ELSTAT DKT15 Total PPI Overall Market base 2021=100 (rolling press-release; deep history via Eurostat fallback)"),
    ("GR", "retail-sales", "elstat",
     "ELSTAT/DKT39/500036", "M",
     "Index (2021=100)", "SA", 1.0,
     "ELSTAT DKT39 Table 3 SA Turnover Index in Retail Trade 2021=100, 2000-onwards"),
    ("GR", "imports", "elstat",
     "ELSTAT/SFC02/115720", "M",
     "Million EUR", "NSA", 1.0,
     "ELSTAT SFC02 Trade Balance SDDS monthly imports/arrivals (intra+extra EU), 2004-onwards"),
    ("GR", "exports", "elstat",
     "ELSTAT/SFC02/115720", "M",
     "Million EUR", "NSA", 1.0,
     "ELSTAT SFC02 Trade Balance SDDS monthly exports/dispatches (intra+extra EU), 2004-onwards"),
    ("GR", "trade-balance", "elstat",
     "ELSTAT/SFC02/115720", "M",
     "Million EUR", "NSA", 1.0,
     "ELSTAT SFC02 Trade Balance SDDS monthly net trade balance (intra+extra EU), 2004-onwards"),
    ("GR", "gdp-real", "elstat",
     "ELSTAT/SEL84/115384", "Q",
     "Million EUR (chain-linked, 2020 prices)", "SA", 1.0,
     "ELSTAT SEL84 Quarterly GDP SA chain-linked volumes constant 2020 prices, 1995-Q1 onwards"),
    ("GR", "employed-persons", "elstat",
     "ELSTAT/SJO01/115983", "Q",
     "Thousand persons", "NSA", 1.0,
     "ELSTAT SJO01 Table 3 LFS Persons employed 15+ quarterly (NACE Rev 2 aggregate, thousands), 2001-onwards"),
]


def main():
    inserted = 0
    for country, slug, src, series_id, freq, unit, adj, conv, note in SEEDS:
        # Idempotent: delete any prior elstat row for this (country, slug)
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

    print(f"\n{inserted} ELSTAT-direct rows promoted; eurostat counterparts demoted.")


if __name__ == "__main__":
    main()
