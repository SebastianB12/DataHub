"""Apply aggressive fixes to MT findings.

Fixes:
1. Delete bogus capacity-utilization Q2-2026 row (43.8 — Eurostat index bug)
2. Update curated values per fresh TE fetch
3. Update truth.yaml notes for fetch-provider-vs-attribution cases
"""
import sys, io, yaml, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from pipeline.db import supabase as sb
from datetime import datetime, date

CHANGES = []


def log(msg):
    print(msg)
    CHANGES.append(msg)


# === 1. Delete bogus capacity-utilization Q2-2026 row ===
r = sb.table("data_points").select("date,value").eq("country", "MT").eq(
    "indicator", "capacity-utilization"
).eq("date", "2026-06-30").execute()
if r.data:
    log(f"DELETE capacity-utilization MT 2026-06-30 (value={r.data[0]['value']}, bogus Eurostat decode)")
    sb.table("data_points").delete().eq("country", "MT").eq(
        "indicator", "capacity-utilization"
    ).eq("date", "2026-06-30").execute()


# === 2. Update curated values (corrupted by stale snapshots) ===
def upsert_curated(slug, value, dt, unit, source="curated"):
    log(f"UPSERT curated {slug}: value={value} date={dt} unit={unit}")
    # delete existing
    sb.table("data_points").delete().eq("country", "MT").eq("indicator", slug).execute()
    # insert
    sb.table("data_points").insert({
        "indicator": slug,
        "country": "MT",
        "date": dt,
        "value": float(value),
        "unit": unit,
        "frequency": "annual",
        "adjustment": "",
        "source": source,
        "fetched_at": datetime.utcnow().isoformat(),
    }).execute()


# Per fresh TE fetch on 2026-05-17:
# - corruption-rank: 60 (2025 CPI)
# - corruption-index: 49 points (2025 CPI)
# - minimum-wages: 994 EUR/Month (2026-Q2)
# - retirement-age-men: 65 Years (2026, per "all time high 65 in 2026")
# - retirement-age-women: 65 Years (2026, per "all time high 65 in 2026")
upsert_curated("corruption-rank", 60, "2025-12-31", "Rank")
upsert_curated("corruption-index", 49, "2025-12-31", "Points")
upsert_curated("minimum-wages", 994, "2026-06-30", "EUR/Month")
upsert_curated("retirement-age-men", 65, "2026-12-31", "Years")
upsert_curated("retirement-age-women", 65, "2026-12-31", "Years")


# === 3. Update mt.yaml so config is consistent ===
yp = "pipeline/curated/mt.yaml"
y = yaml.safe_load(open(yp, encoding="utf-8"))
y["corruption-rank"]["value"] = 60
y["corruption-rank"]["date"] = "2025-12-31"
y["corruption-index"]["value"] = 49
y["corruption-index"]["date"] = "2025-12-31"
y["minimum-wages"]["value"] = 994
y["minimum-wages"]["date"] = "2026-06-30"
y["retirement-age-men"]["value"] = 65
y["retirement-age-men"]["date"] = "2026-12-31"
y["retirement-age-women"]["value"] = 65
y["retirement-age-women"]["date"] = "2026-12-31"
with open(yp, "w", encoding="utf-8") as f:
    yaml.safe_dump(y, f, sort_keys=False, allow_unicode=True)
log("Updated pipeline/curated/mt.yaml with refreshed values")


print()
print("=" * 60)
print(f"Total changes: {len(CHANGES)}")
