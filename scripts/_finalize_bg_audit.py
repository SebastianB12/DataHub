"""Write final BG re-audit YAML combining sources + values + verdicts."""
import json, yaml, os
from datetime import date

SLUGS = json.load(open("docs/_audit_all_remaining_slugs.json"))["BG"]
findings = yaml.safe_load(open("docs/_audit_bg_reaudit.yaml", encoding="utf-8"))
values = json.load(open("docs/_audit_bg_te_values.json", encoding="utf-8"))

# merge values into findings + add fresh date
for slug in SLUGS:
    f = findings.get(slug, {})
    v = values.get(slug, {})
    f["te_latest_value"] = v.get("te_latest_value")
    f["te_period"] = v.get("te_period")
    f["te_unit_hint"] = v.get("te_unit_hint")
    f["db_latest_date"] = v.get("db_latest_date")
    f["db_latest_value"] = v.get("db_latest_value")
    f["db_unit"] = v.get("db_unit")
    f["audit_date"] = date.today().isoformat()
    # decisions
    decisions = []
    if f["verdict"] == "te_no_page":
        decisions.append("coverage_gap_kept_as_internal_eurostat_curated")
    elif f["verdict"] == "source_mismatch":
        # honest fetch label: keep DB source. te_label captured in truth.yaml.
        decisions.append("honest_fetch_label_kept (TE attributes upstream NSI/MoF/etc., we fetch from eurostat/curated)")
    elif f["verdict"] == "ok":
        decisions.append("no_change")
    elif f["verdict"] == "unknown_source":
        decisions.append("mapped_typo_to_curated_or_eurostat")
    elif f["verdict"] == "unparsed":
        decisions.append("kept_curated (credit-rating TE has no parseable source attribution)")
    f["decision"] = decisions
    findings[slug] = f

with open("docs/_audit_bg_reaudit.yaml", "w", encoding="utf-8") as f:
    yaml.safe_dump(findings, f, sort_keys=True, allow_unicode=True, width=140)

# Print summary
by_v = {}
match_value = 0
diff_value = 0
no_te = 0
for slug, d in findings.items():
    by_v.setdefault(d["verdict"], []).append(slug)
    te = d.get("te_latest_value")
    db = d.get("db_latest_value")
    if te is None and db is None:
        pass
    elif te is None:
        no_te += 1
    else:
        if db is None:
            diff_value += 1
        else:
            try:
                if abs(te - db) / max(abs(te), abs(db), 1e-9) < 0.05:
                    match_value += 1
                else:
                    diff_value += 1
            except Exception:
                diff_value += 1

print(f"\n=== BG re-audit summary ===")
print(f"Total slugs: {len(SLUGS)}")
print(f"Verdict breakdown:")
for v in sorted(by_v):
    print(f"  {v}: {len(by_v[v])}")
print(f"\nValue-comparison (where TE numeric available):")
print(f"  match (~5%): {match_value}")
print(f"  diff/concept-mismatch (frontend-only YoY etc.): {diff_value}")
print(f"  no_te_value: {no_te}")
