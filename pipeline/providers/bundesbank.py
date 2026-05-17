"""BundesbankProvider — Deutsche Bundesbank SDMX API (V2 stateless).

Dispatcher ruft fetch_series(spec) pro data_series-Row.

API: https://api.statistiken.bundesbank.de/rest/data/{flowRef}/{key}
Kein API-Key.

SeriesSpec-Konventionen:
  - spec.series_id: voller SDMX-Key inkl. Dataflow, z.B.
      "BBBS2.M.DB.Y.U.M30A.X.1.U2.2300.Z01.E"
      "BBDP1.M.DE.N.VPI.G.A._Z.I20.A"
    Erstes Token (vor erstem '.') = flowRef; Rest = key.
    Alternativ: explizit "FLOW/KEY" via Slash.
    Zusaetzlich: spec.extra_params kann {'flow': ..., 'key': ...} ueberschreiben.
  - spec.freq_hint: 'D'|'W'|'M'|'Q'|'A'|'S'. Wenn leer, abgeleitet aus erstem
    Key-Token nach flow (M/Q/A/D/W/S).
  - spec.conversion: Skalierungsfaktor (z.B. 1/1000 fuer Mio EUR -> Mrd EUR).
"""
from __future__ import annotations

import csv
import io
from datetime import date

import requests

from pipeline.base_provider import (
    BaseProvider, SeriesSpec, Observation,
    ProviderError, TransientProviderError,
)
from pipeline.transforms import normalize_date
from pipeline.dispatcher import register_provider

BASE_URL = "https://api.statistiken.bundesbank.de/rest/data"

# Erstes Key-Token nach flow -> Frequenz (Bundesbank-SDMX-Konvention)
_FREQ_FROM_KEY = {"B": "D", "D": "D", "W": "W", "M": "M", "Q": "Q", "A": "A", "S": "S"}


def _split_flow_key(series_id: str) -> tuple[str, str]:
    """Split 'BBBS2.M.DB.Y...' or 'BBBS2/M.DB.Y...' into (flow, key)."""
    sid = (series_id or "").strip()
    if not sid:
        raise ProviderError("bundesbank: empty series_id")
    if "/" in sid:
        flow, key = sid.split("/", 1)
        return flow, key
    if "." in sid:
        flow, _, key = sid.partition(".")
        return flow, key
    raise ProviderError(
        f"bundesbank: cannot parse series_id '{series_id}' (need FLOW.KEY or FLOW/KEY)"
    )


def _parse_period(period_str: str) -> date | None:
    """Parse Bundesbank period string. Supports YYYY-MM, YYYY-Qn, YYYY, YYYY-MM-DD, YYYY-Sn, YYYY-Wn."""
    s = (period_str or "").strip()
    if not s:
        return None
    try:
        if "-Q" in s:
            year, q = s.split("-Q")
            month = (int(q) - 1) * 3 + 1
            return date(int(year), month, 1)
        if "-S" in s:
            year, sem = s.split("-S")
            month = {"1": 1, "2": 7}[sem]
            return date(int(year), month, 1)
        if "-W" in s:
            from datetime import datetime
            return datetime.strptime(s + "-5", "%G-W%V-%u").date()
        if len(s) == 10:  # YYYY-MM-DD
            return date.fromisoformat(s)
        if len(s) == 7:   # YYYY-MM
            year, month = s.split("-")
            return date(int(year), int(month), 1)
        if len(s) == 4:   # YYYY
            return date(int(s), 1, 1)
    except (ValueError, KeyError, IndexError):
        pass
    return None


def _fetch_csv(flow: str, key: str) -> list[tuple[date, float]]:
    """GET Bundesbank SDMX as CSV. Returns (date, value) pairs."""
    url = f"{BASE_URL}/{flow}/{key}"
    headers = {"Accept": "application/vnd.sdmx.data+csv"}
    try:
        resp = requests.get(url, headers=headers, timeout=60)
    except (requests.ConnectionError, requests.Timeout) as e:
        raise TransientProviderError(f"bundesbank network: {e}") from e

    if resp.status_code >= 500:
        raise TransientProviderError(f"bundesbank HTTP {resp.status_code}")
    if resp.status_code == 404:
        raise ProviderError(f"bundesbank 404: {flow}/{key}")
    if resp.status_code >= 400:
        raise ProviderError(f"bundesbank HTTP {resp.status_code}: {resp.text[:200]}")

    text = resp.text.replace("﻿", "")
    reader = csv.DictReader(io.StringIO(text), delimiter=";")

    results: list[tuple[date, float]] = []
    for row in reader:
        period_str = row.get("TIME_PERIOD", "")
        value_str = row.get("OBS_VALUE", "")
        if not period_str or value_str in ("", None):
            continue
        dt = _parse_period(period_str)
        if dt is None:
            continue
        try:
            results.append((dt, float(value_str)))
        except (ValueError, TypeError):
            continue
    return results


class BundesbankProvider(BaseProvider):
    name = "bundesbank"
    display_name = "Deutsche Bundesbank"

    def fetch_series(self, spec: SeriesSpec) -> list[Observation]:
        ep = spec.extra_params or {}

        # Flow + Key auflösen
        flow = ep.get("flow") or ep.get("flowRef") or ep.get("dataflow")
        key = ep.get("key")
        if not (flow and key):
            flow_parsed, key_parsed = _split_flow_key(spec.series_id)
            flow = flow or flow_parsed
            key = key or key_parsed

        raw = _fetch_csv(flow, key)

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
    register_provider(BundesbankProvider())
except ProviderError as e:
    print(f"[warn] BundesbankProvider not registered: {e}")
