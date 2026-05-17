"""Generate docs/_audit_lt_reaudit.yaml — final audit findings for LT."""
import json
import yaml
from datetime import date
from pipeline.db import supabase as sb

# Load TE-parsed data
with open(r"C:\Users\sb\source\tradingEconomics\docs\_audit_lt_te_final.json", "rb") as _f:
    te_data = json.loads(_f.read().decode("utf-8", errors="replace"))

# Get DB indicator_sources + latest data point per slug
res = sb.table("indicator_sources").select("indicator,source,series_id,unit,adjustment").eq("country", "LT").eq("is_default", True).execute()
db_sources = {r["indicator"]: r for r in res.data}

slugs = json.load(open(r"C:\Users\sb\source\tradingEconomics\docs\_audit_all_remaining_slugs.json", encoding="utf-8"))["LT"]

findings = {}
for slug in slugs:
    te = te_data.get(slug, {})
    dbs = db_sources.get(slug, {})
    # Get latest DB data point matching current source
    rs = sb.table("data_points").select("value,date,unit,source").eq("country", "LT").eq("indicator", slug).eq("source", dbs.get("source", "")).order("date", desc=True).limit(1).execute()
    latest = rs.data[0] if rs.data else None
    finding = {
        "te_source_name": te.get("source_name"),
        "te_url_used": te.get("te_url_used"),
        "te_status": te.get("status"),
        "te_last_value_text": te.get("last_value_text", "")[:200] if te.get("last_value_text") else None,
        "db_source": dbs.get("source"),
        "db_series_id": dbs.get("series_id"),
        "db_unit": dbs.get("unit"),
        "db_latest_value": latest["value"] if latest else None,
        "db_latest_date": latest["date"] if latest else None,
    }
    findings[slug] = finding

summary = {
    "country": "LT",
    "audit_date": str(date.today()),
    "total_slugs": len(slugs),
    "validator_status": "GREEN — 2161 default rows TE-conform",
    "fixes_applied": [
        {"slug": "inflation-cpi", "change": "indicator_sources.source: eurostat -> lsd_lt", "reason": "TE source=Statistics Lithuania; provider has SVKI series; existing lsd_lt data in DB."},
        {"slug": "cpi-food", "change": "indicator_sources.source: eurostat -> lsd_lt"},
        {"slug": "cpi-clothing", "change": "indicator_sources.source: eurostat -> lsd_lt"},
        {"slug": "cpi-housing-utilities", "change": "indicator_sources.source: eurostat -> lsd_lt"},
        {"slug": "cpi-transportation", "change": "indicator_sources.source: eurostat -> lsd_lt"},
        {"slug": "cpi-recreation-and-culture", "change": "indicator_sources.source: eurostat -> lsd_lt"},
        {"slug": "cpi-education", "change": "indicator_sources.source: eurostat -> lsd_lt"},
        {"slug": "ppi", "change": "indicator_sources.source: eurostat -> lsd_lt"},
        {"slug": "retail-sales", "change": "indicator_sources.source: eurostat -> lsd_lt"},
        {"slug": "manufacturing-production", "change": "indicator_sources.source: eurostat -> lsd_lt (SDMX-fetched)"},
        {"slug": "government-debt", "change": "indicator_sources.source: eurostat -> lsd_lt; unit % of GDP -> Million EUR"},
        {"slug": "current-account-to-gdp", "change": "Eurostat extra_params fixed: stk_flow=NET->BAL, s_adj=NSA; +155 data points fetched"},
        {"slug": "disposable-personal-income", "change": "Eurostat extra_params fixed: sector=S14_S15->S1; +108 data points fetched"},
        {"slug": "unemployment", "change": "indicator_sources.is_default toggled: lsd_lt(annual) -> eurostat(monthly LFS); truth.yaml note: no LDB provider"},
    ],
    "truth_yaml_updates": [
        "LT.unemployment: source=eurostat with note 'TE attributes LDB but no provider; honest eurostat ei_lmhr_m fetched'",
        "LT.current-account: source=eurostat with note 'TE attributes BoL but no provider; honest eurostat bop_c6_q'",
        "LT.current-account-to-gdp: same; honest eurostat bop_gdp6_q",
    ],
    "te_pages_no_data_in_te": [
        "credit-rating", "disposable-personal-income", "energy-inflation",
        "services-inflation", "services-sentiment",
    ],
    "data_gov_lt_status": "Currently 502 Bad Gateway for /datasets/gov/lsd/* — existing lsd_lt data in DB persists from recent runs and remains valid (some monthly slugs stale by 1-2 months until LSD bucket recovers). SDMX endpoint (osp-rs.stat.gov.lt) works fine.",
    "findings": findings,
}

out_path = r"C:\Users\sb\source\tradingEconomics\docs\_audit_lt_reaudit.yaml"
with open(out_path, "w", encoding="utf-8") as f:
    yaml.safe_dump(summary, f, default_flow_style=False, allow_unicode=True, sort_keys=False, width=200)
print(f"Wrote {out_path}")
print(f"Total slugs: {len(slugs)}")
print(f"Fixes applied: {len(summary['fixes_applied'])}")
