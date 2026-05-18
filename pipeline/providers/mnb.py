"""MnbProvider — Magyar Nemzeti Bank (National Bank of Hungary) (V2 stateless).

TE-Primärquelle für HU Interest Rate. Direkter XLSX-Download vom MNB
Base-Rate-Endpoint (offizielle Veröffentlichungsform — keine SOAP/REST-API
für Zinsen verfügbar).

Endpoint:
  https://www.mnb.hu/root/BaseRate/BaseRateExcel/alapkamat.xlsx
  Format: zwei Spalten, Header in Zeile 0:
    'Jegybanki alapkamat mértékéről szóló rendelet hatálybalépésének időpontja'
    'Jegybanki alapkamat mértéke'
  Daten: (datetime, "6,25%") — Wert als String mit Komma + '%'.

Series-IDs:
  MNB_BASE_RATE  -> Jegybanki alapkamat (Base Rate, TE-Quelle)
"""
from __future__ import annotations

from datetime import date, datetime
from io import BytesIO

import requests

from pipeline.base_provider import (
    BaseProvider, SeriesSpec, Observation,
    ProviderError, TransientProviderError,
)
from pipeline.dispatcher import register_provider


XLSX_URL = "https://www.mnb.hu/root/BaseRate/BaseRateExcel/alapkamat.xlsx"
USER_AGENT = "EconPulse/1.0 (macroeconomic data pipeline)"


def _parse_value(cell) -> float | None:
    """Parse '6,25%' or '6.25' or 6.25 -> 6.25."""
    if cell is None:
        return None
    if isinstance(cell, (int, float)):
        return float(cell)
    s = str(cell).strip().replace("%", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _parse_date(cell) -> date | None:
    if cell is None:
        return None
    if isinstance(cell, datetime):
        return cell.date()
    if isinstance(cell, date):
        return cell
    s = str(cell).strip()
    for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%d.%m.%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _http_get(url: str, retries: int = 3) -> bytes:
    last_exc: BaseException | None = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=60)
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_exc = exc
            if attempt == retries - 1:
                raise TransientProviderError(f"mnb network: {exc}") from exc
            continue
        if resp.status_code in (429, 502, 503, 504):
            last_exc = TransientProviderError(f"mnb HTTP {resp.status_code}")
            if attempt == retries - 1:
                raise last_exc
            continue
        if resp.status_code == 404:
            raise ProviderError(f"mnb HTTP 404: {url}")
        if resp.status_code >= 400:
            raise ProviderError(f"mnb HTTP {resp.status_code}")
        return resp.content
    raise last_exc  # unreachable


class MnbProvider(BaseProvider):
    name = "mnb"
    display_name = "Magyar Nemzeti Bank"

    def fetch_series(self, spec: SeriesSpec) -> list[Observation]:
        sid = (spec.series_id or "").strip().upper()
        # MNB liefert nur die Base-Rate-Reihe — series_id ist sentinel.
        if sid and sid != "MNB_BASE_RATE":
            raise ProviderError(
                f"mnb: unsupported series_id '{spec.series_id}' "
                "(only MNB_BASE_RATE)"
            )

        try:
            import openpyxl  # lazy import; im venv installiert
        except ImportError as e:
            raise ProviderError(f"mnb: openpyxl not installed: {e}") from e

        raw = _http_get(XLSX_URL)
        wb = openpyxl.load_workbook(BytesIO(raw), read_only=True, data_only=True)
        ws = wb.active

        conv = spec.conversion or 1.0
        out: list[Observation] = []
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i == 0:
                continue
            if not row or len(row) < 2:
                continue
            d = _parse_date(row[0])
            v = _parse_value(row[1])
            if d is None or v is None:
                continue
            out.append(Observation(date=d, value=round(v * conv, 6)))
        return out


try:
    register_provider(MnbProvider())
except ProviderError as e:
    print(f"[warn] MnbProvider not registered: {e}")
