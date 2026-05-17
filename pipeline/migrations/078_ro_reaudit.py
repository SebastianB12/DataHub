"""RO re-audit (2026-05-17) — TE-source conformity sweep.

Scope: All 68 RO slugs verified against fresh TE fetches
(see docs/_audit_ro_reaudit.yaml). Findings:

  Real fixes applied:

    1. inflation-cpi: switch INSSE matrix IPC102A (MoM 100-base) -> IPC102E
       (YoY 100-base index). TE displays the YoY rate as headline (e.g. 9.5%).
       The previous matrix delivered MoM index ~100, off by ~960% scale.
       Code change in pipeline/providers/national_eu.py (RO_SERIES + new
       row_filter arg in fetch_ro_tempo). DB: indicator_sources updated +
       data_points wiped (provider repopulates).

    2. minimum-wages: curated (RON 4050) -> eurostat earn_mw_cur (EUR, geo=RO).
       TE attributes EUROSTAT. The static curated entry of 4050 RON did not
       match TE's display of 795 EUR (2026-S1). Switch to Eurostat for live
       bi-annual EUR figures.

  Deferred gaps (TE attributes national source we don't have a provider for
  yet; we continue to serve from Eurostat/ECB fallback as a TE-acceptable
  approximation; documented as note in docs/te_sources_truth.yaml):

    - budget-deficit, current-account-to-gdp, government-debt,
      government-debt-total, government-spending, government-spending-eur,
      gross-fixed-capital-formation, consumer-spending:
      TE = INSSE / Ministerul Finantelor Publice. We use Eurostat which
      mirrors the same upstream. Scale/unit differs (Eurostat % of GDP /
      index vs TE's RON Million quarterly levels). Future work: extend
      RO INSSE provider with national-accounts and gov-finance matrices.
    - unemployed-persons: TE = ANOFM Romania (registered unemployment count).
      Eurostat LFS provides 504k vs TE ANOFM 260k. Different concepts.
    - current-account: TE = National Bank of Romania (BNR). We use ECB
      SDMX BoP which sources from BNR upstream; honest label = ecb.

  Unknown TE source (TE RO page absent or generic):
    - cpi-clothing, cpi-education, cpi-food, cpi-housing-utilities,
      cpi-recreation-and-culture, energy-inflation, services-inflation,
      services-sentiment, disposable-personal-income, hospital-beds,
      medical-doctors, nurses, credit-rating, unemployment-rate-registered:
      no slug-specific TE page (returns the generic TE homepage). Keep
      existing source.

This migration is idempotent and only changes the rows that are clear
upgrades (inflation-cpi config metadata + minimum-wages source-switch).
"""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8")

from pipeline.db import supabase as sb


def main() -> None:
    # --- inflation-cpi: update metadata (matrix already switched IPC102A->IPC102E
    #     in code; data already refreshed). Idempotent update of the row meta.
    upd = (
        sb.table("indicator_sources")
        .update(
            {
                "series_id": "INSSE/IPC102E",
                "unit": "Index (same month prev year=100)",
                "note": "INSSE Tempo IPC102E CPI YoY index, TOTAL (matches TE headline; 109.5 == +9.5% YoY)",
            }
        )
        .eq("country", "RO")
        .eq("indicator", "inflation-cpi")
        .eq("source", "insse_ro")
        .eq("is_default", True)
        .execute()
    )
    print(f"  + RO/inflation-cpi: indicator_sources note/series_id refreshed (rows: {len(upd.data)})")

    # --- minimum-wages: curated -> eurostat earn_mw_cur ---
    upd2 = (
        sb.table("indicator_sources")
        .update(
            {
                "source": "eurostat",
                "series_id": "earn_mw_cur:RO:EUR",
                "extra_params": {"dataset": "earn_mw_cur", "params": {"currency": "EUR"}},
                "unit": "EUR/Month",
                "adjustment": "",
                "freq_hint": "S",
                "note": "Eurostat earn_mw_cur RO EUR (bi-annual); TE attributes EUROSTAT.",
            }
        )
        .eq("country", "RO")
        .eq("indicator", "minimum-wages")
        .eq("is_default", True)
        .execute()
    )
    print(f"  + RO/minimum-wages: indicator_sources updated to eurostat earn_mw_cur (rows: {len(upd2.data)})")

    # Wipe stale curated point so the next pipeline run repopulates from Eurostat.
    deld = (
        sb.table("data_points")
        .delete()
        .eq("country", "RO")
        .eq("indicator", "minimum-wages")
        .execute()
    )
    print(f"  - RO/minimum-wages: deleted {len(deld.data or [])} stale data_points")

    print()
    print("Done.")


if __name__ == "__main__":
    main()
