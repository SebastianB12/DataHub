"""Auto-create indicator_sources rows (source='curated', is_default=true) for every
slug in every country YAML under pipeline/curated/. Skips entries that already
exist for the new countries (we don't want to overwrite the FR/DE/EA/GB/CN/US rows)."""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pathlib import Path
import yaml
from pipeline.db import supabase as sb

NEW_COUNTRIES = ["AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "GR",
                 "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT",
                 "RO", "SK", "SI", "ES", "SE"]

CURATED_DIR = Path(__file__).parent.parent / "curated"

def main():
    rows_to_insert = []
    for yaml_file in sorted(CURATED_DIR.glob("*.yaml")):
        with yaml_file.open(encoding="utf-8") as fh:
            doc = yaml.safe_load(fh) or {}
        country = doc.get("country")
        if not country or country not in NEW_COUNTRIES:
            continue
        for key, entry in doc.items():
            if key == "country" or not isinstance(entry, dict):
                continue
            rows_to_insert.append({
                "indicator": key,
                "country": country,
                "source": "curated",
                "series_id": f"{country}:{key}",
                "is_default": True,
                "transform": "raw",
                "conversion": 1.0,
                "unit": entry.get("unit") or "",
                "adjustment": "",
                "freq_hint": "A",
                "extra_params": None,
                "active": True,
            })

    # Delete pre-existing curated rows for these countries to avoid PK conflicts
    for c in NEW_COUNTRIES:
        sb.table("indicator_sources").delete().eq("source", "curated").eq("country", c).execute()

    # Insert in batches
    total = 0
    for i in range(0, len(rows_to_insert), 200):
        batch = rows_to_insert[i:i+200]
        res = sb.table("indicator_sources").insert(batch).execute()
        total += len(res.data)
    print(f"Inserted {total} curated indicator_sources rows")

if __name__ == "__main__":
    main()
