"""Promote CYSTAT direct as default source for stage-2 CY indicators.

Migration 015 / earlier already seeded CY for inflation-cpi via CYSTAT PxWeb
(table 0410055E continuous timeseries, base 1986=100).

This migration extends to TE-aligned series currently served by eurostat:
  CPI sub-components: cpi-clothing, cpi-education, cpi-food, cpi-housing-utilities,
                      cpi-recreation-and-culture, cpi-transportation
  Industry:           industrial-production, ppi
  Trade:              imports, exports, trade-balance
  Quarterly NA:       consumer-spending, government-spending,
                      gross-fixed-capital-formation, changes-in-inventories, gdp-real
  Labour:             unemployment-rate, employed-persons

All tables sit under CYSTAT PxWeb (https://cystatdb.cystat.gov.cy/api/v1/en/);
fetcher passes Cloudflare via cloudscraper. See pipeline/providers/national_eu.py
section "Cyprus — CYSTAT PxWeb" for tables/queries.

TE-conformity smoke (verified 2026-05-15 — current scrapes match TE inventory
within revision lag):
  cpi-clothing                 2026M04 = 98.76   (TE 98.76)
  cpi-education                2026M04 = 102.58
  cpi-food                     2026M04 = 104.62  (TE 104.62)
  cpi-housing-utilities        2026M04 = 101.64  (TE 101.64)
  cpi-recreation-and-culture   2026M04 = 102.74  (TE 102.74)
  cpi-transportation           2026M04 = 108.87  (TE 108.87)
  industrial-production        2026M02 = 108.4
  ppi                          2026M03 = 121.0   (TE 121.0 for Feb/26)
  imports                      2026M03 = 1,210.7  mln EUR
  exports                      2026M03 = 506.9    mln EUR
  trade-balance                2026M03 = -703.85  mln EUR
  consumer-spending            2025Q4 = 4,571.0  mln EUR (real SA — TE 4,559.4)
  government-spending          2025Q4 = 1,298.3  mln EUR (real SA — TE 1,325.7)
  gross-fixed-capital-formation 2025Q4 = 1,570.3  mln EUR (real SA — TE 1,566.9)
  changes-in-inventories       2025Q4 = -603.7   mln EUR (current NSA)
  gdp-real                     2025Q4 = 7,795.3  mln EUR (real SA, B1GQ)
  unemployment-rate            2025Q4 = 4.0%      (LFS 15+)
  employed-persons             2025Q4 = 509.77 thousand (LFS 15+)

Not seeded (kept on eurostat or other):
  retail-sales  — TE attributes to Ministry of Finance, no clean monthly CYSTAT
                  PxWeb table; deferred (gap entry suggested for te_coverage_gaps).
  food-inflation — needs YoY derivation on cpi-food; the parent slug now lives
                   on cystat_cy and Frontend computes YoY on the fly.
  changes-in-inventories (real SA)
                 — table 0620020E exposes Measure=1 (Real terms) for P52 as None;
                   we publish Current prices NSA instead.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb


SEEDS = [
    # (slug, series_id, freq, unit, adjustment, conversion, note)
    ("cpi-clothing", "CYSTAT/0410070E.px/CP03", "M",
     "Index (2025=100)", "NSA", 1.0,
     "CYSTAT 0410070E CPI by main categories CP03 Clothing & footwear, base 2025=100"),
    ("cpi-education", "CYSTAT/0410070E.px/CP10", "M",
     "Index (2025=100)", "NSA", 1.0,
     "CYSTAT 0410070E CPI by main categories CP10 Education services, base 2025=100"),
    ("cpi-food", "CYSTAT/0410070E.px/CP01", "M",
     "Index (2025=100)", "NSA", 1.0,
     "CYSTAT 0410070E CPI by main categories CP01 Food & non-alc bev, base 2025=100"),
    ("cpi-housing-utilities", "CYSTAT/0410070E.px/CP04", "M",
     "Index (2025=100)", "NSA", 1.0,
     "CYSTAT 0410070E CPI by main categories CP04 Housing/water/electricity/gas, base 2025=100"),
    ("cpi-recreation-and-culture", "CYSTAT/0410070E.px/CP09", "M",
     "Index (2025=100)", "NSA", 1.0,
     "CYSTAT 0410070E CPI by main categories CP09 Recreation, sport & culture, base 2025=100"),
    ("cpi-transportation", "CYSTAT/0410070E.px/CP07", "M",
     "Index (2025=100)", "NSA", 1.0,
     "CYSTAT 0410070E CPI by main categories CP07 Transport, base 2025=100"),

    ("industrial-production", "CYSTAT/0210045E.px/INDEX", "M",
     "Index (2021=100)", "NSA", 1.0,
     "CYSTAT 0210045E IP timeseries total industry, base 2021=100, monthly"),
    ("ppi", "CYSTAT/0230015E.px/INDEX", "M",
     "Index (2021=100)", "NSA", 1.0,
     "CYSTAT 0230015E PPI timeseries total industry, base 2021=100, monthly"),

    ("imports", "CYSTAT/1000010E.px/Imports", "M",
     "Million EUR", "NSA", 0.001,
     "CYSTAT 1000010E foreign trade summary monthly imports c.i.f. total goods/partners (thousand EUR -> mln)"),
    ("exports", "CYSTAT/1000010E.px/Exports", "M",
     "Million EUR", "NSA", 0.001,
     "CYSTAT 1000010E foreign trade summary monthly exports f.o.b. total goods/partners (thousand EUR -> mln)"),
    ("trade-balance", "CYSTAT/1000010E.px/Balance", "M",
     "Million EUR", "NSA", 0.001,
     "CYSTAT 1000010E foreign trade summary monthly net trade balance (thousand EUR -> mln)"),

    ("consumer-spending", "CYSTAT/0620020E.px/P31-NPISH", "Q",
     "Million EUR (chain-linked, SA)", "SA", 1.0,
     "CYSTAT 0620020E P31 households+NPISH real terms working-day & seasonally adjusted"),
    ("government-spending", "CYSTAT/0620020E.px/P3-Govt", "Q",
     "Million EUR (chain-linked, SA)", "SA", 1.0,
     "CYSTAT 0620020E P3 general government real terms working-day & seasonally adjusted"),
    ("gross-fixed-capital-formation", "CYSTAT/0620020E.px/P51G", "Q",
     "Million EUR (chain-linked, SA)", "SA", 1.0,
     "CYSTAT 0620020E P51G gross fixed capital formation real terms WDA & SA"),
    ("changes-in-inventories", "CYSTAT/0620020E.px/P52", "Q",
     "Million EUR (current, NSA)", "NSA", 1.0,
     "CYSTAT 0620020E P52 changes in inventories current prices NSA"),
    ("gdp-real", "CYSTAT/0620020E.px/B1GQ-SA", "Q",
     "Million EUR (chain-linked, SA)", "SA", 1.0,
     "CYSTAT 0620020E B1GQ GDP real terms working-day & seasonally adjusted"),

    ("unemployment", "CYSTAT/0110010E.px/LFS-Unemp15+", "Q",
     "%", "NSA", 1.0,
     "CYSTAT 0110010E LFS unemployment rate 15+ total (Eurostat-comparable concept; canonical slug=unemployment)"),
    ("employed-persons", "CYSTAT/0110010E.px/LFS-Emp15+", "Q",
     "Thousand persons", "NSA", 0.001,
     "CYSTAT 0110010E LFS employed persons 15+ total (Number converted to thousands)"),
]


def main():
    inserted = 0
    country = "CY"
    src = "cystat_cy"
    for slug, series_id, freq, unit, adj, conv, note in SEEDS:
        # Idempotent: delete existing cystat_cy row for this (slug, country)
        sb.table("indicator_sources").delete().eq(
            "indicator", slug
        ).eq("country", country).eq("source", src).execute()
        # Demote any existing default row from other sources for this (slug, country)
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
        print(f"  + {country}/{slug:<32} | {src} | {series_id}")
    print(f"\n{inserted} CY CYSTAT stage-2 rows promoted; eurostat siblings demoted.")


if __name__ == "__main__":
    main()
