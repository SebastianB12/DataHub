"""Retry slugs where source=None: try variant URLs + description-based source detection."""
import json
import re
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML_DIR = ROOT / "docs" / "_audit_te_html" / "gr_reaudit"
TE_DATA = ROOT / "docs" / "_audit_gr_te.json"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
SOURCE_RE = re.compile(r"source:\s*<a class='source-name'[^>]*href\s*=\s*'([^']*)'[^>]*>([^<]+)</a>", re.I)
DESC_RE = re.compile(r'<h2 id="description"[^>]*>(.*?)</h2>', re.S)

# Map common phrases in descriptions to detected source name
DESC_SOURCE_PATTERNS = [
    (re.compile(r"\bEurostat\b", re.I), "EUROSTAT"),
    (re.compile(r"Bank of Greece", re.I), "Bank of Greece"),
    (re.compile(r"Hellenic Statistical Authority|National Statistical Service of Greece|ELSTAT", re.I), "National Statistical Service of Greece"),
    (re.compile(r"European Commission", re.I), "European Commission"),
    (re.compile(r"European Central Bank|\bECB\b", re.I), "European Central Bank"),
    (re.compile(r"World Bank", re.I), "World Bank"),
    (re.compile(r"Transparency International", re.I), "Transparency International"),
    (re.compile(r"OECD", re.I), "OECD"),
    (re.compile(r"WHO|World Health Organization", re.I), "WHO"),
    (re.compile(r"IMF", re.I), "IMF"),
    (re.compile(r"Ministry of Finance|Ministry of Economy", re.I), "Ministry of Economy and Finance"),
    (re.compile(r"Conference Board", re.I), "Conference Board"),
    (re.compile(r"S&P|Moody|Fitch", re.I), "Credit Rating Agencies"),
    (re.compile(r"GSIS", re.I), "GSIS, Greece"),
    (re.compile(r"Institute for Economics and Peace", re.I), "Institute for Economics and Peace"),
]

data = json.load(open(TE_DATA, encoding="utf-8"))
todo = [k for k, v in data.items() if v.get("source_name") is None]
print(f"Need to retry: {len(todo)}")

for slug in todo:
    html_file = HTML_DIR / f"{slug}.html"
    html = html_file.read_text(encoding="utf-8", errors="ignore")

    # Re-extract description heuristic — sometimes <h2 id="description"> is missing
    # but a <meta name="description"> exists
    meta_desc = re.search(r'<meta name="description" content="([^"]+)"', html)
    meta_text = meta_desc.group(1) if meta_desc else None

    # Look for "Source: <something>" line anywhere
    src_alt = re.search(r"[Ss]ource:\s*</?[^>]+>\s*([A-Z][A-Za-z0-9 ,&\-/]+?)(?:</|<|\.|$)", html)
    src_text = src_alt.group(1).strip() if src_alt else None

    # Search description body for "Source:"
    desc = data[slug].get("description") or ""
    src_in_desc = re.search(r"Source:\s*([^\.<]+)", desc)
    src_from_desc = src_in_desc.group(1).strip() if src_in_desc else None

    # Description-content based pattern matching
    body = (desc or "") + " " + (meta_text or "")
    detected = None
    for pat, name in DESC_SOURCE_PATTERNS:
        if pat.search(body):
            detected = name
            break

    final = src_from_desc or src_text or detected
    data[slug]["source_name_retry"] = final
    data[slug]["description_meta"] = meta_text
    print(f"  {slug:40s} retry={final}")

TE_DATA.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"\nWritten {TE_DATA}")
