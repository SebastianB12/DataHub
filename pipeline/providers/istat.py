"""IstatProvider — Italian National Institute of Statistics (V2 stateless).

Dispatcher ruft fetch_series(spec) pro data_series-Row. KEINE indicator/country/
source-Knowledge, keine Loops ueber Configs.

API: https://esploradati.istat.it/SDMXWS/rest/data — moderner SDMX-REST-Endpoint
(post-2023, ersetzt sdmx.istat.it). Kein API-Key.

NETZWERK-CAVEAT (siehe Git-Historie): esploradati.istat.it kann von manchen
Netzen aus refused werden (Firewall/Geofence). Provider behaelt 3-fach
Exponential-Retry; Dispatcher uebernimmt zusaetzlich Backoff bei
TransientProviderError.

SeriesSpec-Konventionen:
  - spec.series_id: Eine der folgenden Formen:
      a) "DATAFLOW"                 -> /IT1,DATAFLOW,1.0/all/ALL
      b) "DATAFLOW/KEY"             -> /IT1,DATAFLOW,1.0/KEY/ALL
      c) "IT1,DATAFLOW,1.0/KEY"     -> /IT1,DATAFLOW,1.0/KEY/ALL  (passthrough)
      d) "ISTAT/IT1,DATAFLOW,1.0[/KEY]"  -> legacy V1-Format, Praefix wird gestrippt
  - spec.extra_params optional, ueberschreibt series_id:
      {'dataflow': str, 'key': str, 'last_n': int, 'edition_dedup': bool, 'agency': str}
      - dataflow: Esploradati Dataflow-ID (z.B. "163_156" oder kuratiert "CPI")
      - key:      SDMX positional key-path (Dot-getrennt). Leer = /all/.
      - last_n:   lastNObservations Query-Param (Default 360)
      - edition_dedup: True fuer LFS-Flows mit EDI-Dimension (newest edition pro
        TIME_PERIOD gewinnt)
      - agency:   Default "IT1"
  - spec.freq_hint: 'M'|'Q'|'A' (steuert Datums-Parsing). Default 'M'.
  - spec.conversion: Skalierungsfaktor (z.B. 1e-6 fuer Persons -> Million).
"""
from __future__ import annotations

import csv
import io
import time
from datetime import date

import requests

from pipeline.base_provider import (
    BaseProvider, SeriesSpec, Observation,
    ProviderError, TransientProviderError,
)
from pipeline.transforms import normalize_date
from pipeline.dispatcher import register_provider

BASE_URL = "https://esploradati.istat.it/SDMXWS/rest/data"
REQUEST_TIMEOUT = 180  # seconds — ISTAT endpoint can be slow on first request
RETRY_ATTEMPTS = 3
DEFAULT_LAST_N = 360
DEFAULT_AGENCY = "IT1"

HDR = {
    "Accept": "application/vnd.sdmx.data+csv;version=1.0.0",
    "User-Agent": "EconPulse/0.1 (Sebastian/SVM-AG)",
}


def _split_series_id(series_id: str) -> tuple[str, str, str]:
    """Parse spec.series_id -> (agency, dataflow, key).

    Akzeptiert:
      - "DATAFLOW"
      - "DATAFLOW/KEY"
      - "AGENCY,DATAFLOW,VERSION[/KEY]"
      - "ISTAT/AGENCY,DATAFLOW,VERSION[/KEY]"  (legacy V1)
    Liefert key="" wenn nicht angegeben (-> /all/).
    """
    sid = (series_id or "").strip()
    if not sid:
        raise ProviderError("istat: empty series_id")

    # Strip legacy "ISTAT/" prefix
    if sid.upper().startswith("ISTAT/"):
        sid = sid.split("/", 1)[1]

    # Fall: "AGENCY,DATAFLOW,VERSION[/KEY]"
    if "," in sid:
        head, _, tail = sid.partition("/")
        parts = head.split(",")
        if len(parts) < 2:
            raise ProviderError(f"istat: cannot parse series_id '{series_id}'")
        agency = parts[0] or DEFAULT_AGENCY
        dataflow = parts[1]
        key = tail or ""
        return agency, dataflow, key

    # Fall: "DATAFLOW[/KEY]"
    if "/" in sid:
        df, _, key = sid.partition("/")
        return DEFAULT_AGENCY, df, key
    return DEFAULT_AGENCY, sid, ""


def _parse_period(p: str, freq: str) -> date | None:
    """Parse ISTAT TIME_PERIOD -> date. Formats: 'YYYY-MM', 'YYYY-Qn', 'YYYY'."""
    s = (p or "").strip()
    if not s:
        return None
    try:
        if freq == "M" and "-" in s and "-Q" not in s:
            yy, mm = s.split("-")
            return date(int(yy), int(mm), 1)
        if freq == "Q" and "-Q" in s:
            yy, q = s.split("-Q")
            return date(int(yy), {"1": 1, "2": 4, "3": 7, "4": 10}[q], 1)
        if freq == "A" and len(s) == 4:
            return date(int(s), 1, 1)
        # Generic fallbacks
        if "-Q" in s:
            yy, q = s.split("-Q")
            return date(int(yy), {"1": 1, "2": 4, "3": 7, "4": 10}[q], 1)
        if len(s) == 7 and "-" in s:
            yy, mm = s.split("-")
            return date(int(yy), int(mm), 1)
        if len(s) == 4:
            return date(int(s), 1, 1)
    except (ValueError, KeyError):
        pass
    return None


def _fetch_csv(url: str) -> str:
    """GET with retry. Each attempt uses REQUEST_TIMEOUT; back-off 5/15/45s.

    5xx + Timeouts + ConnectionErrors -> TransientProviderError.
    4xx -> ProviderError.
    """
    last_err: Exception | None = None
    for attempt in range(RETRY_ATTEMPTS):
        try:
            resp = requests.get(url, headers=HDR, timeout=REQUEST_TIMEOUT)
        except (requests.ConnectionError, requests.Timeout) as e:
            last_err = e
            if attempt == RETRY_ATTEMPTS - 1:
                raise TransientProviderError(f"istat network: {e}") from e
            time.sleep(5 * (3 ** attempt))
            continue

        if resp.status_code >= 500:
            last_err = TransientProviderError(f"istat HTTP {resp.status_code}")
            if attempt == RETRY_ATTEMPTS - 1:
                raise last_err
            time.sleep(5 * (3 ** attempt))
            continue
        if resp.status_code == 404:
            raise ProviderError(f"istat 404: {url}")
        if resp.status_code >= 400:
            raise ProviderError(
                f"istat HTTP {resp.status_code}: {resp.text[:200]}"
            )
        return resp.text

    if last_err:
        raise TransientProviderError(f"istat: {last_err}")
    return ""


def _parse_csv(text: str, freq: str,
               edition_dedup: bool = False) -> list[tuple[date, float]]:
    """Parse SDMX-CSV body -> [(date, value)].

    edition_dedup=True: bei LFS-Flows mit EDI/EDITION-Dim die neueste Edition
    pro TIME_PERIOD waehlen.
    """
    reader = csv.DictReader(io.StringIO(text))
    if edition_dedup:
        best: dict[date, tuple[str, float]] = {}
        for row in reader:
            per = row.get("TIME_PERIOD", "")
            val = row.get("OBS_VALUE", "")
            edi = row.get("EDI", "") or row.get("EDITION", "")
            if not per or val in ("", None):
                continue
            try:
                v = float(val)
            except (ValueError, TypeError):
                continue
            dt = _parse_period(per, freq)
            if not dt:
                continue
            prev = best.get(dt)
            if prev is None or edi > prev[0]:
                best[dt] = (edi, v)
        return sorted((d, v) for d, (_, v) in best.items())

    out: list[tuple[date, float]] = []
    for row in reader:
        per = row.get("TIME_PERIOD", "")
        val = row.get("OBS_VALUE", "")
        if not per or val in ("", None):
            continue
        try:
            v = float(val)
        except (ValueError, TypeError):
            continue
        dt = _parse_period(per, freq)
        if dt:
            out.append((dt, v))
    return sorted(out)


class IstatProvider(BaseProvider):
    name = "istat"
    display_name = "ISTAT"

    def fetch_series(self, spec: SeriesSpec) -> list[Observation]:
        ep = spec.extra_params or {}

        # Agency/Dataflow/Key aufloesen: extra_params > series_id-Parsing.
        agency = ep.get("agency") or DEFAULT_AGENCY
        dataflow = ep.get("dataflow")
        key = ep.get("key")

        if not dataflow:
            ag_parsed, df_parsed, key_parsed = _split_series_id(spec.series_id)
            agency = ep.get("agency") or ag_parsed
            dataflow = df_parsed
            if key is None:
                key = key_parsed
        if key is None:
            key = ""

        if not dataflow:
            raise ProviderError("istat: dataflow missing (series_id or extra_params.dataflow)")

        edition_dedup = bool(ep.get("edition_dedup", False))
        last_n = int(ep.get("last_n") or DEFAULT_LAST_N)

        # URL bauen — leerer Key -> /all/ALL (kompletter Dataflow)
        if key:
            url = f"{BASE_URL}/{agency},{dataflow},1.0/{key}/ALL?lastNObservations={last_n}"
        else:
            url = f"{BASE_URL}/{agency},{dataflow},1.0/all/ALL"

        text = _fetch_csv(url)

        freq = spec.freq_hint or "M"
        pairs = _parse_csv(text, freq, edition_dedup=edition_dedup)

        conv = spec.conversion or 1.0
        out: list[Observation] = []
        for dt, value in pairs:
            try:
                v = round(float(value) * conv, 6)
            except (ValueError, TypeError):
                continue
            out.append(Observation(date=normalize_date(dt, freq), value=v))
        return out


try:
    register_provider(IstatProvider())
except ProviderError as e:
    print(f"[warn] IstatProvider not registered: {e}")
