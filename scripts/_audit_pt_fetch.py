"""Fetch fresh TE pages for all 66 PT slugs and parse source/value/period.

Stashes raw HTML under docs/_audit_te_html/pt_reaudit/<slug>.html
Writes parsed result to docs/_audit_pt_fetch.json
"""
from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "docs" / "_audit_te_html" / "pt_reaudit"
OUT_JSON = ROOT / "docs" / "_audit_pt_fetch.json"
SLUGS_JSON = ROOT / "docs" / "_audit_all_remaining_slugs.json"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

# Map EconPulse slug -> TE URL path (relative to /portugal/)
SLUG_TO_TE = {
    "budget-deficit": "government-budget",
    "core-cpi": "core-inflation-rate",
    "gdp-real": "gdp-growth-annual",
    "government-debt": "government-debt",
    "government-debt-total": "government-debt",  # same page; TE shows two stats
    "ppi": "producer-prices",
    "unemployment": "unemployment-rate",
    "consumer-spending": "consumer-spending",
    "interest-rate": "interest-rate",
}


def te_url(slug: str) -> str:
    path = SLUG_TO_TE.get(slug, slug)
    return f"https://tradingeconomics.com/portugal/{path}"


SOURCE_RE = re.compile(
    r"source:\s*<a\s+class='source-name'[^>]*href\s*=\s*'([^']*)'[^>]*>([^<]+)</a>",
    re.I,
)
TITLE_VALUE_RE = re.compile(
    r'<meta\s+itemprop="name"[^>]*content="([^"]+)"', re.I
)
DESC_META_RE = re.compile(
    r'<meta\s+name="description"\s+content="([^"]+)"', re.I
)
# TE puts current value inside td#actual
TD_ACTUAL_RE = re.compile(
    r'<td\s+id="actual"[^>]*>\s*([^<\s][^<]*?)\s*</td>', re.I
)
# Header "Latest" stat (varies); fall back to first <td class="...te-...">
INDICATOR_HEADER_RE = re.compile(
    r'<span\s+class="market-header-text">\s*([^<]+?)\s*</span>', re.I
)
# Period from card
PERIOD_RE = re.compile(
    r'<small\s+class="date">([^<]+)</small>', re.I
)


def fetch_html(slug: str) -> str:
    """Fetch TE page, cache on disk."""
    cache = CACHE_DIR / f"{slug}.html"
    if cache.exists() and cache.stat().st_size > 5000:
        return cache.read_text(encoding="utf-8", errors="ignore")
    url = te_url(slug)
    r = subprocess.run(
        ["curl", "-s", "-A", UA, "--max-time", "30", "-L", url],
        capture_output=True,
        timeout=45,
    )
    html = r.stdout.decode("utf-8", errors="ignore")
    if len(html) > 1000:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_text(html, encoding="utf-8", errors="ignore")
    return html


def parse(html: str) -> dict:
    out = {}
    m = SOURCE_RE.search(html)
    if m:
        out["te_source_url"] = m.group(1)
        out["te_source_label"] = m.group(2).strip()

    m = DESC_META_RE.search(html)
    if m:
        out["te_meta_desc"] = m.group(1).strip()[:400]

    m = TD_ACTUAL_RE.search(html)
    if m:
        out["te_actual_td"] = m.group(1).strip()

    m = INDICATOR_HEADER_RE.search(html)
    if m:
        out["te_header"] = m.group(1).strip()

    # Look for "<num> ... <Month> <Year>" in meta desc to pull latest value
    if "te_meta_desc" in out:
        # e.g. "Portugal Inflation Rate increased to 3.30 percent in April from..."
        d = out["te_meta_desc"]
        m_num = re.search(
            r"(\d{1,4}[\.,]?\d{0,3})\s*(?:percent|%|EUR|USD|index|points|thousand|million|billion|of GDP)",
            d,
            re.I,
        )
        if m_num:
            out["te_meta_value"] = m_num.group(1).replace(",", ".")
        m_period = re.search(
            r"in\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})",
            d,
            re.I,
        )
        if m_period:
            out["te_meta_period"] = f"{m_period.group(2)}-{m_period.group(1)[:3]}"
        m_q = re.search(
            r"in\s+(?:Q|the\s+(?:first|second|third|fourth)\s+quarter\s+of\s+)(\d)?\s*(?:of\s+)?(\d{4})",
            d,
            re.I,
        )
        if m_q:
            out["te_meta_quarter"] = m_q.group(0)
    return out


def main():
    slugs_data = json.loads(SLUGS_JSON.read_text(encoding="utf-8"))
    pt_slugs = slugs_data["PT"]
    print(f"Fetching {len(pt_slugs)} PT slugs")
    results = {}
    for i, slug in enumerate(pt_slugs, 1):
        url = te_url(slug)
        try:
            html = fetch_html(slug)
            parsed = parse(html)
            parsed["te_url"] = url
            parsed["html_len"] = len(html)
            results[slug] = parsed
            print(f"  [{i:2d}/{len(pt_slugs)}] {slug:35s} src={parsed.get('te_source_label','?')[:30]:30s} val={parsed.get('te_actual_td','?'):>12s} desc-val={parsed.get('te_meta_value','?')}")
        except Exception as e:
            results[slug] = {"error": str(e), "te_url": url}
            print(f"  [{i:2d}/{len(pt_slugs)}] {slug:35s} ERROR {e}")
        # polite delay
        time.sleep(0.3)
    OUT_JSON.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {OUT_JSON}")


if __name__ == "__main__":
    main()
