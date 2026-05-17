"""DE gap fixes — orchestration.

Tasks:
  1. wages: keep destatis source (no clean EUR-level table; skipped)
  2. core-cpi: switch eurostat -> destatis 61111-0006 CC13B1/CC13-63E
  3. energy-inflation: switch eurostat -> destatis 61111-0006 CC13B1/CC13-65D
  4. productivity: keep eurostat (Bundesbank BBDE1 SDMX discovery deferred)
  5. government-spending-to-gdp: switch curated -> eurostat gov_10a_main TE/GDP S13
"""
import sys
from pipeline.db import supabase as sb
from pipeline.providers.destatis import (
    _setup_pystatis, _fetch_table_direct, _parse_dataframe,
    DestatisProvider,
)
from pipeline.db import upsert_data_points, datapoints_to_rows


def update_indicator_sources():
    """Update indicator_sources rows to the new TE-conformant configuration."""
    # core-cpi -> destatis
    sb.table("indicator_sources").update({
        "source": "destatis",
        "series_id": "61111-0006:CC13-63E",
        "transform": "raw",
        "conversion": 1,
        "unit": "Index",
        "adjustment": "NSA",
        "freq_hint": "M",
        "extra_params": None,
        "note": "Destatis 61111-0006 (CC13B1=Sonderpositionen, CC13-63E='Gesamtindex ohne Nahrungsmittel und Energie'), 2020=100. TE-konform.",
    }).eq("country", "DE").eq("indicator", "core-cpi").eq("is_default", True).execute()
    print("  updated core-cpi -> destatis 61111-0006:CC13-63E")

    # energy-inflation -> destatis
    sb.table("indicator_sources").update({
        "source": "destatis",
        "series_id": "61111-0006:CC13-65D",
        "transform": "raw",
        "conversion": 1,
        "unit": "Index",
        "adjustment": "NSA",
        "freq_hint": "M",
        "extra_params": None,
        "note": "Destatis 61111-0006 (CC13B1=Sonderpositionen, CC13-65D='Energie (Haushaltsenergie und Kraftstoffe)'), 2020=100. TE-konform.",
    }).eq("country", "DE").eq("indicator", "energy-inflation").eq("is_default", True).execute()
    print("  updated energy-inflation -> destatis 61111-0006:CC13-65D")

    # government-spending-to-gdp -> eurostat gov_10a_main
    sb.table("indicator_sources").update({
        "source": "eurostat",
        "series_id": "gov_10a_main:TE:PC_GDP:S13",
        "transform": "raw",
        "conversion": 1,
        "unit": "% of GDP",
        "adjustment": "",
        "freq_hint": "A",
        "extra_params": {
            "params": {"unit": "PC_GDP", "sector": "S13", "na_item": "TE"},
            "dataset": "gov_10a_main",
        },
        "note": "Eurostat gov_10a_main TE/GDP, sector S13 (general government). TE-konform.",
    }).eq("country", "DE").eq("indicator", "government-spending-to-gdp").eq("is_default", True).execute()
    print("  updated government-spending-to-gdp -> eurostat gov_10a_main")


def delete_old_data_points():
    """Drop eurostat data for core-cpi & energy-inflation, curated for gov-spending-to-gdp."""
    for ind, src in [
        ("core-cpi", "eurostat"),
        ("energy-inflation", "eurostat"),
        ("government-spending-to-gdp", "curated"),
    ]:
        r = sb.table("data_points").delete().eq("country", "DE").eq("indicator", ind).eq("source", src).execute()
        print(f"  deleted {ind} ({src}): {len(r.data) if r.data else '?'} rows")


def fetch_destatis_new():
    """Fetch the two new destatis indicators only."""
    _setup_pystatis()
    new_tables = [
        {
            "name": "61111-0006", "indicator": "core-cpi",
            "classifyingvariable1": "CC13B1", "classifyingkey1": "*",
            "filter_unit": "2020=100", "filter_value_code": "PREIS1",
            "filter_attrs": {"3_variable_attribute_code": "CC13-63E"},
            "freq": "M", "unit": "Index", "adjustment": "NSA",
        },
        {
            "name": "61111-0006", "indicator": "energy-inflation",
            "classifyingvariable1": "CC13B1", "classifyingkey1": "*",
            "filter_unit": "2020=100", "filter_value_code": "PREIS1",
            "filter_attrs": {"3_variable_attribute_code": "CC13-65D"},
            "freq": "M", "unit": "Index", "adjustment": "NSA",
        },
    ]
    all_points = []
    for t in new_tables:
        df = _fetch_table_direct(t, startyear="1991")
        pts = _parse_dataframe(df, t)
        # Override series_id for cleaner DB record
        for p in pts:
            p.series_id = f"61111-0006:{t['filter_attrs']['3_variable_attribute_code']}"
        all_points.extend(pts)
        latest = sorted(pts, key=lambda p: p.date)[-1] if pts else None
        print(f"  {t['indicator']}: {len(pts)} points, latest = {latest.date} {latest.value} {latest.unit}" if latest else f"  {t['indicator']}: EMPTY")
        import time
        time.sleep(2)
    return all_points


def fetch_eurostat_gov_spending():
    """Fetch Eurostat gov_10a_main TE/PC_GDP/S13 for DE."""
    import requests
    from datetime import date
    from pipeline.base_provider import DataPoint
    from pipeline.transforms import normalize_date

    url = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/gov_10a_main"
    params = {"format": "JSON", "geo": "DE", "na_item": "TE", "unit": "PC_GDP", "sector": "S13"}
    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    j = r.json()
    time_idx = j["dimension"]["time"]["category"]["index"]
    vals = j["value"]
    points = []
    for t, idx in time_idx.items():
        v = vals.get(str(idx))
        if v is None:
            continue
        try:
            year = int(t)
        except ValueError:
            continue
        points.append(DataPoint(
            indicator="government-spending-to-gdp",
            country="DE",
            date=normalize_date(date(year, 1, 1), "A"),
            value=round(float(v), 2),
            source="eurostat",
            unit="% of GDP",
            series_id="gov_10a_main:TE:PC_GDP:S13",
            adjustment="",
        ))
    latest = sorted(points, key=lambda p: p.date)[-1] if points else None
    print(f"  government-spending-to-gdp: {len(points)} points, latest = {latest.date} {latest.value}" if latest else "  empty")
    return points


def main():
    print("=== Phase 1: update indicator_sources ===")
    update_indicator_sources()

    print("\n=== Phase 2: delete old data_points ===")
    delete_old_data_points()

    print("\n=== Phase 3: fetch new destatis ===")
    points = fetch_destatis_new()

    print("\n=== Phase 4: fetch eurostat gov-spending ===")
    points.extend(fetch_eurostat_gov_spending())

    print(f"\n=== Phase 5: upsert {len(points)} new points ===")
    rows = datapoints_to_rows(points)
    total = 0
    for i in range(0, len(rows), 500):
        batch = rows[i:i+500]
        total += upsert_data_points(batch)
    print(f"  upserted {total} rows")

    print("\n=== Phase 6: verify ===")
    for ind in ["core-cpi", "energy-inflation", "government-spending-to-gdp"]:
        r = sb.table("data_points").select("date,value,source,series_id,unit").eq("country","DE").eq("indicator",ind).order("date", desc=True).limit(2).execute()
        print(f"  {ind}:")
        for x in r.data:
            print(f"    {x}")


if __name__ == "__main__":
    main()
