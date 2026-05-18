"""NationalbankenProvider — Danmarks Nationalbank Statbank (V2 stateless).

TE-Primärquelle für DK Interest Rate. Sebastian-Direktive: Primary Source.

API:
  Base:    https://api.statbank.dk/v1
  POST:    POST /data  body={table, format:BULK, lang:en, variables:[{code,values}]}
           (BULK liefert die ganze Reihe als Semicolon-CSV. Wildcard Tid=*
           funktioniert nur über POST/BULK; GET-CSV mit Tid=* timed out.)
  Auth:    keine
  Format:  Semicolon-CSV mit Header.

DNRENTD (Interest rates by instrument/country/methodology) — Pflichtdimensionen:
  INSTRUMENT, LAND, OPGOER, Tid

Relevante INSTRUMENT-Codes (Auswahl):
  ODKNAA -> Discount rate (Aug 1987-)        — TE-Quelle für DK Interest Rate
  OFONAA -> Current-account deposits (Aug 1987-)
  OIRNAA -> Lending rate (Jan 1992-)
  OIBNAA -> Certificates of deposit (Jan 1992-)

Series-ID-Format: 'TABLE:INSTRUMENT' (z.B. 'DNRENTD:ODKNAA').
Alternativ über extra_params: {"table":"DNRENTD","instrument":"ODKNAA","land":"DK","opgoer":"E"}.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import date

import requests

from pipeline.base_provider import (
    BaseProvider, SeriesSpec, Observation,
    ProviderError, TransientProviderError,
)
from pipeline.dispatcher import register_provider


BASE_URL = "https://api.statbank.dk/v1"
USER_AGENT = "EconPulse/1.0 (macroeconomic data pipeline)"


def _parse_dst_period(s: str) -> date | None:
    """DST-Period-Codes: 2026M05D08 (daily), 2026M05 (monthly), 2026Q1, 2026.

    Daily: YYYY 'M' MM 'D' DD
    """
    s = (s or "").strip()
    if not s:
        return None
    try:
        if "M" in s and "D" in s:
            # Daily: 2026M05D08
            y = int(s[:4]); rest = s[4:]
            month = int(rest.split("M")[1].split("D")[0])
            day = int(rest.split("D")[1])
            return date(y, month, day)
        if "Q" in s:
            y, q = s.split("Q")
            return date(int(y), {"1":1,"2":4,"3":7,"4":10}[q], 1)
        if "M" in s:
            y, m = s.split("M")
            return date(int(y), int(m), 1)
        if len(s) == 4 and s.isdigit():
            return date(int(s), 1, 1)
    except (ValueError, KeyError, IndexError):
        return None
    return None


def _resolve_body(spec: SeriesSpec) -> dict:
    """Bestimmt den POST-Body für /v1/data BULK-Fetch aus spec."""
    ep = spec.extra_params or {}
    table = ep.get("table")
    instrument = ep.get("instrument")

    if not (table and instrument):
        sid = (spec.series_id or "").strip()
        if ":" in sid:
            table, instrument = sid.split(":", 1)
        else:
            raise ProviderError(
                f"nationalbanken: cannot parse series_id '{sid}' "
                "(expected 'TABLE:INSTRUMENT' or extra_params.table+instrument)"
            )

    body = {
        "table": table,
        "format": "BULK",
        "lang": "en",
        "variables": [
            {"code": "INSTRUMENT", "values": [instrument]},
            {"code": "LAND",       "values": [ep.get("land",   "DK")]},
            {"code": "OPGOER",     "values": [ep.get("opgoer", "E")]},
            {"code": "Tid",        "values": [ep.get("tid",    "*")]},
        ],
    }
    return body


def _http_post(url: str, body: dict, retries: int = 3) -> requests.Response:
    last_exc: BaseException | None = None
    for attempt in range(retries):
        try:
            resp = requests.post(
                url, data=json.dumps(body),
                headers={"User-Agent": USER_AGENT,
                         "Content-Type": "application/json"},
                timeout=120,
            )
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_exc = exc
            if attempt == retries - 1:
                raise TransientProviderError(f"nationalbanken network: {exc}") from exc
            continue
        if resp.status_code in (429, 502, 503, 504):
            last_exc = TransientProviderError(f"nationalbanken HTTP {resp.status_code}")
            if attempt == retries - 1:
                raise last_exc
            continue
        if resp.status_code == 404:
            raise ProviderError(f"nationalbanken HTTP 404: {url}")
        if resp.status_code >= 400:
            raise ProviderError(f"nationalbanken HTTP {resp.status_code}: {resp.text[:200]}")
        return resp
    raise last_exc  # unreachable


class NationalbankenProvider(BaseProvider):
    name = "nationalbanken"
    display_name = "Danmarks Nationalbank"

    def fetch_series(self, spec: SeriesSpec) -> list[Observation]:
        body = _resolve_body(spec)
        url = f"{BASE_URL}/data"
        resp = _http_post(url, body)
        text = resp.text
        if text.startswith("{") and "errorTypeCode" in text:
            raise ProviderError(f"nationalbanken extract error: {text[:200]}")

        reader = csv.reader(io.StringIO(text), delimiter=";")
        rows = list(reader)
        if not rows:
            return []
        # BULK header: INSTRUMENT;LAND;OPGOER;TID;INDHOLD
        header = rows[0]
        n = len(header)
        if n < 2:
            raise ProviderError(f"nationalbanken: unexpected header {header}")

        conv = spec.conversion or 1.0
        out: list[Observation] = []
        for r in rows[1:]:
            if len(r) < n:
                continue
            period = r[n - 2]
            val_str = (r[n - 1] or "").strip().replace(",", ".")
            if not val_str or val_str in {"..", "-"}:
                continue
            d = _parse_dst_period(period)
            if d is None:
                continue
            try:
                v = float(val_str) * conv
            except ValueError:
                continue
            out.append(Observation(date=d, value=round(v, 6)))
        return out


try:
    register_provider(NationalbankenProvider())
except ProviderError as e:
    print(f"[warn] NationalbankenProvider not registered: {e}")
