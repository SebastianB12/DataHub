"""Sync docs/te_sources_truth.yaml PL section with current indicator_sources state."""
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.db import supabase as sb  # noqa: E402

TRUTH = ROOT / "docs/te_sources_truth.yaml"


def main():
    with open(TRUTH, "r", encoding="utf-8") as f:
        truth = yaml.safe_load(f) or {}
    pl = truth.get("PL") or {}

    # Get current DB state
    rows = sb.table("indicator_sources").select(
        "indicator,source,series_id,note"
    ).eq("country", "PL").eq("is_default", True).execute().data

    updates = 0
    for r in rows:
        slug = r["indicator"]
        entry = pl.get(slug) or {}
        old_source = entry.get("source")
        new_source = r["source"]
        if old_source != new_source:
            entry["source"] = new_source
            entry["verified"] = True
            print(f"  {slug}: {old_source} -> {new_source}")
            updates += 1
        pl[slug] = entry

    truth["PL"] = pl
    with open(TRUTH, "w", encoding="utf-8") as f:
        yaml.safe_dump(truth, f, sort_keys=True, allow_unicode=True, width=200)
    print(f"\nUpdated {updates} truth entries.")


if __name__ == "__main__":
    main()
