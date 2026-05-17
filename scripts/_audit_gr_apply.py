"""Apply GR re-audit fixes:
1) minimum-wages: switch from curated → eurostat earn_mw_cur (currency=EUR)
2) Update curated GR yaml: social-security rates, hospital-beds, terrorism-index,
   corruption-index, corruption-rank to latest TE values
3) Delete stale data_points for minimum-wages so eurostat reseeds cleanly
4) Update docs/te_sources_truth.yaml minimum-wages entry
"""
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.db import supabase as sb  # noqa: E402

# --- 1) Switch minimum-wages from curated to eurostat ----------------

# 1a. Demote existing curated default for minimum-wages
print("=== Step 1: minimum-wages curated -> eurostat ===")
existing = sb.table("indicator_sources").select("*").eq("country","GR").eq("indicator","minimum-wages").execute().data
print(f"  Existing rows: {[(r['source'], r.get('is_default'), r.get('series_id')) for r in existing]}")

for r in existing:
    if r["source"] == "curated":
        sb.table("indicator_sources").update({"is_default": False, "active": False}).eq("indicator","minimum-wages").eq("country","GR").eq("source","curated").execute()
        print("  -> curated demoted (is_default=False, active=False)")

# 1b. Insert / upsert eurostat row
eurostat_row = {
    "indicator": "minimum-wages",
    "country": "GR",
    "source": "eurostat",
    "series_id": "earn_mw_cur:EL:EUR",
    "transform": "",
    "conversion": 1,
    "unit": "EUR/Month",
    "adjustment": "",
    "freq_hint": "S",
    "extra_params": {
        "params": {"currency": "EUR"},
        "dataset": "earn_mw_cur",
    },
    "active": True,
    "note": "Eurostat earn_mw_cur (Monthly minimum wages, bi-annual), GR=geo EL, EUR/month gross. TE attributes EUROSTAT.",
    "is_default": True,
}
# Insert (no upsert — no unique constraint configured for this combination)
sb.table("indicator_sources").insert(eurostat_row).execute()
print("  -> eurostat row inserted/updated as default")

# 1c. Delete current data_points for minimum-wages/GR to force clean reseed
delete_count = sb.table("data_points").delete().eq("country","GR").eq("indicator","minimum-wages").execute()
print(f"  -> data_points cleared for GR/minimum-wages")

# --- 2) Update curated GR yaml with TE-fresh values ------------------
print("\n=== Step 2: update curated GR yaml ===")
yaml_path = ROOT / "pipeline" / "curated" / "gr.yaml"
content = yaml_path.read_text(encoding="utf-8")

# Targeted in-place edits — preserve YAML formatting/comments
updates = [
    # (old line, new line)
    ('  value: 36.16\n  date: "2026-12-31"', '  value: 35.16\n  date: "2026-12-31"'),  # social-security-rate
    ('  value: 22.29\n  date: "2026-12-31"', '  value: 21.79\n  date: "2026-12-31"'),  # social-security-rate-companies
    ('  value: 13.87\n  date: "2026-12-31"', '  value: 13.37\n  date: "2026-12-31"'),  # social-security-rate-employees
    # minimum-wages curated entry → comment out (eurostat will provide)
    ('minimum-wages:\n  value: 880\n  date: "2026-04-01"\n  unit: "EUR/Month"\n  note: "Κατώτατος μισθός 2026."',
     '# minimum-wages: served by eurostat earn_mw_cur (geo=EL, currency=EUR), TE conform.'),
    # corruption-index 49 -> 50 (2025 TI)
    ('corruption-index:\n  value: 49\n  date: "2025-12-31"\n  unit: "Points"',
     'corruption-index:\n  value: 50\n  date: "2025-12-31"\n  unit: "Points"'),
    # corruption-rank 59 -> 56 (2025 TI)
    ('corruption-rank:\n  value: 59\n  date: "2025-12-31"\n  unit: "Rank"',
     'corruption-rank:\n  value: 56\n  date: "2025-12-31"\n  unit: "Rank"'),
    # hospital-beds 4.21 (2022) -> 4.24 (2023)
    ('hospital-beds:\n  value: 4.21\n  date: "2022-12-31"',
     'hospital-beds:\n  value: 4.24\n  date: "2023-12-31"'),
    # terrorism-index 4.5 -> 2.79 (2025 IEP GTI)
    ('terrorism-index:\n  value: 4.5\n  date: "2025-12-31"\n  unit: "Points"',
     'terrorism-index:\n  value: 2.79\n  date: "2025-12-31"\n  unit: "Points"'),
]

for old, new in updates:
    if old in content:
        content = content.replace(old, new)
        # print which one applied via first line of old
        print(f"  applied: {old.splitlines()[0]}")
    else:
        print(f"  SKIP (not found): {old.splitlines()[0]}")
yaml_path.write_text(content, encoding="utf-8")

# --- 3) Update docs/te_sources_truth.yaml minimum-wages --------------
print("\n=== Step 3: update truth.yaml minimum-wages ===")
truth_path = ROOT / "docs" / "te_sources_truth.yaml"
truth = yaml.safe_load(truth_path.read_text(encoding="utf-8"))
truth["GR"]["minimum-wages"] = {
    "source": "eurostat",
    "te_label": "EUROSTAT",
    "te_page": "https://tradingeconomics.com/greece/minimum-wages",
    "te_url": "https://ec.europa.eu/eurostat/",
    "verified": True,
    "series_id": "earn_mw_cur:EL:EUR",
    "note": "Switched from curated to Eurostat earn_mw_cur (TE-conform). 2026-S1 = 1027 EUR/Month.",
}
truth_path.write_text(yaml.dump(truth, allow_unicode=True, sort_keys=False, width=200), encoding="utf-8")
print("  -> truth.yaml updated for GR.minimum-wages")

print("\nApplied. Next: run eurostat + curated providers.")
