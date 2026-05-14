"""Scrape TE indicator pages for (country, slug) -> source attribution.

Usage: python scripts/te_inventory_scrape.py <country-name> <slug1> <slug2> ...
Output: JSON lines to stdout: {slug, te_label, te_url, te_page, te_value, te_period}
"""
import sys
import re
import json
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# Map our internal slug -> TE URL slug variant (when they differ)
SLUG_TO_TE = {
    "trade-balance": "balance-of-trade",
    "house-price-index": "housing-index",
    "ppi": "producer-prices",
    "government-debt-total": "government-debt",
    "government-spending-eur": "government-spending",  # same value, EUR variant
    "industrial-production-yoy": "industrial-production",
    "retail-sales-yoy": "retail-sales",
    "gdp-growth-rate": "gdp-growth",
    "minimum-wages": "minimum-wages",
}

# Slugs we skip — curated only, no TE page or matches curated table
SKIP_SLUGS = {
    "corporate-tax-rate", "personal-income-tax-rate", "sales-tax-rate",
    "social-security-rate", "social-security-rate-companies",
    "social-security-rate-employees", "withholding-tax-rate",
    "corruption-index", "corruption-rank", "credit-rating",
    "hospital-beds", "hospitals", "medical-doctors", "nurses",
    "retirement-age-men", "retirement-age-women", "terrorism-index",
    "weapons-sales", "military-expenditure", "minimum-wages",
    "government-spending-to-gdp",
}

SOURCE_RE = re.compile(
    r"source:\s*<a class='source-name'[^>]*href\s*=\s*'([^']*)'[^>]*>([^<]+)</a>",
    re.I,
)
DESC_RE = re.compile(
    r'<h2 id="description"[^>]*>(.*?)</h2>', re.S
)
# value extraction: first floating number in description
VALUE_RE = re.compile(r"to\s+(-?\d[\d,\.]*)\s+", re.I)
PERIOD_RE = re.compile(
    r"in\s+(January|February|March|April|May|June|July|August|September|October|November|December|the\s+(?:first|second|third|fourth)\s+quarter\s+of|Q[1-4]|\d{4})\s*(?:of\s+(\d{4}))?",
    re.I,
)
QUARTER_NUM = {"first": "Q1", "second": "Q2", "third": "Q3", "fourth": "Q4"}
MONTH_NUM = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
}


def fetch(url):
    # Use curl since urllib gets 403 from TE's bot defenses
    import subprocess
    try:
        result = subprocess.run(
            ["curl", "-s", "-A", UA, "--max-time", "30", url],
            capture_output=True, timeout=35,
        )
        if result.returncode == 0 and result.stdout:
            return result.stdout.decode("utf-8", errors="replace")
        return f"__ERR__:curl rc={result.returncode}"
    except Exception as e:
        return f"__ERR__:{e}"


def extract_period(desc):
    # Try month: "in March 2026" or "in March of 2026"
    m = re.search(
        r"in\s+(January|February|March|April|May|June|July|August|September|October|November|December)(?:\s+of)?\s+(\d{4})",
        desc, re.I,
    )
    if m:
        return f"{m.group(2)}-{MONTH_NUM[m.group(1).lower()]}"
    # Quarter: "the fourth quarter of 2025"
    m = re.search(
        r"the\s+(first|second|third|fourth)\s+quarter\s+of\s+(\d{4})",
        desc, re.I,
    )
    if m:
        return f"{m.group(2)}-{QUARTER_NUM[m.group(1).lower()]}"
    # Year only: "in 2024"
    m = re.search(r"in\s+(\d{4})\b", desc)
    if m:
        return m.group(1)
    return None


def extract_value(desc):
    m = re.search(r"(?:to|was)\s+(-?\d[\d,\.]+)", desc)
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            return None
    return None


def scrape(country, slug):
    te_slug = SLUG_TO_TE.get(slug, slug)
    url = f"https://tradingeconomics.com/{country}/{te_slug}"
    html = fetch(url)
    if html.startswith("__ERR__"):
        return {
            "slug": slug, "te_page": url, "te_label": None, "te_url": None,
            "te_value": None, "te_period": None, "verified": False,
            "error": html,
        }
    src_m = SOURCE_RE.search(html)
    desc_m = DESC_RE.search(html)
    desc = desc_m.group(1) if desc_m else ""
    if not src_m:
        return {
            "slug": slug, "te_page": url, "te_label": None, "te_url": None,
            "te_value": extract_value(desc), "te_period": extract_period(desc),
            "verified": False,
        }
    return {
        "slug": slug,
        "te_page": url,
        "te_label": src_m.group(2).strip(),
        "te_url": src_m.group(1).strip(),
        "te_value": extract_value(desc),
        "te_period": extract_period(desc),
        "verified": True,
    }


def main():
    country = sys.argv[1]
    slugs = sys.argv[2:]
    out = []
    for slug in slugs:
        if slug in SKIP_SLUGS:
            out.append({"slug": slug, "skip": True})
            continue
        result = scrape(country, slug)
        out.append(result)
        time.sleep(0.4)
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
