"""NIER / Konjunkturinstitutet — Swedish National Institute of Economic Research.

TE attributes both Sweden's consumer-confidence and business-confidence to
NIER (https://www.konj.se/), not to Statistics Sweden (SCB). The Konjunktur-
barometer surveys are NIER-owned; SCB doesn't republish them.

API: PxWeb v1 at https://statistik.konj.se/PxWeb/api/v1/en/KonjBar.

Series mapped:
  business-confidence  ->  KonjBar/indikatorer/Indikatorm.px
                            Indikator=BTOT (Business sector / Företagens
                            konfidensindikator, the BCI composite).
                            2026-04 = 103.3 (TE exact match for 2026-04).

  consumer-confidence  ->  KonjBar/hushall/indikatorhus.px
                            Indikator=bhuscon, Grupp=100 (All households).
                            2026-04 = 91.5 (TE exact match for 2026-04).

Both series are NIER "Indikator" levels with base 2000-2024 mean=100 (their
post-2026 redesign). Monthly NSA (NIER doesn't publish a separate SA balance
on the headline composite indicator).

Verified 2026-05-14 vs https://tradingeconomics.com/sweden/{consumer,business}
-confidence: both exact match on 2026-04.
"""
import os
from datetime import date

import requests
from dotenv import load_dotenv

from pipeline.base_provider import BaseProvider, DataPoint
from pipeline.transforms import normalize_date
from pipeline.db import upsert_data_points, log_pipeline_run, datapoints_to_rows

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

BASE = "https://statistik.konj.se/PxWeb/api/v1/en/KonjBar"

SERIES = [
    {
        "slug": "business-confidence",
        "path": "indikatorer/Indikatorm.px",
        "query": {"Indikator": "BTOT"},
        "series_id": "KONJ/indikatorer/Indikatorm/BTOT",
        "freq": "M",
        "unit": "Index (2000-2024=100)",
        "adjustment": "NSA",
        "conversion": 1.0,
        "note": "NIER Konjunkturbarometer Business Sector composite (BTOT) — Företagens konfidensindikator",
    },
    {
        "slug": "consumer-confidence",
        "path": "hushall/indikatorhus.px",
        # Grupp=100 = all households (the headline panel).
        "query": {"Indikator": "bhuscon", "Grupp": "100"},
        "series_id": "KONJ/hushall/indikatorhus/bhuscon",
        "freq": "M",
        "unit": "Index (2000-2024=100)",
        "adjustment": "NSA",
        "conversion": 1.0,
        "note": "NIER Konjunkturbarometer Consumer Confidence Indicator (bhuscon, all households)",
    },
]


def _parse_period(p: str) -> date | None:
    # NIER uses YYYYMNN (e.g. "2026M04").
    try:
        if "M" in p:
            yy, mm = p.split("M")
            return date(int(yy), int(mm), 1)
    except Exception:
        return None
    return None


def _fetch_series(cfg: dict) -> list[tuple[date, float]]:
    url = f"{BASE}/{cfg['path']}"
    body = {
        "query": [
            {"code": k, "selection": {"filter": "item", "values": [v]}}
            for k, v in cfg["query"].items()
        ],
        "response": {"format": "json-stat2"},
    }
    r = requests.post(url, json=body, timeout=30)
    r.raise_for_status()
    js = r.json()
    values = js.get("value", [])
    dim = js.get("dimension", {})
    # NIER uses "Period" as the time dimension on Indikatorm; same on hushall.
    tid = None
    for k in js.get("id", []):
        if k.lower() == "period":
            tid = k
            break
    if tid is None:
        return []
    cat = dim[tid]["category"]["index"]
    if isinstance(cat, dict):
        pairs = sorted(cat.items(), key=lambda x: x[1])
    else:  # list form
        pairs = [(code, pos) for pos, code in enumerate(cat)]
    out: list[tuple[date, float]] = []
    for code, pos in pairs:
        v = values[pos] if isinstance(pos, int) and pos < len(values) else None
        if v is None:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        dt = _parse_period(code)
        if dt:
            out.append((dt, fv))
    out.sort()
    return out


class KonjSeProvider(BaseProvider):
    name = "konj_se"
    display_name = "NIER / Konjunkturinstitutet"

    def fetch(self) -> list[DataPoint]:
        out: list[DataPoint] = []
        for cfg in SERIES:
            try:
                pairs = _fetch_series(cfg)
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"],
                        country="SE",
                        date=normalize_date(dt, cfg["freq"]),
                        value=round(v * cfg["conversion"], 4),
                        source="konj_se",
                        unit=cfg["unit"],
                        series_id=cfg["series_id"],
                        adjustment=cfg["adjustment"],
                    ))
                print(f"  OK {cfg['slug']}/SE (NIER {cfg['path']}): {len(pairs)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['slug']}/SE (NIER {cfg['path']}): {e}")
        return out


def run():
    p = KonjSeProvider()
    print(f"Fetching from {p.display_name} (statistik.konj.se)...")
    try:
        pts = p.fetch()
        print(f"\nTotal: {len(pts)} data points")
        rows = datapoints_to_rows(pts)
        total = 0
        for i in range(0, len(rows), 500):
            count = upsert_data_points(rows[i:i + 500])
            total += count
        log_pipeline_run("konj_se", "success", total)
        print(f"\nDone. {total} rows upserted.")
    except Exception as e:
        log_pipeline_run("konj_se", "failed", error_message=str(e))
        print(f"\nFailed: {e}")
        raise


if __name__ == "__main__":
    run()
