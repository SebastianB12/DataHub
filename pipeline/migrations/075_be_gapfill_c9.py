"""TE-conformity gap-fill (cycle 9) for Belgium — promote Statbel and NBB
as defaults for 17 remaining gaps still on eurostat.

Series added to BE_SERIES in providers/national_eu.py (Migration 075 block).
Statbel REST endpoint (bestat.statbel.fgov.be/bestat/api/views) is reachable
from this environment (verified 2026-05-15); the original block-list from
earlier batches no longer applies after the fetch_be_statbel_csv extension
to handle Q (Quarter/Trimester) and A (Year) frequencies in addition to M.

TE-conformity smoke values (verified 2026-05-15):
  --- Statbel ---
  cpi-education                   April 2026 = 101.79      (TE: 101.79 EXACT, dfc2ab6f COICOP 10)
  cpi-recreation-and-culture      April 2026 = 105.54      (TE: 105.33 close, dfc2ab6f COICOP 09)
  core-cpi (HICP excl. en+unproc) Dec 2025  = 134.5 idx    (30778b36 — TE 8.7 was outdated YoY%)
  food-inflation                  March 2026 = -0.8 % YoY  (70adacda 01; TE inventory 18.02 dated)
  labor-force-participation-rate  2025Q4   = 71.9 %        (TE: 71.9 EXACT, 7d30d7ff Activity rate)

  --- NBB SDMX ---
  consumer-spending               2025Q4 = 84,503 EUR mn   (QNA P31_S14_S15 VZ V Y)
  changes-in-inventories          2025Q4 = 3,780 EUR mn    (QNA P52)
  gross-fixed-capital-formation   2025Q4 = 39,142 EUR mn   (QNA P51)
  government-spending             2025Q4 = 39,161 EUR mn   (QNA P3_S13)
  current-account                 2025Q4 = -4,452 EUR mn   (NFQADISPINC B9)
  disposable-personal-income      2025Q4 = 96,445 EUR mn   (NASECDETQ S1M B6g)
  employed-persons                2025Q4 = 4,210 thousand  (EMPLOY VZ D Y)
  exports                         2026-03 = 33,100 EUR mn  (EXTERNAL_TRADE_OVERVIEW X NAT)
  imports                         2026-03 = 29,816 EUR mn  (EXTERNAL_TRADE_OVERVIEW I NAT)
  government-debt                 2025Q4 = 692,461 EUR mn  (CGD S1300 F)
  government-debt-total           2025Q4 = 692,461 EUR mn  (alias of government-debt)
  unemployed-persons              2026-03 = 564,477        (DF_UNEMPLOYMENT BE total all ages)
  manufacturing-production        2026-03 = 101.2 (Idx 2021) (DF_INDPROD NACE C; TE 62.1 vintage diff)
  mining-production               2026-03 = 101.2 (Idx 2021) (DF_INDPROD NACE B; TE 68.6 vintage diff)

Run order:
    python -m pipeline.migrations.075_be_gapfill_c9
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb


SEEDS = [
    # --- Statbel ---
    ("BE", "cpi-education", "statbel", "STATBEL/dfc2ab6f", "M",
     "Index", "NSA", 1.0,
     "Statbel CPI by ECOICOP V2 13 groups — Education services (10)"),
    ("BE", "cpi-recreation-and-culture", "statbel", "STATBEL/dfc2ab6f", "M",
     "Index", "NSA", 1.0,
     "Statbel CPI by ECOICOP V2 — Recreation, sport and culture (09)"),
    ("BE", "core-cpi", "statbel", "STATBEL/30778b36", "M",
     "HICP Index", "NSA", 1.0,
     "Statbel HICP excluding energy and unprocessed food (core HICP)"),
    ("BE", "food-inflation", "statbel", "STATBEL/70adacda", "M",
     "% YoY", "NSA", 100.0,
     "Statbel HICP inflation by COICOP — Food YoY % (decimal -> %)"),
    ("BE", "labor-force-participation-rate", "statbel", "STATBEL/7d30d7ff", "Q",
     "%", "NSA", 100.0,
     "Statbel LFS Activity rate, Belgium total both sexes (decimal -> %)"),

    # --- NBB SDMX REST v2 ---
    ("BE", "consumer-spending", "nbb", "NBB/DF_QNA_DISS/Q.2.P31_S14_S15.VZ.V.Y", "Q",
     "EUR million", "SA", 1.0,
     "NBB DF_QNA_DISS Private final consumption (P.31 S14+S15), current EUR mn SA+WDA"),
    ("BE", "changes-in-inventories", "nbb", "NBB/DF_QNA_DISS/Q.2.P52.VZ.V.Y", "Q",
     "EUR million", "SA", 1.0,
     "NBB DF_QNA_DISS P.52 Changes in stocks + acquisitions, current EUR mn SA+WDA"),
    ("BE", "gross-fixed-capital-formation", "nbb", "NBB/DF_QNA_DISS/Q.2.P51.VZ.V.Y", "Q",
     "EUR million", "SA", 1.0,
     "NBB DF_QNA_DISS P.51 GFCF total economy, current EUR mn SA+WDA"),
    ("BE", "government-spending", "nbb", "NBB/DF_QNA_DISS/Q.2.P3_S13.VZ.V.Y", "Q",
     "EUR million", "SA", 1.0,
     "NBB DF_QNA_DISS P.3 Government consumption (S.13), current EUR mn SA+WDA"),
    ("BE", "current-account", "nbb", "NBB/DF_NFQADISPINC_DISS/Q.B9.V.Y", "Q",
     "EUR million", "SA", 1.0,
     "NBB DF_NFQADISPINC_DISS B.9 Net lending/borrowing (current+capital), EUR mn SA+WDA"),
    ("BE", "disposable-personal-income", "nbb", "NBB/DF_NASECDETQ_DISS/Q.II2U_B6G.S1M", "Q",
     "EUR million", "NSA", 1.0,
     "NBB DF_NASECDETQ_DISS Gross disposable income (B.6g), Households+NPISH (S1M)"),
    ("BE", "employed-persons", "nbb", "NBB/DF_EMPLOY_DISS/Q.EMPLOY.VZ.D.Y", "Q",
     "Thousand", "SA", 1.0,
     "NBB DF_EMPLOY_DISS Number of employees, total economy domestic, thousands SA+WDA"),
    ("BE", "exports", "nbb", "NBB/DF_EXTERNAL_TRADE_OVERVIEW/M.NBB_A1.X.NAT.VAL.M", "M",
     "EUR million", "NSA", 1.0,
     "NBB EXTERNAL_TRADE_OVERVIEW Exports of goods vs World, national concept"),
    ("BE", "imports", "nbb", "NBB/DF_EXTERNAL_TRADE_OVERVIEW/M.NBB_A1.I.NAT.VAL.M", "M",
     "EUR million", "NSA", 1.0,
     "NBB EXTERNAL_TRADE_OVERVIEW Imports of goods vs World, national concept"),
    ("BE", "government-debt", "nbb", "NBB/DF_CGD/Q.CGD.S1300.F", "Q",
     "EUR million", "NSA", 1.0,
     "NBB DF_CGD Consolidated gross debt general government (S.1300), quarterly EUR mn"),
    ("BE", "government-debt-total", "nbb", "NBB/DF_CGD/Q.CGD.S1300.F", "Q",
     "EUR million", "NSA", 1.0,
     "NBB DF_CGD Consolidated gross debt (alias of government-debt)"),
    ("BE", "unemployed-persons", "nbb",
     "NBB/DF_UNEMPLOYMENT/M.BE.AA.A0000.Z0000.999.BR00.000.0000.N.00.99.NHU._Z", "M",
     "Number", "NSA", 1.0,
     "NBB DF_UNEMPLOYMENT Belgium total all ages, persons (NHU), monthly NSA"),
    ("BE", "manufacturing-production", "nbb", "NBB/DF_INDPROD/M.2021.INDPROD.W.C.BE", "M",
     "Index (2021=100)", "WDA", 1.0,
     "NBB DF_INDPROD Industrial production index, Manufacturing (NACE C), WDA"),
    ("BE", "mining-production", "nbb", "NBB/DF_INDPROD/M.2021.INDPROD.W.B.BE", "M",
     "Index (2021=100)", "WDA", 1.0,
     "NBB DF_INDPROD Industrial production index, Mining and quarrying (NACE B), WDA"),
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
    print(f"\n{inserted} BE TE-conformity rows promoted (cycle 9); eurostat demoted.")
    print("Run `pipeline/.venv/Scripts/python -m pipeline.providers.national_eu` to ingest.")


if __name__ == "__main__":
    main()
