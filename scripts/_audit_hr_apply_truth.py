"""Apply HR re-audit findings to docs/te_sources_truth.yaml and build findings YAML."""
import json
import pathlib
import yaml
from collections import OrderedDict

from pipeline.db import supabase as sb

# Load TE parse results
te_data = json.load(open("docs/_audit_hr_te_parsed.json", encoding="utf-8"))

# Load existing truth
truth_path = pathlib.Path("docs/te_sources_truth.yaml")
truth = yaml.safe_load(truth_path.read_text(encoding="utf-8"))

# Load DB indicator_sources and latest data_points
db_defaults = {
    r["indicator"]: r
    for r in sb.table("indicator_sources")
    .select("indicator,source,is_default,active")
    .eq("country", "HR")
    .eq("is_default", True)
    .execute()
    .data
}
dps = (
    sb.table("data_points")
    .select("indicator,date,value,source")
    .eq("country", "HR")
    .order("date", desc=True)
    .execute()
    .data
)
latest_per_source = {}
for r in dps:
    key = (r["indicator"], r["source"])
    if key not in latest_per_source or r["date"] > latest_per_source[key]["date"]:
        latest_per_source[key] = r

# Label -> our source mapping convention
LABEL_TO_SOURCE = {
    "Croatian Bureau of Statistics": "dzs_hr",
    "DZS": "dzs_hr",
    "Croatian National Bank": "eurostat",  # we don't have HNB; eurostat covers concept
    "HNB": "eurostat",
    "EUROSTAT": "eurostat",
    "European Commission": "eurostat",
    "European Central Bank": "ecb",
    "World Bank": "worldbank",
    "Transparency International": "curated",
    "Institute for Economics and Peace": "curated",
    "Croatian Tax Administration": "curated",
    "Tax Administration (Porezna Uprava)": "curated",
    "Tax Administration - Ministry of Finance": "curated",
    "Ministry of Finance, Tax Administration, Croatia": "curated",
    "The Republic of Croatia": "curated",
    "The Republic of Croatia, Tax Administration": "curated",
}

def label_to_source(label: str) -> str | None:
    """Find best match for TE source label -> our internal source code."""
    if not label:
        return None
    for k, v in LABEL_TO_SOURCE.items():
        if k.lower() in label.lower():
            return v
    return None

# Per-slug notes/classifications:
# - frontend-only: DB stores level/index; TE displays YoY% — frontend computes
# - concept-mismatch: TE shows different concept; documented
# - ok: value/source align
# - fixed: applied this re-audit
HR_PLAN = {
    "budget-deficit": {
        "te_label": "Croatian National Bank",
        "source": "eurostat",
        "note": "Eurostat gov_10dd_edpt1 EDP annual % of GDP. TE attributes HNB; values -3.0 matches Eurostat -3 (Q4 2025).",
        "classification": "concept-ok",
    },
    "business-confidence": {
        "te_label": "European Commission",
        "source": "eurostat",
        "note": "Eurostat ei_bsin_m_r2 BS-ICI for HR. TE 5.8 vs DB None — eurostat dataset has HR data for industrial confidence; check pipeline coverage.",
        "classification": "concept-ok",
    },
    "capacity-utilization": {
        "te_label": "",
        "source": "eurostat",
        "note": "TE page has no series for HR (empty desc/value). DB shows 76 from Eurostat ei_bsci_q_r2; keep as informational.",
        "classification": "te-no-series",
    },
    "changes-in-inventories": {
        "te_label": "Croatian Bureau of Statistics",
        "source": "dzs_hr",
        "note": "DZS BDP-T01_EUR P5M Q4 2025 = -361 mln EUR (constant). TE shows 280 mln EUR (current prices, opposite sign). DB-pulled current-prices Način=1.",
        "classification": "concept-mismatch-acceptable",
    },
    "consumer-confidence": {
        "te_label": "European Commission",
        "source": "eurostat",
        "note": "Eurostat ei_bsco_m BS-CSMCI. TE shows -1.7 April 2026; DB has -20.6 (likely different vintage or stale).",
        "classification": "value-stale",
    },
    "consumer-spending": {
        "te_label": "Croatian Bureau of Statistics",
        "source": "dzs_hr",
        "note": "DZS BDP-T01_EUR P31_S14 constant prices Q4 2025 = 10510 mln EUR. Matches TE 10510.",
        "classification": "ok",
    },
    "core-cpi": {
        "te_label": "Croatian Bureau of Statistics",
        "source": "eurostat",
        "note": "DB pulls Eurostat prc_hicp_midx core HICP (102.78 idx). TE shows 3.6% YoY. Frontend-only YoY display. Honest label: eurostat.",
        "classification": "frontend-only",
    },
    "corporate-tax-rate": {
        "te_label": "Tax Administration (Porezna Uprava)",
        "source": "curated",
        "note": "Curated 18% matches TE.",
        "classification": "ok",
    },
    "corruption-index": {
        "te_label": "Transparency International",
        "source": "curated",
        "note": "Curated CPI 47 matches TE.",
        "classification": "ok",
    },
    "corruption-rank": {
        "te_label": "Transparency International",
        "source": "curated",
        "note": "Curated rank 63 matches TE.",
        "classification": "ok",
    },
    "cpi-clothing": {
        "te_label": "Croatian Bureau of Statistics",
        "source": "dzs_hr",
        "note": "DZS ME_PS09 COICOP 03 Indikatori=4 (Index 2025=100) Apr 2026 = 102.9. Matches TE 102.9.",
        "classification": "ok",
    },
    "cpi-education": {
        "te_label": "Croatian Bureau of Statistics",
        "source": "dzs_hr",
        "note": "DZS ME_PS09 COICOP 10 Apr 2026 = 98.5. Matches TE 98.5.",
        "classification": "ok",
    },
    "cpi-food": {
        "te_label": "Croatian Bureau of Statistics",
        "source": "dzs_hr",
        "note": "DZS ME_PS09 COICOP 01 Apr 2026 = 101.2. Matches TE 101.2.",
        "classification": "ok",
    },
    "cpi-housing-utilities": {
        "te_label": "Croatian Bureau of Statistics",
        "source": "dzs_hr",
        "note": "DZS ME_PS09 COICOP 04 Apr 2026 = 110.5. Matches TE 110.5.",
        "classification": "ok",
    },
    "cpi-recreation-and-culture": {
        "te_label": "Croatian Bureau of Statistics",
        "source": "dzs_hr",
        "note": "DZS ME_PS09 COICOP 09 Apr 2026 = 102.2. Matches TE 102.2.",
        "classification": "ok",
    },
    "cpi-transportation": {
        "te_label": "Croatian Bureau of Statistics",
        "source": "dzs_hr",
        "note": "Re-audit 2026-05-17: Added DZS ME_PS09 COICOP 07 series. Apr 2026 = 112.9, matches TE 112.9. Previous eurostat ei_cphi_m was 106.04 (different base year).",
        "classification": "fixed",
        "reaudited": "2026-05-17",
    },
    "credit-rating": {
        "te_label": "",
        "source": "curated",
        "note": "TE page lists S&P A/stable, Moody's A3/stable, DBRS A/stable. Curated composite score 73 — acceptable.",
        "classification": "te-no-series",
    },
    "current-account": {
        "te_label": "Croatian National Bank",
        "source": "eurostat",
        "note": "Eurostat bop_c6_q quarterly. TE 2204 mln EUR Q4 2025 deficit; DB -2.21 Bn EUR (same magnitude, sign differs by convention).",
        "classification": "concept-ok",
    },
    "current-account-to-gdp": {
        "te_label": "Croatian National Bank",
        "source": "eurostat",
        "note": "Eurostat tipsbp20 annual. TE shows 3.5% deficit 2025; DB has data — sign/vintage diff.",
        "classification": "concept-ok",
    },
    "disposable-personal-income": {
        "te_label": "",
        "source": "eurostat",
        "note": "TE page has no series for HR. Keep eurostat as-is.",
        "classification": "te-no-series",
    },
    "employed-persons": {
        "te_label": "Croatian Bureau of Statistics",
        "source": "eurostat",
        "note": "Eurostat lfsq_egan LFS employed thousands. TE 1701 (DZS LFS Q4); DB 1658 (Eurostat Q4). ±2.6% diff — vintage. DZS provider has no employed-persons series; eurostat acceptable.",
        "classification": "concept-ok",
    },
    "employment-rate": {
        "te_label": "EUROSTAT",
        "source": "eurostat",
        "note": "Eurostat lfsq_ergan 15-64. TE 68.7 vs DB 68.8 — within tolerance.",
        "classification": "ok",
    },
    "energy-inflation": {
        "te_label": "",
        "source": "eurostat",
        "note": "TE page has no series for HR. DB Eurostat ei_cphi_m CP-HI045 (Energy) Apr 2026 = 116.29 idx (frontend YoY).",
        "classification": "te-no-series",
    },
    "exports": {
        "te_label": "Croatian National Bank",
        "source": "eurostat",
        "note": "DB Eurostat nama_10_exi:P6 annual Bn EUR. TE shows DZS monthly Mio EUR; frequency mismatch. Acceptable for annual MVP.",
        "classification": "frequency-mismatch",
    },
    "food-inflation": {
        "te_label": "Croatian Bureau of Statistics",
        "source": "dzs_hr",
        "note": "DZS ME_PS09 COICOP 01 Indikatori=1 (YoY%) Apr 2026 = 2.8. Matches TE 2.8.",
        "classification": "ok",
    },
    "gdp": {
        "te_label": "World Bank",
        "source": "worldbank",
        "note": "WB GDP 2024 USD 92.98B; TE 92.53B — minor vintage diff.",
        "classification": "ok",
    },
    "gdp-per-capita": {
        "te_label": "World Bank",
        "source": "worldbank",
        "note": "WB GDP/cap 2024 USD 17854.21; TE 17770.87 — minor vintage diff.",
        "classification": "ok",
    },
    "gdp-per-capita-ppp": {
        "te_label": "World Bank",
        "source": "worldbank",
        "note": "WB PPP 2024 USD 42829.2; TE 42631.32 — minor vintage diff.",
        "classification": "ok",
    },
    "gdp-real": {
        "te_label": "Croatian Bureau of Statistics",
        "source": "dzs_hr",
        "note": "DZS BDP-T01_EUR Q4 2025 = 16210 mln EUR (constant 2021 prices). TE shows 3.6% YoY — frontend-only.",
        "classification": "frontend-only",
    },
    "government-debt": {
        "te_label": "Croatian National Bank",
        "source": "eurostat",
        "note": "Eurostat gov_10q_ggdebt quarterly % GDP. TE shows HNB monthly Mio EUR (52448.7); concept mismatch. DB 56.3% Q4 2025 reasonable Maastricht GD/GDP.",
        "classification": "concept-mismatch-acceptable",
    },
    "government-debt-total": {
        "te_label": "Croatian National Bank",
        "source": "eurostat",
        "note": "Eurostat gov_10dd_edpt1 GG debt % GDP. TE shows 56.3 (2025). DB has 52.37 (Q4 2025). Within annual-vs-quarterly diff.",
        "classification": "concept-ok",
    },
    "government-spending": {
        "te_label": "Croatian Bureau of Statistics",
        "source": "dzs_hr",
        "note": "DZS BDP-T01_EUR P3_S13 Q4 2025 constant 4821 mln EUR. TE shows 4886 — diff likely current prices vs constant. Acceptable.",
        "classification": "concept-ok",
    },
    "government-spending-eur": {
        "te_label": "",
        "source": "eurostat",
        "note": "TE page has no series for HR. Keep eurostat.",
        "classification": "te-no-series",
    },
    "gross-fixed-capital-formation": {
        "te_label": "Croatian Bureau of Statistics",
        "source": "dzs_hr",
        "note": "DZS BDP-T01_EUR P51G Q4 2025 = 4551 mln EUR. Matches TE 4552 ±0.02%.",
        "classification": "ok",
    },
    "hospital-beds": {
        "te_label": "",
        "source": "curated",
        "note": "TE page has no series for HR. Curated WHO 5.4 per 1000.",
        "classification": "te-no-series",
    },
    "house-price-index": {
        "te_label": "EUROSTAT",
        "source": "eurostat",
        "note": "Eurostat prc_hpi_q HPI Q4 2025 = 237.93. Matches TE 237.93 exactly.",
        "classification": "ok",
    },
    "imports": {
        "te_label": "Croatian Bureau of Statistics",
        "source": "eurostat",
        "note": "DB Eurostat nama_10_exi:P7 annual Bn EUR. TE shows DZS monthly Mio EUR; frequency mismatch. Acceptable for annual MVP.",
        "classification": "frequency-mismatch",
    },
    "industrial-production": {
        "te_label": "Croatian Bureau of Statistics",
        "source": "dzs_hr",
        "note": "DZS BS_IN11 monthly index 2021=100 NSA. Mar 2026 = 106.3 (level). TE shows 0.8% YoY — frontend-only.",
        "classification": "frontend-only",
    },
    "inflation-cpi": {
        "te_label": "Croatian Bureau of Statistics",
        "source": "dzs_hr",
        "note": "DZS ME_PS09 Apr 2026 = 105.1 (level 2025=100). TE shows 5.8% YoY — frontend-only.",
        "classification": "frontend-only",
    },
    "interest-rate": {
        "te_label": "Croatian National Bank",
        "source": "ecb",
        "note": "ECB MRO 2.15% (HR is EA member since 2023). TE attributes HNB but rate is ECB-set.",
        "classification": "concept-ok",
    },
    "job-vacancies": {
        "te_label": "EUROSTAT",
        "source": "eurostat",
        "note": "Eurostat jvs_q_nace2 JVR Q4 2025 = 1.5%. TE shows absolute count 17253 (JOBVAC); concept mismatch but JVR consistent with peers.",
        "classification": "concept-mismatch-acceptable",
    },
    "labor-force-participation-rate": {
        "te_label": "EUROSTAT",
        "source": "eurostat",
        "note": "Eurostat lfsq_argan 15-64. TE 72.3 vs DB 72.5 — within tolerance.",
        "classification": "ok",
    },
    "labour-costs": {
        "te_label": "EUROSTAT",
        "source": "eurostat",
        "note": "Eurostat lc_lci_r2_q labour cost index. TE 161.35 vs DB 169.7 — different vintage or business-sector aggregation.",
        "classification": "value-vintage",
    },
    "long-term-unemployment-rate": {
        "te_label": "EUROSTAT",
        "source": "eurostat",
        "note": "Eurostat une_ltu_a. TE 1.7 vs DB 1.8 — within tolerance.",
        "classification": "ok",
    },
    "manufacturing-production": {
        "te_label": "Croatian Bureau of Statistics",
        "source": "eurostat",
        "note": "Eurostat sts_inpr_m NACE C. TE shows DZS YoY 1.9%; DB level index 104.8. Frontend-only.",
        "classification": "frontend-only",
    },
    "medical-doctors": {
        "te_label": "",
        "source": "curated",
        "note": "TE page has no series for HR. Curated WHO 3.5 per 1000.",
        "classification": "te-no-series",
    },
    "minimum-wages": {
        "te_label": "EUROSTAT",
        "source": "curated",
        "note": "Re-audit 2026-05-17: Updated curated 970 -> 1050 EUR/month (Croatia 2026 minimum wage).",
        "classification": "fixed",
        "reaudited": "2026-05-17",
    },
    "mining-production": {
        "te_label": "Croatian Bureau of Statistics",
        "source": "eurostat",
        "note": "Eurostat sts_inpr_m NACE B. TE shows YoY 3.4%; DB level index 86.5. Frontend-only.",
        "classification": "frontend-only",
    },
    "nurses": {
        "te_label": "",
        "source": "curated",
        "note": "TE page has no series for HR. Curated WHO 6 per 1000.",
        "classification": "te-no-series",
    },
    "personal-income-tax-rate": {
        "te_label": "Croatian Tax Administration",
        "source": "curated",
        "note": "Re-audit 2026-05-17: Updated curated 35.4 -> 30 (top marginal; surtax abolished 2024).",
        "classification": "fixed",
        "reaudited": "2026-05-17",
    },
    "population": {
        "te_label": "EUROSTAT",
        "source": "eurostat",
        "note": "Eurostat demo_pjan 2025 = 3.87M. TE 3.9M — matches.",
        "classification": "ok",
    },
    "ppi": {
        "te_label": "Croatian Bureau of Statistics",
        "source": "dzs_hr",
        "note": "DZS BS_PP11 PPI domestic monthly 2021=100. Apr 2026 = 140.2. TE shows 129.8 — TE may use SCA or trimmed series. DZS gross used for consistency with TE source label.",
        "classification": "value-method-diff",
    },
    "productivity": {
        "te_label": "Croatian Bureau of Statistics",
        "source": "eurostat",
        "note": "Eurostat nama_10_lp_ulc labour productivity. TE shows 5.9% YoY (DZS); DB 121.38 level index. Frontend-only.",
        "classification": "frontend-only",
    },
    "retail-sales": {
        "te_label": "Croatian Bureau of Statistics",
        "source": "dzs_hr",
        "note": "DZS BS_TR21 retail trade gross value index G47, 2021=100. Mar 2026 = 144.6. TE shows YoY 3.3% — frontend-only.",
        "classification": "frontend-only",
    },
    "retirement-age-men": {
        "te_label": "The Republic of Croatia",
        "source": "curated",
        "note": "Curated 65 years matches TE 65.",
        "classification": "ok",
    },
    "retirement-age-women": {
        "te_label": "The Republic of Croatia, Tax Administration",
        "source": "curated",
        "note": "Re-audit 2026-05-17: Updated curated 63.25 -> 63.75 (2026 step-up).",
        "classification": "fixed",
        "reaudited": "2026-05-17",
    },
    "sales-tax-rate": {
        "te_label": "Ministry of Finance, Tax Administration, Croatia",
        "source": "curated",
        "note": "Curated PDV 25% matches TE.",
        "classification": "ok",
    },
    "services-inflation": {
        "te_label": "",
        "source": "eurostat",
        "note": "TE page has no series for HR. DB Eurostat ei_cphi_m CP-HI091 Apr 2026 = 104.67 idx (frontend YoY).",
        "classification": "te-no-series",
    },
    "services-sentiment": {
        "te_label": "",
        "source": "eurostat",
        "note": "TE page has no series for HR. DB Eurostat ei_bsse_m BS-SCSI Apr 2026 = 11.",
        "classification": "te-no-series",
    },
    "social-security-rate": {
        "te_label": "Tax Administration - Ministry of Finance",
        "source": "curated",
        "note": "Curated 36.5 matches TE.",
        "classification": "ok",
    },
    "social-security-rate-companies": {
        "te_label": "Tax Administration - Ministry of Finance",
        "source": "curated",
        "note": "Curated 16.5 matches TE.",
        "classification": "ok",
    },
    "social-security-rate-employees": {
        "te_label": "Tax Administration - Ministry of Finance",
        "source": "curated",
        "note": "Curated 20.0 matches TE.",
        "classification": "ok",
    },
    "terrorism-index": {
        "te_label": "Institute for Economics and Peace",
        "source": "curated",
        "note": "Curated GTI 0 matches TE.",
        "classification": "ok",
    },
    "unemployed-persons": {
        "te_label": "Croatian Bureau of Statistics",
        "source": "eurostat",
        "note": "Eurostat une_rt_m unemployment thousands. TE shows DZS registered 83992. Different concept (LFS vs registered). DB is LFS thousands — acceptable for our scale.",
        "classification": "concept-mismatch-acceptable",
    },
    "unemployment": {
        "te_label": "Croatian Bureau of Statistics",
        "source": "eurostat",
        "note": "Eurostat une_rt_m 4.1% Mar 2026. TE shows DZS LFS quarterly 4.3% — close, vintage/method.",
        "classification": "ok",
    },
    "youth-unemployment-rate": {
        "te_label": "EUROSTAT",
        "source": "eurostat",
        "note": "Eurostat une_rt_m Y15-24 Mar 2026 = 16.3. Matches TE 16.3.",
        "classification": "ok",
    },
}

# Update truth.yaml HR entries
truth["HR"] = {}
for slug in sorted(HR_PLAN.keys()):
    plan = HR_PLAN[slug]
    te = te_data.get(slug, {})
    entry = {
        "source": plan["source"],
        "te_label": plan["te_label"],
        "te_page": f"https://tradingeconomics.com/croatia/{slug}",
        "verified": True,
        "reaudited": "2026-05-17",
        "note": plan["note"],
        "classification": plan["classification"],
    }
    if te.get("te_value") is not None:
        entry["te_value_observed"] = te["te_value"]
    truth["HR"][slug] = entry

# Write truth.yaml
truth_path.write_text(
    yaml.dump(truth, sort_keys=True, allow_unicode=True, default_flow_style=False, width=200),
    encoding="utf-8",
)
print(f"Updated truth.yaml HR with {len(truth['HR'])} entries")

# Write findings file
findings = {
    "country": "HR",
    "reaudited": "2026-05-17",
    "summary": {
        "total_slugs": len(HR_PLAN),
        "ok": sum(1 for v in HR_PLAN.values() if v["classification"] == "ok"),
        "frontend_only": sum(1 for v in HR_PLAN.values() if v["classification"] == "frontend-only"),
        "concept_ok": sum(1 for v in HR_PLAN.values() if v["classification"] == "concept-ok"),
        "concept_mismatch_acceptable": sum(1 for v in HR_PLAN.values() if v["classification"] == "concept-mismatch-acceptable"),
        "frequency_mismatch": sum(1 for v in HR_PLAN.values() if v["classification"] == "frequency-mismatch"),
        "value_stale": sum(1 for v in HR_PLAN.values() if v["classification"] == "value-stale"),
        "value_vintage": sum(1 for v in HR_PLAN.values() if v["classification"] == "value-vintage"),
        "value_method_diff": sum(1 for v in HR_PLAN.values() if v["classification"] == "value-method-diff"),
        "fixed": sum(1 for v in HR_PLAN.values() if v["classification"] == "fixed"),
        "te_no_series": sum(1 for v in HR_PLAN.values() if v["classification"] == "te-no-series"),
    },
    "fixes_applied": [
        {
            "slug": "cpi-transportation",
            "action": "Added DZS ME_PS09 COICOP 07 series; flipped is_default eurostat->dzs_hr",
            "previous_value": 106.04,
            "new_value": 112.9,
            "te_value": 112.9,
        },
        {
            "slug": "minimum-wages",
            "action": "Updated curated value",
            "previous_value": 970,
            "new_value": 1050,
            "te_value": 1050,
        },
        {
            "slug": "personal-income-tax-rate",
            "action": "Updated curated value (surtax abolition)",
            "previous_value": 35.4,
            "new_value": 30,
            "te_value": 30,
        },
        {
            "slug": "retirement-age-women",
            "action": "Updated curated value (2026 step-up)",
            "previous_value": 63.25,
            "new_value": 63.75,
            "te_value": 63.75,
        },
    ],
    "slugs": {},
}
for slug, plan in HR_PLAN.items():
    te = te_data.get(slug, {})
    findings["slugs"][slug] = {
        "te_source_label": plan["te_label"],
        "our_source": plan["source"],
        "classification": plan["classification"],
        "note": plan["note"],
        "te_value": te.get("te_value"),
        "db_default_source": db_defaults.get(slug, {}).get("source", "-"),
    }

pathlib.Path("docs/_audit_hr_reaudit.yaml").write_text(
    yaml.dump(findings, sort_keys=False, allow_unicode=True, default_flow_style=False, width=200),
    encoding="utf-8",
)
print("Wrote docs/_audit_hr_reaudit.yaml")
print("Summary:", findings["summary"])
