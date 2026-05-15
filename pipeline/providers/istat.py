"""ISTAT direct provider — modern Esploradati endpoint (post-2023 platform).

Uses esploradati.istat.it/SDMXWS/rest — the new SDMX REST web service that
replaced the legacy sdmx.istat.it endpoint (which had read timeouts on most
requests). The new endpoint is stable and returns fresh data.

NETWORK CAVEAT (2026-05-15): esploradati.istat.it (193.204.90.13) refuses TCP
connections on 80/443/8443/8080 from this network — appears to be an ISTAT-side
firewall or geofence. sdmx.istat.it (193.204.90.1) and www.istat.it
(193.204.90.61) on the same /24 are reachable. The provider keeps the modern
URL pattern + a 3-attempt exponential retry; once network access is restored
the new SERIES entries activate automatically.

Confirmed curated dataflows (IT1, all version 1.0):
  CPI    Consumer Price Index (PCPI_IX, base 2025=100, monthly)
  PPI    Producer Price Index (PPPI_IX, base 2021=100, monthly)
  IND    Industrial production index (AIP_SA_IX, SA, monthly)
  UEM    Unemployment (LU_PE_SA_NUM, thousand persons, quarterly)
  EMP    Employment (LE_PE_SA_NUM, thousand persons, quarterly)
  POP    Population (LP_PE_NUM, annual)
  WOE    Index of contractual hourly earnings (LCEAI_H_IX, monthly)

URL pattern:
  https://esploradati.istat.it/SDMXWS/rest/data/IT1,{DATAFLOW},1.0/all/ALL
  Accept: application/vnd.sdmx.data+csv;version=1.0.0

CSV schema:
  DATAFLOW,DATA_DOMAIN,REF_AREA,INDICATOR,COUNTERPART_AREA,FREQ,TIME_PERIOD,
  OBS_VALUE,COMMENT,BASE_PER,UNIT_MULT,OBS_STATUS,TIME_FORMAT
"""
import os
import csv
import io
import time
from datetime import date

import requests
from dotenv import load_dotenv

from pipeline.base_provider import BaseProvider, DataPoint
from pipeline.transforms import normalize_date
from pipeline.db import upsert_data_points, log_pipeline_run, datapoints_to_rows

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

BASE = "https://esploradati.istat.it/SDMXWS/rest/data"
REQUEST_TIMEOUT = 180  # seconds — ISTAT endpoint can be slow on first request
RETRY_ATTEMPTS = 3

# SERIES entries support two forms:
#   1. "dataflow": curated short ID resolved server-side via the /all/ALL path
#      (used for the legacy curated CPI/PPI/IND/etc. flows).
#   2. "dataflow_full" + "filter_key": full Esploradati SDMX dataflow ID with a
#      key-path filter (positional SDMX dimensions, dot-separated). This narrows
#      the response so large flows like the confidence indicators stay fast.
SERIES = [
    {"slug": "inflation-cpi",         "dataflow": "CPI", "freq": "M", "unit": "Index", "adjustment": "NSA",
     "conversion": 1.0, "note": "ISTAT modern Esploradati CPI (PCPI_IX, base 2025=100)"},
    {"slug": "ppi",                   "dataflow": "PPI", "freq": "M", "unit": "Index", "adjustment": "NSA",
     "conversion": 1.0, "note": "ISTAT modern Esploradati PPI (PPPI_IX, base 2021=100)"},
    {"slug": "industrial-production", "dataflow": "IND", "freq": "M", "unit": "Index", "adjustment": "SA",
     "conversion": 1.0, "note": "ISTAT modern Esploradati IP (AIP_SA_IX seasonally adjusted)"},
    {"slug": "unemployed-persons",    "dataflow": "UEM", "freq": "Q", "unit": "Thousand", "adjustment": "SA",
     "conversion": 1.0, "note": "ISTAT modern Esploradati Unemployed (LU_PE_SA_NUM)"},
    {"slug": "employed-persons",      "dataflow": "EMP", "freq": "Q", "unit": "Thousand", "adjustment": "SA",
     "conversion": 1.0, "note": "ISTAT modern Esploradati Employed (LE_PE_SA_NUM)"},
    {"slug": "population",            "dataflow": "POP", "freq": "A", "unit": "Million", "adjustment": "NSA",
     "conversion": 1e-6, "note": "ISTAT modern Esploradati Population (LP_PE_NUM)"},
    # Consumer confidence — raw climate dataflow; only COF_21_WE.N is currently
    # published (weighted-estimate raw, base 2021=100). FIDCONS_10 SA stops at 2020.
    {"slug": "consumer-confidence",   "dataflow_full": "30_264_DF_DCSC_FIDCONS_1",
     "filter_key": "M.IT.COF_21_WE.N.....", "freq": "M", "unit": "Index (2021=100)",
     "adjustment": "NSA", "conversion": 1.0,
     "note": "ISTAT raw climate, consumer confidence indicator (COF_21_WE, weighted)"},
    # Business confidence (manufacturing) — SA climate dataflow (FIDIMPRMAN_17),
    # CLIMAMAN_21 with ADJUSTMENT=Y, NACE=C (manufacturing total), all firm sizes.
    {"slug": "business-confidence",   "dataflow_full": "111_263_DF_DCSC_FIDIMPRMAN_17",
     "filter_key": "M.IT.CLIMAMAN_21.Y.C.TOTAL", "freq": "M", "unit": "Index (2021=100)",
     "adjustment": "SA", "conversion": 1.0,
     "note": "ISTAT SA climate, mfg confidence (CLIMAMAN_21, NACE C)"},
    # ---- TE-conformity gap-fill (verified 2026-05-15) -------------------------
    # Core CPI (HICP excl. energy + unprocessed food, base 2015=100).
    # Dim order: FREQ.REF_AREA.DATA_TYPE.MEASURE.E_COICOP_REV_ISTAT.
    # DATA_TYPE=41 (index level), MEASURE=4, COICOP=00XEFOODUNP.
    {"slug": "core-cpi",              "dataflow_full": "168_760_DF_DCSP_IPCA1B2015_1",
     "filter_key": "M.IT.41.4.00XEFOODUNP", "freq": "M", "unit": "Index (2015=100)",
     "adjustment": "NSA", "conversion": 1.0,
     "note": "ISTAT HICP excl. energy & unprocessed food (core CPI) base 2015=100"},
    # Unemployment rate (LFS monthly, total 15-74, both sexes, latest edition).
    # Verified 2026-05-15: 2026-03 = 5.48 %.
    {"slug": "unemployment",          "dataflow_full": "151_874_DF_DCCV_TAXDISOCCUMENS1_1",
     "filter_key": "M.IT.UNEM_R.N.9.Y15-74.", "freq": "M", "unit": "%",
     "adjustment": "NSA", "conversion": 1.0,
     "note": "ISTAT LFS Unemployment Rate 15-74 both sexes monthly NSA",
     "edition_dedup": True},
    # Exports — Foreign Trade by country & commodity, total goods to WORLD,
    # NSA value (EV) in millions of EUR.
    # Dim order: FREQ.REF_AREA.DATA_TYPE.CPA_ATECO2007_COE.PARTNER_COUNTRY.
    # Verified 2026-05-15: 2026-02 = 53,764 EUR mn (matches TE exactly).
    {"slug": "exports",               "dataflow_full": "139_176",
     "filter_key": "M.ITTOT.EV.0010.WORLD", "freq": "M", "unit": "EUR million",
     "adjustment": "NSA", "conversion": 1.0,
     "note": "ISTAT Foreign Trade total exports to World (NSA, EUR mn)"},
    # Imports — same dataflow, total goods from WORLD.
    # Verified 2026-05-15: 2026-02 = 48,821 EUR mn (matches TE exactly).
    {"slug": "imports",               "dataflow_full": "139_176",
     "filter_key": "M.ITTOT.IV.0010.WORLD", "freq": "M", "unit": "EUR million",
     "adjustment": "NSA", "conversion": 1.0,
     "note": "ISTAT Foreign Trade total imports from World (NSA, EUR mn)"},
    # ---- Deferred (provider entries removed 2026-05-15) -----------------------
    # food-inflation, services-inflation, energy-inflation:
    #   168_760_DF_DCSP_IPCA1B2015_1 only publishes DATA_TYPE=41 (index level).
    #   YoY rates by COICOP not in this flow; would need on-the-fly compute
    #   from index series. Remains on eurostat default until separate
    #   COICOP-by-COICOP index ingest + transform is added.
    # employment-rate: 150_872_DF_DCCV_TAXOCCUMENS1_1 reads time out (~120s)
    #   from current Esploradati path even with filter_key — large series. Try
    #   smaller `lastNObservations` or alt dataflow on next iteration.
    # manufacturing-production, mining-production: 115_333_DF_DCSC_INDXPRODIND_1_1
    #   is stale (latest 2023-12). Modern flow ID TBD.
    # budget-deficit, government-debt-total: 95_42_DF_DCCN_FPQ_2 has 9 dims
    #   (DATA_TYPE_AGGR, NONFIN_ASSETS, VALUATION, ADJUSTMENT, INSTITUTIONAL_SECTOR,
    #   EXPEND_PURPOSE, EDITION); 4-dim filter returns 404. Needs full dim probe.
]

HDR = {
    "Accept": "application/vnd.sdmx.data+csv;version=1.0.0",
    "User-Agent": "EconPulse/0.1 (Sebastian/SVM-AG)",
}


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


def _fetch(dataflow: str, freq: str) -> list[tuple[date, float]]:
    url = f"{BASE}/IT1,{dataflow},1.0/all/ALL"
    return _fetch_url(url, freq)


def _fetch_filtered(dataflow_full: str, filter_key: str, freq: str,
                    last_n: int = 360, edition_dedup: bool = False) -> list[tuple[date, float]]:
    """Fetch a single SDMX series via positional key-path filter.

    `filter_key` is the dot-separated SDMX key (e.g. ``M.IT.CLIMAMAN_21.Y.C.TOTAL``).
    Wildcards are empty between dots; trailing dots wildcard tail dimensions.

    `edition_dedup=True` enables EDI-aware aggregation for LFS series
    (150_872, 151_874): the SDMX flow stores one series per publication date
    (e.g. ``2026M3G4`` = edition March 4, 2026). For each TIME_PERIOD we keep
    the value from the most recent EDI code.
    """
    url = f"{BASE}/IT1,{dataflow_full},1.0/{filter_key}/ALL?lastNObservations={last_n}"
    return _fetch_url(url, freq, edition_dedup=edition_dedup)


def _fetch_url(url: str, freq: str, edition_dedup: bool = False) -> list[tuple[date, float]]:
    """GET with retry. Each attempt uses REQUEST_TIMEOUT; back-off 5/15/45s."""
    last_err: Exception | None = None
    for attempt in range(RETRY_ATTEMPTS):
        try:
            r = requests.get(url, headers=HDR, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            break
        except (requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
                requests.exceptions.HTTPError) as e:
            last_err = e
            if attempt == RETRY_ATTEMPTS - 1:
                raise
            time.sleep(5 * (3 ** attempt))
    else:
        if last_err:
            raise last_err
    if edition_dedup:
        # Track newest EDI per TIME_PERIOD, then collapse.
        reader = csv.DictReader(io.StringIO(r.text))
        best: dict[date, tuple[str, float]] = {}
        for row in reader:
            per = row.get("TIME_PERIOD", "")
            val = row.get("OBS_VALUE", "")
            edi = row.get("EDI", "") or row.get("EDITION", "")
            if not per or not val:
                continue
            try:
                v = float(val)
            except ValueError:
                continue
            dt = _parse_period(per, freq)
            if not dt:
                continue
            prev = best.get(dt)
            if prev is None or edi > prev[0]:
                best[dt] = (edi, v)
        return sorted((d, v) for d, (_, v) in best.items())
    reader = csv.DictReader(io.StringIO(r.text))
    out = []
    for row in reader:
        per = row.get("TIME_PERIOD", "")
        val = row.get("OBS_VALUE", "")
        if not per or not val:
            continue
        try:
            v = float(val)
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
            if "dataflow_full" in cfg:
                df_id = cfg["dataflow_full"]
                series_id = f"ISTAT/IT1,{df_id},1.0/{cfg['filter_key']}"
                fetcher = lambda c=cfg: _fetch_filtered(
                    c["dataflow_full"], c["filter_key"], c["freq"],
                    edition_dedup=c.get("edition_dedup", False),
                )
            else:
                df_id = cfg["dataflow"]
                series_id = f"ISTAT/IT1,{df_id},1.0"
                fetcher = lambda c=cfg: _fetch(c["dataflow"], c["freq"])
            try:
                pairs = fetcher()
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"], country="IT",
                        date=normalize_date(dt, cfg["freq"]),
                        value=round(v * cfg["conversion"], 4),
                        source="istat",
                        unit=cfg["unit"],
                        series_id=series_id,
                        adjustment=cfg["adjustment"],
                    ))
                print(f"  OK {cfg['slug']}/IT (ISTAT {df_id}): {len(pairs)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['slug']}/IT (ISTAT {df_id}): {e}")
        return out


def run():
    p = IstatProvider()
    print(f"Fetching from {p.display_name} (Esploradati)...")
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
