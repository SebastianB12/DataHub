"""EiaProvider — U.S. Energy Information Administration (api.eia.gov v2).

V2 stateless: provider.fetch_series(SeriesSpec) -> list[Observation].
Keine indicator/country/source-Knowledge mehr. Wird vom Dispatcher pro data_series-Row gerufen.

EIA-spezifische Konventionen:
  - spec.series_id     -> EIA Series-Code (z.B. 'WCESTUS1', 'PET.WCRFPUS2.W'). Wird als
                          primaerer Facet-Wert in die EIA-API geschickt (Default-Facet: 'series').
  - spec.extra_params  -> optional, dict mit:
                            endpoint:    EIA v2 Dataset-Pfad (z.B. 'petroleum/stoc/wstk',
                                         'natural-gas/stor/wkly'). Wenn fehlend, wird versucht
                                         den Pfad aus series_id ('PET.WCRFPUS2.W' -> 'petroleum/...')
                                         abzuleiten — schlaegt das fehl: ProviderError.
                            frequency:   'weekly' | 'monthly' | 'daily' | 'annual' | 'quarterly'
                                         (Default leitet sich aus spec.freq_hint ab).
                            facet:       Welcher Facet-Key fuer series_id ('series' default).
                            facets:      dict zusaetzlicher Facets, z.B.
                                         {'duoarea': ['NUS'], 'product': ['EPMR']}.
                            facets_only: bool — wenn True, wird der series_id-Facet NICHT
                                         gesetzt (alle Facets stehen schon in `facets`).
  - spec.freq_hint     -> Frequenz-Hint fuer normalize_date + Default-frequency-Param.

EIA_API_KEY in .env Pflicht — fehlt der Key, registriert sich der Provider NICHT.
"""
from __future__ import annotations

import os
from datetime import date, datetime

import requests
from dotenv import load_dotenv

from pipeline.base_provider import (
    BaseProvider, SeriesSpec, Observation,
    ProviderError, TransientProviderError,
)
from pipeline.transforms import normalize_date
from pipeline.dispatcher import register_provider

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

BASE_URL = "https://api.eia.gov/v2"

# freq_hint -> EIA-API-frequency-Parameter
FREQ_HINT_TO_EIA = {
    "D": "daily",
    "W": "weekly",
    "M": "monthly",
    "Q": "quarterly",
    "A": "annual",
}


def _parse_eia_date(raw: str) -> date:
    """Weekly/daily: 'YYYY-MM-DD'; monthly: 'YYYY-MM'; yearly: 'YYYY';
    quarterly z.B. '2023-Q1' (selten — graceful fallback)."""
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    # Quarterly fallback: '2023-Q1' -> 2023-01-01 (normalize_date rundet auf Q-Ende).
    if "Q" in raw:
        try:
            y, q = raw.split("-Q")
            month = (int(q) - 1) * 3 + 1
            return date(int(y), month, 1)
        except (ValueError, IndexError):
            pass
    raise ValueError(f"Unrecognised EIA period: {raw}")


def _derive_endpoint_from_series_id(series_id: str) -> str | None:
    """Best-effort: leite den v2-Dataset-Pfad aus dem alten Series-Code ab.

    EIA v1 Series-Codes haben das Format 'PET.WCRFPUS2.W' -> 'petroleum/...'.
    Da das Mapping nicht 1:1 maschinell loesbar ist, geben wir None zurueck
    wenn nichts Verlaessliches ableitbar ist (Caller soll endpoint mitliefern).
    """
    return None


class EiaProvider(BaseProvider):
    name = "eia"
    display_name = "U.S. Energy Information Administration"

    def __init__(self):
        self.api_key = os.environ.get("EIA_API_KEY")
        if not self.api_key:
            raise ProviderError(
                "EIA_API_KEY missing in .env — register at eia.gov/opendata/register.php"
            )

    def fetch_series(self, spec: SeriesSpec) -> list[Observation]:
        params_cfg = dict(spec.extra_params or {})
        endpoint = params_cfg.get("endpoint") or _derive_endpoint_from_series_id(spec.series_id)
        if not endpoint:
            raise ProviderError(
                f"EIA fetch_series: 'endpoint' missing in extra_params for series '{spec.series_id}'"
            )

        # frequency: explicit override -> freq_hint mapping -> 'weekly' as last resort
        frequency = (
            params_cfg.get("frequency")
            or FREQ_HINT_TO_EIA.get(spec.freq_hint or "W")
            or "weekly"
        )

        facet_key = params_cfg.get("facet", "series")
        extra_facets = params_cfg.get("facets") or {}
        facets_only = bool(params_cfg.get("facets_only"))

        url = f"{BASE_URL}/{endpoint.strip('/')}/data/"
        params: list[tuple[str, str | int]] = [
            ("api_key", self.api_key),
            ("frequency", frequency),
            ("data[0]", "value"),
            ("sort[0][column]", "period"),
            ("sort[0][direction]", "desc"),
            ("offset", 0),
            ("length", 5000),
        ]
        if not facets_only:
            params.append((f"facets[{facet_key}][]", spec.series_id))
        for fname, fvals in extra_facets.items():
            if isinstance(fvals, str):
                fvals = [fvals]
            for v in fvals:
                params.append((f"facets[{fname}][]", v))

        try:
            resp = requests.get(url, params=params, timeout=30)
        except requests.exceptions.RequestException as e:
            # Connection / Timeout / DNS -> transient
            raise TransientProviderError(f"EIA network error: {e}") from e

        if resp.status_code >= 500:
            raise TransientProviderError(
                f"EIA {resp.status_code} for {endpoint} {spec.series_id}: {resp.text[:200]}"
            )
        if resp.status_code >= 400:
            raise ProviderError(
                f"EIA {resp.status_code} for {endpoint} {spec.series_id}: {resp.text[:200]}"
            )

        try:
            payload = resp.json()
        except ValueError as e:
            raise ProviderError(f"EIA non-JSON response: {e}") from e

        data = (payload.get("response") or {}).get("data") or []

        conv = spec.conversion or 1.0
        freq = spec.freq_hint or "W"

        out: list[Observation] = []
        for row in data:
            raw_period = row.get("period")
            raw_value = row.get("value")
            if raw_period is None or raw_value is None:
                continue
            try:
                dt = _parse_eia_date(raw_period)
                v = float(raw_value) * conv
            except (ValueError, TypeError):
                continue
            out.append(Observation(
                date=normalize_date(dt, freq),
                value=round(v, 6),
            ))
        return out


# Provider-Registry-Self-Registration (lazy: nur wenn Key vorhanden)
try:
    register_provider(EiaProvider())
except ProviderError as e:
    print(f"[warn] EiaProvider not registered: {e}")
