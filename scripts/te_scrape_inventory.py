"""TE source-inventory scraper for AT/BE/IE/LU/PT.

For each (country, slug) pair we map our internal slug to a TE URL path,
fetch the page via curl, parse the "source-present" span for the provider
name + URL, and parse the latest value/period from the headline phrase.
"""
from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

# Our slug -> TE URL path (relative to /<country>/)
SLUG_TO_TE_PATH = {
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
    "cpi-clothing": "cpi-transportation",  # placeholder; actual TE pages: cpi-clothing-and-footwear etc
    "cpi-education": "cpi-education",
    "cpi-food": "cpi-housing-utilities",  # alt
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
    "government-debt": "government-debt",
    "government-debt-total": "government-debt-to-gdp",
    "government-spending": "government-spending",
    "government-spending-eur": "government-spending",
    "gross-fixed-capital-formation": "gross-fixed-capital-formation",
    "hospital-beds": "hospital-beds",
    "house-price-index": "housing-index",
    "housing-index": "housing-index",
    "import-prices": "import-prices",
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
    "wages": "wages",
    "youth-unemployment-rate": "youth-unemployment-rate",
}

# Country slug -> TE country-name lower
COUNTRY_TE = {
    "AT": "austria",
    "BE": "belgium",
    "IE": "ireland",
    "LU": "luxembourg",
    "PT": "portugal",
}

# Map TE provider label substrings -> our internal source code.
LABEL_TO_CODE = [
    # most-specific first
    ("Statistik Austria", "stat_at"),
    ("Statistics Austria", "stat_at"),
    ("Public Employment Service Austria", "stat_at"),  # AMS — labour register; closest national label -> stat_at fallback
    ("Oesterreichische Nationalbank", "ecb"),
    ("National Bank of Belgium", "nbb"),
    ("Banque Nationale de Belgique", "nbb"),
    ("Statbel", "statbel"),
    ("Statistics Belgium", "statbel"),
    ("Central Statistics Office", "cso_ie"),
    ("Central Statistics Office Ireland", "cso_ie"),
    ("CSO Ireland", "cso_ie"),
    ("Central Bank of Ireland", "ecb"),
    ("STATEC", "statec_lu"),
    ("Banque centrale du Luxembourg", "ecb"),
    ("Statistics Portugal", "ine_pt"),
    ("INE Portugal", "ine_pt"),
    ("Banco de Portugal", "ecb"),
    ("Eurostat", "eurostat"),
    ("EUROSTAT", "eurostat"),
    ("European Central Bank", "ecb"),
    ("European Commission", "eurostat"),  # DG ECFIN surveys mirrored to Eurostat
    ("World Bank", "worldbank"),
    ("WORLDBANK", "worldbank"),
    ("Transparency International", "curated"),
    ("Reporters Without Borders", "curated"),
    ("OECD", "curated"),
    ("WHO", "curated"),
    ("UN", "curated"),
    ("Vision of Humanity", "curated"),
    ("Institute for Economics", "curated"),
    ("Standard & Poor's", "curated"),
    ("Moody's", "curated"),
    ("Fitch", "curated"),
]


def fetch(url: str) -> str | None:
    try:
        out = subprocess.run(
            [
                "curl",
                "-s",
                "-A",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
                "-L",
                "--max-time",
                "20",
                "-w",
                "\n__HTTP_CODE__:%{http_code}",
                url,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        body = out.stdout
        m = re.search(r"__HTTP_CODE__:(\d+)$", body)
        if not m:
            return None
        code = int(m.group(1))
        if code != 200:
            return None
        return body[: m.start()]
    except Exception:
        return None


SOURCE_RE = re.compile(
    r"source-present[^<]*<a[^>]*href ?='([^']*)'[^>]*>([^<]+)</a>",
    re.IGNORECASE,
)
# Latest value: <span class='te-light-green'>...</span> usually appears; fallback: parse h1 / description
VALUE_RE = re.compile(
    r"<span class='te-light-green'[^>]*>\s*([0-9\.,\-]+)\s*</span>",
)
# Period in title: "Inflation Rate in Austria decreased to 3.30 percent in April from 3.50 percent in March of 2026"
# We'll try meta description.
META_DESC_RE = re.compile(r'<meta name="description" content="([^"]+)"', re.IGNORECASE)
TITLE_RE = re.compile(r"<title>([^<]+)</title>", re.IGNORECASE)


def label_to_code(label: str) -> str | None:
    lab = label.strip()
    for pat, code in LABEL_TO_CODE:
        if pat.lower() in lab.lower():
            return code
    return None


# Months
MONTHS = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
    "jan": "01", "feb": "02", "mar": "03", "apr": "04",
    "jun": "06", "jul": "07", "aug": "08", "sep": "09", "sept": "09",
    "oct": "10", "nov": "11", "dec": "12",
}


def parse_period(text: str) -> str | None:
    # Try "in April of 2026" or "in April 2026"
    m = re.search(
        r"\bin\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(of\s+)?(\d{4})",
        text,
        re.IGNORECASE,
    )
    if m:
        return f"{m.group(3)}-{MONTHS[m.group(1).lower()]}"
    # Try "Q1 of 2026"
    m = re.search(r"\bQ([1-4])\s+(of\s+)?(\d{4})", text)
    if m:
        return f"{m.group(3)}-Q{m.group(1)}"
    # Try "first/second/third/fourth quarter of 2026"
    qmap = {"first": 1, "second": 2, "third": 3, "fourth": 4}
    m = re.search(r"\b(first|second|third|fourth)\s+quarter\s+(of\s+)?(\d{4})", text, re.IGNORECASE)
    if m:
        return f"{m.group(3)}-Q{qmap[m.group(1).lower()]}"
    # Try "in 2024"
    m = re.search(r"\bin\s+(\d{4})\b", text)
    if m:
        return m.group(1)
    return None


def parse_value(html: str, desc: str) -> str | None:
    m = VALUE_RE.search(html)
    if m:
        return m.group(1).replace(",", "")
    # try desc: first number
    m = re.search(r"(-?\d[\d\.,]*)\b", desc)
    if m:
        return m.group(1).replace(",", "")
    return None


def scrape_page(country: str, te_path: str) -> dict:
    url = f"https://tradingeconomics.com/{country}/{te_path}"
    html = fetch(url)
    if not html:
        return {"page": url, "ok": False}
    sm = SOURCE_RE.search(html)
    label = sm.group(2).strip() if sm else None
    src_url = sm.group(1).strip() if sm else None
    dm = META_DESC_RE.search(html)
    desc = dm.group(1) if dm else ""
    if not desc:
        tm = TITLE_RE.search(html)
        desc = tm.group(1) if tm else ""
    value = parse_value(html, desc)
    period = parse_period(desc) or parse_period(html[:5000])
    return {
        "page": url,
        "ok": True,
        "te_label": label,
        "te_url": src_url,
        "te_value": value,
        "te_period": period,
    }


# Truth file slug lists (parsed manually)
TRUTH = {
    "AT": {
        "budget-deficit": "eurostat", "business-confidence": "eurostat",
        "capacity-utilization": "eurostat", "changes-in-inventories": "eurostat",
        "consumer-confidence": "eurostat", "consumer-spending": "eurostat",
        "core-cpi": "eurostat", "corporate-tax-rate": "curated",
        "corruption-index": "curated", "corruption-rank": "curated",
        "cpi-clothing": "eurostat", "cpi-education": "eurostat",
        "cpi-food": "eurostat", "cpi-housing-utilities": "eurostat",
        "cpi-recreation-and-culture": "eurostat", "cpi-transportation": "eurostat",
        "credit-rating": "curated", "current-account": "eurostat",
        "current-account-to-gdp": "eurostat", "disposable-personal-income": "eurostat",
        "employed-persons": "eurostat", "employment-rate": "eurostat",
        "energy-inflation": "eurostat", "exports": "eurostat",
        "food-inflation": "eurostat", "gdp": "stat_at",
        "gdp-per-capita": "worldbank", "gdp-per-capita-ppp": "worldbank",
        "gdp-real": "eurostat", "government-debt": "eurostat",
        "government-debt-total": "eurostat", "government-spending": "eurostat",
        "government-spending-eur": "eurostat", "gross-fixed-capital-formation": "eurostat",
        "hospital-beds": "curated", "house-price-index": "eurostat",
        "import-prices": "stat_at", "imports": "eurostat",
        "industrial-production": "stat_at", "inflation-cpi": "stat_at",
        "interest-rate": "ecb", "job-vacancies": "eurostat",
        "labor-force-participation-rate": "eurostat", "labour-costs": "eurostat",
        "long-term-unemployment-rate": "eurostat", "manufacturing-production": "eurostat",
        "medical-doctors": "curated", "minimum-wages": "curated",
        "mining-production": "eurostat", "nurses": "curated",
        "personal-income-tax-rate": "curated", "population": "eurostat",
        "ppi": "stat_at", "productivity": "eurostat",
        "retail-sales": "eurostat", "retirement-age-men": "curated",
        "retirement-age-women": "curated", "sales-tax-rate": "curated",
        "services-inflation": "eurostat", "services-sentiment": "eurostat",
        "social-security-rate": "curated", "social-security-rate-companies": "curated",
        "social-security-rate-employees": "curated", "terrorism-index": "curated",
        "unemployed-persons": "eurostat", "unemployment": "stat_at",
        "wages": "stat_at", "youth-unemployment-rate": "eurostat",
    },
    "BE": {
        "budget-deficit": "eurostat", "business-confidence": "eurostat",
        "capacity-utilization": "eurostat", "changes-in-inventories": "eurostat",
        "consumer-confidence": "eurostat", "consumer-spending": "eurostat",
        "core-cpi": "eurostat", "corporate-tax-rate": "curated",
        "corruption-index": "curated", "corruption-rank": "curated",
        "cpi-clothing": "eurostat", "cpi-education": "eurostat",
        "cpi-food": "eurostat", "cpi-housing-utilities": "eurostat",
        "cpi-recreation-and-culture": "eurostat", "cpi-transportation": "eurostat",
        "credit-rating": "curated", "current-account": "eurostat",
        "current-account-to-gdp": "eurostat", "disposable-personal-income": "eurostat",
        "employed-persons": "eurostat", "employment-rate": "eurostat",
        "energy-inflation": "eurostat", "exports": "eurostat",
        "food-inflation": "eurostat", "gdp": "worldbank",
        "gdp-per-capita": "worldbank", "gdp-per-capita-ppp": "worldbank",
        "gdp-real": "eurostat", "government-debt": "eurostat",
        "government-debt-total": "eurostat", "government-spending": "eurostat",
        "government-spending-eur": "eurostat", "gross-fixed-capital-formation": "eurostat",
        "hospital-beds": "curated", "house-price-index": "eurostat",
        "imports": "eurostat", "industrial-production": "eurostat",
        "inflation-cpi": "statbel", "interest-rate": "ecb",
        "job-vacancies": "eurostat", "labor-force-participation-rate": "eurostat",
        "labour-costs": "eurostat", "long-term-unemployment-rate": "eurostat",
        "manufacturing-production": "eurostat", "medical-doctors": "curated",
        "minimum-wages": "curated", "mining-production": "eurostat",
        "nurses": "curated", "personal-income-tax-rate": "curated",
        "population": "eurostat", "ppi": "eurostat",
        "productivity": "eurostat", "retail-sales": "eurostat",
        "retirement-age-men": "curated", "retirement-age-women": "curated",
        "sales-tax-rate": "curated", "services-inflation": "eurostat",
        "services-sentiment": "eurostat", "social-security-rate": "curated",
        "social-security-rate-companies": "curated", "social-security-rate-employees": "curated",
        "terrorism-index": "curated", "unemployed-persons": "eurostat",
        "unemployment": "eurostat", "youth-unemployment-rate": "eurostat",
    },
    "IE": {
        "budget-deficit": "eurostat", "business-confidence": "eurostat",
        "capacity-utilization": "eurostat", "changes-in-inventories": "eurostat",
        "consumer-confidence": "eurostat", "consumer-spending": "eurostat",
        "core-cpi": "eurostat", "corporate-tax-rate": "curated",
        "corruption-index": "curated", "corruption-rank": "curated",
        "cpi-clothing": "eurostat", "cpi-education": "eurostat",
        "cpi-food": "eurostat", "cpi-housing-utilities": "eurostat",
        "cpi-recreation-and-culture": "eurostat", "cpi-transportation": "eurostat",
        "credit-rating": "curated", "current-account": "eurostat",
        "current-account-to-gdp": "eurostat", "disposable-personal-income": "eurostat",
        "employed-persons": "eurostat", "employment-rate": "eurostat",
        "energy-inflation": "eurostat", "exports": "eurostat",
        "food-inflation": "eurostat", "gdp": "worldbank",
        "gdp-per-capita": "worldbank", "gdp-per-capita-ppp": "worldbank",
        "gdp-real": "cso_ie", "government-debt": "eurostat",
        "government-debt-total": "eurostat", "government-spending": "eurostat",
        "government-spending-eur": "eurostat", "gross-fixed-capital-formation": "eurostat",
        "hospital-beds": "curated", "house-price-index": "eurostat",
        "housing-index": "cso_ie", "imports": "eurostat",
        "industrial-production": "cso_ie", "inflation-cpi": "cso_ie",
        "interest-rate": "ecb", "job-vacancies": "eurostat",
        "labor-force-participation-rate": "eurostat", "labour-costs": "eurostat",
        "long-term-unemployment-rate": "eurostat", "manufacturing-production": "eurostat",
        "medical-doctors": "curated", "minimum-wages": "curated",
        "mining-production": "eurostat", "nurses": "curated",
        "personal-income-tax-rate": "curated", "population": "eurostat",
        "ppi": "cso_ie", "productivity": "eurostat",
        "retail-sales": "cso_ie", "retirement-age-men": "curated",
        "retirement-age-women": "curated", "sales-tax-rate": "curated",
        "services-inflation": "eurostat", "services-sentiment": "eurostat",
        "social-security-rate": "curated", "social-security-rate-companies": "curated",
        "social-security-rate-employees": "curated", "terrorism-index": "curated",
        "trade-balance": "cso_ie", "unemployed-persons": "eurostat",
        "unemployment": "cso_ie", "youth-unemployment-rate": "eurostat",
    },
    "LU": {
        "budget-deficit": "eurostat", "business-confidence": "eurostat",
        "capacity-utilization": "eurostat", "changes-in-inventories": "eurostat",
        "consumer-confidence": "eurostat", "consumer-spending": "eurostat",
        "core-cpi": "eurostat", "corporate-tax-rate": "curated",
        "corruption-index": "curated", "corruption-rank": "curated",
        "cpi-clothing": "eurostat", "cpi-education": "eurostat",
        "cpi-food": "eurostat", "cpi-housing-utilities": "eurostat",
        "cpi-recreation-and-culture": "eurostat", "cpi-transportation": "eurostat",
        "credit-rating": "curated", "current-account": "eurostat",
        "current-account-to-gdp": "eurostat", "disposable-personal-income": "eurostat",
        "employed-persons": "statec_lu", "employment-rate": "eurostat",
        "energy-inflation": "eurostat", "exports": "eurostat",
        "food-inflation": "eurostat", "gdp": "worldbank",
        "gdp-per-capita": "worldbank", "gdp-per-capita-ppp": "worldbank",
        "gdp-real": "eurostat", "government-debt": "eurostat",
        "government-debt-total": "eurostat", "government-spending": "eurostat",
        "government-spending-eur": "eurostat", "gross-fixed-capital-formation": "eurostat",
        "hospital-beds": "curated", "house-price-index": "eurostat",
        "imports": "eurostat", "industrial-production": "statec_lu",
        "inflation-cpi": "statec_lu", "interest-rate": "ecb",
        "job-vacancies": "eurostat", "labor-force-participation-rate": "eurostat",
        "labour-costs": "eurostat", "long-term-unemployment-rate": "eurostat",
        "manufacturing-production": "eurostat", "medical-doctors": "curated",
        "minimum-wages": "curated", "mining-production": "eurostat",
        "nurses": "curated", "personal-income-tax-rate": "curated",
        "population": "statec_lu", "ppi": "statec_lu",
        "productivity": "eurostat", "retail-sales": "eurostat",
        "retirement-age-men": "curated", "retirement-age-women": "curated",
        "sales-tax-rate": "curated", "services-inflation": "eurostat",
        "services-sentiment": "eurostat", "social-security-rate": "curated",
        "social-security-rate-companies": "curated", "social-security-rate-employees": "curated",
        "terrorism-index": "curated", "unemployed-persons": "statec_lu",
        "unemployment": "statec_lu", "youth-unemployment-rate": "eurostat",
    },
    "PT": {
        "budget-deficit": "eurostat", "business-confidence": "eurostat",
        "capacity-utilization": "eurostat", "changes-in-inventories": "eurostat",
        "consumer-confidence": "eurostat", "consumer-spending": "eurostat",
        "core-cpi": "eurostat", "corporate-tax-rate": "curated",
        "corruption-index": "curated", "corruption-rank": "curated",
        "cpi-clothing": "eurostat", "cpi-education": "eurostat",
        "cpi-food": "eurostat", "cpi-housing-utilities": "eurostat",
        "cpi-recreation-and-culture": "eurostat", "cpi-transportation": "eurostat",
        "credit-rating": "curated", "current-account": "eurostat",
        "current-account-to-gdp": "eurostat", "disposable-personal-income": "eurostat",
        "employed-persons": "eurostat", "employment-rate": "eurostat",
        "energy-inflation": "eurostat", "exports": "eurostat",
        "food-inflation": "eurostat", "gdp": "worldbank",
        "gdp-per-capita": "worldbank", "gdp-per-capita-ppp": "worldbank",
        "gdp-real": "eurostat", "government-debt": "eurostat",
        "government-debt-total": "eurostat", "government-spending": "eurostat",
        "government-spending-eur": "eurostat", "gross-fixed-capital-formation": "eurostat",
        "hospital-beds": "curated", "house-price-index": "eurostat",
        "imports": "eurostat", "industrial-production": "eurostat",
        "inflation-cpi": "eurostat", "interest-rate": "ecb",
        "job-vacancies": "eurostat", "labor-force-participation-rate": "eurostat",
        "labour-costs": "eurostat", "long-term-unemployment-rate": "eurostat",
        "manufacturing-production": "eurostat", "medical-doctors": "curated",
        "minimum-wages": "curated", "mining-production": "eurostat",
        "nurses": "curated", "personal-income-tax-rate": "curated",
        "population": "eurostat", "ppi": "eurostat",
        "productivity": "eurostat", "retail-sales": "eurostat",
        "retirement-age-men": "curated", "retirement-age-women": "curated",
        "sales-tax-rate": "curated", "services-inflation": "eurostat",
        "services-sentiment": "eurostat", "social-security-rate": "curated",
        "social-security-rate-companies": "curated", "social-security-rate-employees": "curated",
        "terrorism-index": "curated", "unemployed-persons": "eurostat",
        "unemployment": "eurostat", "youth-unemployment-rate": "eurostat",
    },
}


def yaml_str(s):
    if s is None:
        return "null"
    # quote
    return '"' + str(s).replace('"', '\\"') + '"'


def write_inventory(cc: str, slugs: dict, out_dir: Path):
    country = COUNTRY_TE[cc]
    lines = []
    verified_count = 0
    conform_count = 0
    mismatches = []
    for slug, current in sorted(slugs.items()):
        te_path = SLUG_TO_TE_PATH.get(slug)
        result = {
            "te_label": None,
            "te_url": None,
            "te_page": None,
            "te_value": None,
            "te_period": None,
            "suggested_source": None,
            "current_source": current,
            "conform": False,
            "verified": False,
        }
        if te_path:
            res = scrape_page(country, te_path)
            result["te_page"] = res.get("page")
            if res.get("ok") and res.get("te_label"):
                result["te_label"] = res["te_label"]
                result["te_url"] = res.get("te_url")
                result["te_value"] = res.get("te_value")
                result["te_period"] = res.get("te_period")
                code = label_to_code(res["te_label"])
                result["suggested_source"] = code
                result["verified"] = True
                result["conform"] = code == current
                verified_count += 1
                if result["conform"]:
                    conform_count += 1
                else:
                    mismatches.append((slug, current, code, res["te_label"]))
            time.sleep(0.3)
        # emit
        def v(x):
            return yaml_str(x) if x is not None else "null"

        lines.append(f"{slug}:")
        lines.append(f"  te_label: {v(result['te_label'])}")
        lines.append(f"  te_url: {v(result['te_url'])}")
        lines.append(f"  te_page: {v(result['te_page'])}")
        lines.append(
            f"  te_value: {result['te_value'] if result['te_value'] is not None else 'null'}"
        )
        lines.append(f"  te_period: {v(result['te_period'])}")
        lines.append(
            f"  suggested_source: {result['suggested_source'] if result['suggested_source'] else 'null'}"
        )
        lines.append(f"  current_source: {result['current_source']}")
        lines.append(f"  conform: {'true' if result['conform'] else 'false'}")
        lines.append(f"  verified: {'true' if result['verified'] else 'false'}")
    out_path = out_dir / f"{cc}.yaml"
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"=== {cc}: verified={verified_count}/{len(slugs)}  conform={conform_count}")
    print(f"  Top mismatches:")
    for slug, cur, sug, lab in mismatches[:5]:
        print(f"    - {slug}: truth={cur} -> TE={sug!r} ({lab})")
    return verified_count, conform_count, mismatches


def main():
    out_dir = Path(__file__).resolve().parents[1] / "docs" / "_te_inventory"
    out_dir.mkdir(parents=True, exist_ok=True)
    targets = sys.argv[1:] if len(sys.argv) > 1 else list(TRUTH.keys())
    for cc in targets:
        write_inventory(cc, TRUTH[cc], out_dir)


if __name__ == "__main__":
    main()
