"""
CuratedProvider — liest pipeline/curated/<country>.yaml und schreibt deren Werte
als data_points. Für Indikatoren die selten aktualisiert werden und keine
brauchbare freie API haben (Taxes, Credit Rating, Corruption Index, etc.).

Pflegen = YAML editieren, dann `python -m pipeline.providers.curated` laufen lassen.
Idempotent: upsert schreibt bei gleichem (indicator, country, date, source) nur
einmal.
"""

import os
from datetime import date, datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv

from pipeline.base_provider import BaseProvider, DataPoint
from pipeline.db import datapoints_to_rows, upsert_data_points, log_pipeline_run

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

CURATED_DIR = Path(__file__).parent.parent / "curated"


def _parse_date(raw) -> date:
    if isinstance(raw, date):
        return raw
    if isinstance(raw, str):
        return datetime.strptime(raw, "%Y-%m-%d").date()
    raise ValueError(f"Unsupported date type: {type(raw)} -> {raw!r}")


class CuratedProvider(BaseProvider):
    name = "curated"
    display_name = "Curated (hand-maintained YAML)"

    def fetch(self) -> list[DataPoint]:
        points: list[DataPoint] = []
        if not CURATED_DIR.exists():
            print(f"  (no curated directory at {CURATED_DIR})")
            return points

        for yaml_file in sorted(CURATED_DIR.glob("*.yaml")):
            with yaml_file.open(encoding="utf-8") as fh:
                doc = yaml.safe_load(fh) or {}

            country = doc.get("country")
            if not country:
                print(f"  SKIP {yaml_file.name}: missing 'country' key")
                continue

            for key, entry in doc.items():
                if key == "country" or not isinstance(entry, dict):
                    continue
                try:
                    points.append(
                        DataPoint(
                            indicator=key,
                            country=country,
                            date=_parse_date(entry["date"]),
                            value=float(entry["value"]),
                            source="curated",
                            unit=entry.get("unit") or "",
                            series_id=f"{country}:{key}",
                            adjustment="",
                        )
                    )
                except (KeyError, ValueError, TypeError) as exc:
                    print(f"  FAIL {yaml_file.name}:{key}: {exc}")

            print(f"  OK {yaml_file.name}: {country}")

        return points


def run():
    provider = CuratedProvider()
    print(f"Fetching data from {provider.display_name}...")
    try:
        points = provider.fetch()
        print(f"\nTotal: {len(points)} data points")
        if points:
            rows = datapoints_to_rows(points)
            count = upsert_data_points(rows)
            log_pipeline_run("curated", "success", count)
            print(f"Done. {count} rows upserted.")
        else:
            log_pipeline_run("curated", "success", 0)
    except Exception as e:
        log_pipeline_run("curated", "failed", error_message=str(e))
        print(f"\nFailed: {e}")
        raise


if __name__ == "__main__":
    run()
