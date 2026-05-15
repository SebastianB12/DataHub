"""AT gap-fill (Cycle 9, 2026-05-15) — close all `suggested_source: stat_at`
TE-source-conformity gaps.

Promotes Statistik Austria as the default source for:
  CPI sub-indices  : cpi-food, cpi-clothing, cpi-housing-utilities,
                     cpi-transportation, cpi-recreation-and-culture, cpi-education
                     (via OGD_vpi20_VPI_2020_1, COICOP at C-VPI5NEU-0, F-VPIMZBM level
                     index. Coverage runs through 2025-12 — OGD update lag accepted.)
  food-inflation   : OGD_vpi20_VPI_2020_1 VPI-01 F-VPIPZVJM (% YoY column).
  VGR108 components: consumer-spending, government-spending,
                     gross-fixed-capital-formation, changes-in-inventories
                     (real SA via F-RSAIB; for changes-in-inventories use F-NSAIB
                     because RSAIB column is zero-stamped placeholder).
  IP sub-breakdowns: manufacturing-production (NACE C, col F-KJIP_NAC_C),
                     mining-production (NACE B, col F-KJIP_NAC_B)
                     — same OGD_kjiprodindex2021 dataset as industrial-production;
                     KJIB00-10 (Industrie gesamt) row, working-day adjusted (X93-2).
  retail-sales     : OGD_konjidxhan21_KJIX_H_21_1 NACE-G47 nominal SA (F-UIDXNSB,
                     2021=100). Already seeded as inactive in 030_at_stage2; flip default.

Existing eurostat siblings are demoted (is_default=False).

Smoke-tested 2026-05-15:
  cpi-food                       2025-12 = 133.1   (last available, coverage to 2025-12)
  cpi-clothing                   2025-12 = 111.8
  cpi-housing-utilities          2025-12 = 140.9
  cpi-transportation             2025-12 = 128.9
  cpi-recreation-and-culture     2025-12 = 124.7
  cpi-education                  2025-12 = 125.3
  food-inflation                 2025-12 = 3.9% YoY
  consumer-spending              2025-10 = 46.6 Bn EUR (real SA)
  government-spending            2025-10 = 20.6 Bn EUR
  gross-fixed-capital-formation  2025-10 = 22.2 Bn EUR
  changes-in-inventories         2025-10 = -0.156 Bn EUR (nominal SA)
  mining-production              2026-03 = 81.3   (NACE B, WDA, 2021=100)
  manufacturing-production       2026-03 = 115.4  (NACE C, WDA, 2021=100)
  retail-sales                   already in data_points via stage-2; just promote default.
"""
import sys

sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb


SEEDS = [
    # (slug, series_id, freq, unit, adjustment, conversion, note)
    ("cpi-food", "STATAT/OGD_vpi20_VPI_2020_1#VPI-01", "M",
     "Index (2020=100)", "NSA", 1.0,
     "Statistik Austria VPI 2020 COICOP-01 Food (level)"),
    ("cpi-clothing", "STATAT/OGD_vpi20_VPI_2020_1#VPI-03", "M",
     "Index (2020=100)", "NSA", 1.0,
     "Statistik Austria VPI 2020 COICOP-03 Clothing (level)"),
    ("cpi-housing-utilities", "STATAT/OGD_vpi20_VPI_2020_1#VPI-04", "M",
     "Index (2020=100)", "NSA", 1.0,
     "Statistik Austria VPI 2020 COICOP-04 Housing/water/electricity (level)"),
    ("cpi-transportation", "STATAT/OGD_vpi20_VPI_2020_1#VPI-07", "M",
     "Index (2020=100)", "NSA", 1.0,
     "Statistik Austria VPI 2020 COICOP-07 Transport (level)"),
    ("cpi-recreation-and-culture", "STATAT/OGD_vpi20_VPI_2020_1#VPI-09", "M",
     "Index (2020=100)", "NSA", 1.0,
     "Statistik Austria VPI 2020 COICOP-09 Recreation & culture (level)"),
    ("cpi-education", "STATAT/OGD_vpi20_VPI_2020_1#VPI-10", "M",
     "Index (2020=100)", "NSA", 1.0,
     "Statistik Austria VPI 2020 COICOP-10 Education (level)"),
    ("food-inflation", "STATAT/OGD_vpi20_VPI_2020_1#VPI-01-PZVJM", "M",
     "% YoY", "NSA", 1.0,
     "Statistik Austria VPI 2020 COICOP-01 Food YoY % (F-VPIPZVJM)"),

    ("consumer-spending", "STATAT/OGD_vgr108_VGR_HA_vj_1#VGRHAG-16", "Q",
     "Bn EUR (real, SA)", "SA", 0.001,
     "Statistik Austria VGR108 VGRHAG-16 HH final consumption, real SA, Mio→Bn"),
    ("government-spending", "STATAT/OGD_vgr108_VGR_HA_vj_1#VGRHAG-18", "Q",
     "Bn EUR (real, SA)", "SA", 0.001,
     "Statistik Austria VGR108 VGRHAG-18 Government final consumption, real SA"),
    ("gross-fixed-capital-formation", "STATAT/OGD_vgr108_VGR_HA_vj_1#VGRHAG-23", "Q",
     "Bn EUR (real, SA)", "SA", 0.001,
     "Statistik Austria VGR108 VGRHAG-23 Gross fixed capital formation, real SA"),
    ("changes-in-inventories", "STATAT/OGD_vgr108_VGR_HA_vj_1#VGRHAG-32", "Q",
     "Bn EUR (nominal, SA)", "SA", 0.001,
     "Statistik Austria VGR108 VGRHAG-32 Changes in inventories, nominal SA"),

    ("mining-production", "STATAT/OGD_kjiprodindex2021_KJID2021_PI_1#NAC_B", "M",
     "Index (2021=100, WDA)", "WDA", 1.0,
     "Statistik Austria Produktionsindex NACE B Bergbau (col F-KJIP_NAC_B), WDA"),
    ("manufacturing-production", "STATAT/OGD_kjiprodindex2021_KJID2021_PI_1#NAC_C", "M",
     "Index (2021=100, WDA)", "WDA", 1.0,
     "Statistik Austria Produktionsindex NACE C Verarbeitendes (col F-KJIP_NAC_C), WDA"),

    ("retail-sales", "STATAT/OGD_konjidxhan21_KJIX_H_21_1#NACE-47-UIDXNSB", "M",
     "Index (2021=100, SA)", "SA", 1.0,
     "Statistik Austria Konjunkturindizes Handel G47 (Einzelhandel), nominell SA, 2021=100"),
]


def main():
    inserted = 0
    country = "AT"
    src = "stat_at"
    for slug, series_id, freq, unit, adj, conv, note in SEEDS:
        # Drop pre-existing stat_at row for this slug (idempotent re-run)
        sb.table("indicator_sources").delete().eq(
            "indicator", slug
        ).eq("country", country).eq("source", src).execute()
        # Demote any other defaults (e.g. eurostat) for this slug/country
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
        print(f"  + {country}/{slug:<35} | {src} | {series_id}")
    print(f"\n{inserted} AT stat_at rows promoted; eurostat siblings demoted.")


if __name__ == "__main__":
    main()
