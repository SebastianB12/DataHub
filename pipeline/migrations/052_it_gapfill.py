"""TE-conformity gap-fill for Italy — ISTAT-direct seeds.

Provider extensions: see pipeline/providers/istat.py (SERIES entries added
2026-05-15 for core-cpi, unemployment, exports, imports). Note: original
plan included 12 series; 8 were dropped after live verification.

NETWORK STATUS (2026-05-15):
  esploradati.istat.it is now reachable (was blocked in prior session).
  However the endpoint is slow/rate-limited and some flows are stale.

Live smoke-test summary (2026-05-15):
  PROMOTED (4):
    core-cpi              168_760  M.IT.41.4.00XEFOODUNP            (index ok)
    unemployment          151_874  M.IT.UNEM_R.N.9.Y15-74           2026-03 = 5.48%
    exports               139_176  M.ITTOT.EV.0010.WORLD            2026-02 = 53,764 EUR mn (matches TE)
    imports               139_176  M.ITTOT.IV.0010.WORLD            2026-02 = 48,821 EUR mn (matches TE)

  DEFERRED (8) — provider entries removed:
    food-/services-/energy-inflation: 168_760 only publishes DATA_TYPE=41
        (index level). YoY rates not in this dataflow; need on-the-fly compute
        from COICOP index series. Stays on eurostat.
    employment-rate: 150_872 read timeouts (~120s) on filtered key. Stays
        on eurostat.
    manufacturing-production, mining-production: 115_333 stale (last 2023-12).
        Stays on eurostat (manuf was previously on istat via IND dataflow;
        kept that). Modern flow ID TBD.
    budget-deficit, government-debt-total: 95_42_DF_DCCN_FPQ_2 has 9 dims
        (DATA_TYPE_AGGR, NONFIN_ASSETS, VALUATION, ADJUSTMENT,
        INSTITUTIONAL_SECTOR, EXPEND_PURPOSE, EDITION) — 4-dim filter 404s.
        Stays on eurostat.

Run order:
    python -m pipeline.migrations.052_it_gapfill
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb

# (slug, series_id, freq, unit, adjustment, conversion, note)
SEEDS = [
    ("core-cpi",
     "ISTAT/IT1,168_760_DF_DCSP_IPCA1B2015_1,1.0/M.IT.41.4.00XEFOODUNP",
     "M", "Index (2015=100)", "NSA", 1.0,
     "ISTAT HICP excl. energy & unprocessed food (core CPI) base 2015=100"),
    ("unemployment",
     "ISTAT/IT1,151_874_DF_DCCV_TAXDISOCCUMENS1_1,1.0/M.IT.UNEM_R.N.9.Y15-74.",
     "M", "%", "NSA", 1.0,
     "ISTAT LFS Unemployment Rate 15-74 both sexes monthly NSA"),
    ("exports",
     "ISTAT/IT1,139_176,1.0/M.ITTOT.EV.0010.WORLD",
     "M", "EUR million", "NSA", 1.0,
     "ISTAT Foreign Trade total exports to World (NSA, EUR mn)"),
    ("imports",
     "ISTAT/IT1,139_176,1.0/M.ITTOT.IV.0010.WORLD",
     "M", "EUR million", "NSA", 1.0,
     "ISTAT Foreign Trade total imports from World (NSA, EUR mn)"),
]


def main():
    inserted = 0
    for slug, series_id, freq, unit, adj, conv, note in SEEDS:
        sb.table("indicator_sources").delete().eq(
            "indicator", slug
        ).eq("country", "IT").eq("source", "istat").execute()
        sb.table("indicator_sources").update({"is_default": False}).eq(
            "indicator", slug
        ).eq("country", "IT").execute()
        sb.table("indicator_sources").insert({
            "indicator": slug,
            "country": "IT",
            "source": "istat",
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
        }).execute()
        inserted += 1
        print(f"  + IT/{slug:<28} | istat | {series_id}")
    print(f"\n{inserted} ISTAT-direct rows promoted; eurostat counterparts demoted.")


if __name__ == "__main__":
    main()
