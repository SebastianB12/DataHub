"""Fetch all 66 LU TE pages and parse source + latest value."""
import json
import os
import re
import subprocess
import time
from pathlib import Path

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

SOURCE_RE = re.compile(
    r"source:\s*<a class='source-name'[^>]*href\s*=\s*'([^']*)'[^>]*>([^<]+)</a>",
    re.I,
)
DESC_RE = re.compile(r'<h2 id="description"[^>]*>(.*?)</h2>', re.S)
# value parsing — look at the "last" data box (TE renders a top stat)
VAL_RE = re.compile(
    r'<div[^>]*class="[^"]*?card[^"]*?"[^>]*>.*?<h1[^>]*>([^<]+)</h1>', re.S
)
# alt: <span ... id="last">
LAST_RE = re.compile(r'id="last"[^>]*>([^<]+)<', re.I)
META_DESC = re.compile(r'<meta\s+name="description"\s+content="([^"]+)"', re.I)

OUT_DIR = Path("docs/_audit_te_html/lu")
OUT_DIR.mkdir(parents=True, exist_ok=True)


def fetch_te(country_path: str, te_slug: str, max_retries: int = 3) -> tuple[str, str]:
    url = f"https://tradingeconomics.com/{country_path}/{te_slug}"
    cache = OUT_DIR / f"{te_slug}.html"
    if cache.exists() and cache.stat().st_size > 5000:
        return url, cache.read_text(encoding="utf-8", errors="ignore")
    last_err = None
    for attempt in range(max_retries):
        try:
            r = subprocess.run(
                ["curl", "-s", "-A", UA, "--max-time", "30", url],
                capture_output=True, timeout=40,
            )
            text = r.stdout.decode("utf-8", errors="ignore")
            if len(text) > 5000:
                cache.write_text(text, encoding="utf-8")
                return url, text
            last_err = f"too short ({len(text)} bytes)"
        except Exception as e:
            last_err = str(e)
        time.sleep(2 + attempt * 2)
    return url, ""


def parse_source(html: str) -> tuple[str | None, str | None]:
    m = SOURCE_RE.search(html)
    if m:
        return m.group(2).strip(), m.group(1).strip()
    # Fallback: search description box
    m2 = DESC_RE.search(html)
    if m2:
        d = m2.group(1)
        m3 = re.search(r"source:\s*<a[^>]*>([^<]+)</a>", d, re.I)
        if m3:
            return m3.group(1).strip(), None
    return None, None


def parse_value(html: str) -> str | None:
    """Get the headline value from meta description.
    TE puts e.g. "The Inflation Rate ... reported X percent in April of 2026"."""
    m = META_DESC.search(html)
    if m:
        return m.group(1).strip()
    return None


# Slug-to-TE-path mapping. Most slugs map 1:1 to TE URL; some need rewriting.
TE_PATH = {
    "consumer-spending": "consumer-spending",
    "government-spending": "government-spending",
    "gross-fixed-capital-formation": "gross-fixed-capital-formation",
    "gdp-real": "gdp-growth-annual",  # may need re-check; TE has "gdp-constant-prices"
    "gdp": "gdp",
    "gdp-per-capita": "gdp-per-capita",
    "gdp-per-capita-ppp": "gdp-per-capita-ppp",
    # the rest are 1:1
}


def main():
    slugs = json.load(open("docs/_audit_all_remaining_slugs.json"))["LU"]
    results = {}
    for i, slug in enumerate(slugs, 1):
        te_slug = TE_PATH.get(slug, slug)
        # Adjust: a few well-known TE slug variants
        if slug == "gdp-real":
            te_slug = "gdp-constant-prices"
        if slug == "government-debt-total":
            te_slug = "government-debt"  # TE doesn't have -total — overlay shown later
        if slug == "government-spending-eur":
            te_slug = "government-spending-value"
        url, html = fetch_te("luxembourg", te_slug)
        src_name, src_url = parse_source(html) if html else (None, None)
        meta = parse_value(html) if html else None
        results[slug] = {
            "te_slug": te_slug,
            "te_url": url,
            "html_bytes": len(html),
            "src_name": src_name,
            "src_url": src_url,
            "meta_desc": meta,
        }
        print(f"[{i:>2}/66] {slug:35s} -> {src_name!r}")
        time.sleep(0.4)
    Path("docs/_audit_lu_te_raw.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nWrote docs/_audit_lu_te_raw.json with {len(results)} entries.")


if __name__ == "__main__":
    main()
