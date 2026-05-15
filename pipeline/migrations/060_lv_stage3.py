"""LV stage-3: promote csp_lv direct (CSP PxWeb data.stat.gov.lv) as default
source for 4 indicators currently on Eurostat per docs/_te_inventory/LV.yaml
verified=true / conform=false / suggested_source=csp_lv.

The earlier 042_lv_gapfill batch deferred these because:
  * Industrial / manufacturing / mining production: RUI020m (volume indices
    2021=100) returns HTTP 400 for section-level NACE codes (B / C / B_C_D_X_D353)
    no matter which ContentsCode variant is paired.
  * Changes-in-inventories: ISP050c P52 chain-linked (CLV2020) is all-null.

This stage uses workarounds that hit the same source authority:
  * RUI030m ("Volume indices of industrial production by economic activity
    from beginning of year, as % of corresponding period of previous year"):
    DOES accept the NACE section codes. The single ContentsCode RUI030m
    publishes a YTD-YoY percentage which is what TE shows on the industrial-
    production page. Same approach used for manufacturing-production (C) and
    mining-production (B).
  * ISP050c with PRICES=CP (current prices) NSA P52 returns a fully populated
    quarterly series in thousand EUR. We keep this as the headline value;
    CLV2020 P52 stays as the all-null gap.

Indicators promoted to csp_lv:
  - industrial-production   (CSP/RUI030m/B_C_D_X_D353)
  - manufacturing-production (CSP/RUI030m/C)
  - mining-production       (CSP/RUI030m/B)
  - changes-in-inventories  (CSP/ISP050c/P52_CP_NSA)

Smoke-tested 2026-05-15: all 4 series return data; IP latest 2026M03 = 109.2
(+9.2% YoY YTD; TE shows 9.5%), manuf = 101.0 (+1.0%), mining = 69.3 (-30.7%);
inventories 2025Q4 = 229,939 kEUR NSA.

Note: LV ppi stays on Eurostat fallback (RCI020m section-level still HTTP 400).

Run:
    python -m pipeline.migrations.060_lv_stage3
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb


SEEDS = [
    # (slug, src, series_id, freq, unit, adjustment, conversion, note)
    ("industrial-production", "csp_lv", "CSP/RUI030m/B_C_D_X_D353", "M",
     "% YoY (YTD)", "NSA", 1.0,
     "CSP Latvia RUI030m IP YoY%, total industry excl. D353, NSA"),
    ("manufacturing-production", "csp_lv", "CSP/RUI030m/C", "M",
     "% YoY (YTD)", "NSA", 1.0,
     "CSP Latvia RUI030m IP YoY%, manufacturing (NACE C), NSA"),
    ("mining-production", "csp_lv", "CSP/RUI030m/B", "M",
     "% YoY (YTD)", "NSA", 1.0,
     "CSP Latvia RUI030m IP YoY%, mining and quarrying (NACE B), NSA"),
    ("changes-in-inventories", "csp_lv", "CSP/ISP050c/P52_CP_NSA", "Q",
     "Thousand EUR (current prices)", "NSA", 1.0,
     "CSP Latvia ISP050c P52 changes in inventories, current prices, NSA, kEUR"),
]


def main():
    inserted = 0
    for slug, src, series_id, freq, unit, adj, conv, note in SEEDS:
        sb.table("indicator_sources").delete().eq(
            "indicator", slug
        ).eq("country", "LV").eq("source", src).execute()
        sb.table("indicator_sources").update({"is_default": False}).eq(
            "indicator", slug
        ).eq("country", "LV").execute()
        row = {
            "indicator": slug, "country": "LV", "source": src,
            "series_id": series_id, "is_default": True, "transform": "raw",
            "conversion": conv, "unit": unit, "adjustment": adj,
            "freq_hint": freq, "extra_params": None, "active": True, "note": note,
        }
        sb.table("indicator_sources").insert(row).execute()
        inserted += 1
        print(f"  + LV/{slug:<25} | {src:<8} | {series_id}")
    print(f"\n{inserted} CSP-direct rows promoted; eurostat counterparts demoted.")


if __name__ == "__main__":
    main()
