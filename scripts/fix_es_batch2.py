"""ES Re-audit Batch 2 Fixes — TE-source-conformity fixes for INE-direct series.

Switches the following slugs from Eurostat to INE-direct (Tempus3 JSON API):

  labor-force-participation-rate -> EPA388079 (activity rate, 16+)
  employment-rate                -> EPA441060 (employment rate, both genders, total)
  disposable-personal-income     -> CTNFSI10778 (Households gross adjusted disposable income)

All three are quarterly, NSA, national.
"""
from __future__ import annotations
import sys
from pathlib import Path
from datetime import date

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import requests
from pipeline.db import supabase as sb, upsert_data_points

BASE_URL = "https://servicios.ine.es/wstempus/js/EN"

# Quarter period codes for INE: 19=Q1, 20=Q2, 21=Q3, 22=Q4 (some EPA tables)
# OR 1=Q1, 2=Q2, 3=Q3, 4=Q4 (CNTR/CTNFSI). Detected automatically.
QUARTER_END = {1: 3, 2: 6, 3: 9, 4: 12, 19: 3, 20: 6, 21: 9, 22: 12}

FIXES = [
    {
        "slug": "labor-force-participation-rate",
        "cod": "EPA388079",
        "unit": "%",
        "freq": "Q",
        "adjustment": "NSA",
        "note": "INE EPA Activity rate, both genders, 16+ (TE matches exactly)",
    },
    {
        "slug": "employment-rate",
        "cod": "EPA441060",
        "unit": "%",
        "freq": "Q",
        "adjustment": "NSA",
        "note": "INE EPA Employment rate, both genders, total 16+ (TE matches exactly)",
    },
    {
        "slug": "disposable-personal-income",
        "cod": "CTNFSI10778",
        "unit": "Million EUR",
        "freq": "Q",
        "adjustment": "NSA",
        "note": "INE CTNFSI Households gross adjusted disposable income, NSA current prices (table 67204)",
    },
]


def fetch_serie(cod, n_last=400):
    url = f"{BASE_URL}/DATOS_SERIE/{cod}?nult={n_last}"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.json()


def main():
    from calendar import monthrange
    for cfg in FIXES:
        print(f"\n=== {cfg['slug']} -> {cfg['cod']} ===")
        data = fetch_serie(cfg["cod"])
        rows = []
        for obs in data.get("Data", []):
            val = obs.get("Valor")
            if val is None:
                continue
            year = obs.get("Anyo")
            periodo = obs.get("FK_Periodo")
            month = QUARTER_END.get(periodo)
            if not month:
                continue
            last_day = monthrange(year, month)[1]
            dt = date(year, month, last_day)
            rows.append({
                "indicator": cfg["slug"],
                "country": "ES",
                "date": dt.isoformat(),
                "value": float(val),
                "source": "ine_es",
                "unit": cfg["unit"],
                "series_id": f"INE:{cfg['cod']}",
                "adjustment": cfg["adjustment"],
            })
        if not rows:
            print("  FAIL: no rows")
            continue
        last = rows[-1]
        print(f"  Latest: {last['date']} = {last['value']}")

        sb.table("data_points").delete().eq("country", "ES").eq("indicator", cfg["slug"]).execute()
        print(f"  Deleted old data_points")

        n = upsert_data_points(rows)
        print(f"  Upserted {n} new rows")

        sb.table("indicator_sources").update({
            "source": "ine_es",
            "series_id": f"INE:{cfg['cod']}",
            "note": cfg["note"],
        }).eq("country", "ES").eq("indicator", cfg["slug"]).eq("is_default", True).execute()
        print(f"  Updated indicator_sources -> ine_es")


if __name__ == "__main__":
    main()
