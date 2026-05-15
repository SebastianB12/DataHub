"""Promote INE Portugal (pindica.jsp) as default for additional PT slugs.

Migration 054 already wired ine_pt for the headline INE pindica indicators that
TE attributes to "Statistics Portugal": ppi (0012002), industrial-production
(0011900), unemployment (0012136), retail-sales (0012019), and gdp-real
(0013431).

This migration extends to:

  labor-force-participation-rate   0010060   Taxa de atividade da populacao
                                              residente 16-74, monthly, %
                                              (dim_3='T' = both sexes)

TE quotes 'INE Portugal' for the labour-force participation rate; the legacy
DB row pointed to Eurostat lfsi_emp_q. Switching to the INE monthly series
gives both the same value and a more timely monthly cadence (TE itself uses
the monthly version).

TE-conformity smoke (verified 2026-05-15):
  labor-force-participation-rate   2026-03 = 69.7 %  (TE: 69.7)   MATCH

PT slugs still served by eurostat (deferred — see notes):
  cpi-* sub-components  -> INE moved current IPC publication (Base 2017+) off
                           pindica.jsp into a separate dissemination channel
                           that is not yet exposed via JSON; the legacy
                           Base-2012 family (0007320/0008351/0008352) is frozen
                           at 2024-12. Until the new endpoint is identified, the
                           sub-component slugs remain on Eurostat HICP.
  changes-in-inventories,
    disposable-personal-income     -> INE quarterly contas nacionais excel
  employed-persons, unemployed-persons,
    employment-rate                -> INE monthly varcds (0010056/0010054
                                       siblings) need separate sweep + provider
                                       additions; deferred.
  inflation-cpi, food-inflation    -> Eurostat HICP retained (see 054_pt_cpifix)
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb


SEEDS = [
    # (slug, series_id, freq, unit, adjustment, conversion, note)
    ("labor-force-participation-rate", "INE-PT/0010060", "M",
     "%", "NSA", 1.0,
     "INE PT 0010060 Taxa de atividade da populacao residente 16-74 (both sexes), monthly"),
]


def main():
    inserted = 0
    country = "PT"
    src = "ine_pt"
    for slug, series_id, freq, unit, adj, conv, note in SEEDS:
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
        print(f"  + {country}/{slug:<32} | {src} | {series_id}")
    print(f"\n{inserted} PT INE cycle-9 rows promoted; eurostat siblings demoted.")


if __name__ == "__main__":
    main()
