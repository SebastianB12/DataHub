"""TE-Source-Conformity Validator.

Compares every active default row in indicator_sources against
docs/te_sources_truth.yaml. Fails if any (country, indicator) row has a
source code that does not match the truth file.

Exit codes:
  0 = clean
  1 = violations found

Usage: pipeline/.venv/Scripts/python.exe -m pipeline.validate_te_conformity
"""
from __future__ import annotations

import os
import sys
from collections import Counter

import yaml

from pipeline.db import supabase

TRUTH_PATH = os.path.join(os.path.dirname(__file__), "..", "docs", "te_sources_truth.yaml")


def load_truth() -> dict[str, dict[str, dict]]:
    with open(TRUTH_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data


def fetch_default_rows() -> list[dict]:
    rows: list[dict] = []
    page = 0
    while True:
        r = (
            supabase.table("indicator_sources")
            .select("country, indicator, source")
            .eq("is_default", True)
            .eq("active", True)
            .range(page * 1000, page * 1000 + 999)
            .execute()
        )
        chunk = r.data or []
        rows.extend(chunk)
        if len(chunk) < 1000:
            break
        page += 1
    return rows


def main() -> int:
    truth = load_truth()
    rows = fetch_default_rows()

    violations: list[str] = []
    missing_in_truth: list[str] = []
    source_mismatch: list[str] = []
    duplicates: list[str] = []

    seen: Counter[tuple[str, str]] = Counter()
    for row in rows:
        c, i, s = row["country"], row["indicator"], row["source"]
        seen[(c, i)] += 1
        if seen[(c, i)] > 1:
            duplicates.append(f"{c}/{i}: duplicate default row source={s}")
            continue
        entry = (truth.get(c) or {}).get(i)
        if entry is None:
            missing_in_truth.append(f"{c}/{i}: source={s} -- not in truth.yaml")
            continue
        expected = entry.get("source")
        if s != expected:
            te_label = entry.get("te_label") or "?"
            source_mismatch.append(
                f"{c}/{i}: source={s} -- expected {expected} (TE: {te_label})"
            )

    violations = missing_in_truth + source_mismatch + duplicates

    if violations:
        print(f"TE-Conformity violations: {len(violations)}")
        print(f"  missing_in_truth: {len(missing_in_truth)}")
        print(f"  source_mismatch:  {len(source_mismatch)}")
        print(f"  duplicates:       {len(duplicates)}")
        head = 50
        for v in violations[:head]:
            print(f"  - {v}")
        if len(violations) > head:
            print(f"  ... ({len(violations) - head} more)")
        return 1

    print(f"OK: {len(rows)} default rows are TE-conform against {len(truth)} countries.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
