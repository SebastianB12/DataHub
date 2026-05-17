"""Re-fetch description for slugs where we need to classify the mismatch."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
DESC_RE = re.compile(r'<h2 id="description"[^>]*>(.*?)</h2>', re.S)
SOURCE_RE = re.compile(
    r"source:\s*<a class='source-name'[^>]*href\s*=\s*'([^']*)'[^>]*>([^<]+)</a>",
    re.I,
)


def fetch_te(url):
    r = subprocess.run(
        ["curl", "-s", "-A", UA, "--max-time", "30", "-w", "\n__HTTP__%{http_code}", url],
        capture_output=True, timeout=40,
    )
    body = r.stdout.decode("utf-8", errors="ignore")
    m = re.search(r"__HTTP__(\d+)$", body)
    return (int(m.group(1)) if m else 0), (body[:m.start()] if m else body)


SLUGS = sys.argv[1:] if len(sys.argv) > 1 else []
if not SLUGS:
    # Default: all mismatches/unknowns from batch1 findings
    with open(ROOT / "docs/_audit_us_batch1_findings.yaml", encoding="utf-8") as f:
        findings = yaml.safe_load(f)
    SLUGS = [s for s, v in findings.items() if not (v.get("source_match") and v.get("value_match"))]

inv_path = ROOT / "docs/_te_inventory/US.yaml"
with open(inv_path, encoding="utf-8") as f:
    inv = yaml.safe_load(f) or {}

out = {}
for slug in SLUGS:
    te_page = (inv.get(slug) or {}).get("te_page") or f"https://tradingeconomics.com/united-states/{slug}"
    code, html = fetch_te(te_page)
    desc = None
    label = None
    if code == 200:
        m = DESC_RE.search(html)
        if m:
            desc = re.sub(r"<[^>]+>", "", m.group(1)).strip()
            desc = re.sub(r"\s+", " ", desc)
        m = SOURCE_RE.search(html)
        if m:
            label = m.group(2).strip()
    print(f"## {slug}")
    print(f"  label: {label}")
    print(f"  desc:  {desc}")
    print()
    out[slug] = {"label": label, "desc": desc, "http": code}

with open(ROOT / "docs/_audit_us_batch1_desc.yaml", "w", encoding="utf-8") as f:
    yaml.safe_dump(out, f, allow_unicode=True, sort_keys=True, width=200)
