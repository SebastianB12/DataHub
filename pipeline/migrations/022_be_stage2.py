"""Belgium stage-2 expansion (Statbel + NBB SDMX).

Adds 7 TE-aligned indicators on top of the existing Statbel CPI seed:

  ppi                    -> Statbel view 098275aa (PPI industry excl. construction, base 2021)
  retail-sales           -> Statbel view 4ecec356 (4-month rolling retail gross index)
  industrial-production  -> NBB DF_INDPROD, M.2021.INDPROD.W.B_C_D.BE (working-day adj)
  unemployment           -> NBB DF_UNEMPLOY_RATE, M.AA.Z0000.Y.BE.HUR.RATE (harmonised, SA)
  trade-balance          -> NBB DF_EXTERNAL_TRADE_OVERVIEW, M.NBB_A1.B.NAT.VAL.M (vs World)
  gdp-real               -> NBB DF_QNA_DISS, Q.2.B1GM.VZ.LY.Y (chain-linked Y/Y %)
  consumer-confidence    -> NBB DF_CONSN, M.CCI.BE
  business-confidence    -> NBB DF_BUSSURVM, M.SYNC.BE.A999.X (synthetic, smoothed)

NBB stat platform note: stat.nbb.be (Belgostat) was decommissioned. The active
SDMX 2.1 REST endpoint is https://nsidisseminate-stat.nbb.be/rest with
agencyID = "BE2". Browser UI: https://dataexplorer.nbb.be.

Smoke-tested 2026-05-14:
  ppi                    Mar/26 = 124.44 (Index 2021=100)
  retail-sales           Mar/26 = 111.38 (Gross index)
  industrial-production  Mar/26 = 97.3   (WDA, base 2021=100)
  unemployment           Mar/26 = 6.3 %  (NBB HUR; TE shows 5.8 % via Eurostat LFS — methodology gap)
  trade-balance          Mar/26 = 3284.09 EUR mn (NBB national-concept monthly movement)
  gdp-real               Q1/26 = 0.8 % Y/Y
  consumer-confidence    Apr/26 = -9
  business-confidence    Feb/26 = -13.3
"""
import sys

sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb

# (slug, src, series_id, freq, unit, adjustment, conversion, note)
SEEDS = [
    ("ppi",                    "statbel",
     "STATBEL/098275aa",        "M", "Index (2021=100)", "NSA", 1.0,
     "Statbel PPI industry excl. construction, total market index base 2021=100 (view 098275aa)"),

    ("retail-sales",           "statbel",
     "STATBEL/4ecec356",        "M", "Index", "NSA", 1.0,
     "Statbel retail sales gross index, NACE G47 excl. motor vehicles (view 4ecec356; 4-month rolling)"),

    ("industrial-production",  "nbb",
     "NBB/DF_INDPROD/M.2021.INDPROD.W.B_C_D.BE",
                                "M", "Index (2021=100)", "WDA", 1.0,
     "NBB DF_INDPROD total industry (sections B+C+D), working-day adjusted, base 2021=100"),

    ("unemployment",           "nbb",
     "NBB/DF_UNEMPLOY_RATE/M.AA.Z0000.Y.BE.HUR.RATE",
                                "M", "%", "SA", 1.0,
     "NBB harmonised unemployment rate, total, all ages, seasonally and calendar adjusted"),

    ("trade-balance",          "nbb",
     "NBB/DF_EXTERNAL_TRADE_OVERVIEW/M.NBB_A1.B.NAT.VAL.M",
                                "M", "EUR million", "NSA", 1.0,
     "NBB foreign trade balance vs World, national concept, monthly value, EUR mn"),

    ("gdp-real",               "nbb",
     "NBB/DF_QNA_DISS/Q.2.B1GM.VZ.LY.Y",
                                "Q", "% YoY", "SA", 1.0,
     "NBB quarterly GDP, chain-linked Y/Y % change (ref. year 2020), working-day + seasonally adj."),

    ("consumer-confidence",    "nbb",
     "NBB/DF_CONSN/M.CCI.BE",   "M", "Balance", "SA", 1.0,
     "NBB consumer confidence indicator (CCI), Belgium, balance of opinions"),

    ("business-confidence",    "nbb",
     "NBB/DF_BUSSURVM/M.SYNC.BE.A999.X",
                                "M", "Balance", "SA", 1.0,
     "NBB monthly business survey, synthetic curve, Belgium total, SA + smoothed"),
]


def main():
    inserted = 0
    for slug, src, series_id, freq, unit, adj, conv, note in SEEDS:
        # Idempotent: remove any earlier row with same (slug, BE, src)
        sb.table("indicator_sources").delete().eq(
            "indicator", slug
        ).eq("country", "BE").eq("source", src).execute()
        # Demote any prior default for this (slug, BE)
        sb.table("indicator_sources").update({"is_default": False}).eq(
            "indicator", slug
        ).eq("country", "BE").execute()
        row = {
            "indicator": slug,
            "country": "BE",
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
        print(f"  + BE/{slug:<22} | {src:<8} | {series_id}")

    # Register NBB as a data source so the scheduler can pick it up
    existing = sb.table("data_sources").select("slug").eq("slug", "nbb").execute()
    if not existing.data:
        sb.table("data_sources").insert({
            "slug": "nbb",
            "name": "National Bank of Belgium (NBB) — SDMX REST",
            "schedule": "interval:6h",
            "enabled": True,
            "config": {"base_url": "https://nsidisseminate-stat.nbb.be/rest",
                       "agency_id": "BE2",
                       "ui": "https://dataexplorer.nbb.be/?lc=en"},
        }).execute()
        print("  + data_sources.nbb registered")
    else:
        print("  = data_sources.nbb already present")

    print(f"\n{inserted} BE stage-2 rows promoted; previous defaults demoted.")


if __name__ == "__main__":
    main()
