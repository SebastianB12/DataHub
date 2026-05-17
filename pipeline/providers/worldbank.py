"""WorldBankProvider — World Bank Open Data API (V2 stateless).

Dispatcher ruft fetch_series(spec) pro data_series-Row. Kein API-Key noetig.

API: https://api.worldbank.org/v2/country/{country}/indicator/{code}?format=json

country_hint ist ISO-2 (US, DE, ...) — die WB-API akzeptiert beide (ISO-2 und ISO-3),
aber fuer einige Aggregate (Euroraum etc.) brauchen wir Special-Mapping. Optional kann
extra_params.wb_country den Code ueberschreiben (z.B. EA -> EMU).
"""
from __future__ import annotations

import time
from datetime import date

import requests

from pipeline.base_provider import (
    BaseProvider, SeriesSpec, Observation,
    ProviderError, TransientProviderError,
)
from pipeline.transforms import normalize_date
from pipeline.dispatcher import register_provider

BASE_URL = "https://api.worldbank.org/v2/country"

# Mapping unserer internen Country-Codes -> World-Bank-Code, wenn abweichend.
# Die WB-API versteht ISO-2 nativ; nur Aggregate brauchen WB-spezifische Codes.
COUNTRY_TO_WB: dict[str, str] = {
    "EA": "EMU",     # Euro area
    "EU": "EUU",     # European Union
    "GB": "GB",
    "GR": "GR",
}


def _get_with_retry(url: str, params: dict, retries: int = 3, base_delay: float = 5.0):
    """GET with retry on connection/timeout/5xx. WB API is occasionally slow."""
    last_exc: BaseException | None = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, timeout=30)
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_exc = exc
            if attempt == retries - 1:
                raise TransientProviderError(f"network: {exc}") from exc
            time.sleep(base_delay * (attempt + 1))
            continue
        if resp.status_code in (502, 503, 504):
            last_exc = TransientProviderError(f"HTTP {resp.status_code}")
            if attempt == retries - 1:
                raise last_exc
            time.sleep(base_delay * (attempt + 1))
            continue
        if resp.status_code >= 500:
            raise TransientProviderError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        if resp.status_code == 404:
            raise ProviderError(f"HTTP 404: {resp.text[:200]}")
        if resp.status_code >= 400:
            raise ProviderError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        return resp
    raise last_exc  # unreachable


def _fetch_indicator(wb_country: str, wb_code: str) -> list[tuple[int, float]]:
    """Fetch a World Bank indicator over all pages. Returns (year, value) pairs."""
    results: list[tuple[int, float]] = []
    page = 1
    while True:
        resp = _get_with_retry(
            f"{BASE_URL}/{wb_country}/indicator/{wb_code}",
            params={"format": "json", "per_page": 500, "page": page},
        )
        try:
            data = resp.json()
        except ValueError as e:
            raise ProviderError(f"non-JSON response: {e}") from e
        # WB-API liefert bei Fehlern ein dict mit 'message'; Erfolg ist eine Liste.
        if isinstance(data, dict):
            raise ProviderError(f"WB error: {str(data)[:200]}")
        if not isinstance(data, list) or len(data) < 2 or not data[1]:
            break
        for item in data[1]:
            year_str = item.get("date", "")
            value = item.get("value")
            if value is not None and isinstance(year_str, str) and year_str.isdigit():
                try:
                    results.append((int(year_str), float(value)))
                except (TypeError, ValueError):
                    continue
        total_pages = data[0].get("pages", 1) if isinstance(data[0], dict) else 1
        if page >= total_pages:
            break
        page += 1
    return results


class WorldBankProvider(BaseProvider):
    name = "worldbank"
    display_name = "World Bank"

    def fetch_series(self, spec: SeriesSpec) -> list[Observation]:
        wb_code = spec.series_id
        if not wb_code:
            raise ProviderError("worldbank: series_id missing")

        # Country-Resolution: extra_params.wb_country > Mapping > country_hint as-is.
        ep = spec.extra_params or {}
        wb_country = ep.get("wb_country")
        if not wb_country and spec.country_hint:
            wb_country = COUNTRY_TO_WB.get(spec.country_hint, spec.country_hint)
        if not wb_country:
            raise ProviderError("worldbank: country missing (need country_hint or extra_params.wb_country)")

        raw = _fetch_indicator(wb_country, wb_code)

        freq = spec.freq_hint or "A"
        conv = spec.conversion or 1.0
        out: list[Observation] = []
        for year, value in raw:
            try:
                v = round(float(value) * conv, 6)
            except (TypeError, ValueError):
                continue
            out.append(Observation(
                date=normalize_date(date(year, 1, 1), freq),
                value=v,
            ))
        return out


try:
    register_provider(WorldBankProvider())
except ProviderError as e:
    print(f"[warn] WorldBankProvider not registered: {e}")
