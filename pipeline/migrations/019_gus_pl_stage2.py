"""Promote GUS Poland direct as default for PL ppi/industrial-production/
unemployment-rate-registered/retail-sales.

Seeds rows where they don't exist; promotes to is_default=true; demotes
the eurostat fallback for the same (country, indicator) tuple.

Run: pipeline/.venv/Scripts/python.exe -m pipeline.migrations.019_gus_pl_stage2
"""
import sys
import time
sys.stdout.reconfigure(encoding="utf-8")

from pipeline.db import supabase as sb

# (slug, series_id, freq, unit, adjustment, conversion, note)
SEEDS = [
    ("ppi",                          "GUS:var=1667/sec=1413/type=372",
     "M", "Index (2021=100)", "NSA", 1.0,
     "GUS DBW var=1667 sec=1413 type=372 (PPI total industry by KAU, base 2021=100)"),
    ("industrial-production",        "GUS:var=814/sec=2/type=7",
     "M", "Index (YoY const prices)", "NSA", 1.0,
     "GUS DBW var=814 sec=2 type=7 (Industrial production YoY const prices)"),
    ("unemployment-rate-registered", "GUS:var=875/sec=143/type=95",
     "M", "%", "NSA", 1.0,
     "GUS DBW var=875 sec=143 type=95 (Registered unemployment rate)"),
    ("retail-sales",                 "GUS:var=109/sec=849/type=7",
     "M", "Index (YoY const prices)", "NSA", 1.0,
     "GUS DBW var=109 sec=849 type=7 (Retail sales YoY const prices, PKD total)"),
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
        # 1) Upsert gus_pl row, mark is_default=true and active=true.
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
        time.sleep(0.3)

    print(f"\nDone. inserted={inserted}, promoted={promoted}, fallbacks demoted={demoted}")


if __name__ == "__main__":
    main()
