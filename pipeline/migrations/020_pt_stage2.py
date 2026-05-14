"""Promote INE Portugal (Instituto Nacional de Estatistica) as default source
for stage-2 indicators: ppi, industrial-production, unemployment, retail-sales,
gdp-real.

Provider: pipeline.providers.national_eu.fetch_pt_indicator
API:      https://www.ine.pt/ine/json_indicador/pindica.jsp
          op=1 (full history) or op=2 (latest only). No auth.

Verified 2026-05-14 against Trading Economics:
  - ppi                    : varcd 0012002, Mar 2026 = 0.0 % YoY   (TE: 0.0)
  - industrial-production  : varcd 0011900, Mar 2026 = 3.2 % YoY   (TE: 3.2)
  - unemployment           : varcd 0012136, Q1 2026  = 6.1 %       (TE: 6.1)
  - retail-sales           : varcd 0012019, Mar 2026 = 5.5 % YoY   (TE: 5.5)
  - gdp-real               : varcd 0013431, Q1 2026  = 2.3 % YoY   (TE: 2.3)

Trade-balance NOT seeded for PT — INE only exposes monthly trade flows by
NUTS/CGCE in multi-dimensional tables that exceed the pindica row cap; the
aggregated national balance stays on Eurostat (DS-018995 / ext_st_eu27_2020sitc).

GDP-real upstream caveat: INE pindica op=1 for varcd 0013431 currently returns
the same value for every quarter (server-side bug). Provider falls back to
op=2 single-period fetch. History gap is back-filled by Eurostat (namq_10_gdp)
until INE fixes op=1 — that's why the eurostat row stays active=true but
demoted is_default=false.

CPI is intentionally NOT touched here — the existing inflation-cpi seed
(varcd 0008273) is mis-mapped upstream and tracked as a separate fix.

Run:
    python -m pipeline.migrations.020_pt_stage2
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb


# (country, slug, src, series_id, freq, unit, adjustment, conversion, note)
SEEDS = [
    ("PT", "ppi", "ine_pt",
     "INE/0012002",
     "M", "% YoY", "NSA", 1.0,
     "INE PT 0012002 IPPI Total YoY%, Base 2021 (CAE Rev.3, dim_3=TOT)"),

    ("PT", "industrial-production", "ine_pt",
     "INE/0011900",
     "M", "% YoY", "SA+CDA", 1.0,
     "INE PT 0011900 IPI YoY% calendar+seasonally adjusted, Base 2021 (dim_3=T)"),

    ("PT", "unemployment", "ine_pt",
     "INE/0012136",
     "Q", "%", "NSA", 1.0,
     "INE PT 0012136 Taxa de desemprego LFS (Serie 2021), both sexes, NUTS-2024"),

    ("PT", "retail-sales", "ine_pt",
     "INE/0012019",
     "M", "% YoY", "SA+CDA deflated", 1.0,
     "INE PT 0012019 IVN comercio retalho YoY% deflated cal+SA, Base 2021 (CAE 47)"),

    ("PT", "gdp-real", "ine_pt",
     "INE/0013431",
     "Q", "% YoY", "SA+CDA", 1.0,
     "INE PT 0013431 GDP chain-linked YoY%, Base 2021 (op=2 latest-only; op=1 broken upstream)"),
]

# Demote alternative sources for the same (country, slug) tuples.
DEMOTE_SOURCES = ("eurostat", "worldbank", "dbnomics", "fred", "ecb")


def main():
    inserted = 0
    for country, slug, src, series_id, freq, unit, adj, conv, note in SEEDS:
        # Idempotent: drop any prior ine_pt row for this slug/country.
        sb.table("indicator_sources").delete().eq(
            "indicator", slug
        ).eq("country", country).eq("source", src).execute()

        # Demote other-source counterparts for this slug.
        for other in DEMOTE_SOURCES:
            sb.table("indicator_sources").update({"is_default": False}).eq(
                "indicator", slug
            ).eq("country", country).eq("source", other).execute()

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
        print(f"  + {country}/{slug:<22} | {src:<8} | {series_id}")

    print(f"\n{inserted} INE Portugal rows promoted (is_default=true). "
          "Eurostat/WB/DBnomics/FRED/ECB counterparts demoted.")


if __name__ == "__main__":
    main()
