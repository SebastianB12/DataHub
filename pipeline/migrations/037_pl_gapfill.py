"""Promote GUS Poland direct as default for remaining TE-conform PL slugs.

Closes the PL eurostat → gus_pl gaps identified in docs/_te_inventory/PL.yaml
(verified: true + suggested_source: gus_pl).

Seeds gus_pl rows where missing, promotes to is_default=true, and demotes
any eurostat/worldbank/dbnomics fallback default for the same (country, indicator).
Also reaffirms PL/retail-sales (already gus_pl=default).

Run: pipeline/.venv/Scripts/python.exe -m pipeline.migrations.037_pl_gapfill
"""
import sys
import time
sys.stdout.reconfigure(encoding="utf-8")

from pipeline.db import supabase as sb

# (slug, series_id, freq, unit, adjustment, conversion, note)
SEEDS = [
    ("inflation-cpi", "GUS:var=305/COICOP=Total",
     "M", "Index (previous year=100)", "NSA", 1.0,
     "GUS DBW var=305 CPI YoY index, COICOP Total (sec 909 2014-2025 + sec 1698 2026+)"),
    ("business-confidence", "GUS:var=184/sec=751/type=117",
     "M", "Index (balance)", "NSA", 1.0,
     "GUS DBW var=184 sec=751 General business climate indicator, Main industrial groupings Total"),
    ("consumer-confidence", "GUS:var=469/sec=16/type=117",
     "M", "Index (balance)", "NSA", 1.0,
     "GUS DBW var=469 sec=16 Current Consumer Confidence Indicator BWUK"),
    ("capacity-utilization", "GUS:var=189/sec=751/type=95",
     "M", "%", "NSA", 1.0,
     "GUS DBW var=189 sec=751 Capacity utilization %, Main industrial groupings Total"),
    ("mining-production", "GUS:var=814/sec=807/type=7/B",
     "M", "Index (previous year=100, constant prices)", "NSA", 1.0,
     "GUS DBW var=814 sec=807 dim 711 pos B Mining and quarrying YoY"),
    ("manufacturing-production", "GUS:var=814/sec=807/type=7/C",
     "M", "Index (previous year=100, constant prices)", "NSA", 1.0,
     "GUS DBW var=814 sec=807 dim 711 pos C Manufacturing YoY"),
    ("changes-in-inventories", "GUS:var=1199/sec=16/type=105",
     "Q", "mln zl", "NSA", 1.0,
     "GUS DBW var=1199 sec=16 Changes in inventories, current prices, mln zl, quarterly"),
    ("gross-fixed-capital-formation", "GUS:var=1198/sec=1099/type=105",
     "Q", "mln zl", "NSA", 1.0,
     "GUS DBW var=1198 sec=1099 Gross fixed capital formation, Total economy S.1, current prices, quarterly"),
    ("consumer-spending", "GUS:var=1391/sec=950/type=105",
     "Q", "mln zl", "NSA", 1.0,
     "GUS DBW var=1391 sec=950 Final consumption expenditure of households S.14, current prices, quarterly"),
    ("government-spending", "GUS:var=1196/sec=1040/type=105",
     "Q", "mln zl", "NSA", 1.0,
     "GUS DBW var=1196 sec=1040 General government final consumption expenditure S.13, current prices, quarterly"),
    ("employed-persons", "GUS:var=1036/sec=1418/type=98",
     "Q", "thousand persons", "NSA", 1.0,
     "GUS DBW var=1036 sec=1418 Employed persons ESA 2010, Total status, Total NACE, quarterly"),
    ("cpi-food", "GUS:var=305/COICOP=01",
     "M", "Index (previous year=100)", "NSA", 1.0,
     "GUS DBW var=305 CPI COICOP 01 Food and non-alcoholic beverages, YoY index"),
    ("cpi-clothing", "GUS:var=305/COICOP=03",
     "M", "Index (previous year=100)", "NSA", 1.0,
     "GUS DBW var=305 CPI COICOP 03 Clothing and footwear, YoY index"),
    ("cpi-housing-utilities", "GUS:var=305/COICOP=04",
     "M", "Index (previous year=100)", "NSA", 1.0,
     "GUS DBW var=305 CPI COICOP 04 Housing, water, electricity, gas and other fuels, YoY index"),
    ("cpi-transportation", "GUS:var=305/COICOP=07",
     "M", "Index (previous year=100)", "NSA", 1.0,
     "GUS DBW var=305 CPI COICOP 07 Transport, YoY index"),
    ("cpi-recreation-and-culture", "GUS:var=305/COICOP=09",
     "M", "Index (previous year=100)", "NSA", 1.0,
     "GUS DBW var=305 CPI COICOP 09 Recreation and culture, YoY index"),
    ("cpi-education", "GUS:var=305/COICOP=10",
     "M", "Index (previous year=100)", "NSA", 1.0,
     "GUS DBW var=305 CPI COICOP 10 Education, YoY index"),
    ("food-inflation", "GUS:var=305/sec=1722/GR477507",
     "M", "Index (previous year=100)", "NSA", 1.0,
     "GUS DBW var=305 sec=1722 Food and non-alcoholic beverages special aggregate, YoY"),
    ("services-inflation", "GUS:var=305/sec=1722/GR477510",
     "M", "Index (previous year=100)", "NSA", 1.0,
     "GUS DBW var=305 sec=1722 Services special aggregate, YoY"),
    ("energy-inflation", "GUS:var=305/sec=1722/GR477512",
     "M", "Index (previous year=100)", "NSA", 1.0,
     "GUS DBW var=305 sec=1722 Fuels special aggregate (used as energy-inflation proxy)"),
    # Reaffirm: PL/retail-sales already gus_pl=default (kept by 019_gus_pl_stage2)
    ("retail-sales", "GUS:var=109/sec=849/type=7",
     "M", "Index (previous year=100, constant prices)", "NSA", 1.0,
     "GUS DBW var=109 sec=849 pres=7 Retail sales of goods YoY constant prices, PKD total"),
]


def _retry(fn, *args, **kwargs):
    for attempt in range(5):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            if attempt == 4:
                raise
            time.sleep(1 + attempt)
    return None


def main():
    inserted = 0
    promoted = 0
    demoted = 0
    for slug, series_id, freq, unit, adj, conv, note in SEEDS:
        # 1) Upsert gus_pl row, is_default=true.
        existing = _retry(
            lambda: sb.table("indicator_sources")
            .select("source, is_default, active")
            .eq("country", "PL").eq("indicator", slug).eq("source", "gus_pl")
            .execute().data
        )
        if not existing:
            _retry(lambda: sb.table("indicator_sources").insert({
                "country": "PL",
                "indicator": slug,
                "source": "gus_pl",
                "series_id": series_id,
                "transform": "raw",
                "conversion": conv,
                "unit": unit,
                "adjustment": adj,
                "freq_hint": freq,
                "is_default": True,
                "active": True,
                "note": note,
            }).execute())
            inserted += 1
            action = "+ inserted"
        else:
            _retry(lambda: sb.table("indicator_sources").update({
                "is_default": True, "active": True,
                "series_id": series_id, "unit": unit, "adjustment": adj,
                "freq_hint": freq, "note": note,
            }).eq("country", "PL").eq("indicator", slug).eq("source", "gus_pl").execute())
            promoted += 1
            action = "~ promoted"
        print(f"  {action} PL/{slug:32} | gus_pl | {series_id}")

        # 2) Demote eurostat/worldbank/dbnomics defaults for this PL slug.
        for fallback in ("eurostat", "worldbank", "dbnomics", "fred"):
            r = _retry(lambda: sb.table("indicator_sources").update({"is_default": False})
                       .eq("country", "PL").eq("indicator", slug)
                       .eq("source", fallback).eq("is_default", True).execute())
            n = len(r.data or [])
            demoted += n
        time.sleep(0.2)

    print(f"\nDone. inserted={inserted}, promoted={promoted}, fallbacks demoted={demoted}")


if __name__ == "__main__":
    main()
