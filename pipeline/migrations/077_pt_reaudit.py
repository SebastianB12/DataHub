"""PT re-audit (2026-05-17) — TE-source conformity sweep.

Scope: All 66 PT slugs verified against fresh TE fetches
(see docs/_audit_pt_reaudit.yaml). Findings:

  Real source-corrections needed (TE source != DB default, AND a primary-source
  upgrade is feasible without new provider work):

    1. minimum-wages: curated -> eurostat (Eurostat earn_mw_cur, geo=PT, EUR)
       TE attributes EUROSTAT directly. We had this on the static curated YAML
       (PT:minimum-wages = 870 EUR/Month for 2026-01) which is stale vs the
       Eurostat 2026-S1 reading of 1073 EUR/Month. Switching to eurostat brings
       us in line with TE and onto fresh bi-annual data.

  Deferred gaps (TE attributes national source we don't have a provider for yet;
  we continue to serve from Eurostat fallback as a TE-acceptable approximation;
  documented as gap in docs/te_sources_truth.yaml):

    - current-account, current-account-to-gdp, government-debt,
      government-debt-total: TE = Banco de Portugal. No bdp_pt provider yet.
      Eurostat bop_c6_q / gov_10dd_edpt1 are close substitutes.
    - government-spending-eur: TE = DGO - Direccao Geral do Orcamento.
      No dgo_pt provider.
    - job-vacancies: TE = IEFP (Inst of Employment & Professional Formation).
      We have eurostat jvs_q_nace2 fallback.
    - All slugs where TE attributes Statistics Portugal (INE) but pindica
      varcd discovery for the specific HICP/labour/trade subseries has not
      been completed: kept on Eurostat for now. Existing INE-PT provider
      already covers gdp-real, ppi, industrial-production, unemployment,
      retail-sales, labor-force-participation-rate.

  Unknown TE source (TE PT page absent or generic):
    - credit-rating, energy-inflation, medical-doctors, services-inflation,
      services-sentiment: no PT-specific TE page; keep current source.

This migration is idempotent and only changes the one row that is a clear
upgrade (minimum-wages).
"""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8")

from pipeline.db import supabase as sb


def main() -> None:
    # --- minimum-wages: curated -> eurostat earn_mw_cur ---
    # Update the existing default row in place (preserves PK).
    upd = (
        sb.table("indicator_sources")
        .update(
            {
                "source": "eurostat",
                "series_id": "earn_mw_cur:PT:EUR",
                "extra_params": {"dataset": "earn_mw_cur", "params": {"currency": "EUR"}},
                "unit": "EUR/Month",
                "adjustment": "",
                "freq_hint": "S",
                "note": "Eurostat earn_mw_cur PT EUR (bi-annual); TE attributes EUROSTAT.",
            }
        )
        .eq("country", "PT")
        .eq("indicator", "minimum-wages")
        .eq("is_default", True)
        .execute()
    )
    print(f"  + PT/minimum-wages: indicator_sources updated to eurostat earn_mw_cur (rows: {len(upd.data)})")

    # Wipe stale curated point so the next pipeline run repopulates from Eurostat.
    deld = (
        sb.table("data_points")
        .delete()
        .eq("country", "PT")
        .eq("indicator", "minimum-wages")
        .execute()
    )
    print(f"  - PT/minimum-wages: deleted {len(deld.data or [])} stale data_points")

    print()
    print("Done.")


if __name__ == "__main__":
    main()
