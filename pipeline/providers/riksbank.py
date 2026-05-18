"""RiksbankProvider — Sveriges Riksbank SweaWS REST API (V2 stateless).

TE-Primärquelle für SE Interest Rate. Sebastian-Direktive: Primary Source, kein
DBnomics-Proxy, kein Eurostat-Fallback.

API:
  Base:    https://api.riksbank.se/swea/v1
  Series:  GET /Observations/{seriesId}/{fromDate}/{toDate}  -> JSON array
  Latest:  GET /Observations/Latest/{seriesId}
  Auth:    keine (öffentlich)
  Format:  [{"date":"YYYY-MM-DD","value":<float>}, ...]

Series-IDs (relevante Auswahl, dokumentiert beim Riksbank):
  - SECBREPOEFF  -> Styrränta (Policy Rate, früher Reporänta), daily.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import requests

from pipeline.base_provider import (
    BaseProvider, SeriesSpec, Observation,
    ProviderError, TransientProviderError,
)
from pipeline.dispatcher import register_provider


BASE_URL = "https://api.riksbank.se/swea/v1"
USER_AGENT = "EconPulse/1.0 (macroeconomic data pipeline)"
HISTORY_FROM = date(1994, 1, 1)  # Riksbank-Historie geht bis ~1994 zurück


def _http_get_json(url: str, retries: int = 3) -> list | dict:
    last_exc: BaseException | None = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT,
                                              "Accept": "application/json"},
                                timeout=30)
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_exc = exc
            if attempt == retries - 1:
                raise TransientProviderError(f"riksbank network: {exc}") from exc
            continue
        if resp.status_code in (429, 502, 503, 504):
            last_exc = TransientProviderError(f"riksbank HTTP {resp.status_code}")
            if attempt == retries - 1:
                raise last_exc
            continue
        if resp.status_code == 404:
            raise ProviderError(f"riksbank HTTP 404: {url}")
        if resp.status_code >= 400:
            raise ProviderError(f"riksbank HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            return resp.json()
        except ValueError as exc:
            raise ProviderError(f"riksbank: invalid JSON: {exc}") from exc
    raise last_exc  # unreachable


class RiksbankProvider(BaseProvider):
    name = "riksbank"
    display_name = "Sveriges Riksbank"

    def fetch_series(self, spec: SeriesSpec) -> list[Observation]:
        series_id = (spec.series_id or "").strip()
        if not series_id:
            raise ProviderError("riksbank: series_id missing")

        ep = spec.extra_params or {}
        from_date = ep.get("from_date") or HISTORY_FROM.isoformat()
        to_date = ep.get("to_date") or (date.today() + timedelta(days=1)).isoformat()

        url = f"{BASE_URL}/Observations/{series_id}/{from_date}/{to_date}"
        data = _http_get_json(url)
        if not isinstance(data, list):
            raise ProviderError(
                f"riksbank: unexpected response shape for {series_id} "
                f"(expected list, got {type(data).__name__})"
            )

        conv = spec.conversion or 1.0
        out: list[Observation] = []
        for row in data:
            d_str = row.get("date") or row.get("Date")
            v = row.get("value", row.get("Value"))
            if d_str is None or v is None:
                continue
            try:
                d = datetime.fromisoformat(d_str[:10]).date()
                val = float(v) * conv
            except (ValueError, TypeError):
                continue
            out.append(Observation(date=d, value=round(val, 6)))
        return out


try:
    register_provider(RiksbankProvider())
except ProviderError as e:
    print(f"[warn] RiksbankProvider not registered: {e}")
