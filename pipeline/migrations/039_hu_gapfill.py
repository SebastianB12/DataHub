"""Hungary TE-conformity gap-fill: promote KSH + ECB-BPS as default sources
for additional Tier-1 indicators previously served by Eurostat.

TE inventory (docs/_te_inventory/HU.yaml) flagged 17 KSH-attributed slugs and
1 ECB-attributed (current-account, sourced via ECB BPS / national CB). This
migration closes the verified-conformity gaps that the upgraded providers can
actually deliver:

  cpi-transportation       -> KSH STADAT ara0042 row 9 (COICOP 07 Transport YoY)
  mining-production        -> KSH STADAT ipa0037 col 2 (NACE B, 2021=100 index)
  current-account          -> ECB BPS M.N.HU.W1.S1.S1.T.B.CA._Z._Z._Z.EUR... mEUR

Other KSH-attributed slugs in the inventory (employed-persons, employment-rate,
job-vacancies, labor-force-participation-rate, manufacturing-production,
consumer/government-spending, GFCF, changes-in-inventories, population,
food-inflation) do not have a single-column scrapeable KSH STADAT table in
English and are deferred: KSH publishes only quarterly VGR aggregates in the
Hungarian-only STADAT section, and the EN tables either lack a 'C-total'
column (manufacturing-production) or a single 'rate' column (LFP). These
will require an HU-language scraper or KSH internal API access — out of
scope for this migration.

All entries demote prior defaults (eurostat) for the same
(indicator, country) tuple.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb

SEEDS = [
    ("HU", "cpi-transportation",    "ksh_hu", "KSH/ara0042",
     "M", "Index (same month previous year=100)", "NSA", 1.0,
     "KSH STADAT 1.2.1.4 ara0042 row 9 (COICOP 07 Transport) YoY index"),
    ("HU", "mining-production",     "ksh_hu", "KSH/ipa0037",
     "M", "Index (monthly avg 2021=100)", "NSA", 1.0,
     "KSH STADAT 13.2.1.7 ipa0037 col 2 (NACE B Mining&quarrying) 2021=100"),
    ("HU", "current-account",       "ecb",    "BPS/M.N.HU.W1.S1.S1.T.B.CA._Z._Z._Z.EUR._T._X.N.ALL",
     "M", "Million EUR", "NSA", 1.0,
     "ECB BPS Balance of Payments — HU current account, monthly NSA, mill EUR"),
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
        print(f"  + {country}/{slug:<22} | {src:<7} | {series_id}")
    print(f"\n{inserted} HU rows promoted (KSH + ECB BPS); existing HU defaults demoted.")


if __name__ == "__main__":
    main()
