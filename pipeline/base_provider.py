"""BaseProvider — stateless V2.

Jeder Provider implementiert genau eine Methode: `fetch_series(spec) -> list[Observation]`.
KEINE indicator/country/source-Knowledge. KEIN Loop ueber Configs. KEINE Filter-Logik.

Der Provider weiss nur:
  - welche `series_id` zu fetchen ist
  - welche `extra_params` (provider-spezifisch)
  - welche Frequenz erwartet wird (M/Q/A/D/W)
  - welche Skalierung anzuwenden ist (conversion)

Was er NICHT mehr weiss:
  - welcher Indikator-Slug das ist
  - welches Land das ist
  - welche Source-Attribution
  - welche anderen Series er sonst noch hat

Die Mapping-Schicht (instance_id, family_id, country_id) liegt in pipeline/dispatcher.py.
data_points werden ZENTRAL vom Dispatcher geschrieben (mit series_pk).

Migrations-Strategie:
  V1-Provider (legacy): hatten `fetch() -> list[DataPoint]`. Wird in Phase 7 entfernt.
  V2-Provider (neu):    haben `fetch_series(spec) -> list[Observation]`.

Wir benennen den Klassen-Namen NICHT um — `class FredProvider(BaseProvider)` bleibt.
Aber `fetch()` wird durch `fetch_series()` ersetzt.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class SeriesSpec:
    """Was der Provider braucht um *eine* Series zu fetchen.

    Wird vom Dispatcher aus data_series + indicator_families gebaut und an
    provider.fetch_series() uebergeben.
    """
    series_id:     str                 # provider-spezifische Series-ID
    extra_params:  dict | None = None  # JSONB-Bag fuer Eurostat-Filter, SDMX-Keys etc.
    freq_hint:     str = "M"           # 'D' | 'W' | 'M' | 'Q' | 'A' | 'S'
    conversion:    float = 1.0         # Skalierungs-Faktor (z.B. 1/1000 fuer M->B)
    unit:          str = ""            # Optional, fuer Provider die Unit umrechnen
    adjustment:    str = ""             # 'SA' | 'NSA' | 'CA' | ''


@dataclass(frozen=True)
class Observation:
    """Eine einzelne Beobachtung: (date, value). Provider liefert eine Liste davon.

    KEIN indicator/country/source/series_id — die kennt nur der Dispatcher.
    """
    date:  date
    value: float


class ProviderError(Exception):
    """Provider-side Fehler. Dispatcher fängt das, schreibt last_fetch_status='error: ...'."""


class TransientProviderError(ProviderError):
    """Retry-bare Fehler (5xx, Timeout). Dispatcher macht Backoff-Retry."""


class BaseProvider(ABC):
    """V2 Provider-Interface — pro Series fetchbar, stateless.

    Subklassen geben `name` (DB-Provider-Code) + `display_name` an und
    implementieren `fetch_series`.
    """
    name: str
    display_name: str

    @abstractmethod
    def fetch_series(self, spec: SeriesSpec) -> list[Observation]:
        """Holt die ganze Historie der Series.

        - Bei Erfolg: list[Observation], chronologisch oder unsortiert (Dispatcher sortiert).
        - Bei nicht-existierender Series-ID: list leer ODER raise ProviderError.
        - Bei transienten Fehlern (5xx, Timeout): raise TransientProviderError.
        - Bei dauerhaften Fehlern (Auth, 404, Schema-Aenderung): raise ProviderError.

        Conversion (conversion-Faktor) und Datums-Normalisierung erledigt der Provider —
        er liefert bereits skalierten Wert auf normalisiertem Datum.
        """
        ...

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} ({self.name})>"


# ---------------- Legacy V1 Aliases ----------------
# DataPoint blieb als Legacy-Klasse fuer V1-Provider die noch nicht migriert sind.
# Wird in Phase 7 entfernt.

@dataclass
class DataPoint:
    """LEGACY — V1 Provider-Output. Wird in Phase 7 entfernt."""
    indicator: str
    country: str
    date: date
    value: float
    source: str
    unit: str = ""
    series_id: str = ""
    adjustment: str = ""
