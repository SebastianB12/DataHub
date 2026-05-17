"""StatecProvider — STATEC Luxembourg national statistics (V2 stateless).

Dispatcher ruft fetch_series(spec) pro data_series-Row.

API: https://lustat.statec.lu/rest/data/LU1,{DATAFLOW},{VERSION}/all/ALL
(SDMX REST v8.x, .Stat Suite — same platform that ISTAT uses on esploradati.istat.it)
Accept: application/vnd.sdmx.data+csv;version=1.0.0
Kein API-Key.

SeriesSpec-Konventionen:
  - spec.series_id: STATEC SDMX-Key in einer der folgenden Formen:
      "STATEC/LU1,DSD_ECOICOP_PRIX@DF_E5405,1.0#FREQ=M,ECOICOP_2018=CP00"
      "STATEC/LU1,DF_E4202,1.0#B-CA"   (Kurzform: '-'-separated key)
      "LU1,DF_E4202,1.0"                (ohne Filter)
      "DF_E4202,1.0"                     (Agency LU1 angenommen)
    Filter werden hinter '#' angegeben — entweder
       - 'DIM=VAL,DIM=VAL,...'  (explizite Filter), oder
       - 'TOKEN-TOKEN-...'      (Positions-Key wie in SDMX-URLs)
    Die explizite Form wird bevorzugt. Beide Formen filtern client-side die CSV.
  - spec.extra_params optional:
      {'dataflow': str, 'version': str, 'agency': str,
       'filter': {DIM: VAL, ...},     # explizite Filter (ueberschreiben series_id)
       'params': {...}}               # ggf. URL-Query-Params
  - spec.freq_hint: 'M' | 'Q' | 'A'.
  - spec.conversion: Skalierungsfaktor.
"""
from __future__ import annotations

import csv
import io
from datetime import date

import requests

from pipeline.base_provider import (
    BaseProvider, SeriesSpec, Observation,
    ProviderError, TransientProviderError,
)
from pipeline.transforms import normalize_date
from pipeline.dispatcher import register_provider

BASE_URL = "https://lustat.statec.lu/rest/data"

HDR = {
    "Accept": "application/vnd.sdmx.data+csv;version=1.0.0",
    "User-Agent": "EconPulse/0.1 (Sebastian/SVM-AG)",
}


def _parse_series_id(series_id: str) -> tuple[str, str, str, dict | None, list[str] | None]:
    """Parse STATEC series_id forms -> (agency, dataflow, version, filter_dict, key_tokens).

    Forms accepted:
      - 'STATEC/LU1,DF_E4202,1.0#B-CA'
      - 'STATEC/LU1,DSD_X@DF_E5405,1.0#FREQ=M,ECOICOP_2018=CP00'
      - 'LU1,DF_E4202,1.0#...'
      - 'DF_E4202,1.0'                  (agency=LU1 default)

    Returns:
        agency, dataflow, version, filter_dict (or None), key_tokens (or None).
    """
    sid = (series_id or "").strip()
    if not sid:
        raise ProviderError("statec: empty series_id")

    head, _, tail = sid.partition("#")
    # Strip leading 'STATEC/' prefix if present
    if head.upper().startswith("STATEC/"):
        head = head[len("STATEC/"):]

    parts = [p.strip() for p in head.split(",")]
    if len(parts) == 3:
        agency, dataflow, version = parts
    elif len(parts) == 2:
        agency = "LU1"
        dataflow, version = parts
    else:
        raise ProviderError(f"statec: cannot parse series_id head '{head}'")

    if not agency:
        agency = "LU1"

    filter_dict: dict | None = None
    key_tokens: list[str] | None = None
    if tail:
        if "=" in tail:
            filter_dict = {}
            for kv in tail.split(","):
                kv = kv.strip()
                if not kv or "=" not in kv:
                    continue
                k, _, v = kv.partition("=")
                filter_dict[k.strip()] = v.strip()
        else:
            # Positions-Key: 'B-CA' oder 'M.CP00' -> Tokens
            key_tokens = [t for t in tail.replace(".", "-").split("-") if t != ""]

    return agency, dataflow, version, filter_dict, key_tokens


def _parse_period(p: str, freq: str) -> date | None:
    """SDMX TIME_PERIOD parser. Supports M/Q/A and ISO (YYYY-MM-DD)."""
    s = (p or "").strip()
    if not s:
        return None
    try:
        if freq == "M" and "-" in s and len(s) == 7:
            yy, mm = s.split("-")
            return date(int(yy), int(mm), 1)
        if freq == "Q" and "-Q" in s:
            yy, q = s.split("-Q")
            return date(int(yy), {"1": 1, "2": 4, "3": 7, "4": 10}[q], 1)
        if freq == "A":
            if len(s) == 4 and s.isdigit():
                return date(int(s), 1, 1)
            if len(s) == 10 and s[4] == "-":
                yy, mm, dd = s.split("-")
                return date(int(yy), int(mm), int(dd))
        # generic fallbacks
        if len(s) == 7 and "-" in s:
            yy, mm = s.split("-")
            return date(int(yy), int(mm), 1)
        if "-Q" in s:
            yy, q = s.split("-Q")
            return date(int(yy), {"1": 1, "2": 4, "3": 7, "4": 10}[q], 1)
        if len(s) == 4 and s.isdigit():
            return date(int(s), 1, 1)
        if len(s) == 10 and s[4] == "-":
            return date.fromisoformat(s)
    except (ValueError, KeyError, IndexError):
        return None
    return None


def _fetch_csv(agency: str, dataflow: str, version: str,
               params: dict | None = None) -> list[dict]:
    """GET STATEC SDMX-CSV. Returns list of DictReader-Rows."""
    url = f"{BASE_URL}/{agency},{dataflow},{version}/all/ALL"
    query = dict(params or {})
    try:
        resp = requests.get(url, headers=HDR, params=query, timeout=180)
    except (requests.ConnectionError, requests.Timeout) as e:
        raise TransientProviderError(f"statec network: {e}") from e
    if resp.status_code >= 500:
        raise TransientProviderError(f"statec HTTP {resp.status_code}")
    if resp.status_code == 404:
        raise ProviderError(f"statec 404: {agency},{dataflow},{version}")
    if resp.status_code != 200:
        raise ProviderError(f"statec HTTP {resp.status_code}: {resp.text[:200]}")

    reader = csv.DictReader(io.StringIO(resp.text))
    return list(reader)


def _row_matches_filter(row: dict, flt: dict) -> bool:
    for k, v in flt.items():
        if row.get(k) != v:
            return False
    return True


def _dim_cols(fieldnames: list[str], freq_hint: str | None = None) -> list[str]:
    """Return SDMX dimension columns from a CSV header.

    Skips structural metadata (DATAFLOW, STRUCTURE*, ACTION),
    measure columns (TIME_PERIOD, OBS_VALUE, OBS_STATUS, OBS_*, DECIMALS,
    UNIT_MULT, UNIT_MEASURE), and any NOTE_* attribute columns.
    """
    skip = {"DATAFLOW", "STRUCTURE", "STRUCTURE_ID", "STRUCTURE_NAME", "ACTION",
            "TIME_PERIOD", "OBS_VALUE", "OBS_STATUS", "UNIT_MULT",
            "DECIMALS", "UNIT_MEASURE", "CONF_STATUS", "OBS_COMMENT"}
    cols = []
    for c in fieldnames:
        if not c:
            continue
        if c in skip:
            continue
        if c.startswith("NOTE_") or c.startswith("OBS_"):
            continue
        cols.append(c)
    return cols


def _row_matches_key_tokens(row: dict, tokens: list[str], dim_cols: list[str]) -> bool:
    """Match by ordered token list against the SDMX dimension columns.

    Supports two alignments:
      1. Tokens map 1:1 to dim_cols starting at index 0 (covers FREQ).
      2. Tokens map starting after FREQ (i.e. dim_cols[1:]), which is the
         conventional SDMX positional key form (FREQ separately specified).
    """
    if not tokens or not dim_cols:
        return False
    # Try alignment WITHOUT FREQ (most common — key is DIM2.DIM3...)
    if "FREQ" in dim_cols:
        after_freq = [c for c in dim_cols if c != "FREQ"]
        if len(tokens) == len(after_freq):
            return all(row.get(col) == tok for tok, col in zip(tokens, after_freq))
    # Fall back: full alignment from position 0
    if len(tokens) == len(dim_cols):
        return all(row.get(col) == tok for tok, col in zip(tokens, dim_cols))
    # Prefix alignment (tokens cover the first N dims)
    if len(tokens) < len(dim_cols):
        return all(row.get(col) == tok for tok, col in zip(tokens, dim_cols))
    return False


class StatecProvider(BaseProvider):
    name = "statec_lu"
    display_name = "STATEC Luxembourg"

    def fetch_series(self, spec: SeriesSpec) -> list[Observation]:
        ep = spec.extra_params or {}

        # Auflösung der SDMX-Koordinaten: extra_params überschreibt series_id
        agency = ep.get("agency")
        dataflow = ep.get("dataflow")
        version = ep.get("version")
        filter_dict = ep.get("filter")
        key_tokens: list[str] | None = None

        if not (dataflow and version):
            a, df, ver, flt, toks = _parse_series_id(spec.series_id or "")
            agency = agency or a
            dataflow = dataflow or df
            version = version or ver
            if filter_dict is None and flt:
                filter_dict = flt
            if toks:
                key_tokens = toks

        if not agency:
            agency = "LU1"
        if not (dataflow and version):
            raise ProviderError(f"statec: dataflow/version missing (series_id='{spec.series_id}')")

        params = ep.get("params") or None
        rows = _fetch_csv(agency, dataflow, version, params=params)
        if not rows:
            return []

        fieldnames = list(rows[0].keys())
        dim_cols = _dim_cols(fieldnames)

        # Filter-Pfad bestimmen
        use_filter = bool(filter_dict)
        use_key = bool(key_tokens) and not use_filter

        freq = spec.freq_hint or (filter_dict or {}).get("FREQ") or "M"
        conv = spec.conversion or 1.0

        out: list[Observation] = []
        for row in rows:
            if use_filter and not _row_matches_filter(row, filter_dict):
                continue
            if use_key:
                if not _row_matches_key_tokens(row, key_tokens, dim_cols):
                    continue
                # Also enforce FREQ when freq_hint set & FREQ column exists
                if "FREQ" in dim_cols and spec.freq_hint and row.get("FREQ") != spec.freq_hint:
                    continue
            per = row.get("TIME_PERIOD", "")
            val = row.get("OBS_VALUE", "")
            if not per or val in ("", None):
                continue
            try:
                v = float(val)
            except (ValueError, TypeError):
                continue
            dt = _parse_period(per, freq)
            if not dt:
                continue
            out.append(Observation(date=normalize_date(dt, freq),
                                   value=round(v * conv, 6)))
        out.sort(key=lambda o: o.date)
        return out


try:
    register_provider(StatecProvider())
except ProviderError as e:
    print(f"[warn] StatecProvider not registered: {e}")
