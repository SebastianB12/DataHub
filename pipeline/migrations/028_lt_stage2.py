"""Promote LSD Lithuania (Lietuvos statistikos departamentas) as default source
for stage-2 indicators: retail-sales, gdp-real, unemployment.

CPI (inflation-cpi) and PPI already seeded by 014_lsd_lt_seeds.py.

LSD's user-facing portals (osp.stat.gov.lt, www.lb.lt) sit behind Cloudflare
Turnstile; Lithuania's official open-data gateway data.gov.lt re-publishes
the same LSD datasets through a stable, cookie-less REST API
(https://get.data.gov.lt/datasets/gov/lsd/statistika/<namespace>/<table_id>).

Not seeded for LT (data.gov.lt LSD bucket does not currently expose
short-term tables for these indicators, kept on Eurostat fallback):
  - industrial-production  (no LSD pramones_produkcija/produkcijos_indeksai
                            namespace in the data.gov.lt catalog)
  - trade-balance          (no LSD usienio_prekyba namespace in catalog)

Unemployment via LSD data.gov.lt is *annual* only (metinis_nedarbo_lygis);
the monthly LFS unemployment rate from Eurostat (ei_lmhr_m) remains the
default for higher-frequency consumers.

Demotes existing eurostat/worldbank rows for the same (indicator, country) tuples.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb


SEEDS = [
    # (country, slug, src, series_id, freq, unit, adjustment, conversion, note)
    ("LT", "retail-sales", "lsd_lt",
     "LSD/mazmen_prekyb_imoniu_apyvartos_indeksai/S8R838M40701035",
     "M", "Index (2021=100)", "SA", 1.0,
     "LSD Mazmenines prekybos apyvartos indeksai G47 SA 2021=100"),
    ("LT", "gdp-real",     "lsd_lt",
     "LSD/bvp_palyginamosiomis_kainomis/S7R203M21101011",
     "Q", "Million EUR (chain-linked)", "CA", 1.0,
     "LSD BVP palyginamosiomis kainomis (chain-linked), working-day adj, mln EUR"),
    ("LT", "unemployment", "lsd_lt",
     "LSD/metinis_nedarbo_lygis/S3R347M3030903",
     "A", "%", "NSA", 1.0,
     "LSD Metinis nedarbo lygis age 15+ both sexes LT national annual %"),
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
        print(f"  + {country}/{slug:<22} | {src:<8} | {series_id}")

    print(f"\n{inserted} LSD-direct rows promoted; eurostat counterparts demoted.")


if __name__ == "__main__":
    main()
