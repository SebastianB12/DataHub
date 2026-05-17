"""BdfProvider — Banque de France Webstat-Series (V2 stateless).

V2: provider.fetch_series(SeriesSpec) -> list[Observation].
Keine indicator/country/source-Knowledge. Wird vom Dispatcher pro data_series-Row gerufen.

Series-ID-Format:
  Standard BdF/Webstat-Key. Erstes Token = Dataset, gesamter String = Series-Key.
  Beispiele:
    "TOR1.M.FR.EUR.4F.LL.MRR_FR.LEV"   -> Dataset 'TOR1' (Taux d'interet)
    "CONJ.M.N01.S.IN.000CZ.TUTSM000.10"-> Dataset 'CONJ' (Capacity Utilisation)

Routing-Logik:
  - spec.extra_params.dataset / spec.extra_params.series_code (falls explizit gesetzt)
    haben Vorrang.
  - Sonst: spec.series_id wird am ersten '.' gesplittet; vor dem Punkt = dataset,
    nach dem Punkt = series_code.
  - Fetch via DBnomics: GET v22/series/BDF/<dataset>/<series_code>?observations=1.
    DBnomics mirrort die Banque-de-France-SDMX-Datasets und ist auth-frei.
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


DBNOMICS_BASE = "https://api.db.nomics.world/v22/series"
USER_AGENT = "EconPulse/1.0 (macroeconomic data pipeline)"


# ---------------- HTTP-Helfer ----------------

def _http_get(url: str, *, retries: int = 3, base_delay: float = 5.0,
              timeout: float = 90.0) -> requests.Response:
    """GET mit Retry auf 5xx / Connection / Timeout. DBnomics kann langsam sein."""
    headers = {"User-Agent": USER_AGENT}
    last_exc: BaseException | None = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
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
            raise ProviderError(f"HTTP 404: {url}")
        if resp.status_code >= 400:
            raise ProviderError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        return resp
    raise last_exc  # unreachable


# ---------------- Period-Parser ----------------

def _parse_period(p: str, freq: str) -> date | None:
    """DBnomics-Periodenformate: 'YYYY-MM', 'YYYY-Qn', 'YYYY', 'YYYY-MM-DD'."""
    s = str(p).strip()
    try:
        if (freq == "Q") or ("Q" in s):
            normalized = s.replace("-Q", "Q")
            year, q = normalized.split("Q")
            month = {"1": 1, "2": 4, "3": 7, "4": 10}[q]
            return date(int(year), month, 1)
        if freq == "M" or len(s) == 7:
            year, month = s.split("-")
            return date(int(year), int(month), 1)
        if freq == "A" or len(s) == 4:
            return date(int(s), 1, 1)
        if len(s) == 10:
            return date.fromisoformat(s)
    except (ValueError, KeyError):
        pass
    return None


# ---------------- Dataset/Series-Code-Resolver ----------------

def _resolve_dataset_and_key(spec: SeriesSpec) -> tuple[str, str]:
    """Bestimmt (dataset, series_code) aus spec.extra_params bzw. spec.series_id."""
    ep = spec.extra_params or {}
    dataset = ep.get("dataset")
    series_code = ep.get("series_code") or ep.get("series")
    if dataset and series_code:
        return str(dataset), str(series_code)

    sid = (spec.series_id or "").strip()
    if not sid:
        raise ProviderError("bdf: series_id missing and no extra_params.dataset/series_code")

    if "." not in sid:
        raise ProviderError(
            f"bdf: cannot split series_id '{sid}' into dataset.series_code "
            f"(expected 'DATASET.K1.K2...')"
        )
    head, rest = sid.split(".", 1)
    if dataset:
        # extra_params.dataset overrides head, series_code is whole sid
        return str(dataset), sid
    return head, rest


# ---------------- Provider ----------------

class BdfProvider(BaseProvider):
    name = "bdf"
    display_name = "Banque de France"

    def fetch_series(self, spec: SeriesSpec) -> list[Observation]:
        dataset, series_code = _resolve_dataset_and_key(spec)
        url = f"{DBNOMICS_BASE}/BDF/{dataset}/{series_code}?observations=1"

        try:
            resp = _http_get(url)
        except (TransientProviderError, ProviderError):
            raise
        except Exception as e:
            raise ProviderError(f"bdf fetch: {e}") from e

        try:
            payload = resp.json()
        except ValueError as e:
            raise ProviderError(f"bdf non-JSON response: {e}") from e

        docs = (payload.get("series") or {}).get("docs") or []
        if not docs:
            return []
        s = docs[0]
        periods = s.get("period") or []
        values = s.get("value") or []

        freq = spec.freq_hint or "M"
        conv = spec.conversion or 1.0

        out: list[Observation] = []
        for p, v in zip(periods, values):
            if v is None or v == "NA":
                continue
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
