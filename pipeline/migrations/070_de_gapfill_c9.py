"""DE gap-fill (Cycle 9, 2026-05-15) — close `suggested_source: destatis` mismatches.

Promotes Destatis as the default source for the six COICOP-2 CPI sub-indices
(table 61111-0004, base 2020=100, filtered on 3_variable_attribute_code = CC13-XX).

Smoke-tested 2026-05-15 (TE-conformity exact at 2026-04):
  cpi-food                       2026-04 = 138.6
  cpi-clothing                   2026-04 = 112.7
  cpi-housing-utilities          2026-04 = 119.1   matches TE 119.1 exact
  cpi-transportation             2026-04 = 137.4   matches TE 137.4 exact
  cpi-recreation-and-culture     2026-04 = 117.9   matches TE 117.9 exact
  cpi-education                  2026-04 = 124.4   matches TE 124.4 exact

Existing eurostat siblings are demoted (is_default=False).

DE gaps NOT covered by this migration (kept on eurostat for now — deferred):
  - core-cpi / energy-inflation / services-inflation:
      Destatis Sonderaggregate-Tabelle (61111-0007) returns no values via sync
      fetch; requires either a different special-aggregate table id or the
      DSD_ECOICOP_2018 SDMX endpoint. Deferred until special-aggregate table is
      validated.
  - gdp-real:
      Destatis 81000-0020 VGR018 returns the chain-linked-volume INDEX (2020=100),
      not the Bn EUR level shown on tradingeconomics.com. The Mrd EUR level
      requires table 81000-0028 with classifying filters; deferred.
  - food-inflation:
      YoY of cpi-food; the frontend computes YoY on the fly from cpi-food.
"""
import sys

sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb


SEEDS = [
    # (slug, series_id, freq, unit, adjustment, conversion, note)
    ("cpi-food", "61111-0004#CC13-01", "M",
     "Index (2020=100)", "NSA", 1.0,
     "Destatis 61111-0004 CC13-01 Food & non-alc beverages"),
    ("cpi-clothing", "61111-0004#CC13-03", "M",
     "Index (2020=100)", "NSA", 1.0,
     "Destatis 61111-0004 CC13-03 Clothing & footwear"),
    ("cpi-housing-utilities", "61111-0004#CC13-04", "M",
     "Index (2020=100)", "NSA", 1.0,
     "Destatis 61111-0004 CC13-04 Housing/water/electricity/gas"),
    ("cpi-transportation", "61111-0004#CC13-07", "M",
     "Index (2020=100)", "NSA", 1.0,
     "Destatis 61111-0004 CC13-07 Transport"),
    ("cpi-recreation-and-culture", "61111-0004#CC13-09", "M",
     "Index (2020=100)", "NSA", 1.0,
     "Destatis 61111-0004 CC13-09 Recreation & culture"),
    ("cpi-education", "61111-0004#CC13-10", "M",
     "Index (2020=100)", "NSA", 1.0,
     "Destatis 61111-0004 CC13-10 Education"),
]


def main():
    inserted = 0
    country = "DE"
    src = "destatis"
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
        print(f"  + {country}/{slug:<35} | {src} | {series_id}")
    print(f"\n{inserted} DE destatis rows promoted; eurostat siblings demoted.")


if __name__ == "__main__":
    main()
