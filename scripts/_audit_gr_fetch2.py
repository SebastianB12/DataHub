"""Fetch fresh TE pages for slugs where the TE URL is different than our slug name."""
import json
import os
import re
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML_DIR = ROOT / "docs" / "_audit_te_html" / "gr_reaudit"
HTML_DIR.mkdir(parents=True, exist_ok=True)
TE_DATA = ROOT / "docs" / "_audit_gr_te.json"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
SOURCE_RE = re.compile(r"source:\s*<a class='source-name'[^>]*href\s*=\s*'([^']*)'[^>]*>([^<]+)</a>", re.I)
DESC_RE = re.compile(r'<h2 id="description"[^>]*>(.*?)</h2>', re.S)

# Map our slug -> TE actual slug to retry against
SLUG_REMAP = {
    "budget-deficit": "government-budget",
    "core-cpi": "core-inflation-rate",  # also core-consumer-prices
    "credit-rating": "rating",
    "gdp-real": "gdp-constant-prices",
    "government-debt-total": "government-debt",
    "government-spending-eur": "government-spending",
    "house-price-index": "housing-index",
    "ppi": "producer-prices",
    "social-security-rate-companies": "social-security-rate-for-companies",
    "social-security-rate-employees": "social-security-rate-for-employees",
    "trade-balance": "balance-of-trade",
    "unemployment": "unemployment-rate",
}

# Slugs where TE may simply not host a per-Greece page (curated globally)
NO_TE_GR_PAGE = {
    "hospital-beds", "medical-doctors", "nurses",
    "retirement-age-men", "retirement-age-women",
    "social-security-rate",  # group page might still exist; try
    "disposable-personal-income",  # try anyway
    "energy-inflation", "services-inflation", "services-sentiment",
}

data = json.load(open(TE_DATA, encoding="utf-8"))

retry_list = list(SLUG_REMAP.items()) + [
    (slug, slug) for slug in NO_TE_GR_PAGE
]
# Also retry social-security-rate
retry_list.append(("social-security-rate", "social-security-rate"))
retry_list.append(("disposable-personal-income", "disposable-personal-income"))

seen = set()
for our_slug, te_slug in retry_list:
    if our_slug in seen:
        continue
    seen.add(our_slug)
    url = f"https://tradingeconomics.com/greece/{te_slug}"
    html_file = HTML_DIR / f"{our_slug}__remap__{te_slug}.html"
    if not html_file.exists() or html_file.stat().st_size < 5000:
        try:
            r = subprocess.run(
                ["curl", "-s", "-A", UA, "--max-time", "30", url],
                capture_output=True, timeout=40
            )
            html = r.stdout.decode("utf-8", errors="ignore")
            html_file.write_text(html, encoding="utf-8")
        except Exception as e:
            print(f"  FAIL {our_slug}: {e}")
            continue
        time.sleep(0.4)
    else:
        html = html_file.read_text(encoding="utf-8", errors="ignore")

    src_match = SOURCE_RE.search(html)
    desc_match = DESC_RE.search(html)
    h1_match = re.search(r'<h1[^>]*>([^<]+)</h1>', html)
    meta_desc = re.search(r'<meta name="description" content="([^"]+)"', html)

    source_url = src_match.group(1) if src_match else None
    source_name = src_match.group(2).strip() if src_match else None
    description = re.sub(r"\s+", " ", desc_match.group(1)) if desc_match else None
    h1 = h1_match.group(1).strip() if h1_match else None

    # value heuristics: title "Greece X - YYYY Data" → look for h1 value
    title_match = re.search(r'<title>([^<]+)</title>', html)
    title = title_match.group(1).strip() if title_match else None

    val = None
    if h1:
        m = re.search(r'([\-\+]?\d+(?:[\.,]\d+)?)\s*(?:%|points?|EUR|USD|Index)?', h1.split("at")[-1] if "at" in h1.lower() else "")
        if m:
            val = m.group(1)
    if not val and meta_desc:
        m = re.search(r'(?:at|was|stood at|fell to|rose to|recorded|increased to|decreased to)\s+([\-\+]?\d+(?:[\.,]\d+)?)', meta_desc.group(1))
        if m:
            val = m.group(1)

    data[our_slug]["te_slug_remapped"] = te_slug
    data[our_slug]["source_url"] = source_url or data[our_slug].get("source_url")
    data[our_slug]["source_name"] = source_name or data[our_slug].get("source_name")
    data[our_slug]["description"] = description or data[our_slug].get("description")
    data[our_slug]["description_meta"] = meta_desc.group(1) if meta_desc else data[our_slug].get("description_meta")
    data[our_slug]["title"] = title or data[our_slug].get("title")
    data[our_slug]["h1"] = h1 or data[our_slug].get("h1")
    data[our_slug]["te_value_raw"] = val or data[our_slug].get("te_value_raw")
    print(f"  {our_slug:40s} -> {te_slug:35s} src={source_name} h1={h1}")

TE_DATA.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"\nWritten {TE_DATA}")
