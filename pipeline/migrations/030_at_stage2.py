"""Austria stage-2 expansion (Statistik Austria OGD direct).

Stage-1 already promoted stat_at for inflation-cpi, ppi, industrial-production,
unemployment, gdp, wages, import-prices (seeded by 012_national_eu_seeds.py).

Stage-2 adds 6 TE-aligned indicators that were previously left on the Eurostat
fallback:

  exports                -> Konjunkturmonitor F-FAKT-46 (Ausfuhren Insgesamt, EUR)
  imports                -> Konjunkturmonitor F-FAKT-32 (Einfuhren Insgesamt, EUR)
  trade-balance          -> Konjunkturmonitor F-FAKT-46 − F-FAKT-32 (derived in fetcher)
  retail-sales           -> Konjunkturindizes Handel KJIX_H_21_1, NACE G47 nominal SA
  employed-persons       -> VGR111 Flash Erwerbstätigkeit, F-PERSI total SA, quarterly
  government-debt-total  -> Konsolidierte Bruttoverschuldung (Maastricht), annual, F-TKL101

OGD CSV catalog browser: https://data.statistik.gv.at/database/

Smoke-tested 2026-05-14 (matches TE inventory verified values):
  exports                Feb/26 = 16,164.85 Mio EUR (TE: 16,165)
  imports                Feb/26 = 15,822.85 Mio EUR (TE: 15,823)
  trade-balance          Feb/26 = +341.998 Mio EUR
  retail-sales           Feb/26 = 117.6 (G47 nominal SA, 2021=100)
  employed-persons       Q1/26  = 4,726 thousand (VGR-flash SA; differs from TE's
                                  LFS 4,500.2 — ESA-NA concept gap, identical to
                                  our existing ILO-vs-AMS unemployment caveat)
  government-debt-total  2025    = 418.08 Bn EUR (TE shows 81.5 % of GDP)

AMS-registered unemployment rate (7.5 % Apr/26 on TE) is published by AMS at
iambweb.ams.or.at without a clean open-data feed; we keep the Statistik Austria
ILO/LFS rate (5.7 % Q4/25) as the headline stat_at unemployment series. No new
'ams_at' source slug is introduced for this stage.

Demotes existing eurostat rows for the same (indicator, AT) tuples.
"""
import sys

sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb

# (slug, series_id, freq, unit, adjustment, conversion, note)
SEEDS = [
    ("exports",
     "STATAT/OGD_konjunkturmonitor_KonMon_1#F-FAKT-46",
     "M", "Mio EUR", "NSA", 1e-6,
     "Statistik Austria Konjunkturmonitor F-FAKT-46 Ausfuhren Insgesamt, EUR→Mio EUR"),

    ("imports",
     "STATAT/OGD_konjunkturmonitor_KonMon_1#F-FAKT-32",
     "M", "Mio EUR", "NSA", 1e-6,
     "Statistik Austria Konjunkturmonitor F-FAKT-32 Einfuhren Insgesamt, EUR→Mio EUR"),

    ("trade-balance",
     "STATAT/OGD_konjunkturmonitor_KonMon_1#F-FAKT-46-F-FAKT-32",
     "M", "Mio EUR", "NSA", 1e-6,
     "Statistik Austria Konjunkturmonitor derived: Ausfuhren − Einfuhren (F46−F32), EUR→Mio EUR"),

    ("retail-sales",
     "STATAT/OGD_konjidxhan21_KJIX_H_21_1#NACEIDX-47#F-UIDXNSB",
     "M", "Index (2021=100, SA)", "SA", 1.0,
     "Statistik Austria Konjunkturindizes Handel G47 (Einzelhandel), nominell SA, 2021=100"),

    ("employed-persons",
     "STATAT/OGD_vgr111_VGR_Flashes_Erwerb_1#BEREIN-2#F-PERSI",
     "Q", "Thousand persons (SA)", "SA", 1.0,
     "Statistik Austria VGR111 Flash Erwerbstätigkeit, Personen-Insgesamt SA, in 1.000"),

    ("government-debt-total",
     "STATAT/OGD_kons_brv_HVD_KONS_BRV_1#F-TKL101",
     "A", "Bn EUR", "NSA", 0.001,
     "Statistik Austria Konsolidierte Bruttoverschuldung Maastricht (jährlich), Mio→Bn EUR"),
]


def main():
    inserted = 0
    for slug, series_id, freq, unit, adj, conv, note in SEEDS:
        # Idempotent: remove any earlier row with same (slug, AT, stat_at)
        sb.table("indicator_sources").delete().eq(
            "indicator", slug
        ).eq("country", "AT").eq("source", "stat_at").execute()
        # Demote any prior default for this (slug, AT) — e.g. eurostat / worldbank
        sb.table("indicator_sources").update({"is_default": False}).eq(
            "indicator", slug
        ).eq("country", "AT").execute()
        row = {
            "indicator": slug,
            "country": "AT",
            "source": "stat_at",
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
        print(f"  + AT/{slug:<22} | stat_at | {series_id}")

    print(f"\n{inserted} AT stage-2 rows promoted; previous defaults demoted.")


if __name__ == "__main__":
    main()
