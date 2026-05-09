"""ISTAT direct SDMX REST provider (sdmx.istat.it).

Uses ONLY the official ISTAT SDMX REST endpoint — no DBnomics, no Eurostat.
sdmx.istat.it currently exposes base-2015 dataflows; base-2025/2021 dataflows
are partially exposed and may be slower. We accept the data as ISTAT publishes it.
"""
import os
import csv
import io
from datetime import date

import requests
from dotenv import load_dotenv

from pipeline.base_provider import BaseProvider, DataPoint
from pipeline.transforms import normalize_date
from pipeline.db import upsert_data_points, log_pipeline_run, datapoints_to_rows

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

BASE = "https://sdmx.istat.it/SDMXWS/rest/data"

SERIES = [
    # Inflation CPI (NIC base 2015) — dataflow 167_744, key M.IT.39.4.00 (CPI all-items, monthly index)
    {"slug": "inflation-cpi", "dataflow": "167_744", "key": "M.IT.39.4.00",
     "freq": "M", "unit": "Index", "adjustment": "NSA", "conversion": 1.0,
     "note": "ISTAT NIC monthly all-items, base 2015=100"},
    # PPI (Industrial producer prices) — 145_360, base 2015 monthly all-industry total
    {"slug": "ppi", "dataflow": "145_360", "key": "M.IT.IND_PRIC.N.D.0020",
     "freq": "M", "unit": "Index", "adjustment": "NSA", "conversion": 1.0,
     "note": "ISTAT IPRI monthly base 2015"},
    # Industrial production index — 115_333, base 2015 (DCSC_INDXPRODIND_1)
    {"slug": "industrial-production", "dataflow": "115_333", "key": "M.IT.IND_PROD.N.0020",
     "freq": "M", "unit": "Index", "adjustment": "NSA", "conversion": 1.0,
     "note": "ISTAT IPI monthly total industry base 2015"},
    # Retail trade sales volume — 120_337
    {"slug": "retail-sales", "dataflow": "120_337", "key": "M.IT.RTD_TURN_VOL.N.1.9.TOTAL",
     "freq": "M", "unit": "Index", "adjustment": "NSA", "conversion": 1.0,
     "note": "ISTAT retail trade monthly total"},
]


def _parse_period(p: str, freq: str) -> date | None:
    try:
        if freq == "M" and "-" in p:
            yy, mm = p.split("-")
            return date(int(yy), int(mm), 1)
        if freq == "Q" and "-Q" in p:
            yy, q = p.split("-Q")
            return date(int(yy), {"1":1,"2":4,"3":7,"4":10}[q], 1)
        if freq == "A" and len(p) == 4:
            return date(int(p), 1, 1)
    except Exception:
        pass
    return None


def _fetch(dataflow: str, key: str, freq: str) -> list[tuple[date, float]]:
    url = f"{BASE}/{dataflow}/{key}"
    r = requests.get(url, headers={"Accept": "application/vnd.sdmx.data+csv;version=1.0.0"}, timeout=120)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    reader = csv.DictReader(io.StringIO(r.text))
    out = []
    for row in reader:
        per = row.get("TIME_PERIOD", "")
        val_str = row.get("OBS_VALUE", "")
        if not val_str:
            continue
        try:
            v = float(val_str)
        except ValueError:
            continue
        dt = _parse_period(per, freq)
        if dt:
            out.append((dt, v))
    return sorted(out)


class IstatProvider(BaseProvider):
    name = "istat"
    display_name = "ISTAT (Italy)"

    def fetch(self) -> list[DataPoint]:
        out: list[DataPoint] = []
        for cfg in SERIES:
            try:
                pairs = _fetch(cfg["dataflow"], cfg["key"], cfg["freq"])
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"], country="IT",
                        date=normalize_date(dt, cfg["freq"]),
                        value=round(v * cfg["conversion"], 4),
                        source="istat",
                        unit=cfg["unit"],
                        series_id=f"ISTAT/{cfg['dataflow']}/{cfg['key']}",
                        adjustment=cfg["adjustment"],
                    ))
                print(f"  OK {cfg['slug']}/IT (ISTAT {cfg['dataflow']}): {len(pairs)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['slug']}/IT (ISTAT {cfg['dataflow']}): {e}")
        return out


def run():
    p = IstatProvider()
    print(f"Fetching from {p.display_name}...")
    try:
        pts = p.fetch()
        print(f"\nTotal: {len(pts)} data points")
        rows = datapoints_to_rows(pts)
        total = 0
        for i in range(0, len(rows), 500):
            count = upsert_data_points(rows[i:i+500])
            total += count
        log_pipeline_run("istat", "success", total)
        print(f"\nDone. {total} rows upserted.")
    except Exception as e:
        log_pipeline_run("istat", "failed", error_message=str(e))
        print(f"\nFailed: {e}")
        raise


if __name__ == "__main__":
    run()
