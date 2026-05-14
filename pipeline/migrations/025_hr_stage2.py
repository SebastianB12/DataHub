"""Promote DZS Croatia (Drzavni zavod za statistiku) as default source for
stage-2 indicators: industrial-production, ppi, retail-sales, gdp-real.

CPI (inflation-cpi) is already seeded by 012_national_eu_seeds.py and stays
on the existing ME_PS09 ECOICOP v2 series.

Discovery via https://web.dzs.hr/PXWeb/api/v1/en/ — PxWeb DB rooted at the
language code with topic-level dbids (Cijene, Industrija, Trgovina na malo,
Nacionalni racuni, ...). Stage-2 monthly tables use *split* GODINA+MJESEC
(Roman) dimensions; GDP quarterly table BDP-T01_EUR uses Godina + Tromjesecje
(1..4).

Not seeded for HR (no DZS PxWeb path discovered, kept on Eurostat fallback):
  - unemployment   (DZS publishes only registered unemployment in HTML / LFS
                    rate sits behind Eurostat)
  - trade-balance  (DZS publishes only annual CN-coded files via PxWeb)

Demotes existing eurostat rows for the same (indicator, country) tuples.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb


SEEDS = [
    # (country, slug, src, series_id, freq, unit, adjustment, conversion, note)
    ("HR", "industrial-production", "dzs_hr", "DZS/BS_IN11",     "M",
     "Index (2021=100)", "NSA", 1.0,
     "DZS Croatia BS_IN11 IP volume index Total industry gross 2021=100"),
    ("HR", "ppi",                   "dzs_hr", "DZS/BS_PP11",     "M",
     "Index (2021=100)", "NSA", 1.0,
     "DZS Croatia BS_PP11 PPI domestic market Total industry 2021=100"),
    ("HR", "retail-sales",          "dzs_hr", "DZS/BS_TR21",     "M",
     "Index (2021=100)", "NSA", 1.0,
     "DZS Croatia BS_TR21 retail trade turnover gross value index G47 2021=100"),
    ("HR", "gdp-real",              "dzs_hr", "DZS/BDP-T01_EUR", "Q",
     "Million EUR (constant 2021 prices)", "NSA", 1.0,
     "DZS Croatia BDP-T01_EUR real GDP constant ref-year 2021 prices, mln EUR"),
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

    print(f"\n{inserted} DZS-direct rows promoted; eurostat counterparts demoted.")


if __name__ == "__main__":
    main()
