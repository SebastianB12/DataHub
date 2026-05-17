"""Build current-state comparison between TE batch2 values and EconPulse DB."""
import json
import sys
from pathlib import Path

from pipeline.db import supabase as sb

# TE truth (from parsed HTML descriptions, manually verified above)
TE = {
    "energy-inflation": {"label": "INSEE, France", "value": 14.30, "period": "2026-04", "unit": "%"},
    "exports":          {"label": "Ministère de l'Économie et des Finances", "value": 52.5, "period": "2026-03", "unit": "Billion EUR"},
    "food-inflation":   {"label": "INSEE, France", "value": 1.20, "period": "2026-04", "unit": "%"},
    "gdp":              {"label": "World Bank", "value": 3162.08, "period": "2024", "unit": "USD Billion"},
    "gdp-growth-rate":  {"label": "INSEE, France", "value": 0.0, "period": "2026-Q1", "unit": "%"},
    "gdp-per-capita":   {"label": "World Bank", "value": 39441.26, "period": "2024", "unit": "USD"},
    "gdp-per-capita-ppp": {"label": "World Bank", "value": 54464.98, "period": "2024", "unit": "USD"},
    "gdp-real":         {"label": "INSEE, France", "value": 1.1, "period": "2026-Q1", "unit": "% YoY"},
    "government-debt":  {"label": "INSEE, France", "value": 3460.50, "period": "2025-Q4", "unit": "EUR Billion"},
    "government-debt-total": {"label": "INSEE, France", "value": 115.60, "period": "2025", "unit": "% of GDP"},
    "government-spending":   {"label": "INSEE, France", "value": 169953, "period": "2026-Q1", "unit": "EUR Million"},
    "government-spending-eur": {"label": "INSEE/Ministère", "value": None, "period": None, "unit": "EUR Million"},
    "gross-fixed-capital-formation": {"label": "INSEE, France", "value": 142928, "period": "2026-Q1", "unit": "EUR Million"},
    "hospital-beds":    {"label": "OECD", "value": 5.40, "period": "2023", "unit": "per 1000"},
    "house-price-index":{"label": "EUROSTAT", "value": 127.56, "period": "2025-Q4", "unit": "points"},
    "imports":          {"label": "Ministère de l'Économie et des Finances", "value": 59.3, "period": "2026-03", "unit": "Billion EUR"},
    "industrial-production": {"label": "INSEE, France", "value": 0.90, "period": "2026-03", "unit": "% YoY"},
    "inflation-cpi":    {"label": "INSEE, France", "value": 2.2, "period": "2026-04", "unit": "% YoY"},
    "interest-rate":    {"label": "European Central Bank", "value": None, "period": None, "unit": "%"},
    "job-vacancies":    {"label": "DARES, France", "value": 295.20, "period": "2026-03", "unit": "Thousand"},
    "labor-force-participation-rate": {"label": "INSEE, France", "value": 75.60, "period": "2026-Q1", "unit": "%"},
    "labour-costs":     {"label": "European Central Bank", "value": 113.80, "period": "2025-Q4", "unit": "points"},
}

LABEL_TO_CODE = {
    "INSEE, France": "insee",
    "World Bank": "worldbank",
    "Ministère de l'Économie et des Finances": "curated",  # DGDDI/DGFiP, via INSEE balance pdef
    "INSEE/Ministère": "curated",
    "OECD": "curated",
    "EUROSTAT": "eurostat",
    "European Central Bank": "ecb",
    "DARES, France": "curated",
}


def get_db(slug):
    rows = sb.table("indicator_sources").select("*").eq("country", "FR").eq("indicator", slug).eq("is_default", True).eq("active", True).execute().data
    row = rows[0] if rows else None
    dp = sb.table("data_points").select("date, value, source, series_id").eq("country", "FR").eq("indicator", slug).order("date", desc=True).limit(5).execute().data
    return row, dp


def main():
    out = {}
    for slug, te in TE.items():
        row, dp = get_db(slug)
        latest = dp[0] if dp else None
        out[slug] = {
            "te_label": te["label"],
            "te_value": te["value"],
            "te_period": te["period"],
            "te_unit": te["unit"],
            "expected_source_code": LABEL_TO_CODE.get(te["label"]),
            "db_source": row["source"] if row else None,
            "db_series_id": row["series_id"] if row else None,
            "db_extra_params": row.get("extra_params") if row else None,
            "db_latest_value": latest["value"] if latest else None,
            "db_latest_date": latest["date"] if latest else None,
            "db_count": len(dp),
        }
    Path("docs/_audit_fr_batch2_compare.json").write_text(json.dumps(out, indent=2, default=str), "utf-8")
    for slug, d in out.items():
        src_match = (d["db_source"] == d["expected_source_code"])
        print(f"{slug:42s} src={d['db_source']}/{d['expected_source_code']} match={src_match}  db_val={d['db_latest_value']} ({d['db_latest_date']})  te={d['te_value']} ({d['te_period']})")


if __name__ == "__main__":
    main()
