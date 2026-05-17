"""NsiBgProvider — Bulgarian National Statistical Institute via BNB SDDS Plus (V2 stateless).

Dispatcher ruft fetch_series(spec) pro data_series-Row.

Quelle: BNB hostet die kanonischen SDDS-Plus SDMX-ML 2.1 StructureSpecificData
Dateien fuer NSI (CPI/PPI/Employment/Industrial Production/National Accounts)
und fuer sich selbst (Balance of Payments BPM6, Central Government Operations).

Endpoint: https://www.bnb.bg/bnbweb/groups/public/documents/bnb_sdmx/<topic>.xml
Keine Auth, keine Quota.

Topics:
  cpi.xml      Single-Series  PCPI_IX   M  CPI Index 2025=100
  ppi.xml      Single-Series  PPPI_IX   M  PPI Index 2021=100
  emp.xml      Single-Series  LE_PE_NUM Q  Employed persons (thousand)
  ind.xml      Single-Series  AIP_IX    M  Industrial Production 2021=100
  nag.xml      Multi-Series              Q  National Accounts (BGN mln, multiple STO)
  bop_bpm6.xml Multi-Series              M  Balance of Payments (EUR mln)
  cgo.xml      Multi-Series              M  Central Government Operations (BGN mln)

SeriesSpec-Konventionen:
  spec.series_id ist EINE der folgenden Formen:
    a) "NSI-BG/<INDICATOR>"               -> Single-Series Topic
         INDICATOR in {PCPI_IX, PPPI_IX, LE_PE_NUM, AIP_IX}; Topic wird abgeleitet.
    b) "NSI-BG/NAG/<STO>[_<PRICES>]"      -> NAG Multi-Series, Match per STO (+PRICES)
         z.B. "NSI-BG/NAG/B1GQ_Y", "NSI-BG/NAG/P31", "NSI-BG/NAG/P7"
    c) "NSI-BG/BOP/<INT_ACC_ITEM>_<ACCOUNTING_ENTRY>" -> BOP, z.B. "CA_B"
    d) "NSI-BG/CGO/<INDICATOR>"           -> CGO, z.B. "GBXCCB_G01_CA_XDC"

  spec.extra_params optional:
      {'match': {<dim>: <value>, ...}}  -> ueberschreibt das aus series_id parsed match-dict
                                           (z.B. um REF_SECTOR fuer P3/P31 zu fixen).

  spec.freq_hint: M oder Q. Bei single-series Topics auto-bestimmt aus INDICATOR.

Smoke-tests (bekannte series_ids aus DB):
  NSI-BG/PCPI_IX, NSI-BG/PPPI_IX, NSI-BG/LE_PE_NUM, NSI-BG/AIP_IX
  NSI-BG/NAG/B1GQ_Y, NSI-BG/NAG/P31, NSI-BG/NAG/P3, NSI-BG/NAG/P51G,
  NSI-BG/NAG/P5M, NSI-BG/NAG/P6, NSI-BG/NAG/P7
  NSI-BG/BOP/CA_B
  NSI-BG/CGO/GBXCCB_G01_CA_XDC
"""
from __future__ import annotations

import re
from datetime import date

import requests

from pipeline.base_provider import (
    BaseProvider, SeriesSpec, Observation,
    ProviderError, TransientProviderError,
)
from pipeline.transforms import normalize_date
from pipeline.dispatcher import register_provider

BASE = "https://www.bnb.bg/bnbweb/groups/public/documents/bnb_sdmx"

HDR = {
    "User-Agent": "EconPulse/0.1 (Sebastian/SVM-AG)",
    "Accept": "application/xml, text/xml",
}

# INDICATOR -> (topic, freq) fuer Single-Series Topics
SIMPLE_INDICATOR_MAP: dict[str, tuple[str, str]] = {
    "PCPI_IX":   ("cpi", "M"),
    "PPPI_IX":   ("ppi", "M"),
    "LE_PE_NUM": ("emp", "Q"),
    "AIP_IX":    ("ind", "M"),
}

# Empfohlene Defaults pro Multi-Series-Match (REF_SECTOR / PRICES) — wird nur
# verwendet wenn series_id den Wert nicht spezifiziert UND extra_params.match
# fehlt. Mappt STO -> zusaetzliche Filter.
NAG_STO_DEFAULTS: dict[str, dict[str, str]] = {
    "P31":  {"REF_SECTOR": "S1M", "PRICES": "V"},
    "P3":   {"REF_SECTOR": "S13", "PRICES": "V"},
    "P51G": {"PRICES": "V"},
    "P5M":  {"PRICES": "V"},
    "P6":   {"PRICES": "V"},
    "P7":   {"PRICES": "V"},
    "B1GQ": {"PRICES": "Y"},   # chain-linked volumes
}


# ---------------- HTTP ----------------

def _fetch_xml(topic: str) -> str:
    url = f"{BASE}/{topic}.xml"
    try:
        r = requests.get(url, headers=HDR, timeout=60)
    except (requests.ConnectionError, requests.Timeout) as e:
        raise TransientProviderError(f"nsi_bg network: {e}") from e
    if r.status_code >= 500:
        raise TransientProviderError(f"nsi_bg HTTP {r.status_code}")
    if r.status_code == 404:
        raise ProviderError(f"nsi_bg HTTP 404: {url}")
    if r.status_code >= 400:
        raise ProviderError(f"nsi_bg HTTP {r.status_code}: {r.text[:200]}")
    return r.text


# ---------------- Period parsing ----------------

def _parse_period(p: str, freq: str) -> date | None:
    try:
        if freq == "M":
            yy, mm = p.split("-")
            return date(int(yy), int(mm), 1)
        if freq == "Q":
            yy, q = p.split("-Q")
            return date(int(yy), {"1": 1, "2": 4, "3": 7, "4": 10}[q], 1)
        if freq == "A" and len(p) == 4:
            return date(int(p), 1, 1)
    except (ValueError, KeyError):
        return None
    return None


# ---------------- SDMX-ML parsing ----------------

def _parse_simple(xml: str, freq: str) -> list[tuple[date, float]]:
    """Topic mit genau einem <Series>-Block: alle Obs extrahieren."""
    out: list[tuple[date, float]] = []
    for per, val in re.findall(
        r'<Obs\s+TIME_PERIOD="([^"]+)"\s+OBS_VALUE="([^"]+)"',
        xml,
    ):
        dt = _parse_period(per, freq)
        if dt is None:
            continue
        try:
            v = float(val)
        except ValueError:
            continue
        out.append((dt, v))
    return sorted(out)


def _parse_multi(xml: str, match: dict, freq: str) -> list[tuple[date, float]]:
    """Multi-Series Topic: erstes <Series>-Block mit matching Attribut-Dict."""
    for attrs, body in re.findall(r'<Series ([^>]+)>(.*?)</Series>', xml, flags=re.S):
        ok = True
        for k, v in match.items():
            m = re.search(rf'{k}="([^"]+)"', attrs)
            if not m or m.group(1) != v:
                ok = False
                break
        if not ok:
            continue
        out: list[tuple[date, float]] = []
        for per, val in re.findall(
            r'TIME_PERIOD="([^"]+)"\s+OBS_VALUE="([^"]+)"',
            body,
        ):
            dt = _parse_period(per, freq)
            if dt is None:
                continue
            try:
                fv = float(val)
            except ValueError:
                continue
            out.append((dt, fv))
        return sorted(out)
    return []


# ---------------- series_id-Routing ----------------

def _route(series_id: str, extra_params: dict | None
           ) -> tuple[str, str, dict | None]:
    """series_id + extra_params -> (topic, freq, match_dict_or_None).

    Bei Single-Series ist match_dict_or_None=None (alle Obs des Topic-Files).
    Bei Multi-Series ist match_dict_or_None das SDMX-Attribut-Filter-Dict.
    """
    ep = extra_params or {}
    sid = (series_id or "").strip()
    if not sid:
        raise ProviderError("nsi_bg: empty series_id")
    if sid.upper().startswith("NSI-BG/"):
        sid = sid.split("/", 1)[1]
    parts = sid.split("/")

    # extra_params.match hat immer Vorrang, wenn vorhanden — caller weiss, was er tut.
    explicit_match = ep.get("match")

    head = parts[0].upper()

    # Multi-Series: NAG / BOP / CGO
    if head == "NAG":
        if explicit_match:
            return "nag", "Q", dict(explicit_match)
        if len(parts) < 2:
            raise ProviderError(f"nsi_bg: NAG needs STO suffix in '{series_id}'")
        # "<STO>[_<PRICES>]" — z.B. "B1GQ_Y" -> STO=B1GQ, PRICES=Y
        sto_tok = parts[1]
        if "_" in sto_tok:
            sto, prices = sto_tok.split("_", 1)
            match = {"STO": sto, "PRICES": prices}
        else:
            sto = sto_tok
            match = {"STO": sto}
            # Defaults auf STO basis ergaenzen
            for k, v in NAG_STO_DEFAULTS.get(sto, {}).items():
                match.setdefault(k, v)
        return "nag", "Q", match

    if head == "BOP":
        if explicit_match:
            return "bop_bpm6", "M", dict(explicit_match)
        if len(parts) < 2:
            raise ProviderError(f"nsi_bg: BOP needs <ITEM>_<ENTRY> suffix in '{series_id}'")
        tok = parts[1]
        if "_" not in tok:
            raise ProviderError(
                f"nsi_bg: BOP suffix '{tok}' must be '<INT_ACC_ITEM>_<ACCOUNTING_ENTRY>'"
            )
        item, entry = tok.split("_", 1)
        return "bop_bpm6", "M", {"INT_ACC_ITEM": item, "ACCOUNTING_ENTRY": entry}

    if head == "CGO":
        if explicit_match:
            return "cgo", "M", dict(explicit_match)
        if len(parts) < 2:
            raise ProviderError(f"nsi_bg: CGO needs INDICATOR suffix in '{series_id}'")
        # CGO indicator can contain underscores; rejoin
        indicator = "/".join(parts[1:])
        return "cgo", "M", {"INDICATOR": indicator}

    # Single-Series Topics — head is the INDICATOR code (PCPI_IX, etc.)
    # Achtung: head wurde upper-cased; INDICATOR-Codes sind ohnehin uppercase.
    indicator = head
    topic_freq = SIMPLE_INDICATOR_MAP.get(indicator)
    if topic_freq is None:
        raise ProviderError(
            f"nsi_bg: unknown indicator '{indicator}' (series_id '{series_id}'). "
            f"Known simple: {sorted(SIMPLE_INDICATOR_MAP)}; "
            "for NAG/BOP/CGO use 'NSI-BG/<area>/<key>'."
        )
    topic, freq = topic_freq
    return topic, freq, None


class NsiBgProvider(BaseProvider):
    name = "nsi_bg"
    display_name = "NSI Bulgaria (via BNB SDDS Plus SDMX)"

    def fetch_series(self, spec: SeriesSpec) -> list[Observation]:
        topic, default_freq, match = _route(spec.series_id, spec.extra_params)
        # freq_hint vom Dispatcher ist autoritativ wenn gesetzt; sonst Auto-Default
        freq = spec.freq_hint or default_freq
        conv = spec.conversion or 1.0

        xml = _fetch_xml(topic)
        if match is None:
            pairs = _parse_simple(xml, freq)
        else:
            pairs = _parse_multi(xml, match, freq)

        return [
            Observation(
                date=normalize_date(dt, freq),
                value=round(float(v) * conv, 6),
            )
            for dt, v in pairs
        ]


try:
    register_provider(NsiBgProvider())
except ProviderError as e:
    print(f"[warn] NsiBgProvider not registered: {e}")
