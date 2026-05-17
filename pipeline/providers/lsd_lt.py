"""LsdLtProvider — Statistics Lithuania (Lietuvos statistikos departamentas) V2 stateless.

Two upstream APIs, gewaehlt per extra_params.endpoint:

  endpoint="data_gov_lt" (default):
    URL: https://get.data.gov.lt/datasets/gov/lsd/statistika/{ns}/{table_id}
    RQL-style query: ?col1="v1"&select(laikotarpis,verte)&sort(laikotarpis)&limit(N)
    Antwort: {"_data":[{"laikotarpis":"YYYY-MM-DD","verte":123.4}, ...]}

  endpoint="sdmx":
    URL: https://osp-rs.stat.gov.lt/rest_xml/data/{flow}
    Antwort: SDMX 2.1 XML (Generic). LSD unterstuetzt KEINEN serverseitigen
    Partial-Key-Filter — wir holen das volle Dataflow und filtern clientseitig
    auf alle (dim_id, value)-Paare aus extra_params.filter.

SeriesSpec-Konventionen:
  - spec.series_id: human-readable Series-Label, z.B.
        "LSD/svki/S7R246M2020217" (data.gov.lt)
        "LSD/SDMX/S8R918_M4050113_5/EVRKM4050107=B_TO_E_NOT_C19" (SDMX)
    Wird vom Provider NUR fuer Logging verwendet — alle Coordinates kommen aus
    extra_params (entweder ns+table_id oder flow).
  - spec.extra_params:
      endpoint="data_gov_lt":
        {"endpoint":"data_gov_lt", "ns":<str>, "table_id":<str>,
         "filter":{col:val,...}, "limit":5000}
      endpoint="sdmx":
        {"endpoint":"sdmx", "flow":<str>, "filter":{dim_id:value,...}}
    Fallback: wenn endpoint fehlt, aber `flow` da -> sdmx; wenn `ns`/`table_id` da
    -> data_gov_lt.
  - spec.freq_hint: 'M' | 'Q' | 'A'. SDMX-Period-Parser unterstuetzt YYYYMnn,
    YYYYKn (ketvirtis), YYYYQn, sowie YYYY-MM-DD aus data.gov.lt.
  - spec.conversion: Skalierungsfaktor (z.B. 0.000001 fuer Mio -> Persons).

Smoke (V1-Series die jetzt durch extra_params kodiert werden):
  inflation-cpi: ns=svki, table_id=S7R246M2020217, filter={ecoicop_id:"00"}, freq=M
  industrial-production: flow=S8R918_M4050113_5,
                         filter={EVRKM4050107:"B_TO_E_NOT_C19", LYGINIMAS:"palyg_2021",
                                 Islyginimas_indeksai:"sezon"}, freq=M (sdmx)
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


GET_BASE = "https://get.data.gov.lt/datasets/gov/lsd/statistika"
GET_HEADERS = {
    "User-Agent": "EconPulse/1.0 (data.gov.lt open-data)",
    "Accept": "application/json",
}

SDMX_BASE = "https://osp-rs.stat.gov.lt/rest_xml/data"
SDMX_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; EconPulse/1.0)",
    "Accept": "application/xml",
}


# ---------------- HTTP helpers ----------------

def _http_get(url: str, *, headers: dict, params: dict | None = None,
              timeout: int = 60) -> requests.Response:
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=timeout)
    except (requests.ConnectionError, requests.Timeout) as e:
        raise TransientProviderError(f"lsd_lt network: {e}") from e
    if resp.status_code >= 500:
        raise TransientProviderError(f"lsd_lt HTTP {resp.status_code}")
    if resp.status_code == 404:
        raise ProviderError(f"lsd_lt 404: {url}")
    if resp.status_code >= 400:
        raise ProviderError(f"lsd_lt HTTP {resp.status_code}: {resp.text[:200]}")
    return resp


# ---------------- data.gov.lt branch ----------------

def _build_data_gov_query(filter_: dict[str, str], limit: int = 5000) -> dict:
    """Build the data.gov.lt RQL-style query as a single dict of GET params.

    Note: filter values must be quoted in the URL; we emit `col="val"` inside the
    query-string manually because requests' urlencode strips embedded quotes."""
    # We pre-build the raw query string and pass it through params={} by inlining.
    parts = [f'{k}="{v}"' for k, v in filter_.items()]
    parts.append("select(laikotarpis,verte)")
    parts.append("sort(laikotarpis)")
    parts.append(f"limit({limit})")
    return "&".join(parts)


def _fetch_data_gov_lt(ns: str, table_id: str, flt: dict, limit: int) -> list[tuple[date, float]]:
    qs = _build_data_gov_query(flt, limit=limit)
    url = f"{GET_BASE}/{ns}/{table_id}?{qs}"
    resp = _http_get(url, headers=GET_HEADERS, timeout=30)
    try:
        js = resp.json()
    except ValueError as e:
        raise ProviderError(f"lsd_lt data.gov.lt non-JSON: {e}") from e
    out: list[tuple[date, float]] = []
    for d in js.get("_data", []):
        per = d.get("laikotarpis")
        v = d.get("verte")
        if per is None or v is None:
            continue
        try:
            yy, mm, dd = str(per).split("-")
            dt = date(int(yy), int(mm), int(dd))
            out.append((dt, float(v)))
        except (ValueError, TypeError):
            continue
    out.sort(key=lambda kv: kv[0])
    return out


# ---------------- SDMX branch ----------------

_SDMX_OBS_RE = re.compile(
    r"<g:ObsKey>(.*?)</g:ObsKey>\s*<g:ObsValue value=\"([^\"]+)\"", re.S
)
_SDMX_DIM_RE = re.compile(r"id=\"([^\"]+)\" value=\"([^\"]+)\"")


def _parse_sdmx_period(p: str, freq: str) -> date | None:
    """LSD SDMX uses YYYYMmm (monthly), YYYYKn or YYYYQn (quarterly, K=ketvirtis),
    YYYY (annual)."""
    if not p:
        return None
    try:
        if freq == "M" and "M" in p:
            yy, mm = p.split("M")
            return date(int(yy), int(mm), 1)
        if freq == "Q":
            if "K" in p:
                yy, q = p.split("K")
                return date(int(yy), {"1": 1, "2": 4, "3": 7, "4": 10}[q], 1)
            if "Q" in p:
                yy, q = p.split("Q")
                return date(int(yy), {"1": 1, "2": 4, "3": 7, "4": 10}[q], 1)
        if freq == "A" and len(p) == 4 and p.isdigit():
            return date(int(p), 1, 1)
    except (ValueError, KeyError):
        return None
    return None


def _fetch_sdmx(flow: str, flt: dict[str, str], freq: str) -> list[tuple[date, float]]:
    url = f"{SDMX_BASE}/{flow}"
    resp = _http_get(url, headers=SDMX_HEADERS, timeout=60)
    text = resp.text
    out: list[tuple[date, float]] = []
    for ok_inner, val_s in _SDMX_OBS_RE.findall(text):
        dims = dict(_SDMX_DIM_RE.findall(ok_inner))
        if flt and not all(dims.get(k) == v for k, v in flt.items()):
            continue
        period = dims.get("LAIKOTARPIS")
        if not period:
            continue
        dt = _parse_sdmx_period(period, freq)
        if dt is None:
            continue
        try:
            out.append((dt, float(val_s)))
        except ValueError:
            continue
    out.sort(key=lambda kv: kv[0])
    return out


# ---------------- Provider ----------------

class LsdLtProvider(BaseProvider):
    name = "lsd_lt"
    display_name = "LSD Lithuania (Statistikos departamentas)"

    def fetch_series(self, spec: SeriesSpec) -> list[Observation]:
        ep = spec.extra_params or {}
        endpoint = (ep.get("endpoint") or "").lower()
        if not endpoint:
            # Auto-Routing: flow -> sdmx, ns+table_id -> data_gov_lt
            if ep.get("flow"):
                endpoint = "sdmx"
            elif ep.get("ns") and ep.get("table_id"):
                endpoint = "data_gov_lt"
            else:
                raise ProviderError(
                    f"lsd_lt: extra_params must contain 'endpoint' or 'flow' "
                    f"or 'ns'+'table_id' (spec.series_id={spec.series_id!r})"
                )

        freq = (spec.freq_hint or "M").upper()
        conv = spec.conversion or 1.0
        flt = ep.get("filter") or {}

        if endpoint == "data_gov_lt":
            ns = ep.get("ns")
            table_id = ep.get("table_id")
            if not (ns and table_id):
                raise ProviderError("lsd_lt data_gov_lt: 'ns' and 'table_id' required")
            limit = int(ep.get("limit") or 5000)
            pairs = _fetch_data_gov_lt(ns, table_id, flt, limit)
        elif endpoint == "sdmx":
            flow = ep.get("flow")
            if not flow:
                raise ProviderError("lsd_lt sdmx: 'flow' required")
            pairs = _fetch_sdmx(flow, flt, freq)
        else:
            raise ProviderError(f"lsd_lt: unknown endpoint '{endpoint}'")

        return [
            Observation(date=normalize_date(dt, freq), value=round(v * conv, 6))
            for dt, v in pairs
        ]


try:
    register_provider(LsdLtProvider())
except ProviderError as e:
    print(f"[warn] LsdLtProvider not registered: {e}")
