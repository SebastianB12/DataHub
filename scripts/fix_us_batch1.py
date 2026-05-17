"""Apply identified series_id fixes for US batch1 audit."""
from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from fredapi import Fred  # noqa: E402

from pipeline.db import supabase as sb  # noqa: E402

FRED = Fred(api_key=os.environ["FRED_API_KEY"])

# slug -> (new_series_id, new_unit, new_note, scale_factor_for_existing_unit)
FIXES = {
    "cpi-median": {
        "series_id": "MEDCPIM159SFRBCLE",
        "unit": "percent",
        "note": "Cleveland Fed Median CPI, 12-month percent change (matches TE headline)",
    },
    "cpi-trimmed-mean": {
        "series_id": "TRMMEANCPIM159SFRBCLE",
        "unit": "percent",
        "note": "Cleveland Fed 16% Trimmed-Mean CPI, 12-month percent change (matches TE headline)",
    },
    "core-producer-prices": {
        "series_id": "PPIFES",
        "unit": "index",
        "note": "PPI Final Demand Less Foods and Energy, Index Apr 2010=100 (matches TE)",
    },
    "exports": {
        "series_id": "BOPTEXP",
        "unit": "USD Million",
        "note": "Exports of Goods and Services, BoP basis (matches TE total exports)",
    },
    "current-account": {
        "series_id": "IEABC",
        "unit": "USD Million",
        "note": "Balance on Current Account, quarterly $M (matches TE -$190.7B Q4 2025)",
    },
    "car-production": {
        "series_id": "MVAAUTLTTS",
        "unit": "Million Units",
        "note": "Motor Vehicle Assemblies: Autos and Light Truck Assemblies, SAAR (matches TE)",
    },
}


def fetch_and_upsert(slug: str, series_id: str, unit: str):
    print(f"  fetching {series_id} ...")
    s = FRED.get_series(series_id).dropna()
    rows = []
    for ts, v in s.items():
        if pd.isna(v):
            continue
        rows.append(
            {
                "indicator": slug,
                "country": "US",
                "date": ts.date().isoformat(),
                "value": float(v),
                "source": "fred",
                "unit": unit,
                "series_id": series_id,
                "adjustment": "",
            }
        )
    print(f"  {len(rows)} rows")
    # delete then upsert
    sb.table("data_points").delete().eq("country", "US").eq("indicator", slug).execute()
    if rows:
        # chunk
        n = 0
        for i in range(0, len(rows), 1000):
            chunk = rows[i : i + 1000]
            r = sb.table("data_points").upsert(
                chunk, on_conflict="indicator,country,date,source,adjustment"
            ).execute()
            n += len(r.data)
        print(f"  upserted {n} rows")


def main():
    only = sys.argv[1:] if len(sys.argv) > 1 else list(FIXES.keys())
    for slug in only:
        if slug not in FIXES:
            print(f"SKIP {slug} (not in FIXES)")
            continue
        cfg = FIXES[slug]
        print(f"\n== {slug} -> {cfg['series_id']} ==")
        # update indicator_sources
        upd = {
            "series_id": cfg["series_id"],
            "unit": cfg["unit"],
            "note": cfg["note"],
        }
        r = (
            sb.table("indicator_sources")
            .update(upd)
            .eq("country", "US")
            .eq("indicator", slug)
            .eq("is_default", True)
            .execute()
        )
        print(f"  updated {len(r.data)} indicator_sources row(s)")
        # refresh data
        fetch_and_upsert(slug, cfg["series_id"], cfg["unit"])


if __name__ == "__main__":
    main()
