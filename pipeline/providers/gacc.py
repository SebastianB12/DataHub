"""GaccProvider — General Administration of Customs of China (V2 stateless).

V2: provider.fetch_series(SeriesSpec) -> list[Observation].
Keine indicator/country/source-Knowledge. Wird vom Dispatcher pro data_series-Row gerufen.

Datenquelle: english.customs.gov.cn — "Monthly Bulletin", Tabelle "Summary of
Imports and Exports (In USD) B：Monthly". Pro Monatsbulletin liefert die Tabelle
12+ Zeilen mit Spalten YYYY.MM | Total | Export | Import | Balance (USD Mio.).

Die Series-IDs entsprechen den extrahierten Spalten:
  - 'exports'        -> Spalte "Export"
  - 'imports'        -> Spalte "Import"
  - 'trade-balance'  -> Spalte "Balance"
  - 'total'          -> Spalte "Total" (Summe Exp+Imp)

Werte werden von USD Mio. -> USD Mrd. konvertiert (Default; conversion kann
ueberschreiben).

Routing:
  - spec.series_id in {'exports','imports','trade-balance','total'}.
  - spec.extra_params: optional. Nicht benoetigt fuer Standard-Lauf.
  - spec.country_hint: ignoriert (immer CN).
  - spec.freq_hint: ignoriert (immer M).
"""
from __future__ import annotations

import re
import time
from datetime import date

import requests

from pipeline.base_provider import (
    BaseProvider, SeriesSpec, Observation,
    ProviderError, TransientProviderError,
)
from pipeline.transforms import normalize_date
from pipeline.dispatcher import register_provider


INDEX_URL = "http://english.customs.gov.cn/statics/report/monthly.html"
BULLETIN_BASE = "http://english.customs.gov.cn"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; EconPulse/1.0)"}

# Map series_id -> Index in der Bulletin-Tabelle (Spalten 0=YYYY.MM, 1=Total,
# 2=Export, 3=Import, 4=Balance).
_SERIES_COLUMN: dict[str, int] = {
    "total":         1,
    "exports":       2,
    "imports":       3,
    "trade-balance": 4,
}


# ---------------- HTTP-Helfer ----------------

def _get_with_retry(url: str, retries: int = 3, base_delay: float = 5.0) -> requests.Response:
    """GET mit Retry auf 5xx + Connection/Timeout. Raised Transient/ProviderError."""
    last_exc: BaseException | None = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_exc = exc
            if attempt == retries - 1:
                raise TransientProviderError(f"network: {exc}") from exc
            time.sleep(base_delay * (attempt + 1))
            continue
        if resp.status_code == 429:
            if attempt == retries - 1:
                raise TransientProviderError("HTTP 429 (rate limited)")
            time.sleep(base_delay * (attempt + 1))
            continue
        if resp.status_code in (502, 503, 504):
            last_exc = TransientProviderError(f"HTTP {resp.status_code}")
            if attempt == retries - 1:
                raise last_exc
            time.sleep(base_delay * (attempt + 1))
            continue
        if resp.status_code >= 500:
            raise TransientProviderError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        if resp.status_code == 404:
            raise ProviderError(f"HTTP 404: {url}")
        if resp.status_code >= 400:
            raise ProviderError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        return resp
    raise last_exc  # unreachable


# ---------------- Index- + Bulletin-Parser ----------------

def _fetch_bulletin_index() -> dict[str, list[tuple[str, str]]]:
    """Liest die Bulletin-Index-Seite, gibt {year: [(month_label, url), ...]} zurueck.

    Reihen-Index 1 ist "Summary B Monthly".
    """
    resp = _get_with_retry(INDEX_URL)
    html = resp.text
    years = re.findall(r'<option[^>]+value="(\d{4})"', html)
    current_year = years[0] if years else str(date.today().year)

    rows = re.findall(r'<tr><td>(.*?)</td><td>(.*?)</td></tr>', html, re.DOTALL)
    if len(rows) < 2:
        return {}
    _title, cell = rows[1]
    links = re.findall(r'<a[^>]+href=([^>\s]+)>\s*(\w+)\.\s*</a>', cell)
    if not links:
        return {}
    return {current_year: [(month, url) for url, month in links]}


def _parse_bulletin_table(html: str) -> list[tuple[str, int, int, int, int]]:
    """Parse ein Monatsbulletin -> list[(YYYY.MM, total, export, import, balance)]
    (alle Werte in USD Mio.)."""
    table_match = re.search(r'<table[^>]*>(.*?)</table>', html, re.DOTALL)
    if not table_match:
        return []
    table_html = table_match.group(1)
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', table_html, re.DOTALL)

    out: list[tuple[str, int, int, int, int]] = []
    for row in rows:
        cells = re.findall(r'<t[hd][^>]*>(.*?)</t[hd]>', row, re.DOTALL)
        cells_clean = [
            re.sub(r'<[^>]+>|&nbsp;|&amp;', ' ', c).strip().replace(",", "")
            for c in cells
        ]
        if not cells_clean:
            continue
        ym = cells_clean[0]
        if not re.match(r'^\d{4}\.\d{2}$', ym):
            continue
        try:
            total, export, imp, balance = (int(cells_clean[i]) for i in (1, 2, 3, 4))
        except (ValueError, IndexError):
            continue
        out.append((ym, total, export, imp, balance))
    return out


def _collect_all_months() -> list[tuple[str, int, int, int, int]]:
    """Holt aktuelle Index-Seite und parst das jeweils neueste Bulletin pro Jahr."""
    index = _fetch_bulletin_index()
    if not index:
        return []
    all_rows: dict[str, tuple[str, int, int, int, int]] = {}
    for year in sorted(index, reverse=True):
        month_links = index[year]
        if not month_links:
            continue
        month_label, url = month_links[-1]
        full_url = url if url.startswith("http") else f"{BULLETIN_BASE}{url}"
        try:
            resp = _get_with_retry(full_url)
            for r in _parse_bulletin_table(resp.text):
                all_rows[r[0]] = r
            time.sleep(2)
        except TransientProviderError:
            raise
        except Exception as exc:
            # Einzelnes Bulletin-Fail ist kein Provider-Fail; weitermachen.
            print(f"  [gacc] WARN bulletin {year} {month_label}: {exc}")
    return sorted(all_rows.values())


# ---------------- Provider ----------------

class GaccProvider(BaseProvider):
    name = "gacc"
    display_name = "General Administration of Customs (China)"

    # Cache pro Provider-Instance: wir parsen die Index-Seite + Bulletins genau
    # einmal pro Dispatch-Run und bedienen alle 4 series_ids aus dem Cache.
    def __init__(self):
        self._cache: list[tuple[str, int, int, int, int]] | None = None

    def _rows(self) -> list[tuple[str, int, int, int, int]]:
        if self._cache is None:
            self._cache = _collect_all_months()
        return self._cache

    def fetch_series(self, spec: SeriesSpec) -> list[Observation]:
        sid = (spec.series_id or "").strip().lower()
        col = _SERIES_COLUMN.get(sid)
        if col is None:
            raise ProviderError(
                f"gacc: unknown series_id '{spec.series_id}'. "
                f"Expected one of {sorted(_SERIES_COLUMN)}"
            )

        # Default-Conversion: USD Mio. -> USD Mrd. Wenn der Aufrufer eine
        # eigene conversion setzt (z.B. 1.0 fuer Million), respektieren.
        conv = spec.conversion if spec.conversion and spec.conversion != 1.0 else (1.0 / 1000.0)

        try:
            rows = self._rows()
        except TransientProviderError:
            raise
        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError(f"gacc bulletin fetch: {e}") from e

        out: list[Observation] = []
        for r in rows:
            ym = r[0]
            value_m = r[col]
            try:
                y, m = ym.split(".")
                dt = date(int(y), int(m), 1)
            except (ValueError, KeyError):
                continue
            out.append(Observation(
                date=normalize_date(dt, "M"),
                value=round(float(value_m) * conv, 6),
            ))
        return out


# Self-Registration — try/except, niemals Modulimport killen.
try:
    register_provider(GaccProvider())
except Exception as e:
    print(f"[warn] GaccProvider not registered: {e}")
