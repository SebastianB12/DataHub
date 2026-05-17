"""
EiaProvider — US Energy Information Administration (api.eia.gov v2).
Reads series config from indicator_sources (source='eia'). Each row's
extra_params must include `endpoint` (e.g. 'petroleum/stoc/wstk' or
'natural-gas/stor/wkly') — the EIA v2 dataset path. `series_id` is the
EIA series code (e.g. 'WCESTUS1').

Requires EIA_API_KEY in .env (free signup at eia.gov/opendata/register.php).
"""

import os
from datetime import date, datetime

import requests
from dotenv import load_dotenv

from pipeline.base_provider import BaseProvider, DataPoint
from pipeline.transforms import normalize_date
from pipeline.db import datapoints_to_rows, upsert_data_points, log_pipeline_run, load_series_config

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

BASE_URL = "https://api.eia.gov/v2"


def _parse_eia_date(raw: str) -> date:
    # Weekly/daily strings are "YYYY-MM-DD"; monthly "YYYY-MM"; yearly "YYYY".
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unrecognised EIA period: {raw}")


class EiaProvider(BaseProvider):
    name = "eia"
    display_name = "EIA — Energy Information Administration"

    def __init__(self):
        self.api_key = os.environ.get("EIA_API_KEY")
        if not self.api_key:
            raise RuntimeError("EIA_API_KEY missing in .env — register at eia.gov/opendata/register.php")

    def _fetch_one(self, cfg: dict) -> list[DataPoint]:
        params_cfg = cfg.get("extra_params") or {}
        endpoint = params_cfg.get("endpoint")
        if not endpoint:
            raise ValueError(f"indicator_sources.extra_params.endpoint required for EIA {cfg['indicator']}")

        series_id = cfg["series_id"]
        frequency = params_cfg.get("frequency") or "weekly"
        url = f"{BASE_URL}/{endpoint}/data/"

        # The "series" facet key differs per dataset (some use 'series', some 'product', etc.).
        # For multi-facet queries (e.g. petroleum/pri/gnd needs duoarea+product+process),
        # extra_params may also include `facets` as a dict {facet_name: [values]}.
        facet_key = params_cfg.get("facet", "series")
        extra_facets = params_cfg.get("facets") or {}

        params = [
            ("api_key", self.api_key),
            ("frequency", frequency),
            ("data[0]", "value"),
            ("sort[0][column]", "period"),
            ("sort[0][direction]", "desc"),
            ("offset", 0),
            ("length", 5000),
        ]
        # Primary facet (series_id) — skip when extra_facets is fully self-contained
        if not params_cfg.get("facets_only"):
            params.append((f"facets[{facet_key}][]", series_id))
        for fname, fvals in extra_facets.items():
            if isinstance(fvals, str):
                fvals = [fvals]
            for v in fvals:
                params.append((f"facets[{fname}][]", v))
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        data = (payload.get("response") or {}).get("data") or []

        conversion = float(cfg.get("conversion") or 1)
        unit = cfg.get("unit") or ""
        adjustment = cfg.get("adjustment") or ""
        freq_hint = cfg.get("freq_hint") or "W"

        points: list[DataPoint] = []
        for row in data:
            raw_period = row.get("period")
            raw_value = row.get("value")
            if raw_period is None or raw_value is None:
                continue
            try:
                dt = _parse_eia_date(raw_period)
                v = float(raw_value) * conversion
            except (ValueError, TypeError):
                continue
            points.append(
                DataPoint(
                    indicator=cfg["indicator"],
                    country=cfg["country"],
                    date=normalize_date(dt, freq_hint),
                    value=round(v, 2),
                    source="eia",
                    unit=unit,
                    series_id=series_id,
                    adjustment=adjustment,
                )
            )
        return points

    def fetch(self) -> list[DataPoint]:
        configs = load_series_config("eia")
        all_points: list[DataPoint] = []
        for cfg in configs:
            try:
                points = self._fetch_one(cfg)
                all_points.extend(points)
                print(f"  OK {cfg['indicator']} ({cfg['country']}, {cfg['series_id']}): {len(points)} points")
            except Exception as e:
                print(f"  FAIL {cfg['indicator']} ({cfg['country']}, {cfg['series_id']}): {e}")
        return all_points


def run():
    provider = EiaProvider()
    print(f"Fetching data from {provider.display_name}...")
    try:
        points = provider.fetch()
        print(f"\nTotal: {len(points)} data points")
        if points:
            rows = datapoints_to_rows(points)
            total = 0
            for i in range(0, len(rows), 500):
                count = upsert_data_points(rows[i : i + 500])
                total += count
                print(f"  Upserted batch {i // 500 + 1}: {count} rows")
            log_pipeline_run("eia", "success", total)
            print(f"Done. {total} rows upserted.")
        else:
            log_pipeline_run("eia", "success", 0)
    except Exception as e:
        log_pipeline_run("eia", "failed", error_message=str(e))
        print(f"\nFailed: {e}")
        raise


if __name__ == "__main__":
    run()
