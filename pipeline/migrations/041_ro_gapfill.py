"""Romania TE-conformity gap-fill: promote INSSE Tempo + ECB-BPS as default
sources for additional Tier-1 indicators previously served by Eurostat.

TE inventory (docs/_te_inventory/RO.yaml) flagged 5 INSSE-attributed slugs
(employment-rate, job-vacancies, labor-force-participation-rate,
manufacturing-production, mining-production) plus 1 ECB-attributed
(current-account, sourced via National Bank of Romania = ECB BPS).
This migration closes the verified gaps that the upgraded providers deliver:

  employment-rate           -> INSSE FOM116A 'Rata de ocupare a resurselor de munca'
                               (annual employment rate of labour resources, total)
  manufacturing-production  -> INSSE IND104N filtered INDUSTRIA PRELUCRATOARE
                               (CAEN Rev.2 section C, 2021=100)
  mining-production         -> INSSE IND104N filtered INDUSTRIA EXTRACTIVA
                               (CAEN Rev.2 section B, 2021=100)
  job-vacancies             -> INSSE LMV102B quarterly job vacancies (number)
  current-account           -> ECB BPS M.N.RO.W1.S1.S1.T.B.CA... mEUR

labor-force-participation-rate is deferred: INSSE publishes 'Rata de activitate'
only in AMG142* tables that mix annual+quarterly 'Perioade' values with custom
age/gender breakdowns; the existing fetch_ro_tempo Perioade extension handles
the time dim but the specific matrix selection needs verification against the
TE methodology. Will be addressed in a follow-up.

All entries demote prior defaults (eurostat) for the same
(indicator, country) tuple.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb

SEEDS = [
    ("RO", "employment-rate",            "insse_ro", "INSSE/FOM116A",
     "A", "%", "NSA", 1.0,
     "INSSE Tempo FOM116A annual employment rate of labour resources, total"),
    ("RO", "manufacturing-production",   "insse_ro", "INSSE/IND104N/INDUSTRIA-PRELUCRATOARE",
     "M", "Index (2021=100)", "NSA", 1.0,
     "INSSE Tempo IND104N monthly IP index, CAEN Rev.2 section C Manufacturing, 2021=100"),
    ("RO", "mining-production",          "insse_ro", "INSSE/IND104N/INDUSTRIA-EXTRACTIVA",
     "M", "Index (2021=100)", "NSA", 1.0,
     "INSSE Tempo IND104N monthly IP index, CAEN Rev.2 section B Mining, 2021=100"),
    ("RO", "job-vacancies",              "insse_ro", "INSSE/LMV102B",
     "Q", "Number", "NSA", 1.0,
     "INSSE Tempo LMV102B Job vacancies (number), quarterly, total economy"),
    ("RO", "current-account",            "ecb",      "BPS/M.N.RO.W1.S1.S1.T.B.CA._Z._Z._Z.EUR._T._X.N.ALL",
     "M", "Million EUR", "NSA", 1.0,
     "ECB BPS Balance of Payments — RO current account, monthly NSA, mill EUR"),
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
        print(f"  + {country}/{slug:<28} | {src:<8} | {series_id}")
    print(f"\n{inserted} RO rows promoted (INSSE + ECB BPS); existing RO defaults demoted.")


if __name__ == "__main__":
    main()
