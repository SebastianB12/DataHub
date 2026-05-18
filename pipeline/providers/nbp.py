"""NbpProvider — Narodowy Bank Polski (National Bank of Poland) — STUB.

TE-Primärquelle für PL Interest Rate ist NBP. NBP's Web-API
(api.nbp.pl) liefert NUR Wechselkurse und Gold, KEINE Zinsen.
Die Reference-Rate-Historie lebt auf nbp.pl/.../rates/ als JS-rendered
HTML — Cloudflare-Anti-Bot blockiert curl/requests/cloudscraper.

Status: Stub. Provider liefert eine leere Liste; data_series-Row für PL
ist als is_active=false markiert. Aktivierung erfordert entweder:
  (a) Headless-Browser-Integration (Playwright/Selenium)
  (b) Maintainer-kuratierte Static-History mit Update-Procedure pro
      MPC-Decision (NBP Monetary Policy Council Decisions).

TE-Verweis: https://tradingeconomics.com/poland/interest-rate
TE-Attribution: National Bank of Poland (https://www.nbp.pl/).
"""
from __future__ import annotations

from pipeline.base_provider import (
    BaseProvider, SeriesSpec, Observation,
    ProviderError,
)
from pipeline.dispatcher import register_provider


class NbpProvider(BaseProvider):
    name = "nbp"
    display_name = "Narodowy Bank Polski"

    def fetch_series(self, spec: SeriesSpec) -> list[Observation]:
        raise ProviderError(
            "nbp: STUB — NBP Reference Rate page is JS-rendered + Cloudflare-protected. "
            "Activate by implementing one of: "
            "(a) Playwright/Selenium scrape, "
            "(b) Maintainer-curated embedded history with monthly MPC-Decision review."
        )


try:
    register_provider(NbpProvider())
except ProviderError as e:
    print(f"[warn] NbpProvider not registered: {e}")
