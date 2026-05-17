"""CzsoProvider — Czech Statistical Office (V2 stateless).

Backend: data.csu.gov.cz/opendata/sady/{KOD}/distribuce/csv (open-data CSV).

Dispatcher ruft fetch_series(spec) pro data_series-Row.

SeriesSpec-Konventionen:
  - spec.series_id: CZSO-Tabellen-Code, optional mit Filter-Suffix
        Form A: "CEN0101E"                           (dataset only)
        Form B: "CZSO/CEN0101E"                      (prefixed)
        Form C: "CZSO/CEN0101E/COICOP=01"            (legacy slug-Suffix - ignored beim
                                                      Routing, der Filter steht in extra_params)
    Die echte Filterung läuft IMMER ueber extra_params.filter — der Suffix dient nur
    der menschlichen Lesbarkeit in data_series.fetch_series_id.

  - spec.extra_params:
      {
        "kod": "CEN0101E",                # optional override (sonst aus series_id)
        "filter": {                       # row-level Filter, exact match auf CSV-Spalten
          "IndicatorType": "6134",
          "CZCOICOP2.CZCOP1": "0",
          "CZCOICOP2.CZCOP23": "",
          "EKAKTIOCDS": "0",
          "UZ02P": "CZ",
          "TYPUDAJE4A": "IZ2025"
        },
        "date_col": "CASMKMQRM12",        # default-Such-Reihenfolge wenn fehlt: monthly_cols
        "value_col": "Hodnota",           # default 'Hodnota'
        "freq": "M"                       # explizit; sonst spec.freq_hint
      }

  - spec.freq_hint: 'M' | 'Q' | 'A'.
  - spec.conversion: Skalierungsfaktor.

Smoke (V1-Series, jetzt durch extra_params kodierbar):
  inflation-cpi: kod=CEN0101E, filter={IndicatorType=6134, CZCOICOP2.CZCOP1=0,
                  CZCOICOP2.CZCOP23="", EKAKTIOCDS=0, UZ02P=CZ, TYPUDAJE4A=IZ2025},
                  date_col=CASMKMQRM12, freq=M.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date

import requests

from pipeline.base_provider import (
    BaseProvider, SeriesSpec, Observation,
    ProviderError, TransientProviderError,
)
from pipeline.transforms import normalize_date
from pipeline.dispatcher import register_provider

BASE = "https://data.csu.gov.cz/opendata/sady"

HDR = {
    "User-Agent": "EconPulse/1.0 (Sebastian/SVM-AG)",
    "Accept": "text/csv,application/json",
}

MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")
QUARTER_RE = re.compile(r"^(\d{4})-Q([1-4])$")
YEAR_RE = re.compile(r"^(\d{4})$")

# Default date-column probe order pro Frequenz — CZSO uses a handful of column names.
DATE_COL_CANDIDATES = {
    "M": ["CASMKMQRM12", "CASMKMQR", "CasM", "CASRQM.CAS_M", "CasMQ", "CASMQ"],
    "Q": ["CasQ", "CASRQX", "CASQ"],
    "A": ["CasR", "CASR"],
}


# In-process CSV cache (selbe Tabelle wird oft fuer mehrere Filter geholt).
_CSV_CACHE: dict[str, list[dict]] = {}


def _fetch_csv(kod: str) -> list[dict]:
    if kod in _CSV_CACHE:
        return _CSV_CACHE[kod]
    url = f"{BASE}/{kod}/distribuce/csv"
    try:
        r = requests.get(url, headers=HDR, timeout=300)
    except (requests.ConnectionError, requests.Timeout) as e:
        raise TransientProviderError(f"czso network: {e}") from e
    if r.status_code >= 500:
        raise TransientProviderError(f"czso HTTP {r.status_code}")
    if r.status_code == 404:
        raise ProviderError(f"czso 404: dataset {kod} not found")
    if r.status_code != 200:
        raise ProviderError(f"czso HTTP {r.status_code}: {r.text[:200]}")
    r.encoding = "utf-8"
    rows = list(csv.DictReader(io.StringIO(r.text)))
    _CSV_CACHE[kod] = rows
    return rows


def _parse_date(s: str, freq: str) -> date | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        if freq == "M":
            m = MONTH_RE.match(s)
            if m:
                return date(int(m.group(1)), int(m.group(2)), 1)
        if freq == "Q":
            m = QUARTER_RE.match(s)
            if m:
                return date(int(m.group(1)),
                            {1: 1, 2: 4, 3: 7, 4: 10}[int(m.group(2))], 1)
        if freq == "A":
            m = YEAR_RE.match(s)
            if m:
                return date(int(m.group(1)), 1, 1)
        # generic fallbacks (cross-frequency robustness)
        if MONTH_RE.match(s):
            mm = MONTH_RE.match(s)
            return date(int(mm.group(1)), int(mm.group(2)), 1)
        if QUARTER_RE.match(s):
            mm = QUARTER_RE.match(s)
            return date(int(mm.group(1)),
                        {1: 1, 2: 4, 3: 7, 4: 10}[int(mm.group(2))], 1)
        if YEAR_RE.match(s):
            return date(int(s), 1, 1)
    except (ValueError, KeyError, IndexError):
        return None
    return None


def _row_matches(row: dict, flt: dict) -> bool:
    for k, v in flt.items():
        if row.get(k, "") != v:
            return False
    return True


def _resolve_kod(spec: SeriesSpec) -> str:
    """Resolve dataset code from extra_params.kod or series_id (with optional CZSO/ prefix
    and optional /suffix annotation)."""
    ep = spec.extra_params or {}
    kod = ep.get("kod")
    if kod:
        return kod
    sid = (spec.series_id or "").strip()
    if not sid:
        raise ProviderError("czso: series_id empty and extra_params.kod missing")
    # Strip leading "CZSO/" and trailing "/anything"
    s = sid
    if s.upper().startswith("CZSO/"):
        s = s[5:]
    if "/" in s:
        s = s.split("/", 1)[0]
    if ":" in s:
        s = s.split(":", 1)[0]
    if not s:
        raise ProviderError(f"czso: cannot derive kod from series_id '{sid}'")
    return s


def _resolve_date_col(rows: list[dict], freq: str, override: str | None) -> str | None:
    if override:
        return override
    if not rows:
        return None
    header = rows[0].keys()
    for cand in DATE_COL_CANDIDATES.get(freq, []):
        if cand in header:
            return cand
    # fallback: any column starting with "Cas" or "CAS"
    for c in header:
        if c.startswith(("Cas", "CAS")):
            return c
    return None


class CzsoProvider(BaseProvider):
    name = "czso"
    display_name = "Czech Statistical Office (CZSO)"

    def fetch_series(self, spec: SeriesSpec) -> list[Observation]:
        ep = spec.extra_params or {}
        kod = _resolve_kod(spec)
        freq = (ep.get("freq") or spec.freq_hint or "M").upper()
        flt = ep.get("filter") or {}
        value_col = ep.get("value_col") or "Hodnota"
        conv = spec.conversion or 1.0

        rows = _fetch_csv(kod)
        if not rows:
            return []

        date_col = _resolve_date_col(rows, freq, ep.get("date_col"))
        if not date_col:
            raise ProviderError(
                f"czso: cannot find date column for {kod} freq={freq}; "
                f"set extra_params.date_col"
            )

        out: list[Observation] = []
        for row in rows:
            if flt and not _row_matches(row, flt):
                continue
            dt = _parse_date(row.get(date_col, ""), freq)
            if not dt:
                continue
            raw = row.get(value_col, "")
            if raw in (None, ""):
                continue
            try:
                v = float(raw)
            except (TypeError, ValueError):
                continue
            out.append(Observation(date=normalize_date(dt, freq),
                                   value=round(v * conv, 6)))
        out.sort(key=lambda o: o.date)
        return out


try:
    register_provider(CzsoProvider())
except ProviderError as e:
    print(f"[warn] CzsoProvider not registered: {e}")
