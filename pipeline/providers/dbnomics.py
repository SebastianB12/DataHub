"""DBnomics-based universal national-source provider.

DBnomics (https://db.nomics.world) is a free aggregator that mirrors many
national stat offices and central banks (ISTAT, INEPT, CSO, NBB, ELSTAT,
SCB, STATPOL, etc.) with often fresher data than the source's own SDMX
endpoints. We use it as a unified gateway.

Each `indicator_sources` row with source = one of {'istat','inept','cso_ie',
'nbb','elstat','scb','statpol',...} carries `extra_params`:

    {
      "provider": "ISTAT",        # DBnomics provider code
      "dataset":  "115_333_DF_DCSC_INDXPRODIND_1_6",
      "series":   "M.IT.IND_PROD_21.N.0020",
      "freq":     "M"
    }

The provider fetches `https://api.db.nomics.world/v22/series/<provider>/<dataset>/<series>?observations=1`,
parses periods + values and writes data_points with the canonical source code.
"""
import os
import time
from datetime import date

import requests
from dotenv import load_dotenv

from pipeline.base_provider import BaseProvider, DataPoint
from pipeline.transforms import normalize_date
from pipeline.db import (
    upsert_data_points, log_pipeline_run, datapoints_to_rows, load_series_config
)

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

BASE_URL = "https://api.db.nomics.world/v22/series"

# DBnomics-served sources we support. Maps our internal `source` code to DBnomics provider.
SOURCE_TO_DBNOMICS = {
    "istat":      "ISTAT",
    "inept":      "INEPT",
    "cso_ie":     "CSO",
    "nbb":        "NBB",
    "elstat":     "ELSTAT",
    "scb":        "SCB",
    "statpol":    "STATPOL",
    "ine_es_db":  "INE-SPAIN",   # alternative path, only if INE Tempus3 unavailable
    "buba_db":    "BUBA",
}


def _parse_period(p: str, freq: str) -> date | None:
    try:
        if freq == "M" and "-" in p:
            yy, mm = p.split("-")
            return date(int(yy), int(mm), 1)
        if freq == "Q" and "Q" in p:
            yy, q = p.split("-Q") if "-Q" in p else p.split("Q")
            month = {"1": 1, "2": 4, "3": 7, "4": 10}[q]
            return date(int(yy), month, 1)
        if freq == "A" and len(p) == 4:
            return date(int(p), 1, 1)
        if len(p) == 10:  # YYYY-MM-DD daily
            return date.fromisoformat(p)
    except Exception:
        return None
    return None


def _fetch_series(provider: str, dataset: str, series: str) -> tuple[list[str], list]:
    url = f"{BASE_URL}/{provider}/{dataset}/{series}?observations=1"
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    docs = data.get("series", {}).get("docs", [])
    if not docs:
        return [], []
    s = docs[0]
    return s.get("period", []), s.get("value", [])


class DbnomicsProvider(BaseProvider):
    name = "dbnomics"
    display_name = "DBnomics gateway (national stat offices)"

    def fetch(self) -> list[DataPoint]:
        out: list[DataPoint] = []
        # Load all rows whose source is one of our DBnomics-served codes
        for source_code in SOURCE_TO_DBNOMICS:
            try:
                cfgs = load_series_config(source_code)
            except Exception:
                continue
            if not cfgs:
                continue
            for cfg in cfgs:
                ep = cfg.get("extra_params") or {}
                provider = ep.get("provider") or SOURCE_TO_DBNOMICS[source_code]
                dataset = ep.get("dataset")
                series_key = ep.get("series")
                if not dataset or not series_key:
                    print(f"  SKIP {cfg['indicator']}/{cfg['country']} ({source_code}): missing dataset/series in extra_params")
                    continue
                freq = cfg.get("freq_hint") or ep.get("freq") or "M"
                conv = float(cfg.get("conversion") or 1)
                try:
                    periods, values = _fetch_series(provider, dataset, series_key)
                    n = 0
                    for p, v in zip(periods, values):
                        if v is None or v == "NA":
                            continue
                        try:
                            num = float(v) * conv
                        except (TypeError, ValueError):
                            continue
                        dt = _parse_period(p, freq)
                        if not dt:
                            continue
                        out.append(DataPoint(
                            indicator=cfg["indicator"],
                            country=cfg["country"],
                            date=normalize_date(dt, freq),
                            value=round(num, 4),
                            source=source_code,
                            unit=cfg.get("unit") or "",
                            series_id=f"{provider}/{dataset}/{series_key}",
                            adjustment=cfg.get("adjustment") or "",
                        ))
                        n += 1
                    print(f"  OK {cfg['indicator']}/{cfg['country']} ({source_code} {dataset}): {n} pts")
                    # Be polite: 250ms between requests
                    time.sleep(0.25)
                except Exception as e:
                    print(f"  FAIL {cfg['indicator']}/{cfg['country']} ({source_code}): {e}")
        return out


def run():
    p = DbnomicsProvider()
    print(f"Fetching from {p.display_name}...")
    try:
        pts = p.fetch()
        print(f"\nTotal: {len(pts)} data points")
        rows = datapoints_to_rows(pts)
        total = 0
        for i in range(0, len(rows), 500):
            count = upsert_data_points(rows[i:i+500])
            total += count
        log_pipeline_run("dbnomics", "success", total)
        print(f"\nDone. {total} rows upserted.")
    except Exception as e:
        log_pipeline_run("dbnomics", "failed", error_message=str(e))
        print(f"\nFailed: {e}")
        raise


if __name__ == "__main__":
    run()
