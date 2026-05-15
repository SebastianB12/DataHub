"""TE-conformity gap-fill (cycle 9) for Denmark — promote Statistics Denmark (DST)
as default for 11 remaining gaps still on eurostat.

Series added to DK_SERIES in providers/national_eu.py (Migration 071 block).

TE-conformity smoke values (verified 2026-05-15):
  budget-deficit                  2025    = 2.9 (% GDP)        (TE: 2.9 EXACT)
  core-cpi                        2026-04 = 1.6 % YoY          (TE: 1.6 EXACT, PRIS04/151N)
  current-account                 2026-03 = 38,339.6 mio DKK   (BBM net, SA)
  disposable-personal-income      2024    = 1,431,342 mio DKK  (INDKP106)
  job-vacancies                   2025Q4  = 45,766             (TE: 45,766 EXACT)
  labor-force-participation-rate  2025Q4  = 81.5 %             (TE: 81.9, ~0.4pp vintage)
  manufacturing-production        2026-03 = 154.5 (Idx 2021)   (IPOP21 NACE C, SA)
  mining-production               2026-03 = 164.9 (Idx 2021)   (IPOP21 NACE B, SA)
  population                      2026Q2  = 6.031 M            (FOLK1A)
  productivity                    2025    = 105.09 (Idx 2020)  (NP23 PIALT; TE 119.31 — different
                                                                methodology, source-conformity kept)
  services-inflation              2026-04 = 2.2 % YoY          (TE: 2.2 EXACT for 2026-03)

Run order:
    python -m pipeline.migrations.071_dk_gapfill_c9
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb


SEEDS = [
    ("DK", "budget-deficit", "dst", "DST/EDP1/deficit-pct-gdp", "A",
     "% of GDP", "NSA", 1.0,
     "DK Statbank EDP1 Government EMU surplus/deficit % of GDP, annual"),
    ("DK", "core-cpi", "dst", "DST/PRIS04/core-yoy", "M",
     "% YoY", "NSA", 1.0,
     "DK Statbank PRIS04 Net price index excl. energy & unprocessed food (151N) YoY %"),
    ("DK", "current-account", "dst", "DST/BBM/current-account", "M",
     "Million DKK", "SA", 1.0,
     "DK Statbank BBM Current account net vs World, SA, mio DKK monthly"),
    ("DK", "disposable-personal-income", "dst", "DST/INDKP106", "A",
     "Million DKK", "NSA", 0.001,
     "DK Statbank INDKP106 Disposable income total, all ages, DKK 1000 -> mio DKK"),
    ("DK", "job-vacancies", "dst", "DST/LSK03", "Q",
     "Number", "NSA", 1.0,
     "DK Statbank LSK03 Job vacancies (number), NSA, quarterly"),
    ("DK", "labor-force-participation-rate", "dst", "DST/AKU121K/EFK", "Q",
     "%", "SA", 1.0,
     "DK Statbank AKU121K LFS Economic activity rate (EFK), All DK, SA, quarterly"),
    ("DK", "manufacturing-production", "dst", "DST/IPOP21/C", "M",
     "Index (2021=100)", "SA", 1.0,
     "DK Statbank IPOP21 Manufacturing production index (NACE C), SA"),
    ("DK", "mining-production", "dst", "DST/IPOP21/B", "M",
     "Index (2021=100)", "SA", 1.0,
     "DK Statbank IPOP21 Mining and quarrying production index (NACE B), SA"),
    ("DK", "population", "dst", "DST/FOLK1A", "Q",
     "Million", "NSA", 1e-6,
     "DK Statbank FOLK1A Population at first day of quarter, persons -> million"),
    ("DK", "productivity", "dst", "DST/NP23/PIALT", "A",
     "Index (2020=100)", "NSA", 1.0,
     "DK Statbank NP23 Labour productivity index, total economy (PIALT), 2020=100"),
    ("DK", "services-inflation", "dst", "DST/PRIS04/services-yoy", "M",
     "% YoY", "NSA", 1.0,
     "DK Statbank PRIS04 Services (142) YoY % inflation"),
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
        print(f"  + {country}/{slug:<32} | {src:<8} | {series_id}")
    print(f"\n{inserted} DK TE-conformity rows promoted (cycle 9); eurostat demoted.")
    print("Run `pipeline/.venv/Scripts/python -m pipeline.providers.national_eu` to ingest.")


if __name__ == "__main__":
    main()
