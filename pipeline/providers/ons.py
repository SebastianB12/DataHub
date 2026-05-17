"""OnsProvider — UK Office for National Statistics + Bank of England IADB (V2 stateless).

Dispatcher ruft fetch_series(spec) pro data_series-Row.

Routing nach extra_params:
  - extra_params.endpoint == "boe": Bank of England IADB CSV-Endpoint
  - extra_params.endpoint == "ons" (oder fehlt): ONS time-series JSON

ONS pro Series:
  - extra_params.uri: kompletter ONS-URI-Pfad, z.B.
      '/economy/inflationandpriceindices/timeseries/l55o/mm23'
    Wenn fehlt, lookup ueber Beta-Search-API (api.beta.ons.gov.uk/v1/search?q=<cdid>)
  - series_id ist die CDID (4-stelliger Series-Code, case-insensitive, z.B. 'L55O').

  Datenformat: https://www.ons.gov.uk{uri}/data liefert JSON mit:
    months: [{date:'2024 JAN', value:'1.5', ...}, ...]
    quarters: [{date:'2024 Q1', value:'0.3', ...}, ...]
    years: [{date:'2024', value:'2.1', ...}, ...]

BoE pro Series:
  - series_id ist der IADB-Code (z.B. 'IUDBEDR', 'LPMAUYM').
  - extra_params.freq optional ('daily'|'monthly'|'quarterly'); default monthly.
    Bei daily: Provider collapsed auf Monatsende (letzte Beobachtung pro Monat).
"""
from __future__ import annotations

import csv
import io
import re
import time
from datetime import date
from typing import Optional

import requests

from pipeline.base_provider import (
    BaseProvider, SeriesSpec, Observation,
    ProviderError, TransientProviderError,
)
from pipeline.transforms import normalize_date
from pipeline.dispatcher import register_provider

ONS_BETA_SEARCH = "https://api.beta.ons.gov.uk/v1/search"
ONS_HOST = "https://www.ons.gov.uk"
BOE_BASE = "https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp"

USER_AGENT = "EconPulse/1.0 (macroeconomic data pipeline)"

MONTH_MAP = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


# ---------------- HTTP-Helfer ----------------

def _http_get(url: str, params: dict | None = None, *, retries: int = 3,
              base_delay: float = 5.0) -> requests.Response:
    """GET mit 429/5xx-Retry und Connection/Timeout-Mapping auf Transient/Provider-Errors."""
    headers = {"User-Agent": USER_AGENT}
    last_exc: BaseException | None = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=30)
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_exc = exc
            if attempt == retries - 1:
                raise TransientProviderError(f"network: {exc}") from exc
            time.sleep(base_delay * (attempt + 1))
            continue
        if resp.status_code == 429:
            if attempt == retries - 1:
                raise TransientProviderError("HTTP 429 (rate limited)")
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
            raise ProviderError(f"HTTP 404: {url} {resp.text[:200]}")
        if resp.status_code >= 400:
            raise ProviderError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        return resp
    raise last_exc  # unreachable


# ---------------- ONS-Pfad ----------------

def _parse_ons_period(period_str: str) -> tuple[date, str] | None:
    """Parse ONS period: '2024 Q1', '2024 JAN', '2024'. Returns (date, freq)."""
    s = (period_str or "").strip()
    try:
        m = re.match(r"^(\d{4})\s+Q(\d)$", s)
        if m:
            year, q = int(m.group(1)), int(m.group(2))
            month = {1: 1, 2: 4, 3: 7, 4: 10}[q]
            return date(year, month, 1), "Q"
        m = re.match(r"^(\d{4})\s+([A-Za-z]{3})$", s)
        if m:
            year = int(m.group(1))
            month = MONTH_MAP.get(m.group(2).upper())
            if month:
                return date(year, month, 1), "M"
        if re.match(r"^\d{4}$", s):
            return date(int(s), 1, 1), "A"
    except (ValueError, KeyError):
        pass
    return None


def _ons_lookup_uri(cdid: str) -> Optional[str]:
    """Resolve a CDID to the canonical ONS time-series URI via the Beta-Search-API."""
    resp = _http_get(ONS_BETA_SEARCH, params={"q": cdid})
    try:
        data = resp.json()
    except ValueError as e:
        raise ProviderError(f"ons search non-JSON: {e}") from e
    target = cdid.upper()
    for item in data.get("items") or []:
        if item.get("type") != "timeseries":
            continue
        if (item.get("cdid") or "").upper() == target and item.get("uri"):
            return item["uri"]
    return None


def _fetch_ons_series(uri: str, freq_hint: str) -> list[Observation]:
    """Fetch a single ONS timeseries (JSON)."""
    url = f"{ONS_HOST}{uri.rstrip('/')}/data"
    resp = _http_get(url)
    try:
        data = resp.json()
    except ValueError as e:
        raise ProviderError(f"ons /data non-JSON: {e}") from e

    # ONS gibt months/quarters/years als separate Arrays zurueck. Wir nehmen primaer
    # die zum freq_hint passende Granularitaet — wenn leer, fallen wir auf das
    # naechstgranulare Array zurueck.
    buckets_by_freq = {
        "M": ["months", "quarters", "years"],
        "Q": ["quarters", "years"],
        "A": ["years"],
        "D": ["months", "quarters", "years"],  # ONS hat kein D fuer Macro-Series
        "W": ["months", "quarters", "years"],
    }
    pick = buckets_by_freq.get(freq_hint, ["months", "quarters", "years"])
    rows = []
    for name in pick:
        arr = data.get(name) or []
        if arr:
            rows = arr
            break

    out: list[Observation] = []
    for entry in rows:
        period = entry.get("date") or ""
        val_str = entry.get("value")
        if val_str in (None, "", ".."):
            continue
        parsed = _parse_ons_period(period)
        if not parsed:
            continue
        dt, freq = parsed
        try:
            v = float(val_str)
        except (TypeError, ValueError):
            continue
        out.append(Observation(date=normalize_date(dt, freq), value=v))
    return out


# ---------------- BoE-Pfad ----------------

def _parse_boe_date(date_str: str) -> date | None:
    """Parse BoE date: '02 Jan 2020' or '01/Jan/2024'."""
    s = (date_str or "").strip()
    for parts in (s.split(), s.split("/")):
        if len(parts) == 3:
            try:
                day = int(parts[0])
                month = MONTH_MAP.get(parts[1][:3].upper())
                year = int(parts[2])
                if month:
                    return date(year, month, day)
            except (ValueError, IndexError):
                continue
    return None


def _fetch_boe_csv(series_code: str) -> list[tuple[date, float]]:
    """Fetch a Bank of England IADB series as CSV."""
    params = {
        "csv.x": "yes",
        "Datefrom": "01/Jan/1975",
        "Dateto": "now",
        "SeriesCodes": series_code,
        "CSVF": "TN",
        "UsingCodes": "Y",
        "VPD": "Y",
        "VFD": "N",
    }
    resp = _http_get(BOE_BASE, params=params)
    results: list[tuple[date, float]] = []
    reader = csv.DictReader(io.StringIO(resp.text))
    for row in reader:
        dt = _parse_boe_date(row.get("DATE", ""))
        val_str = row.get(series_code, "")
        if not dt or not val_str:
            continue
        try:
            results.append((dt, float(val_str)))
        except ValueError:
            continue
    return results


def _boe_observations(series_code: str, freq_token: str, conv: float) -> list[Observation]:
    raw = _fetch_boe_csv(series_code)
    if freq_token == "daily":
        # Collapse to month-end (latest obs per month)
        monthly: dict[tuple[int, int], tuple[date, float]] = {}
        for dt, value in raw:
            key = (dt.year, dt.month)
            if key not in monthly or dt > monthly[key][0]:
                monthly[key] = (dt, value)
        raw = list(monthly.values())
        boe_freq = "M"
    elif freq_token == "quarterly":
        boe_freq = "Q"
    else:
        boe_freq = "M"
    return [
        Observation(
            date=normalize_date(dt, boe_freq),
            value=round(float(value) * conv, 6),
        )
        for dt, value in raw
    ]


# ---------------- Provider ----------------

class OnsProvider(BaseProvider):
    name = "ons"
    display_name = "Office for National Statistics"

    def fetch_series(self, spec: SeriesSpec) -> list[Observation]:
        if not spec.series_id:
            raise ProviderError("ons: series_id missing")

        ep = spec.extra_params or {}
        endpoint = (ep.get("endpoint") or "ons").lower()
        conv = spec.conversion or 1.0

        if endpoint == "boe":
            freq_token = (ep.get("freq") or "monthly").lower()
            return _boe_observations(spec.series_id, freq_token, conv)

        # ONS time-series endpoint.
        uri = ep.get("uri")
        if not uri:
            uri = _ons_lookup_uri(spec.series_id)
        if not uri:
            raise ProviderError(
                f"ons: cannot resolve URI for CDID '{spec.series_id}' "
                f"(provide extra_params.uri)"
            )

        obs = _fetch_ons_series(uri, spec.freq_hint or "M")
        if conv != 1.0:
            obs = [Observation(date=o.date, value=round(o.value * conv, 6)) for o in obs]
        return obs


try:
    register_provider(OnsProvider())
except ProviderError as e:
    print(f"[warn] OnsProvider not registered: {e}")
