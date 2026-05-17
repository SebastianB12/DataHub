"""EurostatProvider — Eurostat Statistics API (V2 stateless).

Dispatcher ruft fetch_series(spec) pro data_series-Row.
extra_params ist {dataset, params: {filter1:val1,...}, geo_override?: list[str]}.

API: https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/{dataset}
"""
from __future__ import annotations

import json
from datetime import date

import requests

from pipeline.base_provider import (
    BaseProvider, SeriesSpec, Observation,
    ProviderError, TransientProviderError,
)
from pipeline.transforms import normalize_date
from pipeline.dispatcher import register_provider

BASE_URL = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"

# Eurostat geo codes -> unsere internen Country-Codes. Wird benoetigt um den
# richtigen Geo aus dem multi-geo-Response zu picken wenn extra_params kein
# geo_override hat. Default-Reverse: unser code -> bevorzugte Eurostat-Codes.
GEO_MAP = {
    "EA20": "EA", "EA19": "EA", "EA21": "EA", "EA": "EA",
    "UK": "GB", "EL": "GR",
    "DE": "DE", "FR": "FR", "IT": "IT", "ES": "ES", "NL": "NL", "BE": "BE",
    "AT": "AT", "FI": "FI", "GR": "GR", "PT": "PT", "IE": "IE",
    "PL": "PL", "SE": "SE", "DK": "DK", "CZ": "CZ", "HU": "HU",
    "RO": "RO", "SK": "SK", "BG": "BG", "HR": "HR", "SI": "SI",
    "LV": "LV", "LT": "LT", "EE": "EE", "LU": "LU", "MT": "MT", "CY": "CY",
}
COUNTRY_TO_GEO: dict[str, list[str]] = {
    "EA": ["EA20", "EA19", "EA21", "EA"],
    "DE": ["DE"], "GB": ["UK"], "GR": ["EL"],
}


def _parse_period(period_str: str, freq: str) -> date | None:
    try:
        s = period_str.strip()
        if freq == "S" or "S" in s.replace("SA", "").replace("NSA", ""):
            clean = s.replace("-S", "S")
            if "S" in clean and clean.split("S")[0].isdigit():
                year, sem = clean.split("S")
                month = {1: 1, 2: 7}[int(sem)]
                return date(int(year), month, 1)
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
    try:
        resp = requests.get(url, params=query, timeout=60)
    except (requests.ConnectionError, requests.Timeout) as e:
        raise TransientProviderError(f"network: {e}")
    if resp.status_code >= 500:
        raise TransientProviderError(f"HTTP {resp.status_code}")
    if resp.status_code == 404:
        raise ProviderError(f"dataset {dataset} 404")
    if resp.status_code != 200:
        raise ProviderError(f"HTTP {resp.status_code}: {resp.text[:200]}")
    return resp.json()


def _extract_observations(
    data: dict,
    target_geos: list[str],
    freq: str,
    conversion: float,
) -> list[Observation]:
    out: list[Observation] = []
    if "value" not in data or not data["value"]:
        return out

    dim_ids = data.get("id", [])
    dim_sizes = data.get("size", [])

    dim_categories: list[dict[int, str]] = []
    for dim_id in dim_ids:
        cat_info = data.get("dimension", {}).get(dim_id, {}).get("category", {})
        index_map = cat_info.get("index", {})
        inv = {v: k for k, v in index_map.items()}
        dim_categories.append(inv)

    geo_pos = dim_ids.index("geo") if "geo" in dim_ids else None
    time_pos = (
        dim_ids.index("time") if "time" in dim_ids
        else (dim_ids.index("TIME_PERIOD") if "TIME_PERIOD" in dim_ids else None)
    )
    if geo_pos is None or time_pos is None:
        return out

    target_set = set(target_geos)
    for flat_idx_str, value in data["value"].items():
        flat_idx = int(flat_idx_str)
        indices = []
        remainder = flat_idx
        for size in reversed(dim_sizes):
            indices.append(remainder % size)
            remainder //= size
        indices.reverse()

        geo_code = dim_categories[geo_pos].get(indices[geo_pos], "")
        if geo_code not in target_set:
            continue
        time_code = dim_categories[time_pos].get(indices[time_pos], "")
        dt = _parse_period(time_code, freq)
        if not dt:
            continue
        try:
            converted = round(float(value) * conversion, 6)
        except (ValueError, TypeError):
            continue
        out.append(Observation(date=normalize_date(dt, freq), value=converted))
    return out


class EurostatProvider(BaseProvider):
    name = "eurostat"
    display_name = "Eurostat"

    def fetch_series(self, spec: SeriesSpec) -> list[Observation]:
        ep = spec.extra_params or {}
        dataset = ep.get("dataset")
        if not dataset:
            # Falls extra_params nicht da, versuche series_id als "dataset:filter1=v1"
            sid = spec.series_id or ""
            if ":" in sid:
                dataset = sid.split(":", 1)[0]
            else:
                dataset = sid
        if not dataset:
            raise ProviderError("eurostat: dataset missing in extra_params")

        params = ep.get("params") or {}
        # Geo-Priorität: extra_params.geo_override > country_hint mapping > Heuristik
        target_geos = ep.get("geo_override") or []
        if not target_geos and spec.country_hint:
            target_geos = COUNTRY_TO_GEO.get(spec.country_hint, [spec.country_hint])
        if not target_geos:
            # Fallback: series_id Form 'dataset:GEO:...'
            sid = spec.series_id or ""
            if ":" in sid:
                rest = sid.split(":", 1)[1]
                first = rest.split(":")[0].split(",")[0]
                if len(first) <= 4:
                    target_geos = [first]
        if not target_geos:
            raise ProviderError(
                f"eurostat: geo target unknown (need country_hint or extra_params.geo_override). spec={spec}"
            )

        data = _fetch_dataset(dataset, params, target_geos)
        return _extract_observations(
            data,
            target_geos=target_geos,
            freq=spec.freq_hint or "M",
            conversion=spec.conversion or 1.0,
        )


try:
    register_provider(EurostatProvider())
except ProviderError as e:
    print(f"[warn] EurostatProvider not registered: {e}")
