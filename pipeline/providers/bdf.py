"""
BdfProvider — Banque de France series via DBnomics public API.

DBnomics indexes BDF (Banque de France) datasets including CONJ (national business
surveys) where the Capacity Utilisation series for total Manufacturing
(IDBANK M.N01.S.IN.000CZ.TUTSM000.10) is published monthly. TE cites BdF for
this indicator; we fetch from the DBnomics indexed mirror.

API: https://api.db.nomics.world/v22/series/<provider>/<dataset>/<series_code>
Public, no auth.
"""

from datetime import date

import requests

from pipeline.base_provider import BaseProvider, DataPoint
from pipeline.transforms import normalize_date
from pipeline.db import upsert_data_points, log_pipeline_run, datapoints_to_rows


BASE_URL = "https://api.db.nomics.world/v22/series"

# Per-slug config: dbnomics provider, dataset, series_code, target slug,
# country, unit, freq, adjustment, conversion, note.
SERIES = [
    {
        "indicator": "capacity-utilization",
        "country": "FR",
        "provider": "BDF",
        "dataset": "CONJ",
        "series_code": "M.N01.S.IN.000CZ.TUTSM000.10",
        "freq": "M",
        "unit": "%",
        "adjustment": "SA",
        "conversion": 1.0,
        "note": "Banque de France CONJ: Manufacturing industry total capacity utilisation rate, SA, monthly.",
    },
]


def _parse_period(period_str: str, freq: str) -> date | None:
    s = str(period_str).strip()
    try:
        if freq == "M" or len(s) == 7:
            year, month = s.split("-")
            return date(int(year), int(month), 1)
        if freq == "Q" or "Q" in s:
            year, q = s.replace("-Q", "Q").split("Q")
            month = {"1": 1, "2": 4, "3": 7, "4": 10}[q]
            return date(int(year), month, 1)
        if freq == "A" or len(s) == 4:
            return date(int(s), 1, 1)
    except (ValueError, KeyError):
        pass
    return None


def _fetch_series(provider: str, dataset: str, series_code: str) -> list[tuple[str, float]]:
    url = f"{BASE_URL}/{provider}/{dataset}/{series_code}?observations=1"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    docs = resp.json().get("series", {}).get("docs", [])
    if not docs:
        return []
    s = docs[0]
    return list(zip(s.get("period", []), s.get("value", [])))


class BdfProvider(BaseProvider):
    name = "bdf"
    display_name = "Banque de France (via DBnomics)"

    def fetch(self) -> list[DataPoint]:
        out: list[DataPoint] = []
        for cfg in SERIES:
            try:
                rows = _fetch_series(cfg["provider"], cfg["dataset"], cfg["series_code"])
            except Exception as e:
                print(f"  FAIL {cfg['indicator']}/{cfg['country']}: {e}")
                continue
            n = 0
            for period, value in rows:
                if value is None:
                    continue
                dt = _parse_period(period, cfg["freq"])
                if dt is None:
                    continue
                try:
                    val = float(value) * cfg["conversion"]
                except (ValueError, TypeError):
                    continue
                out.append(DataPoint(
                    indicator=cfg["indicator"],
                    country=cfg["country"],
                    date=normalize_date(dt, cfg["freq"]),
                    value=round(val, 6),
                    source="bdf",
                    unit=cfg["unit"],
                    series_id=f"{cfg['dataset']}:{cfg['series_code']}",
                    adjustment=cfg["adjustment"],
                ))
                n += 1
            print(f"  OK {cfg['indicator']}/{cfg['country']} ({cfg['series_code']}): {n} points")
        return out


def run():
    provider = BdfProvider()
    print(f"Fetching data from {provider.display_name}...")
    try:
        points = provider.fetch()
    except Exception as exc:
        print(f"Provider failed: {exc}")
        log_pipeline_run("bdf", "fail", 0, str(exc))
        raise
    rows = datapoints_to_rows(points)
    upserted = upsert_data_points(rows)
    log_pipeline_run("bdf", "success", upserted)
    print(f"Done. {upserted} rows upserted.")


if __name__ == "__main__":
    run()
