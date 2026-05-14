"""Promote ŠÚ SR (Slovakia) as default source for 6 additional Tier-1 indicators.

Stage 1 (012_national_eu_seeds.py) seeded only inflation-cpi from SUSR; the
remaining SK indicators relied on Eurostat / WorldBank. This migration
expands the ŠÚ SR DataCube REST coverage to PPI, industrial-production,
unemployment-rate, retail-sales, trade-balance, and gdp-real.

DataCube endpoint:
  https://data.statistics.sk/api/v2.0/dataset/{dataset_id}/{segments...}

Datasets used:

  ppi                    -> sp0101ms (Producer price indices vs. corresponding
                            period of previous year, monthly). Filter ukaz=UKAZ04
                            (Industrial producers prices - total).
  industrial-production  -> pm0042ms (Industrial production YoY adjusted index).
                            Filter NACE 05-39 × SPECU_Y_ROMR × UNIT_INDEX × U_PM_0001.
  unemployment-rate      -> pr1802qs (LFS Unemployment rate quarterly). Filter
                            VEK_Y15-74 × TOTAL education × TOTAL sex × MJ_VPC × U_PR_0003.
  retail-sales           -> ob0004ms (Retail trade except motor vehicles, turnover).
                            Filter NACE 47 × SPECU_Y_ROMR × UNIT_INDEX_CSP × U_OD_0001.
  trade-balance          -> zo0001ms (Foreign trade by months). Filter UKAZ03 × MJ01.
  gdp-real               -> nu0004qs (Quarterly GDP, chain-linked volumes prev-year
                            prices). Filter UKAZ15 × METO04 × MJ01.

All entries demote prior defaults (eurostat / worldbank) for the same
(indicator, country) tuple.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb

# (country, slug, src, series_id, freq, unit, adjustment, conversion, note)
SEEDS = [
    ("SK", "ppi",                   "susr_sk", "SUSR/sp0101ms/UKAZ04",
     "M", "Index (same month previous year=100)", "NSA", 1.0,
     "SUSR sp0101ms PPI Industrial producers prices total UKAZ04 YoY index"),
    ("SK", "industrial-production", "susr_sk", "SUSR/pm0042ms/SPECU_Y_ROMR/05-39/UNIT_INDEX/U_PM_0001",
     "M", "Index (same month previous year=100)", "WDA", 1.0,
     "SUSR pm0042ms Industrial production YoY adjusted, NACE 05-39 Industry total"),
    ("SK", "unemployment-rate",     "susr_sk", "SUSR/pr1802qs/VEK_Y15-74/TOTAL/TOTAL/all/MJ_VPC/U_PR_0003",
     "Q", "%", "NSA", 1.0,
     "SUSR pr1802qs LFS unemployment rate 15-74 Total %"),
    ("SK", "retail-sales",          "susr_sk", "SUSR/ob0004ms/SPECU_Y_ROMR/47/UNIT_INDEX_CSP/U_OD_0001",
     "M", "Index (same month previous year=100)", "WDA", 1.0,
     "SUSR ob0004ms Retail trade turnover NACE 47 YoY index (constant prices)"),
    ("SK", "trade-balance",         "susr_sk", "SUSR/zo0001ms/UKAZ03/MJ01",
     "M", "Million EUR", "NSA", 1.0,
     "SUSR zo0001ms Foreign trade balance, mill EUR, monthly"),
    ("SK", "gdp-real",              "susr_sk", "SUSR/nu0004qs/UKAZ15/METO04/MJ01",
     "Q", "Million EUR (chain-linked, prev-year prices)", "NSA", 1.0,
     "SUSR nu0004qs Quarterly GDP chain-linked volumes, mill EUR"),
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
        print(f"  + {country}/{slug:<22} | {src:<8} | {series_id}")
    print(f"\n{inserted} SUSR Slovakia rows promoted; existing SK defaults demoted.")


if __name__ == "__main__":
    main()
