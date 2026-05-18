"""NbpProvider — Narodowy Bank Polski (National Bank of Poland) (V2 stateless).

TE-Primärquelle für PL Interest Rate ist NBP. NBP publiziert die offiziellen
Zinssätze als statische XML-Feeds auf static.nbp.pl — direkt fetchbar ohne
Cloudflare-Anti-Bot.

Endpoints:
  Current:  https://static.nbp.pl/dane/stopy/stopy_procentowe.xml
  Archive:  https://static.nbp.pl/dane/stopy/stopy_procentowe_archiwum.xml
            (data_publikacji bis 2015-03-04; danach kommt current XML)

Format:
  <stopy_procentowe data_publikacji="YYYY-MM-DD">
    <tabela id="stoproc"><pozycja id="ref" oprocentowanie="3,75" obowiazuje_od="..."/>
  Plus archive: <pozycje obowiazuje_od="..."><pozycja id="ref" oprocentowanie="..."/>

Series-IDs (id-Attribute des XML):
  NBP_REFERENCE_RATE -> id="ref" (Stopa Referencyjna, TE-Quelle)
  NBP_LOMBARD_RATE   -> id="lom"
  NBP_DEPOSIT_RATE   -> id="dep"
  NBP_DISCOUNT_RATE  -> id="dys"
  NBP_REDISCOUNT_RATE-> id="red"

Provider merged Archiv + Current zu einer Historie.
"""
from __future__ import annotations

from datetime import date, datetime
from xml.etree import ElementTree as ET

import requests

from pipeline.base_provider import (
    BaseProvider, SeriesSpec, Observation,
    ProviderError, TransientProviderError,
)
from pipeline.dispatcher import register_provider


URL_CURRENT = "https://static.nbp.pl/dane/stopy/stopy_procentowe.xml"
URL_ARCHIVE = "https://static.nbp.pl/dane/stopy/stopy_procentowe_archiwum.xml"
USER_AGENT  = "EconPulse/1.0 (macroeconomic data pipeline)"

SERIES_TO_XML_ID = {
    "NBP_REFERENCE_RATE":  "ref",
    "NBP_LOMBARD_RATE":    "lom",
    "NBP_DEPOSIT_RATE":    "dep",
    "NBP_DISCOUNT_RATE":   "dys",
    "NBP_REDISCOUNT_RATE": "red",
}


def _http_get(url: str, retries: int = 3) -> bytes:
    last_exc: BaseException | None = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_exc = exc
            if attempt == retries - 1:
                raise TransientProviderError(f"nbp network: {exc}") from exc
            continue
        if resp.status_code in (429, 502, 503, 504):
            last_exc = TransientProviderError(f"nbp HTTP {resp.status_code}")
            if attempt == retries - 1:
                raise last_exc
            continue
        if resp.status_code == 404:
            raise ProviderError(f"nbp HTTP 404: {url}")
        if resp.status_code >= 400:
            raise ProviderError(f"nbp HTTP {resp.status_code}: {resp.text[:200]}")
        # strip UTF-8 BOM if present
        content = resp.content
        if content.startswith(b"\xef\xbb\xbf"):
            content = content[3:]
        return content
    raise last_exc  # unreachable


def _parse_value(s: str | None) -> float | None:
    if not s:
        return None
    try:
        return float(s.strip().replace(",", "."))
    except ValueError:
        return None


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.strip()[:10]).date()
    except ValueError:
        return None


def _extract_from_current(xml_bytes: bytes, xml_id: str) -> tuple[date, float] | None:
    """Current XML: <pozycja id="ref" oprocentowanie="3,75" obowiazuje_od="..."/>."""
    root = ET.fromstring(xml_bytes)
    # find pozycja in stoproc table
    for tabela in root.findall("tabela"):
        if tabela.get("id") != "stoproc":
            continue
        for poz in tabela.findall("pozycja"):
            if poz.get("id") == xml_id:
                d = _parse_date(poz.get("obowiazuje_od"))
                v = _parse_value(poz.get("oprocentowanie"))
                if d is not None and v is not None:
                    return d, v
    return None


def _extract_from_archive(xml_bytes: bytes, xml_id: str) -> list[tuple[date, float]]:
    """Archive XML: <pozycje obowiazuje_od=...><pozycja id=ref oprocentowanie=.../>."""
    root = ET.fromstring(xml_bytes)
    out: list[tuple[date, float]] = []
    for poz_block in root.findall("pozycje"):
        d = _parse_date(poz_block.get("obowiazuje_od"))
        if d is None:
            continue
        for poz in poz_block.findall("pozycja"):
            if poz.get("id") == xml_id:
                v = _parse_value(poz.get("oprocentowanie"))
                if v is not None:
                    out.append((d, v))
                break
    return out


class NbpProvider(BaseProvider):
    name = "nbp"
    display_name = "Narodowy Bank Polski"

    def fetch_series(self, spec: SeriesSpec) -> list[Observation]:
        sid = (spec.series_id or "").strip().upper()
        ep = spec.extra_params or {}
        xml_id = ep.get("xml_id") or SERIES_TO_XML_ID.get(sid)
        if not xml_id:
            raise ProviderError(
                f"nbp: unknown series_id '{spec.series_id}' "
                f"(known: {sorted(SERIES_TO_XML_ID.keys())} or extra_params.xml_id)"
            )

        archive = _http_get(URL_ARCHIVE)
        current = _http_get(URL_CURRENT)

        hist = _extract_from_archive(archive, xml_id)
        last = _extract_from_current(current, xml_id)

        # Merge: archive has data up to a publication-date, current XML
        # publishes the latest change. Append if newer.
        by_date: dict[date, float] = {d: v for d, v in hist}
        if last is not None:
            d, v = last
            by_date[d] = v  # overwrite if same date

        conv = spec.conversion or 1.0
        out = [Observation(date=d, value=round(v * conv, 6))
               for d, v in sorted(by_date.items())]
        return out


try:
    register_provider(NbpProvider())
except ProviderError as e:
    print(f"[warn] NbpProvider not registered: {e}")
