"""Write final MT re-audit findings YAML and summary report."""
import os, re, json, sys, io, yaml
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from pipeline.db import supabase as sb

SOURCE_RE = re.compile(r"source:\s*<a class='source-name'[^>]*href\s*=\s*'([^']*)'[^>]*>([^<]+)</a>", re.I)
SOURCE_RE2 = re.compile(r'source:\s*<a class="source-name"[^>]*href\s*=\s*"([^"]*)"[^>]*>([^<]+)</a>', re.I)
SOURCE_RE3 = re.compile(
    r"source-present['\"]>source:\s*(?:<a[^>]*href\s*=\s*['\"]([^'\"]*)['\"][^>]*>([^<]+)</a>|([^<]+))</span>",
    re.I,
)
DESC_RE = re.compile(r'<h2 id="description"[^>]*>(.*?)</h2>', re.S)
LEAD_NUM = re.compile(r"(-?\d[\d,]*\.?\d*)\s*(percent|EUR|points?|EUR Thousand|EUR Million|thousand|million|years|per 1000|per 1,000|USD|score)", re.I)

NOT_ON_TE = {
    "core-cpi", "disposable-personal-income", "energy-inflation",
    "hospital-beds", "job-vacancies", "medical-doctors", "nurses",
    "services-inflation", "services-sentiment", "terrorism-index",
}

# Decisions per slug
DECISIONS = {
    # Source-conform + value-conform
    "budget-deficit": {"status": "verified-ok", "decision": "verified", "note": "Eurostat sign convention -2.2% (deficit) vs TE +2.2 deficit magnitude — frontend display."},
    "business-confidence": {"status": "missing-db", "decision": "fetch-needed", "note": "TE EU Commission ESI April 2026 = 107.5; DB has no recent data."},
    "capacity-utilization": {"status": "value-fix-needed", "decision": "delete-bogus-row", "note": "Eurostat dim decode bug stored 43.8 for 2026-06-30; correct Q1-2026 = 67% present. Delete future-dated bogus row.", "actions": ["DELETE data_points MT/capacity-utilization/2026-06-30"]},
    "changes-in-inventories": {"status": "verified-ok", "decision": "unit-match", "note": "TE 42972 EUR Thousand = DB 42.972 mln EUR (×1000)."},
    "consumer-confidence": {"status": "value-divergence", "decision": "different-methodology", "note": "TE EU Commission CCI Apr 2026 = 2.0 (balance of replies); DB eurostat ei_bsco_m raw = -20.6. Different transformations."},
    "consumer-spending": {"status": "verified-ok", "decision": "unit-match", "note": "TE 2246.7 mln (NSO chained vol); DB nso_mt 2246.7231 mln EUR. Match."},
    "core-cpi": {"status": "not-on-te", "decision": "frontend-derive", "note": "No /malta/core-inflation-rate page on TE; EconPulse derives via Eurostat."},
    "corporate-tax-rate": {"status": "verified-ok", "decision": "verified", "note": "TE Gov Malta IR 35%; DB curated 35%."},
    "corruption-index": {"status": "curated-stale", "decision": "update-curated", "note": "TE 2025 CPI = 49 points; DB curated has 51 (2024). Update mt.yaml.", "actions": ["UPDATE curated mt.yaml corruption-index value 51->49"]},
    "corruption-rank": {"status": "curated-stale", "decision": "update-curated", "note": "TE 2025 CPI rank = 60; DB curated has 55. Update mt.yaml.", "actions": ["UPDATE curated mt.yaml corruption-rank value 55->60"]},
    "cpi-clothing": {"status": "verified-ok", "decision": "unit-match", "note": "NSO Malta DF_CPI CP03 index level vs TE YoY% — frontend-only transform."},
    "cpi-education": {"status": "verified-ok", "decision": "unit-match", "note": "NSO Malta DF_CPI CP10 index level vs TE YoY% — frontend-only transform."},
    "cpi-food": {"status": "verified-ok", "decision": "unit-match", "note": "NSO Malta DF_CPI CP01 index level vs TE YoY% — frontend-only transform."},
    "cpi-housing-utilities": {"status": "verified-ok", "decision": "unit-match", "note": "NSO Malta DF_CPI CP04 index level vs TE YoY% — frontend-only transform."},
    "cpi-recreation-and-culture": {"status": "verified-ok", "decision": "unit-match", "note": "NSO Malta DF_CPI CP09 index level vs TE YoY% — frontend-only transform."},
    "cpi-transportation": {"status": "verified-ok", "decision": "unit-match", "note": "NSO Malta DF_CPI CP07 index level vs TE YoY% — frontend-only transform."},
    "credit-rating": {"status": "verified-ok", "decision": "verified", "note": "TE /malta/rating page (no description block; data in <h2>). S&P A- / Moody's A2 / DBRS A (high). DB composite 80."},
    "current-account": {"status": "verified-ok", "decision": "fetch-provider-honored", "note": "TE attributes CBM; we fetch Eurostat (honors hard rule). TE 559.05 mln EUR = DB 0.56 bln EUR."},
    "current-account-to-gdp": {"status": "missing-db", "decision": "fetch-needed", "note": "TE 8.6% (Eurostat tipsbp20); DB has no rows."},
    "disposable-personal-income": {"status": "not-on-te", "decision": "drop", "note": "No /malta/disposable-personal-income TE page."},
    "employed-persons": {"status": "value-divergence", "decision": "methodology-mismatch", "note": "TE 303070 (NSO Malta Jobs Plus monthly registered); DB 318 thousand (Eurostat LFS quarterly). Both valid for their methodology."},
    "employment-rate": {"status": "verified-ok", "decision": "verified", "note": "TE Eurostat; DB eurostat."},
    "energy-inflation": {"status": "not-on-te", "decision": "frontend-derive", "note": "No /malta/energy-inflation TE page."},
    "exports": {"status": "verified-ok", "decision": "unit-match", "note": "NSO Malta DF_ITGS_D_HS sum-products vs TE — same data, ~mln EUR scale."},
    "food-inflation": {"status": "verified-ok", "decision": "verified", "note": "TE attributes NSO Malta; we fetch Eurostat HICP CP01 (honors hard rule)."},
    "gdp": {"status": "verified-ok", "decision": "verified", "note": "TE 24.32 bln USD (2024 WB); DB worldbank 24.97 bln (close, may be different vintage)."},
    "gdp-per-capita": {"status": "verified-ok", "decision": "verified", "note": "TE 33467 USD; DB WB 34670 — within 5%."},
    "gdp-per-capita-ppp": {"status": "verified-ok", "decision": "verified", "note": "TE 60469 PPP; DB WB 62700 — within 5%."},
    "gdp-real": {"status": "verified-ok", "decision": "unit-match", "note": "NSO Malta DF_NA_NAMQ10GDP B1GQ L,Y chain volume. Matches TE."},
    "government-debt": {"status": "verified-ok", "decision": "slug-mapping", "note": "EconPulse government-debt slug = TE government-debt-to-gdp page (46.4% of GDP, Eurostat gov_10dd_edpt1). DB eurostat correct."},
    "government-debt-total": {"status": "verified-ok", "decision": "fetch-provider-honored", "note": "EconPulse government-debt-total = TE government-debt page (11397.10 EUR Million). TE attributes CBM; we fetch Eurostat."},
    "government-spending": {"status": "verified-ok", "decision": "unit-match", "note": "NSO Malta P3_S13 L,N chain vol = 945270 EUR thousand = DB 945.2697 mln EUR."},
    "government-spending-eur": {"status": "verified-ok", "decision": "different-valuation", "note": "DB Eurostat CP_MEUR SCA current-prices (1135 mln); TE /government-spending NSO chain vol (945 mln). Both valid."},
    "gross-fixed-capital-formation": {"status": "verified-ok", "decision": "unit-match", "note": "NSO Malta P51G V,N current = 1140869 EUR thou = DB 1140.8694 mln EUR."},
    "hospital-beds": {"status": "not-on-te", "decision": "curated-keep", "note": "No /malta/hospital-beds TE page; curated WHO 4.5 per 1000 retained."},
    "house-price-index": {"status": "verified-ok", "decision": "verified", "note": "TE Eurostat housing-index; DB eurostat."},
    "imports": {"status": "verified-ok", "decision": "unit-match", "note": "NSO Malta DF_ITGS_A_HS sum-products vs TE."},
    "industrial-production": {"status": "verified-ok", "decision": "fetch-provider-honored", "note": "TE attributes NSO Malta; we fetch Eurostat sts_inpr_m (honors hard rule)."},
    "inflation-cpi": {"status": "verified-ok", "decision": "frontend-transform", "note": "NSO Malta DF_RETAIL_PRICE_INDEX index level vs TE YoY%. Frontend computes YoY."},
    "interest-rate": {"status": "verified-ok", "decision": "verified", "note": "TE ECB; DB ecb 2.15% = current MRO."},
    "job-vacancies": {"status": "not-on-te", "decision": "keep", "note": "No /malta/job-vacancies TE page."},
    "labor-force-participation-rate": {"status": "verified-ok", "decision": "verified", "note": "TE Eurostat; DB eurostat."},
    "labour-costs": {"status": "verified-ok", "decision": "fetch-provider-honored", "note": "TE attributes ECB; we fetch Eurostat lc_lci_q (honors hard rule). TE 143.82 ~ DB."},
    "long-term-unemployment-rate": {"status": "verified-ok", "decision": "minor-revision", "note": "TE Q4-2025 = 0.70%; DB has 0.60% Q4-2025; small revision lag."},
    "manufacturing-production": {"status": "verified-ok", "decision": "fetch-provider-honored", "note": "TE attributes NSO Malta; we fetch Eurostat sts_inpr_m (honors hard rule)."},
    "medical-doctors": {"status": "not-on-te", "decision": "curated-keep", "note": "No /malta/medical-doctors TE page; curated WHO 4.20 per 1000 retained."},
    "minimum-wages": {"status": "curated-stale", "decision": "update-curated", "note": "TE Q2-2026 = 994 EUR/Month (Eurostat earn_mw_cur); DB curated has 925 (2026-01-31). Update mt.yaml.", "actions": ["UPDATE curated mt.yaml minimum-wages value 925->994 date 2026-06-30"]},
    "mining-production": {"status": "verified-ok", "decision": "verified", "note": "TE Eurostat; DB eurostat."},
    "nurses": {"status": "not-on-te", "decision": "curated-keep", "note": "No /malta/nurses TE page; curated WHO 8.40 per 1000 retained."},
    "personal-income-tax-rate": {"status": "verified-ok", "decision": "verified", "note": "TE Gov Malta IR 35%; DB curated 35%."},
    "population": {"status": "verified-ok", "decision": "fetch-provider-honored", "note": "TE attributes Eurostat label, value 0.6 mln; DB nso_mt 0.57 mln (more precise NSO source). Within 5%."},
    "ppi": {"status": "verified-ok", "decision": "fetch-provider-honored", "note": "TE attributes NSO Malta; we fetch Eurostat sts_inpp_m."},
    "productivity": {"status": "verified-ok", "decision": "verified", "note": "TE Eurostat; DB eurostat."},
    "retail-sales": {"status": "verified-ok", "decision": "verified", "note": "TE EUROSTAT; DB eurostat. TE slug = /malta/retail-sales (not retail-sales-yoy as in other countries)."},
    "retirement-age-men": {"status": "curated-stale", "decision": "update-curated", "note": "TE 2025 = 64 (was), 2026 all-time-high = 65 (current). DB curated has 64. Update.", "actions": ["UPDATE curated mt.yaml retirement-age-men 64->65"]},
    "retirement-age-women": {"status": "curated-stale", "decision": "update-curated", "note": "TE 2025 = 64, 2026 all-time-high = 65. DB curated has 64. Update.", "actions": ["UPDATE curated mt.yaml retirement-age-women 64->65"]},
    "sales-tax-rate": {"status": "verified-ok", "decision": "verified", "note": "TE Gov Malta IR 18%; DB curated 18%."},
    "services-inflation": {"status": "not-on-te", "decision": "frontend-derive", "note": "No /malta/services-inflation TE page."},
    "services-sentiment": {"status": "not-on-te", "decision": "keep", "note": "No /malta/services-sentiment TE page."},
    "social-security-rate": {"status": "verified-ok", "decision": "verified", "note": "TE Commisioner of Inland Revenue 20%; DB curated 20%."},
    "social-security-rate-companies": {"status": "verified-ok", "decision": "verified", "note": "TE Commisioner of Inland Revenue 10%; DB curated 10%. TE slug = social-security-rate-for-companies."},
    "social-security-rate-employees": {"status": "verified-ok", "decision": "verified", "note": "TE Commisioner of Inland Revenue 10%; DB curated 10%. TE slug = social-security-rate-for-employees."},
    "terrorism-index": {"status": "not-on-te", "decision": "curated-keep", "note": "No /malta/terrorism-index TE page; curated IEP 0 retained."},
    "trade-balance": {"status": "verified-ok", "decision": "unit-match", "note": "NSO Malta exports−imports = -259547.485 thou EUR = -259.5 mln EUR. TE shows abs(259.5 mln deficit)."},
    "unemployed-persons": {"status": "value-divergence", "decision": "methodology-mismatch", "note": "TE NSO Malta Jobs Plus monthly registered = 1287 persons; DB eurostat LFS quarterly = 12 thousand. Different methodologies — consider switching to nso_mt to match TE.", "actions": ["TODO migrate to nso_mt DF_LABOUR_STATUS LSUNEMP M+F summed"]},
    "unemployment": {"status": "verified-ok", "decision": "verified", "note": "NSO Malta LFS unemployment rate derived from LSUNEMP/(LSEMP+LSUNEMP) M+F summed."},
    "youth-unemployment-rate": {"status": "verified-ok", "decision": "verified", "note": "TE EUROSTAT; DB eurostat."},
}


def parse_html(html):
    out = {}
    m = SOURCE_RE.search(html) or SOURCE_RE2.search(html)
    if m:
        out["source_url"] = m.group(1)
        out["source_label"] = m.group(2).strip()
    else:
        m3 = SOURCE_RE3.search(html)
        if m3:
            label = (m3.group(2) or m3.group(3) or "").strip()
            if label:
                out["source_label"] = label
                if m3.group(1):
                    out["source_url"] = m3.group(1).strip()
    desc_m = DESC_RE.search(html)
    if desc_m:
        desc = re.sub(r"<[^>]+>", "", desc_m.group(1))
        desc = re.sub(r"\s+", " ", desc).strip()
        out["description"] = desc[:400]
        nm = LEAD_NUM.search(desc)
        if nm:
            try:
                out["te_value"] = float(nm.group(1).replace(",", ""))
                out["te_unit"] = nm.group(2).strip().lower()
            except Exception:
                pass
    return out


def main():
    slugs = json.load(open("docs/_audit_all_remaining_slugs.json"))["MT"]
    findings = {}
    summary = {
        "total": len(slugs),
        "verified_ok": 0,
        "curated_stale": 0,
        "value_fix_needed": 0,
        "value_divergence": 0,
        "missing_db": 0,
        "not_on_te": 0,
    }

    for slug in slugs:
        rec = {"slug": slug}
        decision = DECISIONS.get(slug, {})
        rec.update(decision)

        # parse TE HTML if exists
        html_path = f"docs/_audit_te_html/MT/{slug}.html"
        if os.path.exists(html_path):
            html = open(html_path, encoding="utf-8", errors="ignore").read()
            parsed = parse_html(html)
            rec["te_label"] = parsed.get("source_label")
            rec["te_url"] = parsed.get("source_url")
            rec["te_value"] = parsed.get("te_value")
            rec["te_description"] = parsed.get("description", "")[:300]

        # DB
        r = sb.table("indicator_sources").select("source,note").eq(
            "country", "MT"
        ).eq("indicator", slug).eq("is_default", True).execute()
        rec["db_source"] = r.data[0]["source"] if r.data else None

        dp = sb.table("data_points").select("date,value,source").eq(
            "country", "MT"
        ).eq("indicator", slug).order("date", desc=True).limit(1).execute()
        if dp.data:
            d = dp.data[0]
            rec["db_value"] = {"date": str(d["date"]), "value": float(d["value"]), "source": d["source"]}

        status = rec.get("status", "unknown")
        if status == "verified-ok":
            summary["verified_ok"] += 1
        elif status == "curated-stale":
            summary["curated_stale"] += 1
        elif status == "value-fix-needed":
            summary["value_fix_needed"] += 1
        elif status == "value-divergence":
            summary["value_divergence"] += 1
        elif status == "missing-db":
            summary["missing_db"] += 1
        elif status == "not-on-te":
            summary["not_on_te"] += 1

        findings[slug] = rec

    out = {
        "country": "MT",
        "audit_date": "2026-05-17",
        "total_slugs": len(slugs),
        "summary": summary,
        "hard_rule_applied": "source-label = fetch provider, not upstream TE attribution",
        "findings": findings,
    }
    with open("docs/_audit_mt_reaudit.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(out, f, sort_keys=False, allow_unicode=True, width=200)
    print(json.dumps(summary, indent=2))
    print(f"\nWrote docs/_audit_mt_reaudit.yaml ({len(findings)} slugs)")


if __name__ == "__main__":
    main()
