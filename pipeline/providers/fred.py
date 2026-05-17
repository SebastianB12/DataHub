"""FredProvider — Federal Reserve Economic Data (fredapi).

V2 stateless: provider.fetch_series(SeriesSpec) -> list[Observation].
Keine indicator/country/source-Knowledge mehr. Wird vom Dispatcher pro data_series-Row gerufen.
"""
from __future__ import annotations

import os
import time
from fredapi import Fred
from dotenv import load_dotenv

from pipeline.base_provider import (
    BaseProvider, SeriesSpec, Observation,
    ProviderError, TransientProviderError,
)
from pipeline.transforms import normalize_date
from pipeline.dispatcher import register_provider

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

# Strings that indicate FRED-side transient hiccups; retry on these.
TRANSIENT_FRED_ERRORS = (
    "Internal Server Error",
    "Bad Gateway",
    "Service Unavailable",
    "Gateway Timeout",
    "Connection",
    "timed out",
)


def _is_transient(exc: BaseException) -> bool:
    msg = str(exc)
    return any(s in msg for s in TRANSIENT_FRED_ERRORS)


class FredProvider(BaseProvider):
    name = "fred"
    display_name = "Federal Reserve Economic Data"

    def __init__(self):
        key = os.environ.get("FRED_API_KEY")
        if not key:
            raise ProviderError("FRED_API_KEY missing in .env")
        self.fred = Fred(api_key=key)

    def _get_series_with_retry(self, series_id: str,
                                retries: int = 3, base_delay: float = 5.0):
        """Fetch a FRED series with backoff retry on transient 5xx errors."""
        last_exc: BaseException | None = None
        for attempt in range(retries):
            try:
                return self.fred.get_series(series_id)
            except Exception as exc:
                last_exc = exc
                if attempt == retries - 1 or not _is_transient(exc):
                    raise
                time.sleep(base_delay * (attempt + 1))
        raise last_exc  # unreachable

    def fetch_series(self, spec: SeriesSpec) -> list[Observation]:
        """Fetch eine FRED-Series. Wendet conversion an, normalisiert Datum auf freq_hint."""
        try:
            series = self._get_series_with_retry(spec.series_id).dropna()
        except Exception as e:
            if _is_transient(e):
                raise TransientProviderError(str(e)) from e
            raise ProviderError(str(e)) from e

        freq = spec.freq_hint or "M"
        conv = spec.conversion or 1.0
        out: list[Observation] = []

        # Daily series: collapse to month-end value (latest obs per month).
        if freq == "D":
            monthly: dict[tuple[int, int], tuple] = {}
            for dt, value in series.items():
                key = (dt.year, dt.month)
                if key not in monthly or dt > monthly[key][0]:
                    monthly[key] = (dt, value)
            for dt, value in monthly.values():
                out.append(Observation(
                    date=normalize_date(dt.date(), "M"),
                    value=round(float(value) * conv, 6),
                ))
            return out

        for dt, value in series.items():
            out.append(Observation(
                date=normalize_date(dt.date(), freq),
                value=round(float(value) * conv, 6),
            ))
        return out


# Provider-Registry-Self-Registration (lazy: nur wenn Key vorhanden)
try:
    register_provider(FredProvider())
except ProviderError as e:
    print(f"[warn] FredProvider not registered: {e}")
