"""BnrProvider — Banca Națională a României (National Bank of Romania) — STUB.

TE-Primärquelle für RO Interest Rate ist BNR. BNR hat keine öffentliche
JSON/CSV/SDMX-API für Zinsen (nur XML für FX-Kurse via nbrfxrates.xml).
Die HTML-Seiten unter bnr.ro/1970-... und /Indicatori-de-politica-monetara-1744
sind komplett JS-gerendert; curl/requests/cloudscraper bekommen leere
Seiten.

Status: Stub. Provider liefert keine Daten; data_series-Row für RO ist
als is_active=false markiert. Aktivierung erfordert entweder:
  (a) Headless-Browser-Integration (Playwright/Selenium)
  (b) Maintainer-kuratierte Static-History, gepflegt aus BNR-Press-
      Releases & Inflation Reports (PDFs, statisch hostable).

TE-Verweis: https://tradingeconomics.com/romania/interest-rate
TE-Attribution: National Bank of Romania (http://www.bnro.ro).
"""
from __future__ import annotations

from pipeline.base_provider import (
    BaseProvider, SeriesSpec, Observation,
    ProviderError,
)
from pipeline.dispatcher import register_provider


class BnrProvider(BaseProvider):
    name = "bnr"
    display_name = "Banca Națională a României"

    def fetch_series(self, spec: SeriesSpec) -> list[Observation]:
        raise ProviderError(
            "bnr: STUB — BNR rate pages are fully JS-rendered, no public API exists. "
            "Activate by implementing one of: "
            "(a) Playwright/Selenium scrape, "
            "(b) Maintainer-curated embedded history with quarterly Inflation Report review."
        )


try:
    register_provider(BnrProvider())
except ProviderError as e:
    print(f"[warn] BnrProvider not registered: {e}")
