"""
One-shot cleanup after data-model refinements:

1. Remove stale DE central-bank-balance rows (Eurosystem aggregate, not DE-specific).
2. Deduplicate rows that share (indicator, country, date, source) but have
   NULL vs "" adjustment (the two are treated as distinct by Postgres unique
   constraints, so upserts could not overwrite them). Keeps the newer value.
3. Migrate remaining NULL adjustments to empty string so the unique constraint
   behaves as intended going forward.

Safe to rerun — idempotent.
"""

from pipeline.db import supabase


def delete_stale_ecb_de_central_bank_balance() -> int:
    res = (
        supabase.table("data_points")
        .delete()
        .eq("indicator", "central-bank-balance")
        .eq("country", "DE")
        .eq("source", "ecb")
        .execute()
    )
    return len(res.data)


def _fetch_all_rows() -> list[dict]:
    """Fetch every data_points row (paginated)."""
    out: list[dict] = []
    step = 1000
    offset = 0
    while True:
        batch = (
            supabase.table("data_points")
            .select("id, indicator, country, date, source, adjustment, fetched_at")
            .range(offset, offset + step - 1)
            .execute()
        ).data
        out.extend(batch)
        if len(batch) < step:
            break
        offset += step
    return out


def _key(row: dict) -> tuple:
    # Treat NULL and "" as the same adjustment (target post-migration state).
    adj = row.get("adjustment") or ""
    return (row["indicator"], row["country"], row["date"], row["source"], adj)


def dedupe_adjustment_duplicates() -> int:
    """For every (indicator, country, date, source, adjustment-or-empty) group,
    keep the newest row (by fetched_at) and delete the rest. Catches NULL/NULL,
    NULL/"" and ""/"" duplicates in one pass."""
    rows = _fetch_all_rows()

    # Group by logical key
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        groups.setdefault(_key(r), []).append(r)

    to_delete: list[int] = []
    for group in groups.values():
        if len(group) <= 1:
            continue
        # Prefer rows with non-NULL adjustment; within that, the newest fetched_at.
        group.sort(
            key=lambda r: (r.get("adjustment") is not None, r.get("fetched_at") or ""),
            reverse=True,
        )
        keep = group[0]
        for r in group[1:]:
            to_delete.append(r["id"])

    deleted = 0
    chunk = 500
    for i in range(0, len(to_delete), chunk):
        ids = to_delete[i : i + chunk]
        supabase.table("data_points").delete().in_("id", ids).execute()
        deleted += len(ids)
    return deleted


def migrate_null_to_empty_adjustment() -> int:
    """Set adjustment = '' where NULL, so unique constraint treats them consistently."""
    res = (
        supabase.table("data_points")
        .update({"adjustment": ""})
        .is_("adjustment", "null")
        .execute()
    )
    return len(res.data)


def main() -> None:
    print("1. Deleting stale DE central-bank-balance (ECB aggregate copied to DE)...")
    n = delete_stale_ecb_de_central_bank_balance()
    print(f"   deleted {n} rows")

    print("2. Deduping rows with duplicate (indicator, country, date, source, adjustment-or-empty)...")
    n = dedupe_adjustment_duplicates()
    print(f"   deleted {n} duplicate rows")

    print("3. Migrating remaining NULL adjustments to empty string...")
    n = migrate_null_to_empty_adjustment()
    print(f"   updated {n} rows")

    print("Done.")


if __name__ == "__main__":
    main()
