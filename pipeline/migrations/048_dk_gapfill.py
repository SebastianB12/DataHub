"""TE-conformity gap-fill for Denmark — promote Statistics Denmark (DST) as default
for CPI subcomponents (PRIS01 COICOP), national-accounts expenditure components
(NKN1), food-inflation YoY%, and LFS employment-rate (AKU121K).

Also promotes worldbank for `gdp` (TE attributes to World Bank).

NOT promoted (kept on eurostat fallback):
  - labour-costs: TE attributes to ECB but ECB SDW does not expose national LCI
    for DK; deferred until a national LCI table is wired.
  - services-inflation, energy-inflation: DK Statbank PRIS* tables do not expose
    pre-computed services / energy aggregates. Eurostat ei_cphi_m covers these.
  - government-debt, government-debt-total (Danmarks Nationalbank), labor-force-
    participation-rate, current-account, mining/manufacturing-production,
    job-vacancies, productivity, population, disposable-personal-income:
    out of immediate scope; can be added in a follow-up batch.

TE-conformity smoke values (verified 2026-05-14):
  cpi-food                        2026-04 = 100.74    (TE matches via DST PRIS01)
  cpi-clothing                    2026-04 = 102.02    (TE: 102.02)
  cpi-housing-utilities           2026-04 = 99.36     (TE: 99.36)
  cpi-transportation              2026-04 = 103.46    (TE: 103.46)
  cpi-recreation-and-culture      2026-04 = 98.88     (TE: 98.88)
  cpi-education                   2026-04 = 103.22
  food-inflation                  2026-04 = 2.7%
  consumer-spending               2025Q4  = 276.7 bn  (TE: 274.9 bn, vintage diff)
  changes-in-inventories          2025Q4  = -8.8 bn DKK SA
  government-spending             2025Q4  = 158.4 bn  (TE: 157.6 bn)
  gross-fixed-capital-formation   2025Q4  = 140.8 bn  (TE: 130.5 bn, vintage diff)
  employment-rate                 2025Q4  = 76.2%     (TE: 76.6%)

Run order:
    python -m pipeline.migrations.048_dk_gapfill
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb


# (country, slug, src, series_id, freq, unit, adjustment, conversion, note)
SEEDS = [
    ("DK", "cpi-food", "dst", "DST/PRIS01/cpi-food", "M",
     "Index", "NSA", 1.0,
     "DK Statbank PRIS01 CPI Food & non-alc beverages (COICOP 01) index"),
    ("DK", "cpi-clothing", "dst", "DST/PRIS01/cpi-clothing", "M",
     "Index", "NSA", 1.0,
     "DK Statbank PRIS01 CPI Clothing & footwear (COICOP 03) index"),
    ("DK", "cpi-housing-utilities", "dst", "DST/PRIS01/cpi-housing", "M",
     "Index", "NSA", 1.0,
     "DK Statbank PRIS01 CPI Housing & utilities (COICOP 04) index"),
    ("DK", "cpi-transportation", "dst", "DST/PRIS01/cpi-transport", "M",
     "Index", "NSA", 1.0,
     "DK Statbank PRIS01 CPI Transport (COICOP 07) index"),
    ("DK", "cpi-recreation-and-culture", "dst", "DST/PRIS01/cpi-recreation", "M",
     "Index", "NSA", 1.0,
     "DK Statbank PRIS01 CPI Recreation & culture (COICOP 09) index"),
    ("DK", "cpi-education", "dst", "DST/PRIS01/cpi-education", "M",
     "Index", "NSA", 1.0,
     "DK Statbank PRIS01 CPI Education (COICOP 10) index"),
    ("DK", "food-inflation", "dst", "DST/PRIS01/food-yoy", "M",
     "% YoY", "NSA", 1.0,
     "DK Statbank PRIS01 CPI Food YoY% (COICOP 01, ENHED 300)"),
    ("DK", "consumer-spending", "dst", "DST/NKN1/consumer-spending", "Q",
     "Billion DKK (2020 chained)", "SA", 1.0,
     "DK Statbank NKN1 Household consumption (P31S14D), chained 2020 SA, bn DKK"),
    ("DK", "changes-in-inventories", "dst", "DST/NKN1/inventories", "Q",
     "Billion DKK", "SA", 1.0,
     "DK Statbank NKN1 Changes in inventories (P52D), current prices SA, bn DKK"),
    ("DK", "government-spending", "dst", "DST/NKN1/gov-spending", "Q",
     "Billion DKK (2020 chained)", "SA", 1.0,
     "DK Statbank NKN1 Government consumption (P3S13D), chained 2020 SA, bn DKK"),
    ("DK", "gross-fixed-capital-formation", "dst", "DST/NKN1/gfcf", "Q",
     "Billion DKK (2020 chained)", "SA", 1.0,
     "DK Statbank NKN1 GFCF (P51GD), chained 2020 SA, bn DKK"),
    ("DK", "employment-rate", "dst", "DST/AKU121K", "Q",
     "%", "SA", 1.0,
     "DK Statbank AKU121K LFS employment rate (BFK), All DK SA quarterly"),
    # gdp: TE attributes to World Bank. Promote WB row, demote DST national accounts
    # (national-accounts annual is kept inactive in db but unused as headline).
    ("DK", "gdp", "worldbank", "NY.GDP.MKTP.CD", "A",
     "Billion USD", "NSA", 1.0,
     "DK World Bank NY.GDP.MKTP.CD annual GDP, current USD (TE source)"),
]


def main():
    inserted = 0
    for country, slug, src, series_id, freq, unit, adj, conv, note in SEEDS:
        # Idempotent: clear same-source row first
        sb.table("indicator_sources").delete().eq(
            "indicator", slug
        ).eq("country", country).eq("source", src).execute()
        # Demote any other defaults for this (slug, country)
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
        print(f"  + {country}/{slug:<32} | {src:<10} | {series_id}")
    print(f"\n{inserted} DK TE-conformity rows promoted; eurostat/national counterparts demoted.")


if __name__ == "__main__":
    main()
