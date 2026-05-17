"""BdfProvider — Banque de France Webstat API (V2 stateless, primary source).

Direktzugriff auf die Banque-de-France Webstat-Production-API (IBM API Connect
Gateway) — KEINE DBnomics-Proxy mehr. "Primary Sources only" (Sebastian-Direktive).

API:
  Base:   https://api.webstat.banque-france.fr/webstat-en/v1/data/{dataset}/{key}
  Auth:   Header `X-IBM-Client-Id: <key>` (kostenlose Registrierung auf
          https://developer.webstat.banque-france.fr/).
  Format: ?format=csv  (SDMX-konformes CSV; einfacher Parser).

Series-ID-Format (data_series.series_id):
  Standard BdF/Webstat-Key. Erstes Token vor erstem '.' = Dataset,
  Rest = Series-Key. Beispiele:
    "CONJ.M.N01.S.IN.000CZ.TUTSM000.10"
    "BPM6.M.S.FR.W1.S1.S1.T.B.CA._Z._Z._Z.EUR._T._X.N.ALL"

  Alternativ explizit via spec.extra_params:
    {"dataset": "CONJ", "key": "M.N01.S.IN.000CZ.TUTSM000.10"}

Auth-Fehlend (kein BDF_API_KEY in env):
  Provider wird trotzdem registriert; fetch_series wirft ProviderError mit
  klarem Hinweis, sodass der Dispatcher die Series als 'error: no auth' markiert.
"""
from __future__ import annotations

import csv
import io
import os
import time
from datetime import date, datetime

import requests

from pipeline.base_provider import (
    BaseProvider, SeriesSpec, Observation,
    ProviderError, TransientProviderError,
)
from pipeline.transforms import normalize_date
from pipeline.dispatcher import register_provider


BASE_URL = "https://api.webstat.banque-france.fr/webstat-en/v1/data"
USER_AGENT = "EconPulse/1.0 (macroeconomic data pipeline)"

# Erstes Key-Token nach Dataset -> Frequenz (BdF-SDMX-Konvention).
_FREQ_FROM_KEY = {"D": "D", "B": "D", "W": "W", "M": "M", "Q": "Q", "A": "A", "S": "S"}


# ---------------- Helpers ----------------

def _get_api_key() -> str | None:
    """Lies Client-Id aus env. None falls nicht gesetzt."""
    return (
        os.environ.get("BDF_API_KEY")
        or os.environ.get("BDF_CLIENT_ID")
        or os.environ.get("WEBSTAT_CLIENT_ID")
    )


def _resolve_dataset_and_key(spec: SeriesSpec) -> tuple[str, str]:
    """Bestimmt (dataset, key) aus spec.extra_params bzw. spec.series_id."""
    ep = spec.extra_params or {}
    dataset = ep.get("dataset") or ep.get("flowRef") or ep.get("flow")
    key = ep.get("key") or ep.get("series_code") or ep.get("series")
    if dataset and key:
        return str(dataset), str(key)

    sid = (spec.series_id or "").strip()
    if not sid:
        raise ProviderError("bdf: series_id missing and no extra_params.dataset/key")

    # Erlaube auch "DATASET/KEY"
    if "/" in sid:
        head, rest = sid.split("/", 1)
        return head, rest
    if ":" in sid:
        head, rest = sid.split(":", 1)
        return head, rest
    if "." not in sid:
        raise ProviderError(
            f"bdf: cannot split series_id '{sid}' into dataset.key "
            f"(expected 'DATASET.K1.K2...')"
        )
    head, rest = sid.split(".", 1)
    return head, rest


def _http_get(url: str, headers: dict, *, retries: int = 3, base_delay: float = 5.0,
              timeout: float = 60.0) -> requests.Response:
    """GET mit Retry auf 5xx / Connection / Timeout."""
    last_exc: BaseException | None = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_exc = exc
            if attempt == retries - 1:
                raise TransientProviderError(f"bdf network: {exc}") from exc
            time.sleep(base_delay * (attempt + 1))
            continue
        if resp.status_code == 429:
            if attempt == retries - 1:
                raise TransientProviderError("bdf HTTP 429 (rate limited)")
            time.sleep(base_delay * (attempt + 1))
            continue
        if resp.status_code in (502, 503, 504):
            if attempt == retries - 1:
                raise TransientProviderError(f"bdf HTTP {resp.status_code}")
            time.sleep(base_delay * (attempt + 1))
            continue
        if resp.status_code >= 500:
            raise TransientProviderError(
                f"bdf HTTP {resp.status_code}: {resp.text[:200]}"
            )
        if resp.status_code == 401 or resp.status_code == 403:
            raise ProviderError(
                f"bdf HTTP {resp.status_code}: auth failed — check BDF_API_KEY "
                f"(register at https://developer.webstat.banque-france.fr/)"
            )
        if resp.status_code == 404:
            raise ProviderError(f"bdf HTTP 404: {url}")
        if resp.status_code >= 400:
            raise ProviderError(f"bdf HTTP {resp.status_code}: {resp.text[:200]}")
        return resp
    raise last_exc  # unreachable


def _parse_period(s: str, freq: str) -> date | None:
    """Parse BdF/SDMX period: YYYY, YYYY-MM, YYYY-Qn, YYYY-Sn, YYYY-Wn, YYYY-MM-DD."""
    s = (s or "").strip()
    if not s:
        return None
    try:
        if "Q" in s:
            t = s.replace("-Q", "Q")
            y, q = t.split("Q")
            month = (int(q) - 1) * 3 + 1
            return date(int(y), month, 1)
        if "-S" in s:
            y, sem = s.split("-S")
            month = {"1": 1, "2": 7}[sem]
            return date(int(y), month, 1)
        if "-W" in s:
            return datetime.strptime(s + "-5", "%G-W%V-%u").date()
        if len(s) == 10:
            return date.fromisoformat(s)
        if len(s) == 7:
            y, m = s.split("-")
            return date(int(y), int(m), 1)
        if len(s) == 4:
            return date(int(s), 1, 1)
        if freq == "M" and "-" in s:
            y, m = s.split("-")
            return date(int(y), int(m), 1)
    except (ValueError, KeyError):
        pass
    return None


def _parse_csv(text: str) -> list[tuple[str, str]]:
    """Parse BdF Webstat CSV. Sucht eine Spalte mit Period und eine mit Value.

    BdF CSV-Variants:
      - SDMX 2.1 'csv': Spalten DATAFLOW, KEY, TIME_PERIOD, OBS_VALUE, ...
      - Webstat 'csv':  Spalten 'Date'/'period' + 'Value'/'OBS_VALUE'
    Wir versuchen mehrere Header-Kombinationen.
    """
    # BOM strippen, beide Delimiter zulassen
    text = text.replace("﻿", "")
    # delimiter sniffing
    sample = text[:4096]
    delim = ";" if sample.count(";") > sample.count(",") else ","

    reader = csv.DictReader(io.StringIO(text), delimiter=delim)
    field_lc = {f.lower(): f for f in (reader.fieldnames or [])}

    period_col = (
        field_lc.get("time_period")
        or field_lc.get("period")
        or field_lc.get("date")
        or field_lc.get("time")
    )
    value_col = (
        field_lc.get("obs_value")
        or field_lc.get("value")
        or field_lc.get("obs")
    )
    if not period_col or not value_col:
        return []

    rows: list[tuple[str, str]] = []
    for r in reader:
        p = (r.get(period_col) or "").strip()
        v = (r.get(value_col) or "").strip()
        if not p or v in ("", "NA", "NaN", "None"):
            continue
        # Französisches Dezimaltrennzeichen
        if "," in v and "." not in v:
            v = v.replace(",", ".")
        rows.append((p, v))
    return rows


# ---------------- Provider ----------------

class BdfProvider(BaseProvider):
    name = "bdf"
    display_name = "Banque de France"

    def fetch_series(self, spec: SeriesSpec) -> list[Observation]:
        api_key = _get_api_key()
        if not api_key:
            raise ProviderError(
                "bdf: BDF_API_KEY not set — register at "
                "https://developer.webstat.banque-france.fr/ and set BDF_API_KEY in .env"
            )

        dataset, key = _resolve_dataset_and_key(spec)
        url = f"{BASE_URL}/{dataset}/{key}?format=csv"
        headers = {
            "X-IBM-Client-Id": api_key,
            "Accept": "text/csv",
            "User-Agent": USER_AGENT,
        }

        resp = _http_get(url, headers=headers)

        rows = _parse_csv(resp.text)
        if not rows:
            return []

        freq = spec.freq_hint or _FREQ_FROM_KEY.get(key[:1], "M")
        conv = spec.conversion or 1.0

        out: list[Observation] = []
        for p, v in rows:
            try:
                num = float(v)
            except (TypeError, ValueError):
                continue
            dt = _parse_period(p, freq)
            if dt is None:
                continue
            out.append(Observation(
                date=normalize_date(dt, freq),
                value=round(num * conv, 6),
            ))
        return out


# Self-Registration — try/except, niemals Modulimport killen.
try:
    register_provider(BdfProvider())
except Exception as e:
    print(f"[warn] BdfProvider not registered: {e}")
