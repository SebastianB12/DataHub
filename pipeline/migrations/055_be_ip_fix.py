"""BE industrial-production source attribution check (2026-05-15).

Task brief asked to switch BE/industrial-production from nbb -> statbel.
Investigation result:

    The Statbel REST API (https://bestat.statbel.fgov.be/bestat/api/views) was
    enumerated in full on 2026-05-15 — 1341 views across all four locales
    (nl/fr/de/en). The only "industry"-tagged 2021=100 monthly index family
    is "Erzeugerpreisindex / Indices des prix a la production de l'industrie
    / Afzetprijsindexen voor de industrie / Producer price index of industry"
    — i.e. PPI, not the industrial-production (IPI) volume index.

    Statbel does NOT publish the IPI volume index (NACE B+C+D, monthly,
    2021=100, working-day adjusted) directly through bestat.statbel.fgov.be.
    The IPI is compiled by Statbel and redistributed by the NBB on the
    Belgostat platform (NBB SDMX REST endpoint nsidisseminate-stat.nbb.be,
    dataflow DF_INDPROD). NBB documents the source as Statbel.

    The existing indicator_sources row
        (BE, industrial-production, nbb, DF_INDPROD/M.2021.INDPROD.W.B_C_D.BE)
    therefore already maps to the Statbel methodology. No DB change is
    required — the technical fetch URL stays NBB, the underlying data
    provider is Statbel, and TE's "Statbel" attribution is preserved.

    The provider entry for BE industrial-production in
    pipeline/providers/national_eu.py BE_SERIES has been annotated with this
    investigation note in the same commit.

Run:
    python -m pipeline.migrations.055_be_ip_fix

This script is intentionally non-destructive: it just updates the `note`
column on the existing row so the rationale is visible to future maintainers.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb


NEW_NOTE = (
    "NBB DF_INDPROD total industry B+C+D (NACE), WDA, base 2021=100. "
    "Underlying data compiled by Statbel; redistributed via NBB Belgostat SDMX "
    "(nsidisseminate-stat.nbb.be). Statbel REST API has no direct IPI volume "
    "view as of 2026-05-15 — full enumeration of 1341 views returned only PPI."
)


def main():
    res = sb.table("indicator_sources").update(
        {"note": NEW_NOTE}
    ).eq("indicator", "industrial-production").eq(
        "country", "BE"
    ).eq("source", "nbb").execute()
    n = len(res.data) if hasattr(res, "data") else "?"
    print(f"  ~ BE/industrial-production/nbb note refreshed (rows touched: {n})")
    print("\nNo source switch executed: Statbel REST has no IPI view; NBB "
          "redistribution remains the canonical pull.")


if __name__ == "__main__":
    main()
