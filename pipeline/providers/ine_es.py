"""INE-ES Provider — Instituto Nacional de Estadistica (Spain), V2 stateless.

API: https://servicios.ine.es/wstempus/js/EN/{endpoint}
- DATOS_SERIE/<COD>?nult=N — fetch one series, last N observations.

Dispatcher ruft fetch_series(spec) pro data_series-Row. Provider hat keine
indicator/country/source-Knowledge. spec.series_id ist der INE COD (z.B.
"IPC290751"). spec.freq_hint bestimmt die FK_Periodo-Interpretation.

Optional extra_params:
  - nult: int (default 400) — wie viele Observations holen
"""
from __future__ import annotations

from datetime import date

import requests

from pipeline.base_provider import (
    BaseProvider, SeriesSpec, Observation,
    ProviderError, TransientProviderError,
)
from pipeline.transforms import normalize_date
from pipeline.dispatcher import register_provider

BASE_URL = "https://servicios.ine.es/wstempus/js/EN"


def _parse_period_to_date(year: int, fk_periodo: int, freq: str) -> date | None:
    """INE FK_Periodo codes:
    - monthly: 1-12 (calendar months)
    - quarterly EPA: 19, 20, 21, 22 -> Q1, Q2, Q3, Q4 (INE-specific)
    - quarterly other: 1-4
    - annual: 1
    """
    try:
        if freq == "M":
            return date(int(year), int(fk_periodo), 1)
        if freq == "Q":
            quarter_map = {1: 1, 2: 4, 3: 7, 4: 10,
                           19: 1, 20: 4, 21: 7, 22: 10}
            month = quarter_map[int(fk_periodo)]
            return date(int(year), month, 1)
        if freq == "A":
            return date(int(year), 1, 1)
        if freq == "S":
            sem_map = {1: 1, 2: 7}
            return date(int(year), sem_map[int(fk_periodo)], 1)
    except (ValueError, KeyError, TypeError):
        pass
    return None


def _fetch_serie(cod: str, n_last: int) -> dict:
    url = f"{BASE_URL}/DATOS_SERIE/{cod}"
    params = {"nult": n_last}
    try:
        resp = requests.get(url, params=params, timeout=60)
    except (requests.ConnectionError, requests.Timeout) as e:
        raise TransientProviderError(f"network: {e}") from e
    if resp.status_code >= 500:
        raise TransientProviderError(f"HTTP {resp.status_code}")
    if resp.status_code == 404:
        raise ProviderError(f"INE series {cod} not found (404)")
    if resp.status_code != 200:
        raise ProviderError(f"HTTP {resp.status_code}: {resp.text[:200]}")
    try:
        return resp.json()
    except ValueError as e:
        raise ProviderError(f"INE JSON decode error: {e}") from e


class IneEsProvider(BaseProvider):
    name = "ine_es"
    display_name = "Instituto Nacional de Estadistica (Spain)"

    def fetch_series(self, spec: SeriesSpec) -> list[Observation]:
        cod = (spec.series_id or "").strip()
        if not cod:
            raise ProviderError("ine_es: empty series_id")
        # Accept "INE:<COD>" prefix from legacy V1 series_ids.
        if cod.upper().startswith("INE:"):
            cod = cod.split(":", 1)[1]

        ep = spec.extra_params or {}
        n_last = int(ep.get("nult", 400))

        data = _fetch_serie(cod, n_last=n_last)

        # Spec contract: list[Observation] or empty list. Dispatcher tolerates [].
        if not isinstance(data, dict):
            raise ProviderError(f"INE unexpected payload type: {type(data).__name__}")

        obs_list = data.get("Data") or []
        freq = spec.freq_hint or "M"
        conv = spec.conversion or 1.0

        out: list[Observation] = []
        for obs in obs_list:
            val = obs.get("Valor")
            if val is None:
                continue
            year = obs.get("Anyo")
            periodo = obs.get("FK_Periodo")
            if year is None or periodo is None:
                continue
            dt = _parse_period_to_date(year, periodo, freq)
            if not dt:
                continue
            try:
                v = round(float(val) * conv, 6)
            except (TypeError, ValueError):
                continue
            out.append(Observation(date=normalize_date(dt, freq), value=v))
        return out


try:
    register_provider(IneEsProvider())
except ProviderError as e:
    print(f"[warn] IneEsProvider not registered: {e}")
