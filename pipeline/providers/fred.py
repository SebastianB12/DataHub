"""
FredProvider — Federal Reserve Economic Data (fredapi).
Reads its series config from the DB table `indicator_sources` (source='fred').
Adding a new FRED series = INSERT one row, no Python edit.
"""

import os
import time
from fredapi import Fred
from dotenv import load_dotenv

from pipeline.base_provider import BaseProvider, DataPoint
from pipeline.transforms import normalize_date
from pipeline.db import datapoints_to_rows, upsert_data_points, log_pipeline_run, load_series_config

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

# Strings that indicate FRED-side transient hiccups; retry on these.
# "Internal Server Error" is the most common — FRED's API drops a few %
# of requests under load. Retry-once is enough to clear nearly all of them.
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
        self.fred = Fred(api_key=os.environ["FRED_API_KEY"])

    def _get_series_with_retry(self, series_id: str, retries: int = 3, base_delay: float = 5.0):
        """Fetch a FRED series with backoff retry on transient 5xx errors."""
        last_exc: BaseException | None = None
        for attempt in range(retries):
            try:
                return self.fred.get_series(series_id)
            except Exception as exc:  # fredapi wraps urllib.HTTPError as plain Exception
                last_exc = exc
                if attempt == retries - 1 or not _is_transient(exc):
                    raise
                delay = base_delay * (attempt + 1)  # 5s, 10s, 15s
                time.sleep(delay)
        raise last_exc  # unreachable, satisfies type checkers

    def _fetch_series(self, cfg: dict) -> list[DataPoint]:
        series = self._get_series_with_retry(cfg["series_id"]).dropna()
        indicator = cfg["indicator"]
        country = cfg["country"]
        conversion = float(cfg.get("conversion") or 1)
        unit = cfg.get("unit") or ""
        adjustment = cfg.get("adjustment") or ""
        freq = cfg.get("freq_hint") or "M"
        series_id = cfg["series_id"]

        # Daily series: collapse to month-end value (latest obs per month).
        if freq == "D":
            monthly: dict[tuple[int, int], tuple] = {}
            for dt, value in series.items():
                key = (dt.year, dt.month)
                if key not in monthly or dt > monthly[key][0]:
                    monthly[key] = (dt, value)
            return [
                DataPoint(
                    indicator=indicator, country=country,
                    date=normalize_date(dt.date(), "M"),
                    value=round(float(value) * conversion, 2),
                    source="fred", unit=unit, series_id=series_id, adjustment=adjustment,
                )
                for dt, value in monthly.values()
            ]

        return [
            DataPoint(
                indicator=indicator, country=country,
                date=normalize_date(dt.date(), freq),
                value=round(float(value) * conversion, 2),
                source="fred", unit=unit, series_id=series_id, adjustment=adjustment,
            )
            for dt, value in series.items()
        ]

    def fetch(self) -> list[DataPoint]:
        configs = load_series_config("fred")
        all_points: list[DataPoint] = []
        for cfg in configs:
            try:
                points = self._fetch_series(cfg)
                all_points.extend(points)
                adj = f" [{cfg['adjustment']}]" if cfg.get("adjustment") else ""
                print(f"  OK {cfg['indicator']} ({cfg['country']}){adj}: {len(points)} ({cfg.get('unit') or ''})")
            except Exception as e:
                print(f"  FAIL {cfg['indicator']} ({cfg['country']}, {cfg['series_id']}): {e}")
        return all_points


def run():
    provider = FredProvider()
    print(f"Fetching data from {provider.display_name}...")
    try:
        points = provider.fetch()
        print(f"\nTotal: {len(points)} data points")
        rows = datapoints_to_rows(points)
        total = 0
        batch_size = 500
        for i in range(0, len(rows), batch_size):
            batch = rows[i : i + batch_size]
            count = upsert_data_points(batch)
            total += count
            print(f"  Upserted batch {i // batch_size + 1}: {count} rows")
        log_pipeline_run("fred", "success", total)
        print(f"\nDone. {total} rows upserted.")
    except Exception as e:
        log_pipeline_run("fred", "failed", error_message=str(e))
        print(f"\nFailed: {e}")
        raise


if __name__ == "__main__":
    run()
