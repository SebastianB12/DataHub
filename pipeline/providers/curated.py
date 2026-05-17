"""CuratedProvider — V2 stateless.

Liest pro Aufruf die curated YAML-Datei des Landes (pipeline/curated/<iso2>.yaml)
und gibt fuer einen bestimmten Slug die enthaltenen Observations zurueck.

YAML-Form (typisch):
    country: US
    <slug>:
      value: 21
      date: "2026-12-31"
      unit: "%"
      ...

Optional history-Form (mehrere Datenpunkte pro Slug):
    <slug>:
      history:
        - { date: "2017-12-31", value: 35 }
        - { date: "2018-12-31", value: 21 }

KEIN Network. KEINE indicator-/country-/source-Knowledge ueber den
SeriesSpec hinaus. Datums-Normalisierung via transforms.normalize_date.

series_id-Konvention: "{COUNTRY}:{slug}" (z.B. "US:corporate-tax-rate").
Falls kein ":" vorhanden ist, wird series_id als Slug interpretiert und
country_hint genutzt, um die YAML zu finden.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import yaml

from pipeline.base_provider import (
    BaseProvider, SeriesSpec, Observation,
    ProviderError,
)
from pipeline.transforms import normalize_date
from pipeline.dispatcher import register_provider

CURATED_DIR = Path(__file__).parent.parent / "curated"


def _parse_date(raw) -> date:
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if isinstance(raw, str):
        return datetime.strptime(raw, "%Y-%m-%d").date()
    raise ValueError(f"unsupported date type: {type(raw).__name__} -> {raw!r}")


def _load_country_yaml(country: str) -> dict:
    """Parse pipeline/curated/<iso2>.yaml. Raises ProviderError on YAML errors."""
    path = CURATED_DIR / f"{country.lower()}.yaml"
    if not path.exists():
        return {}
    try:
        with path.open(encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except yaml.YAMLError as e:
        raise ProviderError(f"curated YAML parse error {path.name}: {e}") from e
    except OSError as e:
        raise ProviderError(f"curated YAML read error {path.name}: {e}") from e


def _entry_to_observations(entry: dict, freq: str, conversion: float) -> list[Observation]:
    """Convert one slug entry (dict) into a list of Observations.

    Supports two shapes:
      single:  {value, date, ...}
      history: {history: [{value, date}, ...]}
    """
    out: list[Observation] = []

    history = entry.get("history")
    if isinstance(history, list):
        items = history
    else:
        items = [entry]

    for item in items:
        if not isinstance(item, dict):
            continue
        if "value" not in item or "date" not in item:
            continue
        try:
            dt = _parse_date(item["date"])
            v = float(item["value"]) * conversion
        except (KeyError, ValueError, TypeError):
            continue
        out.append(Observation(date=normalize_date(dt, freq), value=round(v, 6)))
    return out


class CuratedProvider(BaseProvider):
    name = "curated"
    display_name = "Curated"

    def fetch_series(self, spec: SeriesSpec) -> list[Observation]:
        # series_id-Parsing: "{COUNTRY}:{slug}" bevorzugt; sonst country_hint + series_id.
        sid = (spec.series_id or "").strip()
        country: str | None
        slug: str
        if ":" in sid:
            head, tail = sid.split(":", 1)
            country = head.strip() or spec.country_hint
            slug = tail.strip()
        else:
            country = spec.country_hint
            slug = sid

        if not country:
            raise ProviderError(
                f"curated: country missing (use 'CC:slug' series_id or country_hint). spec={spec}"
            )
        if not slug:
            raise ProviderError(f"curated: slug missing in series_id={spec.series_id!r}")

        doc = _load_country_yaml(country)
        if not doc:
            return []

        entry = doc.get(slug)
        if not isinstance(entry, dict):
            return []

        return _entry_to_observations(
            entry,
            freq=spec.freq_hint or "A",
            conversion=spec.conversion or 1.0,
        )


register_provider(CuratedProvider())
