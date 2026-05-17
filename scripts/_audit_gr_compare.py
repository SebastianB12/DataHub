"""Compare current DB values to TE values for all 67 GR slugs."""
import json
from pathlib import Path
from pipeline.db import supabase as sb

ROOT = Path(__file__).resolve().parents[1]
data = json.load(open(ROOT / "docs" / "_audit_gr_te.json", encoding="utf-8"))

# Get current DB defaults + latest data point
rows = sb.table("indicator_sources").select("indicator,source,is_default,series_id,unit,adjustment").eq("country","GR").eq("is_default",True).execute().data
db_src = {r["indicator"]: r for r in rows}

print(f"{'slug':40s} | DB source     | TE provider  | TE value       | DB latest      | match?")
print("-" * 145)

issues = []
for slug, v in sorted(data.items()):
    p = v.get("parsed") or {}
    te_val = p.get("value_str")
    te_prov = p.get("provider_guess") or ""
    te_src_text = p.get("source_text") or ""
    db = db_src.get(slug, {})
    db_source = db.get("source", "")

    # Get latest data point
    dp_rows = sb.table("data_points").select("date,value,unit").eq("country","GR").eq("indicator",slug).order("date", desc=True).limit(1).execute().data
    db_latest = dp_rows[0] if dp_rows else None
    db_val_str = f"{db_latest['value']} @ {db_latest['date']}" if db_latest else "NONE"

    # Determine "is source aligned?"
    # If TE says ELSTAT but we fetch eurostat, that's a known compromise; document it.
    # If TE says e.g. World Bank and we have worldbank → OK.
    # If TE says EUROSTAT and we have eurostat → OK.
    aligned = "OK"
    fix = None
    if te_prov == "eurostat" and db_source == "eurostat":
        aligned = "OK"
    elif te_prov == "worldbank" and db_source == "worldbank":
        aligned = "OK"
    elif te_prov == "elstat" and db_source == "elstat":
        aligned = "OK"
    elif te_prov == "curated" and db_source == "curated":
        aligned = "OK"
    elif te_prov == "ecb" and db_source == "ecb":
        aligned = "OK"
    elif te_prov == "elstat" and db_source == "eurostat":
        aligned = "TE_ELSTAT_we_eurostat (honest label OK; document gap)"
    elif te_prov == "bog" and db_source in ("eurostat", "ecb"):
        aligned = "TE_BoG_we_eurostat (honest label OK; document gap)"
    elif te_prov == "curated_or_bog" and db_source == "eurostat":
        aligned = "TE_Ministry_we_eurostat (honest label OK)"
    elif te_prov is None or te_prov == "":
        aligned = "TE_no_source_parsed"
    else:
        aligned = f"MISMATCH te={te_prov} db={db_source}"

    print(f"{slug:40s} | {db_source:13s} | {te_prov:12s} | {(te_val or ''):14s} | {db_val_str[:14]:14s} | {aligned}")

    if "MISMATCH" in aligned:
        issues.append((slug, te_prov, db_source, te_val, db_val_str))

print(f"\n=== {len(issues)} MISMATCH(es) ===")
for slug, tp, dbs, tv, dbv in issues:
    print(f"  {slug}: TE={tp} DB={dbs} TE_val={tv} DB_val={dbv}")
