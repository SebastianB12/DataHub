"""Fetch fresh TE pages for all 67 GR slugs and parse source + value."""
import json
import os
import re
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML_DIR = ROOT / "docs" / "_audit_te_html" / "gr_reaudit"
HTML_DIR.mkdir(parents=True, exist_ok=True)
OUT = ROOT / "docs" / "_audit_gr_te.json"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

SOURCE_RE = re.compile(r"source:\s*<a class='source-name'[^>]*href\s*=\s*'([^']*)'[^>]*>([^<]+)</a>", re.I)
DESC_RE = re.compile(r'<h2 id="description"[^>]*>(.*?)</h2>', re.S)
TITLE_RE = re.compile(r'<title>([^<]+)</title>', re.I)
# TE country pages have "Last" current-value summary table
LAST_RE = re.compile(r'<td[^>]*class="datatable-item-first"[^>]*>([^<]+)</td>\s*<td[^>]*>([^<]+)</td>', re.I)
# Common pattern: "Greece <slug> at <value>"
H1_VALUE_RE = re.compile(r'<span[^>]*itemprop="title"[^>]*>([^<]+)</span>.*?<h1[^>]*>([^<]+)</h1>', re.S)

slugs = json.load(open(ROOT / "docs" / "_audit_all_remaining_slugs.json"))["GR"]

results = {}
for i, slug in enumerate(slugs, 1):
    url = f"https://tradingeconomics.com/greece/{slug}"
    html_file = HTML_DIR / f"{slug}.html"
    if html_file.exists() and html_file.stat().st_size > 5000:
        html = html_file.read_text(encoding="utf-8", errors="ignore")
    else:
        try:
            r = subprocess.run(
                ["curl", "-s", "-A", UA, "--max-time", "30", url],
                capture_output=True, timeout=40
            )
            html = r.stdout.decode("utf-8", errors="ignore")
            html_file.write_text(html, encoding="utf-8")
        except Exception as e:
            print(f"  FAIL fetch {slug}: {e}")
            results[slug] = {"url": url, "error": str(e)}
            continue
        time.sleep(0.3)

    src_match = SOURCE_RE.search(html)
    desc_match = DESC_RE.search(html)
    title_match = TITLE_RE.search(html)

    source_url = src_match.group(1) if src_match else None
    source_name = src_match.group(2).strip() if src_match else None
    description = re.sub(r"\s+", " ", desc_match.group(1)) if desc_match else None
    title = title_match.group(1).strip() if title_match else None

    # try to extract current TE value from title or h1
    te_value = None
    # title pattern: "Greece <Name> - 2026 Data - 2027 Forecast"
    # h1 pattern: <h1>Greece <Name> at <value>%</h1> sometimes
    h1_match = re.search(r'<h1[^>]*>([^<]+)</h1>', html)
    h1_text = h1_match.group(1).strip() if h1_match else None
    if h1_text:
        # Look for "at X.XX" pattern
        m = re.search(r'(?:at|was|stood at|fell to|rose to|recorded|increased to|decreased to)\s+([\-\+]?\d+(?:[\.,]\d+)?)', h1_text + " " + (description or ""))
        if m:
            te_value = m.group(1).replace(",", ".")

    # Also look for "Greece <indicator>" stand-alone fact tables
    # Pattern: <span class="te-summary-up...">+X.XX%</span> or similar
    fact_match = re.search(r'<span[^>]*class="te-summary-[^"]*"[^>]*>([\-\+]?\d+(?:[\.,]\d+)?[^<]*)</span>', html)
    if fact_match and not te_value:
        te_value = fact_match.group(1).strip()

    print(f"  [{i:2d}/67] {slug:40s} src={source_name}")
    results[slug] = {
        "url": url,
        "source_url": source_url,
        "source_name": source_name,
        "description": description[:500] if description else None,
        "title": title,
        "h1": h1_text,
        "te_value_raw": te_value,
    }

OUT.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"\nWritten {OUT} with {len(results)} entries")
