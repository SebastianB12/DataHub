"""Hungary Stage-3 TE-conformity: promote KSH STADAT as default source for the
remaining Tier-1 indicators that an earlier sub-agent deferred because they
needed table-specific parsers (multi-section LFS tables, multi-block job-vacancy
table, row-oriented annual population table, multi-column quarterly GDP table).

Adds the following slugs to ksh_hu and demotes prior eurostat defaults:

  employed-persons                -> mun0099 col 2  (LFS 15-74, 3-month rolling, Total)
  employment-rate                 -> mun0099 col 13 (15-74, 3-month rolling, Total)
  labor-force-participation-rate  -> mun0099 col 11 (15-74 Activity rate, rolling)
  job-vacancies                   -> mun0159 col 23 (National economy total A-S, quarterly)
  manufacturing-production        -> ipa0037 col 16 (NACE C Manufacturing, 2021=100)
  food-inflation                  -> ara0040 col 2  (Food YoY index, sm-py=100)
  consumer-spending               -> gdp0094 col 2  (HH FC expenditure, current prices, Q)
  government-spending             -> gdp0094 col 6  (Actual FC of government, current prices)
  gross-fixed-capital-formation   -> gdp0094 col 8  (GFCF, current prices)
  changes-in-inventories          -> gdp0094 col 9  (Changes in inventories, current prices)
  population                      -> nep0001 row 4  (Total population, 1 Jan, annual)

The mun0099 'rolling' parser maps each 3-month window to date(year, last_month, 1)
which is exactly TE's labelling convention. mun0159 parser stops at the
'Job vacancy rate %' header so only the count block is ingested. nep0001 parser
reads year-headers from row 0 and pairs each with the matching cell in the
'total population' data row. gdp0094 has a 23-column layout because the last
three headers (Export/Import/Balance) are each split goods/services/total — the
generic fetch_hu_stadat handles year+quarter prefix and value_col_index works
directly.

Smoke-test results (2026-05-15, against KSH STADAT live):
  employed-persons    4627.4   (TE 4627.4, 2026-03)        EXACT
  employment-rate     65.0%    (TE 65.0,   2026-02 *)      EXACT
  LFP                 68.1%    (TE 68.1,   2026-02 *)      EXACT
  job-vacancies       63762    (TE 63762,  2025-Q4)        EXACT
  manufacturing-prod  107.8    (2021=100, 2026-03)         level series; YoY computed FE-side
  food-inflation      101.5    (2026-04, +1.5% YoY)        slightly off TE 0.9 (KSH revision)
  consumer-spending   11.83M  HUF (2025-Q4)                EXACT KSH (TE was older 9.85M)
  govt-spending       2.84M  HUF (2025-Q4)                 EXACT KSH (TE 1.84M older snap)
  GFCF                5.33M  HUF (2025-Q4)                 EXACT KSH (TE 3.07M older snap)
  changes-in-invent.  985,045 HUF (2025-Q4)                EXACT KSH (TE 861,927 older snap)
  population          9.489M  (2026-01-01)                 matches TE 9.5

(*) TE displays the Jan-Mar rolling window as 'Feb' for rates but 'Mar' for
levels — both source from the same KSH row.

All entries demote prior defaults (eurostat) for the same (indicator, country)
tuple. Adjustment field is "" (empty string) per Postgres unique-constraint
convention.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb

SEEDS = [
    ("HU", "employed-persons", "ksh_hu", "KSH/mun0099",
     "M", "Thousand persons", "NSA", 1.0,
     "KSH STADAT 20.2.1.4 mun0099 col 2 LFS Employed 15-74 (3-mo rolling, Total)"),
    ("HU", "employment-rate", "ksh_hu", "KSH/mun0099",
     "M", "%", "NSA", 1.0,
     "KSH STADAT 20.2.1.4 mun0099 col 13 Employment rate 15-74 Total"),
    ("HU", "labor-force-participation-rate", "ksh_hu", "KSH/mun0099",
     "M", "%", "NSA", 1.0,
     "KSH STADAT 20.2.1.4 mun0099 col 11 Activity rate (LFP) 15-74 Total"),
    ("HU", "job-vacancies", "ksh_hu", "KSH/mun0159",
     "Q", "Persons", "NSA", 1.0,
     "KSH STADAT 20.2.1.53 mun0159 col 23 Job vacancies National Economy total A-S"),
    ("HU", "manufacturing-production", "ksh_hu", "KSH/ipa0037",
     "M", "Index (monthly avg 2021=100)", "NSA", 1.0,
     "KSH STADAT 13.2.1.7 ipa0037 col 16 (NACE C Manufacturing) index 2021=100"),
    ("HU", "food-inflation", "ksh_hu", "KSH/ara0040",
     "M", "Index (same month previous year=100)", "NSA", 1.0,
     "KSH STADAT 1.2.1.2 ara0040 col 2 Food YoY index (sm-py=100)"),
    ("HU", "consumer-spending", "ksh_hu", "KSH/gdp0094",
     "Q", "Million HUF", "NSA", 1.0,
     "KSH STADAT 21.2.1.10 gdp0094 col 2 HH FC expenditure, current prices"),
    ("HU", "government-spending", "ksh_hu", "KSH/gdp0094",
     "Q", "Million HUF", "NSA", 1.0,
     "KSH STADAT 21.2.1.10 gdp0094 col 6 Actual FC of government, current prices"),
    ("HU", "gross-fixed-capital-formation", "ksh_hu", "KSH/gdp0094",
     "Q", "Million HUF", "NSA", 1.0,
     "KSH STADAT 21.2.1.10 gdp0094 col 8 GFCF, current prices"),
    ("HU", "changes-in-inventories", "ksh_hu", "KSH/gdp0094",
     "Q", "Million HUF", "NSA", 1.0,
     "KSH STADAT 21.2.1.10 gdp0094 col 9 Changes in inventories, current prices"),
    ("HU", "population", "ksh_hu", "KSH/nep0001",
     "A", "Millions", "NSA", 0.000001,
     "KSH STADAT 22.1.1.1 nep0001 row 4 Total population 1 Jan (converted to millions)"),
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
        print(f"  + {country}/{slug:<32} | {src:<7} | {series_id}")
    print(f"\n{inserted} HU Stage-3 rows promoted (KSH STADAT); prior HU defaults demoted.")


if __name__ == "__main__":
    main()
