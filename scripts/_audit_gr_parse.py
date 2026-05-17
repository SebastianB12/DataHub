"""Re-parse all GR TE pages with robust description extraction.
Source is in the description after 'source:'. Value is the first number after slug name.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML_DIR = ROOT / "docs" / "_audit_te_html" / "gr_reaudit"
TE_DATA = ROOT / "docs" / "_audit_gr_te.json"

# Source name canonicalizer → our internal provider
SOURCE_TO_PROVIDER = [
    (re.compile(r"\b(?:Hellenic Statistical Authority|National Statistical Service of Greece|ELSTAT)\b", re.I), ("elstat", "ELSTAT")),
    (re.compile(r"\bBank of Greece\b", re.I), ("bog", "Bank of Greece")),
    (re.compile(r"\bEUROSTAT|Eurostat\b"), ("eurostat", "EUROSTAT")),
    (re.compile(r"\bEuropean Central Bank|ECB\b"), ("ecb", "ECB")),
    (re.compile(r"\bWorld Bank\b", re.I), ("worldbank", "World Bank")),
    (re.compile(r"\bEuropean Commission\b", re.I), ("eurostat", "European Commission (via Eurostat ei_*)")),
    (re.compile(r"\bMinistry of (?:Economy|Finance)|Ministry of Finance\b", re.I), ("curated_or_bog", "Ministry of Economy and Finance")),
    (re.compile(r"\bGSIS\b", re.I), ("curated", "GSIS Greece")),
    (re.compile(r"\bTransparency International\b", re.I), ("curated", "Transparency International")),
    (re.compile(r"\bConference Board\b", re.I), ("curated", "Conference Board")),
    (re.compile(r"\bOECD\b"), ("curated", "OECD")),
    (re.compile(r"\bWHO\b|World Health Organization", re.I), ("curated", "WHO")),
    (re.compile(r"\bIMF\b"), ("curated", "IMF")),
    (re.compile(r"\bInstitute for Economics and Peace\b", re.I), ("curated", "Institute for Economics and Peace")),
    (re.compile(r"\bSIPRI\b"), ("curated", "SIPRI")),
    (re.compile(r"\bUnited Nations\b", re.I), ("curated", "United Nations")),
    (re.compile(r"\bMoody|S&P|Fitch\b", re.I), ("curated", "Credit Rating Agencies")),
    (re.compile(r"\bHellenic Ministry of Labour|Ministry of Labour\b", re.I), ("curated", "Hellenic Ministry of Labour")),
]


def clean_html(html_chunk: str) -> str:
    t = re.sub(r"<[^>]+>", " ", html_chunk)
    return re.sub(r"\s+", " ", t).strip()


def parse_te_page(html: str) -> dict:
    """Extract: source-name, source-url, description text, current value."""
    # Description block
    desc_match = re.search(r'<h2 id="description"[^>]*>(.*?)(?:<h2|</div>\s*</div>)', html, re.S)
    desc_text = clean_html(desc_match.group(1)) if desc_match else None

    # Source name from description "source: X"
    source_text = None
    if desc_text:
        m = re.search(r"source:\s*([^.]+?)\s*$", desc_text)
        if m:
            source_text = m.group(1).strip()

    # Also try the <a class='source-name'> pattern
    src_a = re.search(r"class=['\"]source-name['\"][^>]*>([^<]+)<", html, re.I)
    if src_a and not source_text:
        source_text = src_a.group(1).strip()
    src_url = re.search(r"class=['\"]source-name['\"][^>]*href=['\"]([^'\"]+)['\"]", html, re.I)
    source_url = src_url.group(1) if src_url else None

    # Current value: first numeric quote in description before " in Greece" or "at"
    value_str = None
    if desc_text:
        # patterns:
        # 'X in Greece <changed> to <value> <unit> in <date> from <prev> <unit> in <date>'
        m = re.search(r"\b(?:to|at|of|was|stood at|reached|remained unchanged at)\s+([\-\+]?\d+(?:[\.,]\d+)?)\s*(?:%|Years?|points?|EUR|USD|points|Million|Thousand)?", desc_text)
        if m:
            value_str = m.group(1).replace(",", "")

    # Map to our provider
    provider, provider_label = None, None
    if source_text:
        for pat, (p, lbl) in SOURCE_TO_PROVIDER:
            if pat.search(source_text):
                provider, provider_label = p, lbl
                break

    return {
        "source_text": source_text,
        "source_url": source_url,
        "description": desc_text[:500] if desc_text else None,
        "value_str": value_str,
        "provider_guess": provider,
        "provider_label": provider_label,
    }


data = json.load(open(TE_DATA, encoding="utf-8"))

for slug in list(data.keys()):
    # Try remapped first, then plain
    candidates = []
    if data[slug].get("te_slug_remapped"):
        candidates.append(HTML_DIR / f"{slug}__remap__{data[slug]['te_slug_remapped']}.html")
    candidates.append(HTML_DIR / f"{slug}.html")
    html = None
    used_file = None
    for f in candidates:
        if f.exists() and f.stat().st_size > 5000:
            html = f.read_text(encoding="utf-8", errors="ignore")
            used_file = f.name
            break
    if not html:
        data[slug]["parse_error"] = "no html"
        continue
    parsed = parse_te_page(html)
    data[slug]["parsed"] = parsed
    data[slug]["html_file"] = used_file

TE_DATA.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

# Print summary
print(f"{'slug':40s} | {'TE-source-text':50s} | provider     | value")
print("-" * 130)
for slug, v in sorted(data.items()):
    p = v.get("parsed") or {}
    src = (p.get("source_text") or "")[:48]
    prov = p.get("provider_guess") or ""
    val = p.get("value_str") or ""
    print(f"{slug:40s} | {src:50s} | {prov:12s} | {val}")
