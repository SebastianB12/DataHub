"""HR gap-fill data ingestion: One-off script to fetch and upsert the new HR
series defined in HR_SERIES from national_eu.py. Mirrors the logic of the main
NationalEUProvider but adds:
  * Polite 5s delay between requests (DZS PxWeb 429-rate-limits).
  * Exponential back-off retry on HTTP 429 (up to 4 attempts).
  * Drops NaN/Inf values (HR retail-sales has occasional NaN observations).

Run after `046_hr_gapfill.py` to back-fill the data_points rows.
"""
import sys, time, math
sys.stdout.reconfigure(encoding="utf-8")

import requests
from pipeline.providers.national_eu import (
    HR_SERIES, _parse_jsonstat, _parse_jsonstat_roman_year_month,
    _parse_jsonstat_hr_year_quarter,
)
from pipeline.base_provider import DataPoint
from pipeline.transforms import normalize_date
from pipeline.db import upsert_data_points, log_pipeline_run, datapoints_to_rows


def fetch_hr_pxweb_retry(path: str, query: dict, freq: str, parse: str = "tid",
                          attempts: int = 4) -> list:
    import urllib.parse
    encoded_path = "/".join(urllib.parse.quote(p) for p in path.split("/"))
    url = f"https://web.dzs.hr/PXWeb/api/v1/en/{encoded_path}"
    body = {
        "query": [{"code": k, "selection": {"filter": "item", "values": [v]}}
                  for k, v in query.items()],
        "response": {"format": "json-stat2"},
    }
    backoff = 30
    for i in range(attempts):
        r = requests.post(url, json=body, timeout=60)
        if r.status_code == 429:
            if i == attempts - 1:
                r.raise_for_status()
            print(f"    429 — sleep {backoff}s then retry")
            time.sleep(backoff)
            backoff *= 2
            continue
        r.raise_for_status()
        js = r.json()
        if parse == "roman_ym":
            return _parse_jsonstat_roman_year_month(js)
        if parse == "hr_year_quarter":
            return _parse_jsonstat_hr_year_quarter(js)
        return _parse_jsonstat(js, freq)
    return []


def main():
    all_points: list[DataPoint] = []
    for cfg in HR_SERIES:
        try:
            pairs = fetch_hr_pxweb_retry(cfg["path"], cfg["query"], cfg["freq"],
                                          cfg.get("parse", "tid"))
            table_id = cfg["path"].rsplit("/", 1)[-1].replace(".px", "")
            kept = 0
            for dt, v in pairs:
                # Drop NaN / Inf values (HR retail-sales has them)
                if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                    continue
                all_points.append(DataPoint(
                    indicator=cfg["slug"], country="HR",
                    date=normalize_date(dt, cfg["freq"]),
                    value=round(v * cfg["conversion"], 4),
                    source="dzs_hr", unit=cfg["unit"],
                    series_id=f"DZS/{table_id}",
                    adjustment=cfg["adjustment"],
                ))
                kept += 1
            print(f"  OK {cfg['slug']}/HR ({table_id}): {kept} pts (of {len(pairs)} raw)")
        except Exception as e:
            print(f"  FAIL {cfg['slug']}/HR: {e}")
        time.sleep(5)  # Be polite — DZS rate-limits aggressively

    print(f"\nTotal: {len(all_points)} data points")
    rows = datapoints_to_rows(all_points)
    total = 0
    for i in range(0, len(rows), 500):
        count = upsert_data_points(rows[i:i+500])
        total += count
    print(f"Done. {total} rows upserted.")
    log_pipeline_run("dzs_hr", "success", total)


if __name__ == "__main__":
    main()
