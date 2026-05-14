"""TE-Source-Conformity: demote Eurostat-as-default + dedupe known duplicates.

Two steps:

**Step 1 — Dedupe 6 known is_default duplicates** identified by the validator
on 2026-05-14. These are rows that have multiple `is_default=true` entries for
the same (country, indicator). Per TE-source-conformity:

  FR/current-account-to-gdp  keep series_id=bop_c6_q:CAtoGDP, demote bop_gdp6_q:CA
  DE/current-account-to-gdp  keep series_id=bop_c6_q:CAtoGDP, demote bop_gdp6_q:CA
  EA/current-account-to-gdp  keep series_id=bop_eu6_q:CAtoGDP, demote bop_gdp6_q:CA
  FR/population              keep source=worldbank (TE-aligned), demote eurostat
  AT/gdp                     keep source=stat_at (national), demote worldbank
  SI/gdp                     keep source=surs_si (national), demote worldbank

**Step 2 — Strict Eurostat-Demotion**: for every (country, indicator) where
`docs/te_sources_truth.yaml` lists `source != 'eurostat'`, demote the
Eurostat-default row to `is_default=false`. Eurostat rows remain active as
fallback. If the truth-source row doesn't exist yet (national provider not
implemented), the slug falls visibly empty for that country — honest coverage.

Run: `pipeline/.venv/Scripts/python.exe -m pipeline.migrations.017_demote_eurostat_aggregator`
"""
import os
import sys
sys.stdout.reconfigure(encoding="utf-8")

import yaml

from pipeline.db import supabase as sb

# Step 1: hardcoded dedupe targets (composite key: country, indicator, source, series_id).
DEDUPE_DEMOTE = [
    ("FR", "current-account-to-gdp", "eurostat",  "bop_gdp6_q:CA"),
    ("DE", "current-account-to-gdp", "eurostat",  "bop_gdp6_q:CA"),
    ("EA", "current-account-to-gdp", "eurostat",  "bop_gdp6_q:CA"),
    ("FR", "population",             "eurostat",  "demo_pjan:TOTAL"),
    ("AT", "gdp",                    "worldbank", "NY.GDP.MKTP.CD"),
    ("SI", "gdp",                    "worldbank", "NY.GDP.MKTP.CD"),
]

TRUTH = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "te_sources_truth.yaml")


def step1_dedupe() -> int:
    """Set is_default=false for the 6 known duplicates."""
    n = 0
    for c, i, src, sid in DEDUPE_DEMOTE:
        r = (
            sb.table("indicator_sources")
            .update({"is_default": False})
            .eq("country", c).eq("indicator", i)
            .eq("source", src).eq("series_id", sid)
            .execute()
        )
        affected = len(r.data or [])
        if affected:
            print(f"  dedupe {c}/{i} {src}/{sid}: demoted ({affected} row)")
            n += affected
        else:
            print(f"  dedupe {c}/{i} {src}/{sid}: no row (already done)")
    return n


def step2_demote_eurostat() -> int:
    """For each truth.yaml entry with source != 'eurostat': demote the Eurostat
    default for that (country, indicator). Promote the truth-source row if it exists.
    """
    with open(TRUTH, encoding="utf-8") as f:
        truth = yaml.safe_load(f) or {}

    demoted = 0
    promoted = 0
    for country, slugs in truth.items():
        for slug, entry in slugs.items():
            want = entry.get("source")
            if not want or want == "eurostat":
                continue

            # Demote any eurostat is_default row for this (country, slug).
            r = (
                sb.table("indicator_sources")
                .update({"is_default": False})
                .eq("country", country).eq("indicator", slug)
                .eq("source", "eurostat").eq("is_default", True)
                .execute()
            )
            if r.data:
                demoted += len(r.data)
                print(f"  demote eurostat for {country}/{slug} (truth wants {want})")

            # Promote the truth-source row if it exists and isn't already default.
            r2 = (
                sb.table("indicator_sources")
                .update({"is_default": True})
                .eq("country", country).eq("indicator", slug)
                .eq("source", want).eq("is_default", False)
                .execute()
            )
            if r2.data:
                promoted += len(r2.data)
                print(f"  promote {want} for {country}/{slug}")
    return demoted + promoted


def main():
    print("=== Step 1: Dedupe 6 known is_default duplicates ===")
    n1 = step1_dedupe()
    print(f"Step 1 done. {n1} rows demoted.\n")

    print("=== Step 2: Strict Eurostat-Demotion per truth.yaml ===")
    n2 = step2_demote_eurostat()
    print(f"Step 2 done. {n2} rows changed.")


if __name__ == "__main__":
    main()
