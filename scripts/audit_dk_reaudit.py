"""DK fresh re-audit. Fetches TE pages, parses source label + latest value,
compares to DB, and writes docs/_audit_dk_reaudit.yaml.
"""
from __future__ import annotations
import json, os, re, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.db import supabase as sb  # type: ignore

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
HTML_DIR = ROOT / "docs" / "_audit_te_html" / "DK"
HTML_DIR.mkdir(parents=True, exist_ok=True)

# DK slug -> TE slug (most are same)
SLUG_TO_TE_DK = {
    "inflation-cpi": "inflation-cpi",
    "core-cpi": "core-inflation-rate",
    "ppi": "producer-prices",
    "industrial-production": "industrial-production",
    "manufacturing-production": "manufacturing-production",
    "mining-production": "mining-production",
    "unemployment": "unemployment-rate",
    "employed-persons": "employed-persons",
    "unemployed-persons": "unemployed-persons",
    "employment-rate": "employment-rate",
    "labor-force-participation-rate": "labor-force-participation-rate",
    "youth-unemployment-rate": "youth-unemployment-rate",
    "long-term-unemployment-rate": "long-term-unemployment-rate",
    "job-vacancies": "job-vacancies",
    "labour-costs": "labour-costs",
    "minimum-wages": "minimum-wages",
    "retail-sales": "retail-sales-annual",  # DK often shows YoY
    "consumer-spending": "consumer-spending",
    "consumer-confidence": "consumer-confidence",
    "business-confidence": "business-confidence",
    "capacity-utilization": "capacity-utilization",
    "changes-in-inventories": "changes-in-inventories",
    "gdp-real": "gdp-growth-annual",
    "gdp": "gdp",
    "gdp-per-capita": "gdp-per-capita",
    "gdp-per-capita-ppp": "gdp-per-capita-ppp",
    "gross-fixed-capital-formation": "gross-fixed-capital-formation",
    "government-spending": "government-spending",
    "government-spending-eur": "government-spending-to-gdp",
    "government-debt": "government-debt-to-gdp",
    "government-debt-total": "government-debt",
    "current-account": "current-account",
    "current-account-to-gdp": "current-account-to-gdp",
    "trade-balance": "balance-of-trade",
    "exports": "exports",
    "imports": "imports",
    "budget-deficit": "government-budget",
    "population": "population",
    "food-inflation": "food-inflation",
    "services-inflation": "services-inflation",
    "energy-inflation": "energy-inflation",
    "cpi-food": "cpi-food",  # override broken SLUG_TO_TE
    "cpi-clothing": "cpi-clothing",
    "cpi-housing-utilities": "cpi-housing-utilities",
    "cpi-transportation": "cpi-transportation",
    "cpi-recreation-and-culture": "cpi-recreation-and-culture",
    "cpi-education": "cpi-education",
    "disposable-personal-income": "disposable-personal-income",
    "corporate-tax-rate": "corporate-tax-rate",
    "personal-income-tax-rate": "personal-income-tax-rate",
    "sales-tax-rate": "sales-tax-rate",
    "social-security-rate": "social-security-rate",
    "social-security-rate-companies": "social-security-rate-for-companies",
    "social-security-rate-employees": "social-security-rate-for-employees",
    "corruption-index": "corruption-index",
    "corruption-rank": "corruption-rank",
    "credit-rating": "rating",
    "hospital-beds": "hospital-beds",
    "medical-doctors": "medical-doctors",
    "nurses": "nurses",
    "terrorism-index": "terrorism-index",
    "retirement-age-men": "retirement-age-men",
    "retirement-age-women": "retirement-age-women",
    "house-price-index": "housing-index",
    "services-sentiment": "services-sentiment",
    "productivity": "productivity",
}

SOURCE_RE = re.compile(
    r"source:\s*<a\s+class='source-name'[^>]*?href\s*=\s*'([^']*)'[^>]*>([^<]+)</a>",
    re.I,
)
SOURCE_PRESENT_RE = re.compile(
    r"source-present['\"][^>]*>source:\s*([^<]+)",
    re.I,
)
TITLE_RE = re.compile(r"<title>([^<]+)</title>", re.I)
DESC_RE = re.compile(r'<h2 id="description"[^>]*>(.*?)</h2>', re.S)
# Latest value: search for "table table-hover" current value cell or `data-toggle="tooltip"`
# TE page typically has <span class="value"> or a card with class="te-card"; safer approach:
# pull value from the country indicators master page or rely on page text patterns.
META_VAL_RE = re.compile(
    r'<meta[^>]*?name=["\']description["\'][^>]*?content=["\']([^"\']+)["\']',
    re.I,
)
H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S | re.I)
# Big value near top of page in TE: "<div class='te-card-content[^']*'>" with main value
CARD_VAL_RE = re.compile(
    r"<span[^>]*class=['\"]te-summary-card-value['\"][^>]*>([^<]+)</span>",
    re.I,
)
# Fallback: first <td> inside <table class='table table-hover'> contains symbol; row contains latest
# Simpler: pull first number from page title/desc

def fetch_te(country_path: str, te_slug: str) -> tuple[str, str]:
    url = f"https://tradingeconomics.com/{country_path}/{te_slug}"
    cache = HTML_DIR / f"{te_slug}.html"
    if cache.exists() and cache.stat().st_size > 2000:
        return url, cache.read_text("utf-8", errors="ignore")
    r = subprocess.run(
        ["curl", "-s", "-A", UA, "--max-time", "30", url],
        capture_output=True, timeout=40,
    )
    html = r.stdout.decode("utf-8", errors="ignore")
    if len(html) > 2000:
        cache.write_text(html, encoding="utf-8")
    return url, html


def parse_source(html: str) -> tuple[str | None, str | None]:
    m = SOURCE_RE.search(html)
    if m:
        return m.group(2).strip(), m.group(1).strip()
    m = SOURCE_PRESENT_RE.search(html)
    if m:
        return m.group(1).strip(), None
    return None, None


def map_label_to_code(label: str | None) -> str | None:
    if not label:
        return None
    s = label.lower()
    if "statistics denmark" in s or "danmarks statistik" in s or s.strip() == "dst":
        return "dst"
    if "nationalbank" in s:
        return "dnb_dk"  # provider may not exist; mapping kept for honesty
    if "eurostat" in s or "european commission" in s:
        return "eurostat"
    if "european central bank" in s or s.strip() == "ecb":
        return "ecb"
    if "world bank" in s:
        return "worldbank"
    if "imf" in s:
        return "imf"
    if "oecd" in s or "conference board" in s or "transparency international" in s \
            or "who" in s or "sipri" in s or "moody" in s or "s&p" in s or "fitch" in s \
            or "dbrs" in s or "tax administration" in s or "institute for economics" in s:
        return "curated"
    return None


def parse_latest_value(html: str) -> tuple[str | None, str | None]:
    """Try multiple patterns. Return (value_str, period_str)."""
    # 1) meta description (most reliable for TE)
    desc = META_VAL_RE.search(html)
    if desc:
        txt = desc.group(1)
        # Match patterns like:
        # "Inflation Rate in Denmark increased to 1.40 percent in April from 1.20 percent in March of 2026"
        # "GDP in Denmark was last reported at 412.06 USD Billion in 2024"
        # "Government Debt in Denmark increased to 592.73 DKK Billion in March from 580.5"
        m = re.search(
            r"(?:to|at|of|reached|reported at|stood at|was)\s+(-?\d[\d,]*\.?\d*)",
            txt, re.I,
        )
        if not m:
            m = re.search(r"(-?\d[\d,]*\.?\d*)\s+(percent|points|index|EUR|USD|DKK|Million|Thousand|Billion|%)", txt, re.I)
        if m:
            mp = re.search(
                r"in\s+([A-Z][a-z]+(?:\s+of\s+\d{4})?|\d{4}(?:Q[1-4])?)",
                txt,
            )
            return m.group(1).replace(",", ""), (mp.group(1) if mp else None)
    # 2) summary card
    m = CARD_VAL_RE.search(html)
    if m:
        return m.group(1).strip(), None
    return None, None


def fetch_db_latest(slug: str):
    r = sb.table("data_points").select("date,value,source").eq("country", "DK") \
        .eq("indicator", slug).order("date", desc=True).limit(1).execute()
    if r.data:
        return r.data[0]["date"], r.data[0]["value"], r.data[0]["source"]
    return None, None, None


def main():
    with open(ROOT / "docs" / "_audit_all_remaining_slugs.json", "r", encoding="utf-8") as f:
        dk_slugs = json.load(f)["DK"]

    # current sources
    rows = sb.table("indicator_sources").select("indicator,source,series_id,note") \
        .eq("country", "DK").eq("is_default", True).execute().data
    db_src = {x["indicator"]: x for x in rows}

    out: dict[str, dict] = {}
    for i, slug in enumerate(dk_slugs):
        te_slug = SLUG_TO_TE_DK.get(slug, slug)
        url, html = fetch_te("denmark", te_slug)
        label, src_url = parse_source(html)
        te_code = map_label_to_code(label)
        val, period = parse_latest_value(html)
        db_date, db_val, db_pt_source = fetch_db_latest(slug)
        cur = db_src.get(slug, {})
        out[slug] = {
            "te_slug": te_slug,
            "te_page": url,
            "te_label": label,
            "te_source_url": src_url,
            "te_source_code": te_code,
            "te_value_raw": val,
            "te_period_raw": period,
            "db_source": cur.get("source"),
            "db_series_id": cur.get("series_id"),
            "db_note": cur.get("note"),
            "db_latest_date": db_date,
            "db_latest_value": db_val,
            "db_latest_source": db_pt_source,
            "status": (
                "OK" if cur.get("source") and te_code and cur.get("source") == te_code
                else ("HTML_MISSING" if label is None else "SRC_MISMATCH")
            ),
        }
        if (i + 1) % 10 == 0:
            print(f"  fetched {i+1}/{len(dk_slugs)}", flush=True)
        time.sleep(0.4)
    # save
    import yaml
    out_path = ROOT / "docs" / "_audit_dk_reaudit.yaml"
    with open(out_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(out, f, allow_unicode=True, sort_keys=True)
    print(f"wrote {out_path}")
    # summary
    statuses = {}
    for v in out.values():
        statuses[v["status"]] = statuses.get(v["status"], 0) + 1
    print("status counts:", statuses)


if __name__ == "__main__":
    main()
