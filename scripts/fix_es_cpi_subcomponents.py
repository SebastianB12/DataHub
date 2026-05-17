"""Fix ES CPI sub-components: switch from Eurostat to INE direct (TE-source-conformity).

TE attributes "National Statistics Institute (INE)" for all CPI sub-components.
We currently use Eurostat ei_cphi_m. Switch to INE Tempus3 table 76125 (ECOICOP v2 groups,
base 2025).

Slugs:
  cpi-clothing            -> IPC290759
  cpi-education           -> IPC290791
  cpi-housing-utilities   -> IPC290763
  cpi-recreation-and-culture -> IPC290787
  cpi-transportation      -> IPC290775

(cpi-food already uses INE IPC290755.)
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import requests
from pipeline.db import supabase as sb, upsert_data_points
from datetime import date

BASE_URL = "https://servicios.ine.es/wstempus/js/EN"

CPI_MAP = {
    "cpi-clothing": "IPC290759",
    "cpi-education": "IPC290791",
    "cpi-housing-utilities": "IPC290763",
    "cpi-recreation-and-culture": "IPC290787",
    "cpi-transportation": "IPC290775",
}


def fetch_serie(cod: str, n_last: int = 400):
    url = f"{BASE_URL}/DATOS_SERIE/{cod}?nult={n_last}"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.json()


def to_rows(slug: str, cod: str) -> list[dict]:
    data = fetch_serie(cod)
    rows = []
    for obs in data.get("Data", []):
        val = obs.get("Valor")
        if val is None:
            continue
        year = obs.get("Anyo")
        periodo = obs.get("FK_Periodo")
        if not (1 <= periodo <= 12):
            continue
        # Month-end date
        from calendar import monthrange
        last_day = monthrange(year, periodo)[1]
        dt = date(year, periodo, last_day)
        rows.append({
            "indicator": slug,
            "country": "ES",
            "date": dt.isoformat(),
            "value": float(val),
            "source": "ine_es",
            "unit": "Index",
            "series_id": f"INE:{cod}",
            "adjustment": "",
        })
    return rows


def main():
    for slug, cod in CPI_MAP.items():
        print(f"\n=== {slug} -> {cod} ===")
        rows = to_rows(slug, cod)
        if not rows:
            print("  FAIL: no rows")
            continue
        last = rows[-1]
        print(f"  Latest: {last['date']} = {last['value']:.3f}")

        # Delete old Eurostat data
        sb.table("data_points").delete().eq("country", "ES").eq("indicator", slug).execute()
        print(f"  Deleted old data_points for ES/{slug}")

        # Upsert new INE data
        from pipeline.db import upsert_data_points
        n = upsert_data_points(rows)
        print(f"  Upserted {n} new rows")

        # Update indicator_sources
        sb.table("indicator_sources").update({
            "source": "ine_es",
            "series_id": f"INE:{cod}",
            "note": f"INE IPC base 2025 ECOICOP v2 group, table 76125",
        }).eq("country", "ES").eq("indicator", slug).eq("is_default", True).execute()
        print(f"  Updated indicator_sources")


if __name__ == "__main__":
    main()
