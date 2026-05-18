"""BnrProvider — Banca Națională a României (National Bank of Romania) (V2 stateless).

TE-Primärquelle für RO Interest Rate ist BNR. BNR hostet die monatliche
Zinsreihe als statischen CSV-Export über die Interactive-Database-Files
Schnittstelle:

Endpoint:
  https://www.bnr.ro/en/idbfiles?cid=665&dfrom=&dto=&period=all&format=CSV

  cid=665 -> "NBR's interest rates - monthly values"
  format=CSV liefert UTF-8 mit BOM, Semicolon-Separator, EOP-Werte.

Spalten (nach 8 Header-Zeilen):
  "Date";"Policy Rate";"Credit facility rate";"Deposit facility rate"
  Codes: BNRDOBL_DPM, BNRDOBL_DFC, BNRDOBL_DFD

Series-IDs:
  BNR_MONETARY_POLICY_RATE  -> BNRDOBL_DPM (TE-Quelle)
  BNR_CREDIT_FACILITY_RATE  -> BNRDOBL_DFC
  BNR_DEPOSIT_FACILITY_RATE -> BNRDOBL_DFD
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
from pipeline.dispatcher import register_provider


CSV_URL = "https://www.bnr.ro/en/idbfiles?cid=665&dfrom=&dto=&period=all&format=CSV"
USER_AGENT = "EconPulse/1.0 (macroeconomic data pipeline)"

SERIES_TO_COL = {
    # series_id -> CSV column code in header row 8
    "BNR_MONETARY_POLICY_RATE":  "BNRDOBL_DPM",
    "BNR_CREDIT_FACILITY_RATE":  "BNRDOBL_DFC",
    "BNR_DEPOSIT_FACILITY_RATE": "BNRDOBL_DFD",
}


def _http_get(url: str, retries: int = 3) -> str:
    last_exc: BaseException | None = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT,
                                              "Accept": "text/csv,*/*"},
                                allow_redirects=True, timeout=30)
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_exc = exc
            if attempt == retries - 1:
                raise TransientProviderError(f"bnr network: {exc}") from exc
            continue
        # BNR's edge WAF sometimes intermittently rejects with 403; treat as transient.
        if resp.status_code in (403, 429, 502, 503, 504):
            last_exc = TransientProviderError(f"bnr HTTP {resp.status_code}")
            if attempt == retries - 1:
                raise last_exc
            continue
        if resp.status_code == 404:
            raise ProviderError(f"bnr HTTP 404: {url}")
        if resp.status_code >= 400:
            raise ProviderError(f"bnr HTTP {resp.status_code}: {resp.text[:200]}")
        # strip BOM
        return resp.text.lstrip("﻿")
    raise last_exc  # unreachable


def _parse_month(s: str) -> date | None:
    """YYYY-MM -> date(YYYY, MM, 1). Reject obviously-malformed years (BNR
    occasionally emits rows like '0024-12' as data-quality artefacts)."""
    s = (s or "").strip()
    if len(s) != 7 or s[4] != "-":
        return None
    try:
        y = int(s[:4]); m = int(s[5:])
    except ValueError:
        return None
    if y < 1990 or y > 2100 or not (1 <= m <= 12):
        return None
    return date(y, m, 1)


def _resolve_col_index(header_codes: list[str], code: str) -> int | None:
    for i, c in enumerate(header_codes):
        if (c or "").strip() == code:
            return i
    return None


class BnrProvider(BaseProvider):
    name = "bnr"
    display_name = "Banca Națională a României"

    def fetch_series(self, spec: SeriesSpec) -> list[Observation]:
        sid = (spec.series_id or "").strip().upper()
        ep = spec.extra_params or {}
        col_code = ep.get("col_code") or SERIES_TO_COL.get(sid)
        if not col_code:
            raise ProviderError(
                f"bnr: unknown series_id '{spec.series_id}' "
                f"(known: {sorted(SERIES_TO_COL.keys())} or extra_params.col_code)"
            )

        text = _http_get(CSV_URL)
        reader = csv.reader(io.StringIO(text), delimiter=";")
        rows = list(reader)
        if not rows:
            raise ProviderError("bnr: empty CSV body")

        # BNR header layout: rows 0..4 = meta (Statistic class name, Note, etc).
        # Row 5: "Date";"Policy Rate";"Credit facility rate";"Deposit facility rate"
        # Row 6: blank/units row
        # Row 7: "";"BNRDOBL_DPM";"BNRDOBL_DFC";"BNRDOBL_DFD"
        # Data starts at row 8.
        # Find code row by scanning for one of the known code prefixes.
        code_row_idx = None
        for i, r in enumerate(rows[:15]):
            if any((c or "").strip().startswith("BNRDOBL_") for c in r):
                code_row_idx = i
                break
        if code_row_idx is None:
            raise ProviderError("bnr: cannot find code header row (BNRDOBL_*)")

        col = _resolve_col_index(rows[code_row_idx], col_code)
        if col is None:
            raise ProviderError(f"bnr: column '{col_code}' not found")

        conv = spec.conversion or 1.0
        out: list[Observation] = []
        for r in rows[code_row_idx + 1:]:
            if not r or len(r) <= col:
                continue
            d = _parse_month(r[0])
            if d is None:
                continue
            val_str = (r[col] or "").strip().replace(",", ".")
            if not val_str or val_str in {"..", "-"}:
                continue
            try:
                v = float(val_str)
            except ValueError:
                continue
            out.append(Observation(date=d, value=round(v * conv, 6)))
        return out


try:
    register_provider(BnrProvider())
except ProviderError as e:
    print(f"[warn] BnrProvider not registered: {e}")
