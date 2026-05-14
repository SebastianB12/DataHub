"""Slovakia TE-conformity gap-fill: promote ŠÚ SR DataCube + ECB-BPS as
default sources for additional Tier-1 indicators previously served by
Eurostat.

TE inventory (docs/_te_inventory/SK.yaml) flagged 23 SUSR-attributed slugs
+ 2 ECB (current-account, current-account-to-gdp via National Bank of
Slovakia, sourced from ECB BPS). This migration closes the verified-conformity
gaps that the upgraded providers can actually deliver:

  cpi-food                  -> SUSR sp2038ms/odb02/mj38 (COICOP 01 Food)
  cpi-clothing              -> SUSR sp2038ms/odb04/mj38 (COICOP 03 Clothing)
  cpi-housing-utilities     -> SUSR sp2038ms/odb05/mj38 (COICOP 04 Housing)
  cpi-transportation        -> SUSR sp2038ms/odb08/mj38 (COICOP 07 Transport)
  cpi-recreation-and-culture-> SUSR sp2038ms/odb09/mj38 (COICOP 09 Recreation)
  cpi-education             -> SUSR sp2038ms/odb10/mj38 (COICOP 10 Education)
  manufacturing-production  -> SUSR pm0042ms/SPECU_Y_ROMR/10-33 (NACE C, YoY)
  mining-production         -> SUSR pm0042ms/SPECU_Y_ROMR/05-09 (NACE B, YoY)
  current-account           -> ECB BPS M.N.SK.W1.S1.S1.T.B.CA... mEUR

CPI sub-COICOP values are stored as Dec-2000=100 continuous indices (the only
measure SUSR publishes for sp2038ms). The frontend computes YoY/MoM derivations
on-the-fly via cohorts of (date, value).

Other inventory gaps (business/consumer-confidence balances, employed-persons,
consumer/government-spending, GFCF, changes-in-inventories, food-inflation,
labor-force-participation-rate, population, imports) are deferred: SUSR
publishes them only in surveys with custom 'balances of questions' formats
(kp0012ms etc), quarterly national-accounts aggregates that lack a TE-conform
direct mapping (nu1063qs COICOP18 vs TE consumer-spending), or annual-only
LFP. These require additional dataset-specific parsing wrappers.

All entries demote prior defaults (eurostat) for the same
(indicator, country) tuple.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb

SEEDS = [
    # CPI sub-COICOP series (sp2038ms, different odb codes), continuous Dec-2000=100
    ("SK", "cpi-food",                   "susr_sk", "SUSR/sp2038ms/odb02/mj38",
     "M", "Index (Dec 2000=100)", "NSA", 1.0,
     "SUSR sp2038ms CPI COICOP 01 Food & non-alc bev, Dec 2000=100 continuous"),
    ("SK", "cpi-clothing",               "susr_sk", "SUSR/sp2038ms/odb04/mj38",
     "M", "Index (Dec 2000=100)", "NSA", 1.0,
     "SUSR sp2038ms CPI COICOP 03 Clothing & footwear, Dec 2000=100 continuous"),
    ("SK", "cpi-housing-utilities",      "susr_sk", "SUSR/sp2038ms/odb05/mj38",
     "M", "Index (Dec 2000=100)", "NSA", 1.0,
     "SUSR sp2038ms CPI COICOP 04 Housing+utilities, Dec 2000=100 continuous"),
    ("SK", "cpi-transportation",         "susr_sk", "SUSR/sp2038ms/odb08/mj38",
     "M", "Index (Dec 2000=100)", "NSA", 1.0,
     "SUSR sp2038ms CPI COICOP 07 Transport, Dec 2000=100 continuous"),
    ("SK", "cpi-recreation-and-culture", "susr_sk", "SUSR/sp2038ms/odb09/mj38",
     "M", "Index (Dec 2000=100)", "NSA", 1.0,
     "SUSR sp2038ms CPI COICOP 09 Recreation & culture, Dec 2000=100 continuous"),
    ("SK", "cpi-education",              "susr_sk", "SUSR/sp2038ms/odb10/mj38",
     "M", "Index (Dec 2000=100)", "NSA", 1.0,
     "SUSR sp2038ms CPI COICOP 10 Education, Dec 2000=100 continuous"),
    # Industrial production YoY adjusted, manufacturing & mining
    ("SK", "manufacturing-production",   "susr_sk", "SUSR/pm0042ms/SPECU_Y_ROMR/10 - 33/UNIT_INDEX/U_PM_0001",
     "M", "Index (same month previous year=100)", "WDA", 1.0,
     "SUSR pm0042ms IP YoY adjusted, NACE 10 - 33 Manufacturing"),
    ("SK", "mining-production",          "susr_sk", "SUSR/pm0042ms/SPECU_Y_ROMR/05 - 09/UNIT_INDEX/U_PM_0001",
     "M", "Index (same month previous year=100)", "WDA", 1.0,
     "SUSR pm0042ms IP YoY adjusted, NACE 05 - 09 Mining & quarrying"),
    # ECB BPS current-account
    ("SK", "current-account",            "ecb",     "BPS/M.N.SK.W1.S1.S1.T.B.CA._Z._Z._Z.EUR._T._X.N.ALL",
     "M", "Million EUR", "NSA", 1.0,
     "ECB BPS Balance of Payments — SK current account, monthly NSA, mill EUR"),
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
        print(f"  + {country}/{slug:<28} | {src:<7} | {series_id}")
    print(f"\n{inserted} SK rows promoted (SUSR + ECB BPS); existing SK defaults demoted.")


if __name__ == "__main__":
    main()
