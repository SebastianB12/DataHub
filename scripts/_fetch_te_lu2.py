"""Fetch all 66 LU TE pages with correct TE-slug mapping.
TE has different slugs than our internal ones. Map carefully."""
import json
import re
import subprocess
import time
from pathlib import Path

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

SOURCE_RE = re.compile(
    r"source:\s*<a class='source-name'[^>]*href\s*=\s*'([^']*)'[^>]*>([^<]+)</a>",
    re.I,
)
META_DESC = re.compile(r'<meta\s+name="description"\s+content="([^"]+)"', re.I)
CANON_RE = re.compile(r'<link rel="canonical" href="([^"]+)"')
TITLE_RE = re.compile(r"<title>([^<]+)</title>", re.S)

OUT_DIR = Path("docs/_audit_te_html/lu")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Map our slug -> TE slug. None = same as our slug.
TE_PATH = {
    "ppi": "producer-prices",
    "inflation-cpi": "inflation-cpi",  # this one we'll verify
    "gdp-real": "gdp-constant-prices",
    "gdp": "gdp",
    "consumer-spending": "consumer-spending",
    "government-spending": "government-spending",
    "government-spending-eur": "government-spending-value",
    "gross-fixed-capital-formation": "gross-fixed-capital-formation",
    "core-cpi": "core-inflation-rate",
    "food-inflation": "food-inflation",
    "energy-inflation": "energy-inflation",
    "services-inflation": "services-inflation",
    "cpi-food": "cpi-housing-utilities",  # WRONG - placeholder, fix below
    # CPI subindex pages on TE:
    # On TE these are usually pages like "/luxembourg/cpi-housing-utilities" — same slug.
    "cpi-clothing": "cpi-clothing",
    "cpi-education": "cpi-education",
    "cpi-food": "cpi-food",  # override above
    "cpi-housing-utilities": "cpi-housing-utilities",
    "cpi-recreation-and-culture": "cpi-recreation-and-culture",
    "cpi-transportation": "cpi-transportation",
    "unemployment": "unemployment-rate",
    "unemployed-persons": "unemployed-persons",
    "employed-persons": "employed-persons",
    "employment-rate": "employment-rate",
    "youth-unemployment-rate": "youth-unemployment-rate",
    "labor-force-participation-rate": "labor-force-participation-rate",
    "long-term-unemployment-rate": "long-term-unemployment-rate",
    "industrial-production": "industrial-production",
    "manufacturing-production": "manufacturing-production",
    "mining-production": "mining-production",
    "capacity-utilization": "capacity-utilization",
    "business-confidence": "business-confidence",
    "consumer-confidence": "consumer-confidence",
    "services-sentiment": "services-sentiment",
    "house-price-index": "housing-index",
    "retail-sales": "retail-sales-mom",  # TE usually has both -mom and a level; verify
    "interest-rate": "interest-rate",
    "current-account": "current-account",
    "current-account-to-gdp": "current-account-to-gdp",
    "exports": "exports",
    "imports": "imports",
    "budget-deficit": "government-budget",
    "government-debt": "government-debt-to-gdp",
    "government-debt-total": "government-debt",
    "disposable-personal-income": "disposable-personal-income",
    "labour-costs": "labour-costs",
    "job-vacancies": "job-vacancies",
    "productivity": "productivity",
    "minimum-wages": "minimum-wages",
    "population": "population",
    "changes-in-inventories": "changes-in-inventories",
    "personal-income-tax-rate": "personal-income-tax-rate",
    "corporate-tax-rate": "corporate-tax-rate",
    "sales-tax-rate": "sales-tax-rate",
    "social-security-rate": "social-security-rate",
    "social-security-rate-companies": "social-security-rate-for-companies",
    "social-security-rate-employees": "social-security-rate-for-employees",
    "retirement-age-men": "retirement-age-men",
    "retirement-age-women": "retirement-age-women",
    "credit-rating": "rating",
    "corruption-index": "corruption-index",
    "corruption-rank": "corruption-rank",
    "hospital-beds": "hospital-beds",
    "medical-doctors": "medical-doctors",
    "nurses": "nurses",
    "terrorism-index": "terrorism-index",
    "gdp-per-capita": "gdp-per-capita",
    "gdp-per-capita-ppp": "gdp-per-capita-ppp",
}


def fetch_te(country_path: str, te_slug: str, force: bool = False) -> tuple[str, str]:
    url = f"https://tradingeconomics.com/{country_path}/{te_slug}"
    cache = OUT_DIR / f"_{te_slug}.html"  # underscore prefix for new fetches
    if not force and cache.exists() and cache.stat().st_size > 50000:
        return url, cache.read_text(encoding="utf-8", errors="ignore")
    for attempt in range(3):
        try:
            r = subprocess.run(
                ["curl", "-sL", "-A", UA, "--max-time", "30", url],
                capture_output=True, timeout=40,
            )
            text = r.stdout.decode("utf-8", errors="ignore")
            if len(text) > 50000:
                cache.write_text(text, encoding="utf-8")
                return url, text
        except Exception:
            pass
        time.sleep(2 + attempt * 2)
    return url, ""


def parse_source(html: str) -> tuple[str | None, str | None]:
    m = SOURCE_RE.search(html)
    if m:
        return m.group(2).strip(), m.group(1).strip()
    return None, None


def parse_meta(html: str) -> str | None:
    m = META_DESC.search(html)
    return m.group(1).strip() if m else None


def parse_canonical(html: str) -> str | None:
    m = CANON_RE.search(html)
    return m.group(1).strip() if m else None


def main():
    slugs = json.load(open("docs/_audit_all_remaining_slugs.json"))["LU"]
    results = {}
    for i, slug in enumerate(slugs, 1):
        te_slug = TE_PATH.get(slug, slug)
        url, html = fetch_te("luxembourg", te_slug)
        src_name, src_url = parse_source(html) if html else (None, None)
        meta = parse_meta(html) if html else None
        canon = parse_canonical(html) if html else None
        results[slug] = {
            "te_slug": te_slug,
            "te_url": url,
            "canonical": canon,
            "html_bytes": len(html),
            "src_name": src_name,
            "src_url": src_url,
            "meta_desc": (meta[:400] if meta else None),
        }
        print(f"[{i:>2}/66] {slug:35s} -> {te_slug:35s} -> {src_name!r}")
        time.sleep(0.3)
    Path("docs/_audit_lu_te_raw.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nWrote {len(results)} entries to docs/_audit_lu_te_raw.json")


if __name__ == "__main__":
    main()
