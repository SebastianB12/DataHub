"""CnbProvider — Česká národní banka (Czech National Bank) (V2 stateless).

TE-Primärquelle für CZ Interest Rate. Direkter Download der historischen
2W-Repo-Rate als pipe-separated Textfile von der CNB-FAQ-Seite.

Endpoint:
  https://www.cnb.cz/en/faq/.galleries/development_of_the_cnb_2w_repo_rate.txt
  Format: 'VALID_FROM|CNB_REPO_RATE_IN_%' Header
          'YYYYMMDD|<value>' Data rows.

Series-IDs (extra_params.endpoint oder series_id):
  CNB_2W_REPO_RATE  -> 2W Repo Rate (Policy Rate; TE-Quelle)
  CNB_DISCOUNT_RATE -> Discount Rate
  CNB_LOMBARD_RATE  -> Lombard Rate
"""
from __future__ import annotations

from datetime import date

import requests

from pipeline.base_provider import (
    BaseProvider, SeriesSpec, Observation,
    ProviderError, TransientProviderError,
)
from pipeline.dispatcher import register_provider


USER_AGENT = "EconPulse/1.0 (macroeconomic data pipeline)"

SERIES_URL = {
    "CNB_2W_REPO_RATE":  "https://www.cnb.cz/en/faq/.galleries/development_of_the_cnb_2w_repo_rate.txt",
    "CNB_DISCOUNT_RATE": "https://www.cnb.cz/en/faq/.galleries/development_of_the_cnb_discount_rate.txt",
    "CNB_LOMBARD_RATE":  "https://www.cnb.cz/en/faq/.galleries/development_of_the_cnb_lombard_rate.txt",
}


def _http_get(url: str, retries: int = 3) -> str:
    last_exc: BaseException | None = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_exc = exc
            if attempt == retries - 1:
                raise TransientProviderError(f"cnb network: {exc}") from exc
            continue
        if resp.status_code in (429, 502, 503, 504):
            last_exc = TransientProviderError(f"cnb HTTP {resp.status_code}")
            if attempt == retries - 1:
                raise last_exc
            continue
        if resp.status_code == 404:
            raise ProviderError(f"cnb HTTP 404: {url}")
        if resp.status_code >= 400:
            raise ProviderError(f"cnb HTTP {resp.status_code}: {resp.text[:200]}")
        # Server liefert mit BOM. Strip.
        return resp.text.lstrip("﻿")
    raise last_exc  # unreachable


def _parse_pipe_csv(text: str) -> list[tuple[date, float]]:
    out: list[tuple[date, float]] = []
    for raw in text.splitlines():
        s = raw.strip()
        if not s or s.startswith("VALID_FROM") or "|" not in s:
            continue
        valid_from, val_str = s.split("|", 1)
        valid_from = valid_from.strip()
        val_str = val_str.strip().replace(",", ".")
        if len(valid_from) != 8 or not valid_from.isdigit():
            continue
        try:
            d = date(int(valid_from[:4]), int(valid_from[4:6]), int(valid_from[6:8]))
            v = float(val_str)
        except ValueError:
            continue
        out.append((d, v))
    return out


class CnbProvider(BaseProvider):
    name = "cnb"
    display_name = "Česká národní banka"

    def fetch_series(self, spec: SeriesSpec) -> list[Observation]:
        sid = (spec.series_id or "").strip().upper()
        ep = spec.extra_params or {}
        url = ep.get("url") or SERIES_URL.get(sid)
        if not url:
            raise ProviderError(
                f"cnb: unknown series_id '{spec.series_id}' "
                f"(known: {sorted(SERIES_URL.keys())} or extra_params.url)"
            )
        text = _http_get(url)
        conv = spec.conversion or 1.0
        rows = _parse_pipe_csv(text)
        return [Observation(date=d, value=round(v * conv, 6)) for d, v in rows]


try:
    register_provider(CnbProvider())
except ProviderError as e:
    print(f"[warn] CnbProvider not registered: {e}")
