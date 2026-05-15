"""TE-conformity gap-fill for Italy — ISTAT-direct seeds for 12 indicators.

Provider extensions: see pipeline/providers/istat.py (SERIES entries added
2026-05-15 for core-cpi, food/services/energy-inflation, employment-rate,
unemployment, exports, imports, manufacturing/mining-production,
budget-deficit, government-debt-total).

Already wired before this migration (no-op here, listed for completeness):
  - consumer-confidence  (30_264_DF_DCSC_FIDCONS_1, COF_21_WE.N....)
  - business-confidence  (111_263_DF_DCSC_FIDIMPRMAN_17, CLIMAMAN_21.Y.C.TOTAL)

NETWORK STATUS (2026-05-15):
  esploradati.istat.it (193.204.90.13) refuses TCP from this network on all
  tested ports (80/443/8443/8080). Sibling hosts sdmx.istat.it (.1) and
  www.istat.it (.61) reachable. Probable ISTAT-side firewall or geofence.

  Legacy sdmx.istat.it (NSI Web Service v6.16) responds but freshness lags
  badly: HICP 2025-04, FOI 2025-03, Foreign-trade 2025-07. TE attribution
  values are 2026-04 / 2026-02 / 2026-03 — only the modern Esploradati flow
  carries them. DBnomics ISTAT mirror has the same freshness issue (most
  series stop mid-2024 except a handful at 2025-12).

DECISION:
  Provider code is wired with the correct modern Esploradati URLs +
  filter_key per slug + 3-attempt exponential retry (180s/attempt). Once
  the network/firewall path to esploradati.istat.it is restored, the next
  scheduler run will populate IT/<slug> on source='istat' automatically.

  This migration is INTENTIONALLY A NO-OP for indicator_sources rows: we do
  NOT demote eurostat-default for these slugs while we cannot verify TE
  values against a live ISTAT pull. Promoting stale ISTAT-direct over fresh
  Eurostat data would regress the public Frontend.

  When connectivity returns, re-run with `--promote` to flip the defaults
  (see SEEDS list below) and demote the eurostat counterparts.

TE-match expectations (from docs/_te_inventory/IT.yaml, verified true):
  budget-deficit         2025      ~-3.1 %
  core-cpi               2026-04   ~1.6 % YoY  (TE column is YoY; we ingest both index and YoY)
  employment-rate        2026-03   ~62.4 %
  energy-inflation       2026-04   ~9.5 %
  exports                2026-02   ~53,764 EUR mn
  food-inflation         2026-04   ~3.1 %
  government-debt-total  2025      ~137 % GDP
  imports                2026-02   ~48,821 EUR mn
  services-inflation     2026-04   ~2.4 %
  unemployment           2026-03   ~5.2 %
  manufacturing-prod     2026-03   (TE value rate-limited)
  mining-production      2026-03   (TE value rate-limited)
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb

# (slug, series_id, freq, unit, adjustment, conversion, note)
# series_id mirrors the format already used in 013_istat_modern_default.py:
#   ISTAT/IT1,<dataflow_full>,1.0/<filter_key>
SEEDS = [
    ("core-cpi",
     "ISTAT/IT1,168_760_DF_DCSP_IPCA1B2015_1,1.0/M.IT.41.4.00XEFOODUNP",
     "M", "Index (2015=100)", "NSA", 1.0,
     "IT HICP excl. energy & unprocessed food (core CPI) base 2015=100"),
    ("food-inflation",
     "ISTAT/IT1,168_760_DF_DCSP_IPCA1B2015_1,1.0/M.IT.43.4.01",
     "M", "% YoY", "NSA", 1.0,
     "IT HICP Food & non-alc beverages (COICOP 01) YoY%"),
    ("services-inflation",
     "ISTAT/IT1,168_760_DF_DCSP_IPCA1B2015_1,1.0/M.IT.43.4.SERV",
     "M", "% YoY", "NSA", 1.0,
     "IT HICP Services aggregate YoY%"),
    ("energy-inflation",
     "ISTAT/IT1,168_760_DF_DCSP_IPCA1B2015_1,1.0/M.IT.43.4.ENRGY",
     "M", "% YoY", "NSA", 1.0,
     "IT HICP Energy aggregate YoY%"),
    ("employment-rate",
     "ISTAT/IT1,150_872_DF_DCCV_TAXOCCUMENS1_1,1.0/M.IT.EMP_R.N.9.Y15-64.",
     "M", "%", "NSA", 1.0,
     "IT LFS Employment Rate 15-64 both sexes monthly NSA"),
    ("unemployment",
     "ISTAT/IT1,151_874_DF_DCCV_TAXDISOCCUMENS1_1,1.0/M.IT.UNEM_R.N.9.Y15-74.",
     "M", "%", "NSA", 1.0,
     "IT LFS Unemployment Rate 15-74 both sexes monthly NSA"),
    ("exports",
     "ISTAT/IT1,139_176,1.0/M.0010.WORLD.ITTOT.EV",
     "M", "EUR million", "NSA", 1.0,
     "IT Foreign Trade total exports to World (NSA, EUR mn)"),
    ("imports",
     "ISTAT/IT1,139_176,1.0/M.0010.WORLD.ITTOT.IV",
     "M", "EUR million", "NSA", 1.0,
     "IT Foreign Trade total imports from World (NSA, EUR mn)"),
    ("manufacturing-production",
     "ISTAT/IT1,115_333_DF_DCSC_INDXPRODIND_1_1,1.0/M.IT.IND_PROD2.N.C",
     "M", "Index (2015=100)", "NSA", 1.0,
     "IT Industrial Production Index NACE C (manufacturing) NSA"),
    ("mining-production",
     "ISTAT/IT1,115_333_DF_DCSC_INDXPRODIND_1_1,1.0/M.IT.IND_PROD2.N.B",
     "M", "Index (2015=100)", "NSA", 1.0,
     "IT Industrial Production Index NACE B (mining & quarrying) NSA"),
    ("budget-deficit",
     "ISTAT/IT1,95_42_DF_DCCN_FPQ_2,1.0/A.IT.S13.B9_GDP",
     "A", "% of GDP", "NSA", 1.0,
     "IT Public Finance: General Government net lending S13 (% GDP)"),
    ("government-debt-total",
     "ISTAT/IT1,95_42_DF_DCCN_FPQ_2,1.0/A.IT.S13.DEBT_GDP",
     "A", "% of GDP", "NSA", 1.0,
     "IT General Government Maastricht debt (% GDP)"),
]


def main(promote: bool = False):
    """Default: NO-OP (just print intent). Pass promote=True after network
    connectivity to esploradati.istat.it is verified and the provider has
    successfully ingested fresh data points for each slug."""
    if not promote:
        print("== 052_it_gapfill: NO-OP MODE ==")
        print("ISTAT esploradati endpoint unreachable from current network.")
        print("Provider code (pipeline/providers/istat.py) has SERIES entries")
        print("ready. Re-run with promote=True once data is ingested.\n")
        print("Planned promotions:")
        for slug, sid, freq, unit, adj, conv, note in SEEDS:
            print(f"  IT/{slug:<28} | istat | {sid}")
        return

    inserted = 0
    for slug, series_id, freq, unit, adj, conv, note in SEEDS:
        sb.table("indicator_sources").delete().eq(
            "indicator", slug
        ).eq("country", "IT").eq("source", "istat").execute()
        sb.table("indicator_sources").update({"is_default": False}).eq(
            "indicator", slug
        ).eq("country", "IT").eq("source", "eurostat").execute()
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
    import sys as _sys
    promote = "--promote" in _sys.argv
    main(promote=promote)
