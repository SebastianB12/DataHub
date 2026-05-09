"""
WorldBankProvider — World Bank Open Data API
Reads series config from the DB table `indicator_sources` (source='worldbank').
Each row's extra_params.wb_country holds the World Bank country code
(which may differ from our internal code, e.g. EA -> EMU).

API: https://api.worldbank.org/v2/country/{iso2}/indicator/{code}?format=json
No API key required.
"""

import time
from datetime import date

import requests

from pipeline.base_provider import BaseProvider, DataPoint
from pipeline.transforms import normalize_date
from pipeline.db import upsert_data_points, log_pipeline_run, datapoints_to_rows, load_series_config

BASE_URL = "https://api.worldbank.org/v2/country"


def _get_with_retry(url: str, params: dict, retries: int = 3, base_delay: float = 5.0):
    """GET with retry on connection/read-timeout/5xx — World Bank's API is occasionally slow."""
    last_exc: BaseException | None = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, timeout=30)
            if resp.status_code in (502, 503, 504):
                last_exc = RuntimeError(f"HTTP {resp.status_code}")
                time.sleep(base_delay * (attempt + 1))
                continue
            resp.raise_for_status()
            return resp
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_exc = exc
            if attempt == retries - 1:
                raise
            time.sleep(base_delay * (attempt + 1))
    raise last_exc  # unreachable


def _fetch_indicator(wb_country: str, wb_code: str) -> list[tuple[int, float]]:
    """Fetch a World Bank indicator. Returns (year, value) pairs."""
    results: list[tuple[int, float]] = []
    page = 1
    while True:
        resp = _get_with_retry(
            f"{BASE_URL}/{wb_country}/indicator/{wb_code}",
            params={"format": "json", "per_page": 500, "page": page},
        )
        data = resp.json()
        if len(data) < 2 or not data[1]:
            break
        for item in data[1]:
            year_str = item.get("date", "")
            value = item.get("value")
            if value is not None and year_str.isdigit():
                results.append((int(year_str), float(value)))
        total_pages = data[0].get("pages", 1)
        if page >= total_pages:
            break
        page += 1
    return results


class WorldBankProvider(BaseProvider):
    name = "worldbank"
    display_name = "World Bank"

    def fetch(self) -> list[DataPoint]:
        configs = load_series_config("worldbank")
        all_points: list[DataPoint] = []

        for cfg in configs:
            indicator = cfg["indicator"]
            country = cfg["country"]
            wb_code = cfg["series_id"]
            conversion = float(cfg.get("conversion") or 1)
            unit = cfg.get("unit") or ""
            adjustment = cfg.get("adjustment") or ""

            wb_country = (cfg.get("extra_params") or {}).get("wb_country") or country

            try:
                raw = _fetch_indicator(wb_country, wb_code)
                points = [
                    DataPoint(
                        indicator=indicator,
                        country=country,
                        date=normalize_date(date(year, 1, 1), "A"),
                        value=round(value * conversion, 2),
                        source="worldbank",
                        unit=unit,
                        series_id=wb_code,
                        adjustment=adjustment,
                    )
                    for year, value in raw
                ]
                all_points.extend(points)
                years = [y for y, _ in raw]
                earliest = min(years) if years else "?"
                print(f"  OK {indicator} ({country}): {len(points)} points, from {earliest}")
            except Exception as e:
                print(f"  FAIL {indicator} ({country}, {wb_code}): {e}")

        return all_points


def run():
    provider = WorldBankProvider()
    print(f"Fetching data from {provider.display_name}...")
    try:
        points = provider.fetch()
        print(f"\nTotal: {len(points)} data points")
        rows = datapoints_to_rows(points)
        total = 0
        batch_size = 500
        for i in range(0, len(rows), batch_size):
            batch = rows[i : i + batch_size]
            count = upsert_data_points(batch)
            total += count
            print(f"  Upserted batch {i // batch_size + 1}: {count} rows")
        log_pipeline_run("worldbank", "success", total)
        print(f"\nDone. {total} rows upserted.")
    except Exception as e:
        log_pipeline_run("worldbank", "failed", error_message=str(e))
        print(f"\nFailed: {e}")
        raise


if __name__ == "__main__":
    run()
