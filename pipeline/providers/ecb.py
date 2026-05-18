"""EcbProvider — European Central Bank Statistical Data Warehouse (V2 stateless).

Dispatcher ruft fetch_series(spec) pro data_series-Row.

API: https://data-api.ecb.europa.eu/service/data/{dataflow}/{key}?format=csvdata
Kein API-Key.

SeriesSpec-Konventionen:
  - spec.series_id: voller SDMX-Key inkl. Dataflow, z.B. "FM.B.U2.EUR.4F.KR.MRR_FR.LEV".
    Erstes Token (vor erstem '.') = dataflow; Rest = key.
    Alternativ: explizit "DATAFLOW/KEY" via Slash.
    Zusaetzlich: spec.extra_params kann {'dataflow': 'FM', 'key': '...'} ueberschreiben.
  - spec.extra_params optional: {'dataflow': str, 'key': str, 'params': {...}}
  - spec.freq_hint: 'D'|'W'|'M'|'Q'|'A'. Wenn leer, abgeleitet aus erstem Key-Token
    (B/D->D, W->W, M->M, Q->Q, A->A).
  - spec.conversion: Skalierungsfaktor (z.B. 1/1000 fuer Mio->Mrd EUR).
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime

import requests

from pipeline.base_provider import (
    BaseProvider, SeriesSpec, Observation,
    ProviderError, TransientProviderError,
)
from pipeline.transforms import normalize_date
from pipeline.dispatcher import register_provider

BASE_URL = "https://data-api.ecb.europa.eu/service/data"

# Erstes Key-Token -> Frequenz (ECB SDMX-Konvention)
_FREQ_FROM_KEY = {"B": "D", "D": "D", "W": "W", "M": "M", "Q": "Q", "A": "A", "S": "S"}


def _split_dataflow_key(series_id: str) -> tuple[str, str]:
    """Split 'FM.B.U2.EUR.4F.KR.MRR_FR.LEV' or 'FM/B.U2....' into (dataflow, key)."""
    sid = series_id.strip()
    if "/" in sid:
        df, key = sid.split("/", 1)
        return df, key
    if "." in sid:
        df, _, key = sid.partition(".")
        return df, key
    raise ProviderError(f"ecb: cannot parse series_id '{series_id}' (need DATAFLOW.KEY or DATAFLOW/KEY)")


def _parse_period(period_str: str) -> date | None:
    """Parse ECB time period to date.

    Formats: '2024-03-15' (daily/business), '2026-W15' (weekly),
             '2024-03' (monthly), '2024-Q1' (quarterly), '2024' (annual),
             '2024-S1' (semi-annual).
    """
    s = (period_str or "").strip()
    if not s:
        return None
    try:
        if "-W" in s:
            return datetime.strptime(s + "-5", "%G-W%V-%u").date()
        if "-Q" in s:
            year, q = s.split("-Q")
            month = {"1": 1, "2": 4, "3": 7, "4": 10}[q]
            return date(int(year), month, 1)
        if "-S" in s:
            year, sem = s.split("-S")
            month = {"1": 1, "2": 7}[sem]
            return date(int(year), month, 1)
        if len(s) == 10:  # YYYY-MM-DD
            return date.fromisoformat(s)
        if len(s) == 7:   # YYYY-MM
            year, month = s.split("-")
            return date(int(year), int(month), 1)
        if len(s) == 4:   # YYYY
            return date(int(s), 1, 1)
    except (ValueError, KeyError):
        pass
    return None


def _fetch_csv(dataflow: str, key: str, params: dict | None = None) -> list[tuple[date, float]]:
    """GET ECB CSV-data. Returns (date, value) pairs."""
    url = f"{BASE_URL}/{dataflow}/{key}"
    query = {"format": "csvdata"}
    if params:
        query.update(params)
    try:
        resp = requests.get(url, params=query, timeout=60)
    except (requests.ConnectionError, requests.Timeout) as e:
        raise TransientProviderError(f"ecb network: {e}") from e
    if resp.status_code >= 500:
        raise TransientProviderError(f"ecb HTTP {resp.status_code}")
    if resp.status_code == 404:
        raise ProviderError(f"ecb 404: {dataflow}/{key}")
    if resp.status_code != 200:
        raise ProviderError(f"ecb HTTP {resp.status_code}: {resp.text[:200]}")

    reader = csv.DictReader(io.StringIO(resp.text))
    results: list[tuple[date, float]] = []
    for row in reader:
        period = _parse_period(row.get("TIME_PERIOD", ""))
        value_str = row.get("OBS_VALUE", "")
        if period is None or value_str in ("", None):
            continue
        try:
            results.append((period, float(value_str)))
        except (ValueError, TypeError):
            continue
    return results


class EcbProvider(BaseProvider):
    name = "ecb"
    display_name = "European Central Bank"

    def fetch_series(self, spec: SeriesSpec) -> list[Observation]:
        ep = spec.extra_params or {}

        # Dataflow + Key auflösen. Akzeptiere historische Aliases
        # ('dataset' / 'series_key' aus älteren Migrations).
        dataflow = ep.get("dataflow") or ep.get("dataset") or ep.get("flowRef") or ep.get("flow")
        key      = ep.get("key")      or ep.get("series_key") or ep.get("series_code") or ep.get("series")
        if not (dataflow and key):
            if not spec.series_id:
                raise ProviderError("ecb: series_id (DATAFLOW.KEY) required")
            df_parsed, key_parsed = _split_dataflow_key(spec.series_id)
            dataflow = dataflow or df_parsed
            key = key or key_parsed

        params = ep.get("params") or None

        raw = _fetch_csv(dataflow, key, params=params)

        # Frequenz: spec.freq_hint > erstes Key-Token
        freq = spec.freq_hint or _FREQ_FROM_KEY.get(key[:1], "M")
        conv = spec.conversion or 1.0

        out: list[Observation] = []
        for dt, value in raw:
            try:
                v = round(float(value) * conv, 6)
            except (ValueError, TypeError):
                continue
            out.append(Observation(date=normalize_date(dt, freq), value=v))
        return out


try:
    register_provider(EcbProvider())
except ProviderError as e:
    print(f"[warn] EcbProvider not registered: {e}")
