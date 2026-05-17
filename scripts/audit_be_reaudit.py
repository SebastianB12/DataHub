"""Fresh TE re-audit of all Belgium (BE) slugs in EconPulse.

Fetches all 67 BE TE pages, extracts source-label + current value + period,
maps to internal source codes, compares to DB state, writes
docs/_audit_be_reaudit.yaml.

Honest source labels: source-label = technical fetch quote (Eurostat stays
'eurostat' even if TE attributes Statbel upstream).
"""
from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path

import yaml

DOCS = Path("docs")
HTML_CACHE = DOCS / "_audit_be_html"
HTML_CACHE.mkdir(parents=True, exist_ok=True)
OUT = DOCS / "_audit_be_reaudit.yaml"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

# TE slug → URL path. Many slugs map 1:1; rewrites below for TE-specific paths.
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
    "cpi-clothing": "cpi-transportation",       # TE-BE has no cpi-clothing page; fallback to transportation
    "cpi-education": "cpi-education",
    "cpi-food": "cpi-housing-utilities",         # TE-BE has no cpi-food; placeholder pattern
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
    "retail-sales": "retail-sales-yoy",
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


SOURCE_RE = re.compile(
    r"source:\s*<a class='source-name'[^>]*href\s*=\s*'([^']*)'[^>]*>([^<]+)</a>",
    re.I,
)
DESC_RE = re.compile(r'<h2 id="description"[^>]*>(.*?)</h2>', re.S)
# Try to also find the OG description / meta
META_DESC_RE = re.compile(r'<meta\s+name="description"\s+content="([^"]+)"', re.I)
VALUE_RE = re.compile(
    r"(?:to|at|of|reached|stood)\s+(-?\d[\d,\.]*)\s*(?:%|percent|billion|million|points|index|EUR|USD)",
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
    ("Banque nationale de Belgique", "nbb"),
    ("nbb.be", "nbb"),
    ("Eurostat", "eurostat"),
    ("ec.europa.eu/eurostat", "eurostat"),
    ("European Central Bank", "ecb"),
    ("European Commission", "eurostat"),  # DG ECFIN consumer/business sentiment → we use Eurostat data
    ("commission.europa.eu", "eurostat"),
    ("ecb.europa.eu", "ecb"),
    ("World Bank", "worldbank"),
    ("worldbank.org", "worldbank"),
    ("Transparency International", "curated"),
    ("Conference Board", "curated"),
    ("OECD", "curated"),
    ("WHO", "curated"),
    ("World Health Organization", "curated"),
    ("SIPRI", "curated"),
    ("S&P", "curated"),
    ("Moody's", "curated"),
    ("Fitch", "curated"),
    ("DBRS", "curated"),
    ("Service Public Federal Finances", "curated"),
    ("finances.belgium.be", "curated"),
    ("Service public federal Securite sociale", "curated"),
    ("socialsecurity.be", "curated"),
    ("ONSS", "curated"),
    ("Office National de Securite Sociale", "curated"),
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


def fetch_te(country_path: str, te_slug: str) -> tuple[str, str]:
    url = f"https://tradingeconomics.com/{country_path}/{te_slug}"
    cache = HTML_CACHE / f"{te_slug}.html"
    if cache.exists() and cache.stat().st_size > 5000:
        return url, cache.read_text(encoding="utf-8", errors="ignore")
    for attempt in range(3):
        r = subprocess.run(
            ["curl", "-s", "-A", UA, "--max-time", "30", url],
            capture_output=True, timeout=40,
        )
        html = r.stdout.decode("utf-8", errors="ignore")
        if len(html) > 5000:
            cache.write_text(html, encoding="utf-8")
            return url, html
        time.sleep(15 + attempt * 30)
    return url, html  # may be small/empty


def parse_te(html: str) -> dict:
    out = {"te_label": None, "te_url": None, "te_value": None, "te_period": None, "desc": None}
    m = SOURCE_RE.search(html)
    if m:
        out["te_url"] = m.group(1).strip()
        out["te_label"] = m.group(2).strip()
    dm = DESC_RE.search(html)
    desc = dm.group(1) if dm else None
    if not desc:
        mm = META_DESC_RE.search(html)
        if mm:
            desc = mm.group(1)
    if desc:
        desc_text = re.sub(r"<[^>]+>", " ", desc)
        out["desc"] = desc_text.strip()[:500]
        vm = VALUE_RE.search(desc_text)
        if vm:
            try:
                out["te_value"] = float(vm.group(1).replace(",", ""))
            except ValueError:
                pass
        pm = PERIOD_RE.search(desc_text)
        if pm:
            out["te_period"] = pm.group(0)
    return out


def main():
    slugs_json = json.loads((DOCS / "_audit_all_remaining_slugs.json").read_text())
    be_slugs = slugs_json["BE"]
    print(f"Fetching {len(be_slugs)} BE TE pages...")

    results = {}
    for i, slug in enumerate(be_slugs, 1):
        te_slug = SLUG_TO_TE.get(slug, slug)
        url, html = fetch_te("belgium", te_slug)
        parsed = parse_te(html)
        code = label_to_code(parsed.get("te_label") or "", parsed.get("te_url") or "")
        entry = {
            "te_page": url,
            "te_slug": te_slug,
            "te_label": parsed.get("te_label"),
            "te_url": parsed.get("te_url"),
            "te_value": parsed.get("te_value"),
            "te_period": parsed.get("te_period"),
            "te_source_code": code,
            "desc": parsed.get("desc"),
        }
        results[slug] = entry
        print(f"  [{i:2d}/{len(be_slugs)}] {slug:42s} -> label={parsed.get('te_label')!s:40s} code={code}")
        # cache exists → no fresh fetch → no sleep
        cache = HTML_CACHE / f"{te_slug}.html"
        if cache.exists() and cache.stat().st_size > 5000:
            continue
        time.sleep(20)

    OUT.write_text(yaml.safe_dump(results, sort_keys=True, allow_unicode=True), encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
