"""Fetch TE pages for FR batch2 slugs and extract source label + latest value."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

# slug -> te path on tradingeconomics.com/france/<...>
SLUG_TO_TE = {
    "energy-inflation": "energy-inflation",
    "exports": "exports",
    "food-inflation": "food-inflation",
    "gdp": "gdp",
    "gdp-growth-rate": "gdp-growth",   # quarterly QoQ
    "gdp-per-capita": "gdp-per-capita",
    "gdp-per-capita-ppp": "gdp-per-capita-ppp",
    "gdp-real": "gdp-growth-annual",
    "government-debt": "government-debt",
    "government-debt-total": "government-debt-to-gdp",  # TE shows debt-to-gdp; or just government-debt? we'll fetch both
    "government-spending": "government-spending",
    "government-spending-eur": "government-spending-value",
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
}

OUT_DIR = Path("docs/_audit_te_html/fr_batch2")
OUT_DIR.mkdir(parents=True, exist_ok=True)


def fetch_te(url):
    r = subprocess.run(
        ["curl", "-s", "-A", UA, "--max-time", "30", "-w", "\n__HTTP__%{http_code}", url],
        capture_output=True, timeout=40
    )
    body = r.stdout.decode("utf-8", errors="ignore")
    m = re.search(r"__HTTP__(\d+)$", body)
    code = int(m.group(1)) if m else 0
    return code, body[:m.start()] if m else body


SOURCE_RE = re.compile(r"source:\s*<a\s+class='source-name'[^>]*href\s*=\s*'([^']*)'[^>]*>([^<]+)</a>", re.I)
DESC_RE = re.compile(r'<h2 id="description"[^>]*>(.*?)</h2>', re.S)
# Latest value table — look for <table id="ctl00_..."> or the panel-heading
LATEST_RE = re.compile(r'data-symbol[^>]*>\s*([\-\d\.,]+)\s*</td>', re.I)
# Multiple alternates


def parse(slug, html):
    src_m = SOURCE_RE.search(html)
    src = (src_m.group(2).strip() if src_m else None)
    src_url = (src_m.group(1).strip() if src_m else None)
    desc_m = DESC_RE.search(html)
    desc = desc_m.group(1).strip()[:240] if desc_m else None
    # Try to find latest value row from the indicator page
    # TE has table.calendar with first <td> = country, then date, then unit, then value
    # Heuristic: find first "<tr" then group of "<td"
    # Use og:description fallback
    og = re.search(r'<meta\s+property="og:description"\s+content="([^"]+)"', html)
    og_desc = og.group(1) if og else None
    return {"source": src, "source_url": src_url, "desc": desc, "og": og_desc}


def main():
    results = {}
    for slug, te in SLUG_TO_TE.items():
        cache = OUT_DIR / f"{slug}.html"
        if cache.exists() and cache.stat().st_size > 1000:
            html = cache.read_text("utf-8", errors="ignore")
            code = 200
        else:
            url = f"https://tradingeconomics.com/france/{te}"
            code, html = fetch_te(url)
            cache.write_text(html, "utf-8", errors="ignore")
        if code != 200 or len(html) < 1000:
            results[slug] = {"http": code, "size": len(html)}
            print(f"  FAIL {slug}: http={code} size={len(html)}")
            continue
        parsed = parse(slug, html)
        parsed["http"] = code
        parsed["te_slug"] = te
        results[slug] = parsed
        print(f"  OK   {slug}: src={parsed.get('source')!r} te={te}")
    (OUT_DIR / "_parsed.json").write_text(json.dumps(results, indent=2), "utf-8")


if __name__ == "__main__":
    main()
