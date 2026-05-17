"""KonjSeProvider — NIER / Konjunkturinstitutet (Sweden) V2 stateless.

API: PxWeb v1 unter https://statistik.konj.se/PxWeb/api/v1/en/KonjBar/{path}.
POST mit JSON-Body (json-stat2 response).

SeriesSpec-Konventionen:
  - spec.series_id: human-readable Label, z.B. "KONJ/indikatorer/Indikatorm/BTOT".
    Wird vom Provider NUR fuer Logging genutzt. Routing-relevant ist extra_params.
  - spec.extra_params:
      {
        "path": "indikatorer/Indikatorm.px",   # PxWeb-Pfad unter /KonjBar/, REQUIRED
        "query": {                              # PxWeb-Dimensionen, mind. Indikator
          "Indikator": "BTOT",
          "Grupp": "100"                        # optional, je nach Tabelle
        }
      }
  - spec.freq_hint: 'M' | 'Q' | 'A'. NIER liefert Periodencodes "2026M04",
    "2025K3" oder "2024". Parser deckt alle drei ab.
  - spec.conversion: Skalierungsfaktor.

Smoke (V1-Series):
  business-confidence: path="indikatorer/Indikatorm.px",   query={Indikator: BTOT}
  consumer-confidence: path="hushall/indikatorhus.px",      query={Indikator: bhuscon, Grupp: 100}
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


BASE = "https://statistik.konj.se/PxWeb/api/v1/en/KonjBar"
HDR = {
    "User-Agent": "EconPulse/1.0 (Sebastian/SVM-AG)",
    "Accept": "application/json",
    "Content-Type": "application/json",
}


def _parse_period(p: str, freq: str) -> date | None:
    s = (p or "").strip()
    if not s:
        return None
    try:
        if freq == "M" and "M" in s:
            yy, mm = s.split("M")
            return date(int(yy), int(mm), 1)
        if freq == "Q":
            for sep in ("K", "Q"):
                if sep in s:
                    yy, q = s.split(sep)
                    return date(int(yy), {"1": 1, "2": 4, "3": 7, "4": 10}[q], 1)
        if freq == "A" and len(s) == 4 and s.isdigit():
            return date(int(s), 1, 1)
        # generic fallbacks
        if "M" in s:
            yy, mm = s.split("M")
            return date(int(yy), int(mm), 1)
        if "K" in s:
            yy, q = s.split("K")
            return date(int(yy), {"1": 1, "2": 4, "3": 7, "4": 10}[q], 1)
        if "Q" in s:
            yy, q = s.split("Q")
            return date(int(yy), {"1": 1, "2": 4, "3": 7, "4": 10}[q], 1)
        if len(s) == 4 and s.isdigit():
            return date(int(s), 1, 1)
    except (ValueError, KeyError):
        return None
    return None


def _fetch_pxweb(path: str, query: dict) -> dict:
    url = f"{BASE}/{path}"
    body = {
        "query": [
            {"code": k, "selection": {"filter": "item", "values": [v]}}
            for k, v in query.items()
        ],
        "response": {"format": "json-stat2"},
    }
    try:
        resp = requests.post(url, headers=HDR, json=body, timeout=30)
    except (requests.ConnectionError, requests.Timeout) as e:
        raise TransientProviderError(f"konj_se network: {e}") from e
    if resp.status_code >= 500:
        raise TransientProviderError(f"konj_se HTTP {resp.status_code}")
    if resp.status_code == 404:
        raise ProviderError(f"konj_se 404: {path}")
    if resp.status_code >= 400:
        raise ProviderError(f"konj_se HTTP {resp.status_code}: {resp.text[:200]}")
    try:
        return resp.json()
    except ValueError as e:
        raise ProviderError(f"konj_se non-JSON: {e}") from e


def _extract_observations(js: dict, freq: str, conv: float) -> list[Observation]:
    values = js.get("value", [])
    dim = js.get("dimension", {})
    if not values or not dim:
        return []

    # Identify the time dimension (NIER uses "Period" but be lenient on case).
    tid = None
    for k in js.get("id", []):
        if k.lower() == "period" or k.lower() == "tid":
            tid = k
            break
    if tid is None:
        # Fall back: first dim whose category has multiple entries.
        for k in js.get("id", []):
            cat = dim.get(k, {}).get("category", {}).get("index")
            if isinstance(cat, (dict, list)) and len(cat) > 1:
                tid = k
                break
    if tid is None:
        return []

    cat_idx = dim[tid].get("category", {}).get("index")
    if isinstance(cat_idx, dict):
        pairs = sorted(cat_idx.items(), key=lambda x: x[1])
    elif isinstance(cat_idx, list):
        pairs = [(code, pos) for pos, code in enumerate(cat_idx)]
    else:
        return []

    out: list[Observation] = []
    for code, pos in pairs:
        if not isinstance(pos, int) or pos >= len(values):
            continue
        raw = values[pos]
        if raw is None:
            continue
        try:
            v = float(raw)
        except (TypeError, ValueError):
            continue
        dt = _parse_period(code, freq)
        if not dt:
            continue
        out.append(Observation(date=normalize_date(dt, freq),
                               value=round(v * conv, 6)))
    out.sort(key=lambda o: o.date)
    return out


class KonjSeProvider(BaseProvider):
    name = "konj_se"
    display_name = "NIER / Konjunkturinstitutet"

    def fetch_series(self, spec: SeriesSpec) -> list[Observation]:
        ep = spec.extra_params or {}
        path = ep.get("path")
        query = ep.get("query") or {}
        if not path:
            raise ProviderError(
                f"konj_se: extra_params.path required (series_id={spec.series_id!r})"
            )
        if not query:
            raise ProviderError(
                f"konj_se: extra_params.query required (series_id={spec.series_id!r})"
            )

        freq = (spec.freq_hint or "M").upper()
        conv = spec.conversion or 1.0
        js = _fetch_pxweb(path, query)
        return _extract_observations(js, freq, conv)


try:
    register_provider(KonjSeProvider())
except ProviderError as e:
    print(f"[warn] KonjSeProvider not registered: {e}")
