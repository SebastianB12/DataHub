"""DestatisProvider — Statistisches Bundesamt (GENESIS-Online) via pystatis.

V2 stateless: fetch_series(SeriesSpec) -> list[Observation].

SeriesSpec.series_id ist der GENESIS-Tabellen-Code (z.B. "61111-0001", "52411-0011").
spec.extra_params kapselt provider-spezifische Filter (ein Dict). Anerkannt:

  Server-side classifying filters (wenn gesetzt: direct POST statt pystatis):
    classifyingvariable1/2/3, classifyingkey1/2/3
    regionalvariable, regionalkey

  Row-Level filter (auf ffcsv-DataFrame nach Fetch):
    filter_unit          : substring im 'value_unit' (z.B. "2020=100", "Prozent", "Tsd. EUR")
    filter_value_code    : exact gegen 'value_variable_code' (z.B. "WERTA"/"WERTE", "PREIS1")
    filter_series        : substring gegen alle Zellen (z.B. "ERW112")
    filter_region        : substring; skipped "Früheres Bundesgebiet"/"Neue Länder"
    filter_attrs         : dict {col_name: expected_exact_value} (NaN -> "")

  Pipeline-Hints:
    startyear            : default "1991"
    conversion           : Skalierungs-Faktor (alternativ zu spec.conversion)

Die Frequenz kommt aus spec.freq_hint ("M"/"Q"/"A"). Datums-Normalisierung via
pipeline.transforms.normalize_date.

ProviderError-Strategie:
  - Token fehlt -> ProviderError (Dispatcher schreibt error: ...)
  - "Ups, ein Fehler!" (Destatis generic 500) -> ProviderError (NICHT transient,
    laut feedback_destatis_api: das ist generic 500 nicht überlastet — nicht parallel
    retryen, der Dispatcher würde sich sonst selbst rate-limiten)
  - HTTP 5xx (502/503/504) -> TransientProviderError (Dispatcher retryt)
  - Code 6 "parallel limit" -> TransientProviderError (passt zur Politik)

NICHT mehr in V2:
  - Kein TABLES-Loop
  - Kein _compute_trade_balance (Trade-Balance ist ein separater computed indicator)
  - Keine DB-Schreiblogik
"""
from __future__ import annotations

import io
import os
import time
import zipfile
from datetime import date

import requests
from dotenv import load_dotenv

from pipeline.base_provider import (
    BaseProvider, SeriesSpec, Observation,
    ProviderError, TransientProviderError,
)
from pipeline.transforms import normalize_date
from pipeline.dispatcher import register_provider


load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

DIRECT_BASE_URL = "https://www-genesis.destatis.de/genesisWS/rest/2020/data/tablefile"
DIRECT_HEADERS_TEMPLATE = {
    "User-Agent": "Mozilla/5.0 (compatible; EconPulse/1.0)",
    "Content-Type": "application/x-www-form-urlencoded",
}

MONTH_MAP = {
    "Januar": 1, "Februar": 2, "März": 3, "April": 4,
    "Mai": 5, "Juni": 6, "Juli": 7, "August": 8,
    "September": 9, "Oktober": 10, "November": 11, "Dezember": 12,
}

QUARTER_MAP = {
    "1. Quartal": 1, "2. Quartal": 4, "3. Quartal": 7, "4. Quartal": 10,
    "Quartal 1": 1, "Quartal 2": 4, "Quartal 3": 7, "Quartal 4": 10,
}

# Substrings that indicate generic Destatis "Ups, ein Fehler!" responses.
GENERIC_DESTATIS_ERROR = "ups, ein fehler"


def _setup_pystatis() -> None:
    """Inject DESTATIS_TOKEN into pystatis' in-memory config (no file write)."""
    token = os.environ.get("DESTATIS_TOKEN", "").strip()
    if not token:
        raise ProviderError("DESTATIS_TOKEN missing in .env")

    try:
        from pystatis import config as cfg
    except ImportError as e:
        raise ProviderError(f"pystatis not installed: {e}") from e

    cfg.config.set("genesis", "username", token)
    cfg.config.set("genesis", "password", token)


def _fetch_table_pystatis(table_code: str, startyear: str = "1991", retries: int = 5):
    """Fetch a GENESIS table via pystatis with retry on transient 5xx.

    Returns the pandas DataFrame (raw ffcsv layout, prettify=False).
    """
    try:
        from pystatis import Table
    except ImportError as e:
        raise ProviderError(f"pystatis not installed: {e}") from e

    last_exc: BaseException | None = None
    for attempt in range(retries):
        if attempt:
            time.sleep(15 * attempt)
        try:
            t = Table(table_code)
            t.get_data(
                prettify=False,
                compress=False,
                language="de",
                startyear=startyear,
            )
            return t.data
        except Exception as e:
            last_exc = e
            msg = str(e)
            if GENERIC_DESTATIS_ERROR in msg.lower():
                # Generic 500 — not retry-worth at provider level (laut feedback_destatis_api).
                raise ProviderError(f"Destatis generic 500 for {table_code}: {msg[:160]}") from e
            if "502" in msg or "503" in msg or "504" in msg:
                continue
            raise ProviderError(f"pystatis fetch failed for {table_code}: {msg[:200]}") from e
    raise TransientProviderError(
        f"pystatis fetch retries exhausted for {table_code}: {last_exc}"
    ) from last_exc


def _fetch_table_direct(table_code: str, extra: dict, startyear: str = "1991"):
    """Direct POST to /data/tablefile with server-side classifying filters.

    Used when extra_params contains classifying* keys — pystatis would otherwise
    trigger Destatis' background-job mode which our token is not authorised for.

    Returns a pandas DataFrame in the same ffcsv shape as pystatis prettify=False.
    """
    import pandas as pd
    token = os.environ.get("DESTATIS_TOKEN", "").strip()
    if not token:
        raise ProviderError("DESTATIS_TOKEN missing in .env")

    headers = {**DIRECT_HEADERS_TEMPLATE, "username": token, "password": token}
    data = {
        "name": table_code,
        "area": "all",
        "format": "ffcsv",
        "language": "de",
        "compress": "true",
        "startyear": startyear,
    }
    for key in (
        "classifyingvariable1", "classifyingkey1",
        "classifyingvariable2", "classifyingkey2",
        "classifyingvariable3", "classifyingkey3",
        "regionalvariable", "regionalkey",
    ):
        if extra.get(key):
            data[key] = extra[key]

    last_exc: BaseException | None = None
    for attempt in range(5):
        if attempt:
            time.sleep(15 * attempt)
        try:
            resp = requests.post(
                DIRECT_BASE_URL, headers=headers, data=data, timeout=(30, 240),
            )
            ct = resp.headers.get("content-type", "")
            if "json" in ct:
                payload = resp.json() if resp.text else {}
                code = payload.get("Status", {}).get("Code") or payload.get("Code")
                content = payload.get("Status", {}).get("Content") or payload.get("Content", "")
                if code == 6:
                    last_exc = TransientProviderError(
                        f"Code 6 parallel limit ({str(content)[:120]})"
                    )
                    continue
                content_lower = str(content).lower()
                if GENERIC_DESTATIS_ERROR in content_lower:
                    raise ProviderError(
                        f"Destatis generic 500 for {table_code}: {str(content)[:160]}"
                    )
                raise ProviderError(
                    f"Destatis Code {code} for {table_code}: {str(content)[:200]}"
                )
            if resp.status_code in (502, 503, 504):
                last_exc = TransientProviderError(f"HTTP {resp.status_code}")
                continue
            if resp.status_code >= 400:
                body = resp.text[:200] if resp.text else ""
                if GENERIC_DESTATIS_ERROR in body.lower():
                    raise ProviderError(
                        f"Destatis generic 500 for {table_code}: {body}"
                    )
                raise ProviderError(
                    f"HTTP {resp.status_code} for {table_code}: {body}"
                )
            # ZIP with one CSV inside
            z = zipfile.ZipFile(io.BytesIO(resp.content))
            csv_text = z.read(z.namelist()[0]).decode("utf-8-sig")
            return pd.read_csv(io.StringIO(csv_text), sep=";", dtype=str, na_filter=False)
        except (requests.RequestException, zipfile.BadZipFile) as e:
            last_exc = e
            continue
    raise TransientProviderError(
        f"direct-fetch retries exhausted for {table_code}: {last_exc}"
    ) from last_exc


def _parse_period(year_str: str, sub_label: str, freq: str) -> date | None:
    """Parse GENESIS time fields to a date.

    `year_str` may be "1991" or a full date "2024-12-31" (when the primary
    time-dim is Stichtag).
    """
    try:
        if len(year_str) >= 10 and "-" in year_str:
            return date.fromisoformat(year_str[:10])
    except ValueError:
        pass

    try:
        year = int(year_str[:4])
    except (ValueError, TypeError):
        return None

    if freq == "M":
        month = MONTH_MAP.get(sub_label)
        return date(year, month, 1) if month else None
    if freq == "Q":
        month = QUARTER_MAP.get(sub_label)
        return date(year, month, 1) if month else None
    return date(year, 1, 1)


def _row_matches(row: dict, filter_series: str, filter_region: str) -> bool:
    """Apply series/region filters (substring match across all cells)."""
    if filter_series:
        haystack = ";".join(str(v) for v in row.values())
        if filter_series not in haystack:
            return False

    if filter_region:
        haystack = ";".join(str(v) for v in row.values())
        if "Früheres Bundesgebiet;" in haystack or "Neue Länder;" in haystack:
            attr_hits = [
                v for k, v in row.items()
                if "attribute_label" in k and filter_region in str(v)
            ]
            if not attr_hits:
                return False
        elif filter_region not in haystack:
            return False
    return True


def _extract_observations(df, extra: dict, freq: str, conversion: float) -> list[Observation]:
    """Convert a GENESIS ffcsv DataFrame to Observations using extra-param filters."""
    filter_unit = extra.get("filter_unit", "")
    filter_value_code = extra.get("filter_value_code", "")
    filter_series = extra.get("filter_series", "")
    filter_region = extra.get("filter_region", "")
    filter_attrs = extra.get("filter_attrs") or {}

    out: list[Observation] = []
    for _, row in df.iterrows():
        d = row.to_dict()

        unit = str(d.get("value_unit", "")).strip()
        if filter_unit and filter_unit not in unit:
            continue
        if filter_value_code and str(d.get("value_variable_code", "")).strip() != filter_value_code:
            continue
        if filter_attrs:
            mismatch = False
            for col, expected in filter_attrs.items():
                raw = d.get(col, "")
                if raw is None:
                    val = ""
                else:
                    s = str(raw).strip()
                    val = "" if s.lower() == "nan" else s
                if val != expected:
                    mismatch = True
                    break
            if mismatch:
                continue
        if not _row_matches(d, filter_series, filter_region):
            continue

        value_str = str(d.get("value", "")).strip()
        if not value_str or value_str in ("-", "...", "nan"):
            continue
        try:
            value = float(value_str.replace(",", "."))
        except ValueError:
            continue

        year_str = str(d.get("time", "")).strip()
        sub_label = str(d.get("1_variable_attribute_label", "")).strip()
        if not sub_label:
            sub_label = str(d.get("2_variable_attribute_label", "")).strip()

        dt = _parse_period(year_str, sub_label, freq)
        if not dt:
            continue

        out.append(Observation(
            date=normalize_date(dt, freq),
            value=round(value * conversion, 6),
        ))
    return out


class DestatisProvider(BaseProvider):
    name = "destatis"
    display_name = "Statistisches Bundesamt"

    def __init__(self):
        _setup_pystatis()

    def fetch_series(self, spec: SeriesSpec) -> list[Observation]:
        table_code = (spec.series_id or "").strip()
        if not table_code:
            raise ProviderError("destatis: series_id (table code) missing")

        extra = spec.extra_params or {}
        freq = spec.freq_hint or "M"
        conversion = spec.conversion if spec.conversion else float(extra.get("conversion", 1.0))
        startyear = str(extra.get("startyear", "1991"))

        has_classifying = any(
            extra.get(k) for k in (
                "classifyingvariable1", "classifyingvariable2", "classifyingvariable3",
                "regionalvariable",
            )
        )

        if has_classifying:
            df = _fetch_table_direct(table_code, extra, startyear=startyear)
        else:
            df = _fetch_table_pystatis(table_code, startyear=startyear)

        return _extract_observations(df, extra, freq=freq, conversion=conversion)


try:
    register_provider(DestatisProvider())
except ProviderError as e:
    print(f"[warn] DestatisProvider not registered: {e}")
