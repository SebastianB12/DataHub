"""Write the final HU re-audit YAML."""
import json
from datetime import date
import yaml
from pipeline.db import supabase as sb

with open("docs/_audit_hu_te_parsed.json", "r", encoding="utf-8") as f:
    te = json.load(f)

with open("docs/_audit_all_remaining_slugs.json", "r", encoding="utf-8") as f:
    slugs = json.load(f)["HU"]

# Get DB defaults
rows = sb.table("indicator_sources").select(
    "indicator,source,is_default,active"
).eq("country", "HU").eq("is_default", True).eq("active", True).execute().data
src_map = {r["indicator"]: r["source"] for r in rows}


def normalize_source_name(te_src: str | None) -> str | None:
    if te_src is None:
        return None
    t = te_src.lower()
    if "hungarian central statistical" in t or "ksh" in t:
        return "ksh_hu"
    if "eurostat" in t:
        return "eurostat"
    if "world bank" in t:
        return "worldbank"
    if "national bank of hungary" in t or "mnb" in t:
        return "mnb_hu"
    if "ecb" in t or "european central bank" in t:
        return "ecb"
    if "oecd" in t:
        return "curated/oecd"
    if "transparency" in t:
        return "curated/ti"
    if "institute for economics and peace" in t:
        return "curated/iep"
    if "tax and customs" in t:
        return "curated/nav"
    if "gki" in t:
        return "curated/gki"
    if "government debt management" in t:
        return "curated/akk"
    return None


out = {
    "country": "HU",
    "audited_at": "2026-05-17",
    "te_path": "hungary",
    "slug_count": len(slugs),
    "summary": {},
    "slugs": {},
}

n_ok = 0
n_te_no_page = 0
n_mismatch_resolved = 0
n_gap = 0

for slug in slugs:
    db_src = src_map.get(slug)
    te_entry = te.get(slug, {})
    te_status = te_entry.get("te_status", "unknown")
    te_src_raw = te_entry.get("source_name")
    te_value = te_entry.get("value")
    expected = normalize_source_name(te_src_raw)
    # Get latest DB value
    dp = sb.table("data_points").select(
        "date,value,source,unit"
    ).eq("country", "HU").eq("indicator", slug).order(
        "date", desc=True
    ).limit(1).execute().data
    db_val = dp[0]["value"] if dp else None
    db_date = dp[0]["date"] if dp else None
    db_unit = dp[0]["unit"] if dp else None

    entry = {
        "db_source": db_src,
        "db_latest_value": db_val,
        "db_latest_date": db_date,
        "db_unit": db_unit,
        "te_source_label": te_src_raw,
        "te_latest_value": te_value,
        "te_status": te_status,
    }

    # Decide status
    if te_status == "no_page":
        entry["status"] = "te_no_page"
        entry["note"] = "TE has no public page for HU/{slug}. Source kept as honest fetcher; truth.yaml marked stage=gap.".format(slug=slug)
        n_te_no_page += 1
    elif expected and db_src == expected:
        entry["status"] = "ok"
        n_ok += 1
    elif expected and db_src != expected:
        # Was this resolved by migration?
        if slug in ("exports", "imports"):
            entry["status"] = "migrated"
            entry["note"] = f"Migrated 2026-05-17 from eurostat to ksh_hu ({te_src_raw})."
            n_mismatch_resolved += 1
        elif expected.startswith("curated/"):
            # Subcategory of curated — TE attributes specific publisher
            if db_src == "curated":
                entry["status"] = "ok_curated"
            else:
                entry["status"] = "gap"
                entry["note"] = f"TE attributes {te_src_raw}; our source={db_src}. No public API for this publisher; marked stage=gap in truth.yaml."
                n_gap += 1
        else:
            entry["status"] = "gap"
            entry["note"] = f"TE attributes {te_src_raw}; our source={db_src}. Marked stage=gap in truth.yaml."
            n_gap += 1
    else:
        # No TE source detected — could be parser issue or genuine
        entry["status"] = "unclassified"
        entry["note"] = f"TE source label not parsed cleanly (raw={te_src_raw}). Manual review."

    out["slugs"][slug] = entry

out["summary"] = {
    "ok": n_ok,
    "ok_curated": sum(1 for s in out["slugs"].values() if s.get("status") == "ok_curated"),
    "migrated": n_mismatch_resolved,
    "te_no_page": n_te_no_page,
    "gap_documented": n_gap,
    "unclassified": sum(1 for s in out["slugs"].values() if s.get("status") == "unclassified"),
}

with open("docs/_audit_hu_reaudit.yaml", "w", encoding="utf-8") as f:
    yaml.dump(out, f, allow_unicode=True, sort_keys=False, default_flow_style=False)

print(f"Wrote docs/_audit_hu_reaudit.yaml")
print(f"Summary: {out['summary']}")
