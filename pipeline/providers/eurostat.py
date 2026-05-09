"""
EurostatProvider — Eurostat Statistics API
Reads its series config from the DB table `indicator_sources` (source='eurostat').

Each indicator_sources row:
  - indicator + country: target slug + ISO-2
  - series_id: synthetic key 'dataset:filter1=v1,filter2=v2' (only used to differentiate
    rows; the provider parses extra_params for the actual fetch)
  - extra_params: JSON {dataset: str, params: dict[str,str], geo_override?: list[str]}
  - freq_hint: 'M' / 'Q' / 'A'
  - conversion: float multiplier on raw values

The provider groups rows by (dataset, params) and fetches each combination once
with the union of countries (Eurostat returns multi-country in one query). Geo
codes are mapped via GEO_MAP.

API: https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/{dataset}
No API key required.
"""

import json
from datetime import date

import requests

from pipeline.base_provider import BaseProvider, DataPoint
from pipeline.transforms import normalize_date
from pipeline.db import upsert_data_points, log_pipeline_run, datapoints_to_rows, load_series_config

BASE_URL = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"

# Eurostat geo codes → our internal country codes.
GEO_MAP = {
    "EA20": "EA", "EA19": "EA", "EA21": "EA", "EA": "EA",
    "DE": "DE",
    "UK": "GB",   # Eurostat uses UK, we use GB
    "EL": "GR",   # Eurostat uses EL, we use GR (ISO-3166)
    "FR": "FR", "IT": "IT", "ES": "ES", "NL": "NL", "BE": "BE",
    "AT": "AT", "FI": "FI", "GR": "GR", "PT": "PT", "IE": "IE",
    "PL": "PL", "SE": "SE", "DK": "DK", "CZ": "CZ", "HU": "HU",
    "RO": "RO", "SK": "SK", "BG": "BG", "HR": "HR", "SI": "SI",
    "LV": "LV", "LT": "LT", "EE": "EE", "LU": "LU", "MT": "MT", "CY": "CY",
}

# Reverse map: our code → preferred Eurostat geo codes (try in order)
COUNTRY_TO_GEO: dict[str, list[str]] = {
    "EA": ["EA20", "EA19", "EA21", "EA"],
    "DE": ["DE"], "GB": ["UK"], "GR": ["EL"],
    "FR": ["FR"], "IT": ["IT"], "ES": ["ES"],
}


def _parse_period(period_str: str, freq: str) -> date | None:
    try:
        s = period_str.strip()
        if freq == "Q" or "Q" in s:
            clean = s.replace("-Q", "Q")
            if "Q" in clean:
                year, quarter = clean.split("Q")
                month = {1: 1, 2: 4, 3: 7, 4: 10}[int(quarter)]
                return date(int(year), month, 1)
        if freq == "M" or (len(s) == 7 and "-" in s):
            clean = s.replace("M", "-")
            year, month = clean.split("-")
            return date(int(year), int(month), 1)
        if freq == "A" or len(s) == 4:
            return date(int(s), 1, 1)
    except (ValueError, KeyError, IndexError):
        pass
    return None


def _fetch_dataset(dataset: str, params: dict, geo_codes: list[str]) -> dict:
    url = f"{BASE_URL}/{dataset}"
    query = {**params, "geo": geo_codes, "format": "JSON", "lang": "en"}
    resp = requests.get(url, params=query, timeout=60)
    resp.raise_for_status()
    return resp.json()


def _extract_points_for_country(
    data: dict,
    indicator: str,
    target_country: str,
    target_geos: list[str],
    conversion: float,
    freq: str,
    unit: str,
    adjustment: str,
    series_id: str,
) -> list[DataPoint]:
    points: list[DataPoint] = []
    if "value" not in data or not data["value"]:
        return points

    dim_ids = data.get("id", [])
    dim_sizes = data.get("size", [])

    dim_categories: list[dict[int, str]] = []
    for dim_id in dim_ids:
        cat_info = data.get("dimension", {}).get(dim_id, {}).get("category", {})
        index_map = cat_info.get("index", {})
        inv = {v: k for k, v in index_map.items()}
        dim_categories.append(inv)

    geo_pos = dim_ids.index("geo") if "geo" in dim_ids else None
    time_pos = dim_ids.index("time") if "time" in dim_ids else (
        dim_ids.index("TIME_PERIOD") if "TIME_PERIOD" in dim_ids else None
    )
    if geo_pos is None or time_pos is None:
        return points

    target_geo_set = set(target_geos)

    for flat_idx_str, value in data["value"].items():
        flat_idx = int(flat_idx_str)
        indices = []
        remainder = flat_idx
        for size in reversed(dim_sizes):
            indices.append(remainder % size)
            remainder //= size
        indices.reverse()

        geo_code = dim_categories[geo_pos].get(indices[geo_pos], "")
        if geo_code not in target_geo_set:
            continue
        time_code = dim_categories[time_pos].get(indices[time_pos], "")

        dt = _parse_period(time_code, freq)
        if not dt:
            continue
        try:
            converted = round(float(value) * conversion, 2)
        except (ValueError, TypeError):
            continue

        points.append(DataPoint(
            indicator=indicator,
            country=target_country,
            date=normalize_date(dt, freq),
            value=converted,
            source="eurostat",
            unit=unit,
            series_id=series_id,
            adjustment=adjustment,
        ))

    return points


class EurostatProvider(BaseProvider):
    name = "eurostat"
    display_name = "Eurostat"

    def fetch(self) -> list[DataPoint]:
        configs = load_series_config("eurostat")

        # Group rows by (dataset, params_json) so we fetch each dataset once
        # with the union of all needed geos.
        groups: dict[tuple, list[dict]] = {}
        for cfg in configs:
            ep = cfg.get("extra_params") or {}
            dataset = ep.get("dataset")
            if not dataset:
                print(f"  SKIP {cfg['indicator']}/{cfg['country']}: extra_params.dataset missing")
                continue
            params = ep.get("params") or {}
            key = (dataset, json.dumps(params, sort_keys=True))
            groups.setdefault(key, []).append(cfg)

        all_points: list[DataPoint] = []
        for (dataset, params_json), rows in groups.items():
            params = json.loads(params_json)
            # Build union of preferred geo codes across rows in this group
            geos: list[str] = []
            seen_geo: set[str] = set()
            for cfg in rows:
                ep = cfg.get("extra_params") or {}
                if ep.get("geo_override"):
                    candidates = ep["geo_override"]
                else:
                    candidates = COUNTRY_TO_GEO.get(cfg["country"], [cfg["country"]])
                for g in candidates:
                    if g not in seen_geo:
                        seen_geo.add(g)
                        geos.append(g)

            try:
                data = _fetch_dataset(dataset, params, geos)
            except requests.HTTPError as e:
                print(f"  FAIL {dataset} ({list({c['indicator'] for c in rows})}): HTTP {e.response.status_code}")
                continue
            except Exception as e:
                print(f"  FAIL {dataset}: {e}")
                continue

            for cfg in rows:
                ep = cfg.get("extra_params") or {}
                target_geos = ep.get("geo_override") or COUNTRY_TO_GEO.get(cfg["country"], [cfg["country"]])
                pts = _extract_points_for_country(
                    data,
                    indicator=cfg["indicator"],
                    target_country=cfg["country"],
                    target_geos=target_geos,
                    conversion=float(cfg.get("conversion") or 1),
                    freq=cfg.get("freq_hint") or "M",
                    unit=cfg.get("unit") or "",
                    adjustment=cfg.get("adjustment") or "",
                    series_id=cfg.get("series_id") or dataset,
                )
                all_points.extend(pts)
                print(f"  OK {cfg['indicator']}/{cfg['country']} ({dataset}): {len(pts)} points")

        return all_points


def run():
    provider = EurostatProvider()
    print(f"Fetching data from {provider.display_name}...")
    try:
        points = provider.fetch()
        print(f"\nTotal: {len(points)} data points")
        rows = datapoints_to_rows(points)
        total = 0
        for i in range(0, len(rows), 500):
            count = upsert_data_points(rows[i : i + 500])
            total += count
            print(f"  Upserted batch {i // 500 + 1}: {count} rows")
        log_pipeline_run("eurostat", "success", total)
        print(f"\nDone. {total} rows upserted.")
    except Exception as e:
        log_pipeline_run("eurostat", "failed", error_message=str(e))
        print(f"\nFailed: {e}")
        raise


if __name__ == "__main__":
    run()
