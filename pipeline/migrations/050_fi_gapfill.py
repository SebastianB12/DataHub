"""TE-conformity gap-fill for Finland — promote Tilastokeskus (Statistics Finland)
as default for CPI subcomponents (khi 15b5 by COICOP), national-accounts
expenditure components (ntp 132h), food-inflation YoY%, and LFS employment-rate
(tyti 135y Tyollisyysaste).

NOT promoted (kept on eurostat or external):
  - labour-costs: TE attributes to ECB but ECB SDW does not expose national LCI
    for FI; deferred.
  - services-inflation, energy-inflation: StatFin khi tables don't expose direct
    services / energy aggregates. Eurostat ei_cphi_m covers these.
  - consumer/business-confidence: TE source is EK / Tilastokeskus consumer survey
    — Tilastokeskus does publish KBAR, but wiring is out of immediate scope.
  - job-vacancies: Ministry of Employment, out of scope.
  - government-debt(-total): State Treasury Finland, out of scope.
  - population, current-account, mining/manufacturing-production,
    disposable-personal-income, labor-force-participation-rate: covered or
    deferred separately.

TE-conformity smoke values (verified 2026-05-14):
  cpi-food                        2026-04 = 101.75   (TE: 101.75)
  cpi-clothing                    2026-04 = 99.67    (TE: 99.67)
  cpi-housing-utilities           2026-04 = 100.11   (TE: 100.11)
  cpi-transportation              2026-04 = 105.80   (TE: 105.80)
  cpi-recreation-and-culture      2026-04 = 101.02
  cpi-education                   2026-04 = 110.48
  food-inflation                  2026-04 = 1.7 %
  employment-rate                 2026-03 = 69.2 %   (TE: 69.2 EXACT for 2026-02)
  consumer-spending               2025Q4  = 29,614 EUR mn  (TE: 29,614 EXACT)
  changes-in-inventories          2025Q4  = 85 EUR mn (current prices SA)
  government-spending             2025Q4  = 15,070 EUR mn (chained 2015 SA)
  gross-fixed-capital-formation   2025Q4  = 12,341 EUR mn (chained 2015 SA)

Run order:
    python -m pipeline.migrations.050_fi_gapfill
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb


SEEDS = [
    ("FI", "cpi-food", "stat_fi", "STATFI/khi/15b5/cpi-food", "M",
     "Index (2025=100)", "NSA", 1.0,
     "FI Tilastokeskus 15b5 CPI Food & non-alc beverages (COICOP 01)"),
    ("FI", "cpi-clothing", "stat_fi", "STATFI/khi/15b5/cpi-clothing", "M",
     "Index (2025=100)", "NSA", 1.0,
     "FI Tilastokeskus 15b5 CPI Clothing & footwear (COICOP 03)"),
    ("FI", "cpi-housing-utilities", "stat_fi", "STATFI/khi/15b5/cpi-housing", "M",
     "Index (2025=100)", "NSA", 1.0,
     "FI Tilastokeskus 15b5 CPI Housing/utilities (COICOP 04)"),
    ("FI", "cpi-transportation", "stat_fi", "STATFI/khi/15b5/cpi-transport", "M",
     "Index (2025=100)", "NSA", 1.0,
     "FI Tilastokeskus 15b5 CPI Transport (COICOP 07)"),
    ("FI", "cpi-recreation-and-culture", "stat_fi", "STATFI/khi/15b5/cpi-recreation", "M",
     "Index (2025=100)", "NSA", 1.0,
     "FI Tilastokeskus 15b5 CPI Recreation & culture (COICOP 09)"),
    ("FI", "cpi-education", "stat_fi", "STATFI/khi/15b5/cpi-education", "M",
     "Index (2025=100)", "NSA", 1.0,
     "FI Tilastokeskus 15b5 CPI Education (COICOP 10)"),
    ("FI", "food-inflation", "stat_fi", "STATFI/khi/15b5/food-yoy", "M",
     "% YoY", "NSA", 1.0,
     "FI Tilastokeskus 15b5 CPI Food YoY% (01, vm_khi)"),
    ("FI", "employment-rate", "stat_fi", "STATFI/tyti/135y/empl-rate", "M",
     "%", "NSA", 1.0,
     "FI Tilastokeskus 135y LFS Employment Rate 15-64 both sexes NSA"),
    ("FI", "consumer-spending", "stat_fi", "STATFI/ntp/132h/consumer", "Q",
     "EUR million (chained 2015)", "SA", 1.0,
     "FI Tilastokeskus 132h Private consumption (P3KS14_S15), chained 2015 SA EUR mn"),
    ("FI", "changes-in-inventories", "stat_fi", "STATFI/ntp/132h/inventories", "Q",
     "EUR million (current prices)", "SA", 1.0,
     "FI Tilastokeskus 132h Change in inventories (P52K), current prices SA EUR mn"),
    ("FI", "government-spending", "stat_fi", "STATFI/ntp/132h/gov-spending", "Q",
     "EUR million (chained 2015)", "SA", 1.0,
     "FI Tilastokeskus 132h Government consumption (P3KS13), chained 2015 SA EUR mn"),
    ("FI", "gross-fixed-capital-formation", "stat_fi", "STATFI/ntp/132h/gfcf", "Q",
     "EUR million (chained 2015)", "SA", 1.0,
     "FI Tilastokeskus 132h GFCF (P51K), chained 2015 SA EUR mn"),
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
    print(f"\n{inserted} FI TE-conformity rows promoted; eurostat counterparts demoted.")


if __name__ == "__main__":
    main()
