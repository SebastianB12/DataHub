"""GusPlProvider — Statistics Poland (GUS DBW) — V2 stateless.

Reverse-engineered REST: dbw.stat.gov.pl/api_app
Endpoint: POST /api_app/wsk/GetTableNewManyIndicatorsNew (dimensional payload)
Rate limit: 5 req/s, 100/15min — Dispatcher haelt PROVIDER_RATE_LIMITS ein.

Spec-Mapping (Dispatcher -> Provider):
  spec.series_id     : Composite-Key (informational), z.B. "GUS:var=305/COICOP=Total"
                       Optional: reine numerische indicator_id (z.B. "305") als Fallback.
  spec.extra_params  : dict mit dimensional payload (Pflicht fuer alle nicht-trivialen Series):
       {
         "specs": [
           {
             "variable_id":  int,
             "section_id":   int,
             "type_id":      int,
             "positions":    list[str],   # z.B. ["305;909;5;784.7215815","305;909;5;562.6902025"]
             "freq":         "M" | "Q",
             "years":        list[int] | None,  # None = 2010..today
           },
           ...     # mehrere Specs werden konkateniert (multi-section-join wie CPI 909+1698)
         ],
         "conversion_after_fetch": float | omitted  # z.B. 0.001 fuer persons->thousand
       }
  spec.freq_hint     : 'M' | 'Q' | 'A' — fuer Datumsnormalisierung (das spec-eigene
                       freq steuert payload-Layout; freq_hint normalisiert das Resultat).

Errors:
  5xx / Connection / Timeout         -> TransientProviderError (Dispatcher retried)
  4xx (incl. 404) / Payload-/Schema  -> ProviderError
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

API = "https://dbw.stat.gov.pl/api_app"
HDR = {
    "User-Agent": "Mozilla/5.0",
    "Content-Type": "application/json",
    "Accept": "application/json",
}

# Period-IDs (Okresy). Monthly: M01=247..M12=258. Quarterly: Q1=270..Q4=273.
MONTH_OKRESY = {1: 247, 2: 248, 3: 249, 4: 250, 5: 251, 6: 252,
                7: 253, 8: 254, 9: 255, 10: 256, 11: 257, 12: 258}
QUARTER_OKRESY = {1: 270, 2: 271, 3: 272, 4: 273}

# Territorial-unit-id Polen (national total)
JT_POLAND = 33617

# Inter-call backoff zwischen mehreren payload-Specs einer Serie.
_INTER_SPEC_SLEEP = 0.3


def _build_payload(spec: dict) -> dict:
    """Build GetTableNewManyIndicatorsNew payload aus einem dict-Spec.

    Erwartete Keys: variable_id, section_id, type_id, positions, freq, years?
    """
    try:
        var = int(spec["variable_id"])
        sec = int(spec["section_id"])
        typ = int(spec["type_id"])
        positions = list(spec["positions"])
        freq = (spec.get("freq") or "M").upper()
    except (KeyError, TypeError, ValueError) as e:
        raise ProviderError(f"gus_pl: invalid spec dict: {e}; got {spec!r}")

    years = spec.get("years") or list(range(2010, date.today().year + 1))

    col_values: list[int] = []
    col_years: list[int] = []
    col_titles: list[str] = []
    if freq == "M":
        for yr in years:
            for k, oid in MONTH_OKRESY.items():
                col_values.append(oid)
                col_years.append(yr)
                col_titles.append(f"{yr} M{k:02d}")
    elif freq == "Q":
        for yr in years:
            for k, oid in QUARTER_OKRESY.items():
                col_values.append(oid)
                col_years.append(yr)
                col_titles.append(f"{yr} Q{k}")
    else:
        raise ProviderError(f"gus_pl: unsupported spec freq {freq!r} (need M or Q)")

    rows = [
        {"type": "Zm", "title": "Variable", "values": [var], "idx": 0,
         "loaded": True, "titles": [""], "titles_orig": [""]},
        {"type": "TYPE", "title": "Information type", "values": [typ],
         "new_values": [typ], "idx": 1, "titles": [""]},
    ]
    for i, posval in enumerate(positions):
        rows.append({"type": "POS", "section_id": sec, "title": f"dim{i}",
                     "loaded": True, "values": [posval], "titles": [], "idx": 2 + i})
    rows.append({"type": "JT", "title": "Territorial unit",
                 "values": [JT_POLAND], "titles": ["POLAND"],
                 "titles_orig": ["POLSKA"], "idx": 2 + len(positions)})

    return {
        "opts": {"showSymbols": False, "showEmptyRows": True,
                 "showEmptyCols": True, "lang": "en"},
        "list": [],
        "rows": rows,
        "cols": [{
            "type": "SC",
            "title": "Time series",
            "values": col_values,
            "years": col_years,
            "titles": col_titles,
            "titles_orig": col_titles,
            "idx": 999999990,
            "values_sort": [],
        }],
        "params": {"page": 0, "offset": 0, "rowsPerPage": 100, "sort": []},
    }


def _post_payload(payload: dict) -> dict:
    """POST an die GUS-DBW-API. 5xx/Timeout -> Transient. 4xx -> Permanent."""
    url = f"{API}/wsk/GetTableNewManyIndicatorsNew"
    try:
        r = requests.post(url, json=payload, headers=HDR, timeout=30)
    except (requests.ConnectionError, requests.Timeout) as e:
        raise TransientProviderError(f"gus_pl network: {e}") from e
    except requests.RequestException as e:
        raise ProviderError(f"gus_pl request error: {e}") from e

    if r.status_code >= 500:
        raise TransientProviderError(f"gus_pl HTTP {r.status_code}: {r.text[:200]}")
    if r.status_code == 404:
        raise ProviderError(f"gus_pl HTTP 404: {r.text[:200]}")
    if r.status_code >= 400:
        raise ProviderError(f"gus_pl HTTP {r.status_code}: {r.text[:200]}")

    try:
        return r.json()
    except ValueError as e:
        raise ProviderError(f"gus_pl: invalid JSON response: {e}") from e


def _parse_response(resp_json: dict, spec: dict) -> list[tuple[date, float]]:
    """Parse das data[0]-Array zu (date, value)-Tupeln. Leere/markierte Zellen -> skip."""
    data = resp_json.get("data") or []
    if not data:
        return []
    row = data[0]
    freq = (spec.get("freq") or "M").upper()
    years = spec.get("years") or list(range(2010, date.today().year + 1))
    period_keys = list(MONTH_OKRESY.keys()) if freq == "M" else list(QUARTER_OKRESY.keys())
    n_per_year = len(period_keys)

    data_cells: list[float | None] = []
    for cell in row:
        if not isinstance(cell, dict):
            continue
        d = cell.get("d")
        if isinstance(d, (int, float)):
            data_cells.append(float(d))
        elif isinstance(d, str) and d.startswith("("):
            data_cells.append(None)
        # else: metadata-string label -> ignore

    expected = len(years) * n_per_year
    if len(data_cells) < expected:
        return []
    data_cells = data_cells[-expected:]

    out: list[tuple[date, float]] = []
    idx = 0
    for yr in years:
        for k in period_keys:
            v = data_cells[idx]
            idx += 1
            if v is None:
                continue
            if freq == "M":
                dt = date(yr, k, 1)
            else:
                dt = date(yr, (k - 1) * 3 + 1, 1)
            out.append((dt, v))
    return out


def _extract_int_from_series_id(series_id: str) -> int | None:
    """Versucht eine numerische variable_id aus dem Composite-Key zu ziehen.

    Beispiele:
      "305"                         -> 305
      "GUS:var=305/COICOP=Total"   -> 305
      "GUS:var=1667/sec=1413/..."  -> 1667
    """
    if not series_id:
        return None
    s = series_id.strip()
    if s.isdigit():
        return int(s)
    # Suche "var=NNN"
    marker = "var="
    i = s.find(marker)
    if i >= 0:
        tail = s[i + len(marker):]
        num = ""
        for ch in tail:
            if ch.isdigit():
                num += ch
            else:
                break
        if num:
            return int(num)
    return None


def _resolve_specs(spec: SeriesSpec) -> tuple[list[dict], float]:
    """Liefert (payload_specs, conversion_after_fetch).

    Bevorzugt extra_params['specs']. Fallback: minimal-spec aus series_id (numerisch).
    """
    ep = spec.extra_params or {}
    raw_specs = ep.get("specs")
    if isinstance(raw_specs, list) and raw_specs:
        payload_specs: list[dict] = []
        for s in raw_specs:
            if not isinstance(s, dict):
                raise ProviderError(f"gus_pl: spec entry not a dict: {s!r}")
            payload_specs.append(s)
        conv = float(ep.get("conversion_after_fetch") or 1.0)
        return payload_specs, conv

    # Fallback: spec.series_id rein numerisch -> nicht ausreichend (section_id/type_id
    # fehlen). Wir akzeptieren das nur fuer Smoke-Test wenn extra_params zumindest
    # section_id+type_id+positions liefert.
    var_id = _extract_int_from_series_id(spec.series_id)
    if var_id is None:
        raise ProviderError(
            f"gus_pl: cannot resolve payload — extra_params.specs missing "
            f"and series_id not parseable: {spec.series_id!r}"
        )
    if not all(k in ep for k in ("section_id", "type_id", "positions")):
        raise ProviderError(
            f"gus_pl: minimal-spec fallback needs section_id+type_id+positions in "
            f"extra_params (variable_id={var_id})"
        )
    payload_specs = [{
        "variable_id": var_id,
        "section_id": ep["section_id"],
        "type_id": ep["type_id"],
        "positions": ep["positions"],
        "freq": ep.get("freq") or spec.freq_hint or "M",
        "years": ep.get("years"),
    }]
    conv = float(ep.get("conversion_after_fetch") or 1.0)
    return payload_specs, conv


class GusPlProvider(BaseProvider):
    name = "gus_pl"
    display_name = "Statistics Poland"

    def fetch_series(self, spec: SeriesSpec) -> list[Observation]:
        payload_specs, conv = _resolve_specs(spec)
        freq_norm = (spec.freq_hint or payload_specs[0].get("freq") or "M").upper()
        scale = float(spec.conversion or 1.0) * conv

        merged: dict[date, float] = {}
        for s in payload_specs:
            payload = _build_payload(s)
            resp = _post_payload(payload)
            for dt, val in _parse_response(resp, s):
                merged[dt] = val
            if len(payload_specs) > 1:
                time.sleep(_INTER_SPEC_SLEEP)

        out: list[Observation] = []
        for dt, val in sorted(merged.items()):
            try:
                v = float(val) * scale
            except (TypeError, ValueError):
                continue
            out.append(Observation(date=normalize_date(dt, freq_norm), value=v))
        return out


try:
    register_provider(GusPlProvider())
except ProviderError as e:
    print(f"[warn] GusPlProvider not registered: {e}")
