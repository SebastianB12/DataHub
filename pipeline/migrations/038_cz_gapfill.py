"""Promote CZSO direct as default for remaining TE-conform CZ slugs.

Closes the CZ eurostat → czso gaps identified in docs/_te_inventory/CZ.yaml
(verified: true + suggested_source: czso).

Seeds czso rows where missing, promotes to is_default=true, and demotes
any eurostat/worldbank/dbnomics fallback default for the same (country, indicator).

Run: pipeline/.venv/Scripts/python.exe -m pipeline.migrations.038_cz_gapfill
"""
import sys
import time
sys.stdout.reconfigure(encoding="utf-8")

from pipeline.db import supabase as sb

# (slug, series_id, freq, unit, adjustment, conversion, note)
SEEDS = [
    ("business-confidence", "CZSO/KPR1/5865",
     "M", "Index (2005=100)", "SA", 1.0,
     "CZSO KPR1 Business confidence (Podnikatelé) bazický indeks"),
    ("consumer-confidence", "CZSO/KPR1/5866",
     "M", "Index (2005=100)", "SA", 1.0,
     "CZSO KPR1 Consumer confidence (Spotřebitelé) bazický indeks"),
    ("consumer-spending", "CZSO/NUC06Q/10000DOM",
     "Q", "mil Kc", "NSA", 1.0,
     "CZSO NUC06Q Final consumption of households, current prices, mil. Kc, quarterly"),
    ("gross-fixed-capital-formation", "CZSO/NUC06Q/9991BC",
     "Q", "mil Kc", "NSA", 1.0,
     "CZSO NUC06Q Gross fixed capital formation, current prices, mil. Kc, quarterly"),
    ("employed-persons", "CZSO/ZAM01/6285Z",
     "Q", "thousand persons", "NSA", 1.0,
     "CZSO ZAM01 Employed persons (Zaměstnaní), tis. osob, quarterly"),
    ("unemployed-persons", "CZSO/ZAM01/6284",
     "Q", "thousand persons", "NSA", 1.0,
     "CZSO ZAM01 Unemployed persons (Nezaměstnaní), tis. osob, quarterly"),
    ("retail-sales", "CZSO/OBC01/47",
     "M", "Index (previous year=100, constant prices)", "NSA", 1.0,
     "CZSO OBC01 Retail sales NACE 47, constant prices, YoY index, NSA"),
    ("mining-production", "CZSO/PRU01D/B",
     "M", "Index (2021=100)", "NSA", 1.0,
     "CZSO PRU01D Mining and quarrying (NACE B), base 2021=100"),
    ("manufacturing-production", "CZSO/PRU01D/C",
     "M", "Index (2021=100)", "NSA", 1.0,
     "CZSO PRU01D Manufacturing (NACE C), base 2021=100"),
    ("government-debt", "CZSO/WNUC05D/600602",
     "A", "mil Kc", "NSA", 1.0,
     "CZSO WNUC05D General government gross consolidated debt, mil. Kc, annual"),
    ("cpi-food", "CZSO/CEN0101E/COICOP=01",
     "M", "Index (2025=100)", "NSA", 1.0,
     "CZSO CEN0101E CPI COICOP-2018 01 Food and non-alcoholic beverages, base 2025=100"),
    ("cpi-clothing", "CZSO/CEN0101E/COICOP=03",
     "M", "Index (2025=100)", "NSA", 1.0,
     "CZSO CEN0101E CPI COICOP-2018 03 Clothing and footwear, base 2025=100"),
    ("cpi-housing-utilities", "CZSO/CEN0101E/COICOP=04",
     "M", "Index (2025=100)", "NSA", 1.0,
     "CZSO CEN0101E CPI COICOP-2018 04 Housing, water, electricity, gas and other fuels, base 2025=100"),
    ("cpi-transportation", "CZSO/CEN0101E/COICOP=07",
     "M", "Index (2025=100)", "NSA", 1.0,
     "CZSO CEN0101E CPI COICOP-2018 07 Transport, base 2025=100"),
    ("cpi-recreation-and-culture", "CZSO/CEN0101E/COICOP=09",
     "M", "Index (2025=100)", "NSA", 1.0,
     "CZSO CEN0101E CPI COICOP-2018 09 Recreation and culture, base 2025=100"),
    ("cpi-education", "CZSO/CEN0101E/COICOP=10",
     "M", "Index (2025=100)", "NSA", 1.0,
     "CZSO CEN0101E CPI COICOP-2018 10 Education, base 2025=100"),
    ("food-inflation", "CZSO/CEN0101E/COICOP=01:food-inflation",
     "M", "Index (2025=100)", "NSA", 1.0,
     "CZSO CEN0101E CPI COICOP-2018 01 Food index (level; frontend derives YoY)"),
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
        existing = _retry(
            lambda: sb.table("indicator_sources")
            .select("source, is_default, active")
            .eq("country", "CZ").eq("indicator", slug).eq("source", "czso")
            .execute().data
        )
        if not existing:
            _retry(lambda: sb.table("indicator_sources").insert({
                "country": "CZ",
                "indicator": slug,
                "source": "czso",
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
            }).eq("country", "CZ").eq("indicator", slug).eq("source", "czso").execute())
            promoted += 1
            action = "~ promoted"
        print(f"  {action} CZ/{slug:32} | czso | {series_id}")

        for fallback in ("eurostat", "worldbank", "dbnomics", "fred"):
            r = _retry(lambda: sb.table("indicator_sources").update({"is_default": False})
                       .eq("country", "CZ").eq("indicator", slug)
                       .eq("source", fallback).eq("is_default", True).execute())
            n = len(r.data or [])
            demoted += n
        time.sleep(0.2)

    print(f"\nDone. inserted={inserted}, promoted={promoted}, fallbacks demoted={demoted}")


if __name__ == "__main__":
    main()
