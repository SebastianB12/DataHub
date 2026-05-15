"""PT inflation-cpi: deactivate broken INE-PT pindica row, promote Eurostat HICP.

Background:
    The legacy `indicator_sources` row for (PT, inflation-cpi, ine_pt) pointed
    at INE pindica varcd 0008273. A 2026-05-15 inspection showed that varcd
    is actually "Populacao residente (NUTS-2013)" — Resident population — not
    IPC. The data_points written under inflation-cpi/PT/ine_pt were therefore
    population counts, not CPI.

    A full pindica sweep of varcd range 0007000-0014000 produced only the old
    IPC Base-2012 family (0007320, 0007324, 0008351, 0008352), all frozen at
    "Dezembro de 2024" with DataUltimoAtualizacao 2025-01-13. The new IPC
    (Base 2017 / 2022) is not exposed via pindica.jsp at all — INE migrated
    that publication off the legacy JSON endpoint into a different channel
    that does not yet have a documented public REST API. No replacement
    varcd exists that returns Apr 2026 IPC.

Fix:
    1. Deactivate (active=false, is_default=false) the broken
       (PT, inflation-cpi, ine_pt) row in indicator_sources.
    2. Insert / promote Eurostat HICP as the PT inflation-cpi default,
       matching the EA/DE/GB pattern (ei_cphi_m:TOTAL).
    3. The provider entry in pipeline/providers/national_eu.py PT_SERIES is
       removed in the same commit so the scheduler stops fetching population
       data under the inflation-cpi label.

    The TE attribution change (INE -> Eurostat) is acceptable per the
    documented EU fallback policy: Eurostat publishes the harmonised PT HICP
    sourced directly from INE, with the same underlying methodology.

Run:
    python -m pipeline.migrations.054_pt_cpifix
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb


def main():
    # 1) Deactivate any existing (PT, inflation-cpi, ine_pt) row.
    res = sb.table("indicator_sources").update(
        {"is_default": False, "active": False,
         "note": "DEPRECATED 2026-05-15: pindica varcd 0008273 is Resident "
                 "Population, not IPC. INE-PT has no public pindica varcd for "
                 "current IPC (Base 2017+). PT inflation-cpi now defaults to "
                 "Eurostat HICP."}
    ).eq("indicator", "inflation-cpi").eq("country", "PT").eq(
        "source", "ine_pt"
    ).execute()
    print(f"  - PT/inflation-cpi/ine_pt deactivated "
          f"(rows touched: {len(res.data) if hasattr(res, 'data') else '?'})")

    # 2) Demote any other PT inflation-cpi defaults so the new one wins.
    sb.table("indicator_sources").update({"is_default": False}).eq(
        "indicator", "inflation-cpi"
    ).eq("country", "PT").execute()

    # 3) Upsert Eurostat HICP as new default.
    sb.table("indicator_sources").delete().eq(
        "indicator", "inflation-cpi"
    ).eq("country", "PT").eq("source", "eurostat").execute()

    row = {
        "indicator": "inflation-cpi",
        "country": "PT",
        "source": "eurostat",
        "series_id": "ei_cphi_m:TOTAL",
        "is_default": True,
        "transform": "raw",
        "conversion": 1,
        "unit": "Index",
        "adjustment": "NSA",
        "freq_hint": "M",
        "extra_params": {"dataset": "ei_cphi_m",
                         "params": {"indic": "TOTAL", "unit": "HICP2025"}},
        "active": True,
        "note": "PT Eurostat HICP ei_cphi_m TOTAL (Eurostat-redistributed INE-PT "
                "harmonised CPI; replaces broken pindica varcd 0008273).",
    }
    sb.table("indicator_sources").insert(row).execute()
    print(f"  + PT/inflation-cpi    | eurostat | ei_cphi_m:TOTAL  (is_default=true)")

    print("\nPT inflation-cpi migrated: ine_pt deactivated, eurostat default.")


if __name__ == "__main__":
    main()
