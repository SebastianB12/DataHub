"""Build consolidated BE re-audit YAML by re-parsing all cached HTML pages
with stronger source regex + add DB+truth.yaml comparison."""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from pipeline.db import supabase as sb

DOCS = Path("docs")
HTML_CACHE = DOCS / "_audit_be_html"
OUT = DOCS / "_audit_be_reaudit.yaml"

# Strong label extractors — three TE source markup variants
SRC_A_RE = re.compile(
    r"source:\s*<a class=['\"]source-name['\"][^>]*href\s*=\s*['\"]([^'\"]*)['\"][^>]*>([^<]+)</a>",
    re.I,
)
SRC_PRESENT_RE = re.compile(
    r"<span class=['\"]source-present['\"][^>]*>\s*source:\s*(.+?)\s*</span>",
    re.I | re.S,
)
SRC_SPAN_RE = re.compile(r"source:\s*([A-Z][A-Za-z &.()/'-]{2,80})</span>", re.I)
META_DESC_RE = re.compile(r'<meta\s+name="description"\s+content="([^"]+)"', re.I)
TITLE_RE = re.compile(r"<title>([^<]+)</title>", re.I)
VALUE_RE = re.compile(
    r"(?:to|at|of|reached|stood|stands?)\s+(-?\d[\d,\.]*)\s*(?:%|percent|billion|million|points|index|EUR|USD)",
    re.I,
)
PERIOD_RE = re.compile(
    r"in\s+(January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Q[1-4]|the\s+(?:first|second|third|fourth)\s+quarter)\s*(?:of\s+)?(\d{4})?",
    re.I,
)

LABEL_TO_CODE = [
    ("Statbel", "statbel"),
    ("Statistics Belgium", "statbel"),
    ("statbel.fgov.be", "statbel"),
    ("National Bank of Belgium", "nbb"),
    ("National Bank Of Belgium", "nbb"),
    ("Banque nationale de Belgique", "nbb"),
    ("nbb.be", "nbb"),
    ("Eurostat", "eurostat"),
    ("EUROSTAT", "eurostat"),
    ("ec.europa.eu/eurostat", "eurostat"),
    ("European Commission", "eurostat"),
    ("commission.europa.eu", "eurostat"),
    ("European Central Bank", "ecb"),
    ("ecb.europa.eu", "ecb"),
    ("World Bank", "worldbank"),
    ("worldbank.org", "worldbank"),
    ("Transparency International", "curated"),
    ("Conference Board", "curated"),
    ("OECD", "curated"),
    ("WHO", "curated"),
    ("World Health Organization", "curated"),
    ("SIPRI", "curated"),
    ("Institute for Economics and Peace", "curated"),
    ("National Social Security Office", "curated"),
    ("Service Public", "curated"),
    ("finances.belgium.be", "curated"),
    ("Commission Bancaire", "curated"),
    ("S&P", "curated"),
    ("Moody", "curated"),
    ("Fitch", "curated"),
]


def label_to_code(label: str, url: str = "") -> str | None:
    if not label and not url:
        return None
    blob = (label or "") + " " + (url or "")
    low = blob.lower()
    for pat, code in LABEL_TO_CODE:
        if pat.lower() in low:
            return code
    return None


# Internal slug -> TE slug used in TE URL
SLUG_TO_TE = {
    "budget-deficit": "government-budget",
    "business-confidence": "business-confidence",
    "capacity-utilization": "capacity-utilization",
    "changes-in-inventories": "changes-in-inventories",
    "consumer-confidence": "consumer-confidence",
    "consumer-spending": "consumer-spending",
    "core-cpi": "core-inflation-rate",
    "corporate-tax-rate": "corporate-tax-rate",
    "corruption-index": "corruption-index",
    "corruption-rank": "corruption-rank",
    "cpi-clothing": "cpi-clothing",
    "cpi-education": "cpi-education",
    "cpi-food": "cpi-food",
    "cpi-housing-utilities": "cpi-housing-utilities",
    "cpi-recreation-and-culture": "cpi-recreation-and-culture",
    "cpi-transportation": "cpi-transportation",
    "credit-rating": "rating",
    "current-account": "current-account",
    "current-account-to-gdp": "current-account-to-gdp",
    "disposable-personal-income": "disposable-personal-income",
    "employed-persons": "employed-persons",
    "employment-rate": "employment-rate",
    "energy-inflation": "energy-inflation",
    "exports": "exports",
    "food-inflation": "food-inflation",
    "gdp": "gdp",
    "gdp-per-capita": "gdp-per-capita",
    "gdp-per-capita-ppp": "gdp-per-capita-ppp",
    "gdp-real": "gdp-growth-annual",
    "government-debt": "government-debt-to-gdp",
    "government-debt-total": "government-debt",
    "government-spending": "government-spending",
    "government-spending-eur": "government-spending",
    "gross-fixed-capital-formation": "gross-fixed-capital-formation",
    "hospital-beds": "hospital-beds",
    "house-price-index": "housing-index",
    "imports": "imports",
    "industrial-production": "industrial-production",
    "inflation-cpi": "inflation-cpi",
    "interest-rate": "interest-rate",
    "job-vacancies": "job-vacancies",
    "labor-force-participation-rate": "labor-force-participation-rate",
    "labour-costs": "labour-costs",
    "long-term-unemployment-rate": "long-term-unemployment-rate",
    "manufacturing-production": "manufacturing-production",
    "medical-doctors": "medical-doctors",
    "minimum-wages": "minimum-wages",
    "mining-production": "mining-production",
    "nurses": "nurses",
    "personal-income-tax-rate": "personal-income-tax-rate",
    "population": "population",
    "ppi": "producer-prices",
    "productivity": "productivity",
    "retail-sales": "retail-sales",
    "retirement-age-men": "retirement-age-men",
    "retirement-age-women": "retirement-age-women",
    "sales-tax-rate": "sales-tax-rate",
    "services-inflation": "services-inflation",
    "services-sentiment": "services-sentiment",
    "social-security-rate": "social-security-rate",
    "social-security-rate-companies": "social-security-rate-for-companies",
    "social-security-rate-employees": "social-security-rate-for-employees",
    "terrorism-index": "terrorism-index",
    "trade-balance": "balance-of-trade",
    "unemployed-persons": "unemployed-persons",
    "unemployment": "unemployment-rate",
    "youth-unemployment-rate": "youth-unemployment-rate",
}


def parse_html(html: str) -> dict:
    out = {
        "te_label": None, "te_url": None,
        "te_value": None, "te_period": None,
        "te_landing_page": False, "te_title": None,
        "desc": None,
    }
    t = TITLE_RE.search(html)
    if t:
        out["te_title"] = t.group(1).strip()
        if "TRADING ECONOMICS | 20 Million Indicators" in out["te_title"]:
            out["te_landing_page"] = True
    m = SRC_A_RE.search(html)
    if m:
        out["te_url"] = m.group(1).strip()
        out["te_label"] = m.group(2).strip()
    else:
        m_present = SRC_PRESENT_RE.search(html)
        if m_present:
            cleaned = re.sub(r"<[^>]+>", " ", m_present.group(1)).strip()
            if cleaned and "function" not in cleaned.lower():
                out["te_label"] = cleaned
        if not out["te_label"]:
            m2 = SRC_SPAN_RE.search(html)
            if m2 and "function" not in m2.group(1).lower():
                out["te_label"] = m2.group(1).strip()
    dm = META_DESC_RE.search(html)
    if dm:
        out["desc"] = dm.group(1).strip()[:600]
    if out["desc"]:
        vm = VALUE_RE.search(out["desc"])
        if vm:
            try:
                out["te_value"] = float(vm.group(1).replace(",", ""))
            except ValueError:
                pass
        pm = PERIOD_RE.search(out["desc"])
        if pm:
            out["te_period"] = pm.group(0)
    return out


def main():
    slugs = json.loads((DOCS / "_audit_all_remaining_slugs.json").read_text())["BE"]

    # Load DB state in two batches to avoid timeout
    db_state: dict[str, dict] = {}
    for s in slugs:
        try:
            r = sb.table("indicator_sources").select("source,series_id,note,is_default").eq(
                "country", "BE"
            ).eq("indicator", s).eq("is_default", True).limit(1).execute()
            db_state[s] = {"isource": r.data[0] if r.data else None}
        except Exception as e:
            db_state[s] = {"isource_err": str(e)[:120]}
        try:
            r = sb.table("data_points").select("date,value,source").eq(
                "country", "BE"
            ).eq("indicator", s).order("date", desc=True).limit(1).execute()
            db_state[s]["latest_dp"] = r.data[0] if r.data else None
        except Exception as e:
            db_state[s]["latest_dp_err"] = str(e)[:120]

    out = {}
    for slug in slugs:
        te_slug = SLUG_TO_TE.get(slug, slug)
        cache_paths = [
            HTML_CACHE / f"{te_slug}.html",
            HTML_CACHE / f"{slug}.html",
        ]
        html_path = next((p for p in cache_paths if p.exists() and p.stat().st_size > 5000), None)
        parsed = parse_html(html_path.read_text(encoding="utf-8", errors="ignore")) if html_path else {}
        te_code = label_to_code(parsed.get("te_label") or "", parsed.get("te_url") or "")

        db = db_state.get(slug, {})
        isrc = db.get("isource") or {}
        dp = db.get("latest_dp") or {}

        # status
        if parsed.get("te_landing_page"):
            status = "TE_PAGE_MISSING"
        elif not parsed.get("te_label"):
            status = "TE_LABEL_UNPARSED"
        elif not te_code:
            status = "TE_CODE_UNMAPPED"
        elif te_code == isrc.get("source"):
            status = "OK"
        else:
            status = "MISMATCH"

        # Policy note: source-label = technical fetch quote (user rule).
        # For mismatches where TE attributes an upstream that does not have
        # a working data API, we keep the honest fetch source and document.
        policy_note = None
        if status == "MISMATCH":
            if slug in ("industrial-production", "manufacturing-production", "mining-production") \
               and isrc.get("source") == "nbb" and te_code == "statbel":
                policy_note = (
                    "honest_fetch: Statbel REST API has NO IPI volume view (verified "
                    "2026-05-15 by full enumeration of 1341 views). NBB Belgostat SDMX "
                    "(DF_INDPROD) redistributes the same Statbel IPI methodology. "
                    "Source-label = fetch quote per user rule."
                )
            elif slug == "labour-costs" and isrc.get("source") == "eurostat" and te_code == "ecb":
                policy_note = (
                    "honest_fetch: ECB data-api.ecb.europa.eu has NO labour-cost dataflow. "
                    "ECB redistributes Eurostat lc_lci_r2_q. Source-label = fetch quote."
                )
        if status == "TE_PAGE_MISSING":
            policy_note = "TE does not publish a BE page for this indicator (verified 2026-05-16). Keeping current source."
        if status == "TE_LABEL_UNPARSED" and slug == "credit-rating":
            policy_note = "TE rating page shows S&P AA-, Moody's A1, DBRS AA in a table without a single 'source:' attribution. Curated stays."

        out[slug] = {
            "te_page": f"https://tradingeconomics.com/belgium/{te_slug}",
            "te_slug": te_slug,
            "te_label": parsed.get("te_label"),
            "te_url": parsed.get("te_url"),
            "te_value": parsed.get("te_value"),
            "te_period": parsed.get("te_period"),
            "te_title": parsed.get("te_title"),
            "te_landing_page": parsed.get("te_landing_page", False),
            "te_source_code": te_code,
            "db_source": isrc.get("source"),
            "db_series_id": isrc.get("series_id"),
            "db_note": isrc.get("note"),
            "db_latest_date": dp.get("date") if isinstance(dp, dict) else None,
            "db_latest_value": dp.get("value") if isinstance(dp, dict) else None,
            "db_latest_source": dp.get("source") if isinstance(dp, dict) else None,
            "desc": parsed.get("desc"),
            "status": status,
            "policy_note": policy_note,
        }

    OUT.write_text(yaml.safe_dump(out, sort_keys=True, allow_unicode=True), encoding="utf-8")
    print(f"Wrote {OUT}")
    # summary
    from collections import Counter
    c = Counter(v["status"] for v in out.values())
    for k, n in c.most_common():
        print(f"  {k}: {n}")


if __name__ == "__main__":
    main()
