"""Parse all TE pages for HR. Extract source label/url and current value."""
import re, pathlib, json

HTML_DIR = pathlib.Path("docs/_audit_te_html/HR")

SOURCE_RE = re.compile(
    r"source:\s*<a class='source-name'[^>]*href\s*=\s*'([^']*)'[^>]*>([^<]+)</a>",
    re.I,
)
DESC_RE = re.compile(r'<h2 id="description"[^>]*>(.*?)</h2>', re.S)
# Inline source fallback: parse text after "source:" from description
INLINE_SOURCE_RE = re.compile(r'source[:\s]+([A-Z][^.,<\n]{2,100})')

LAST_SPAN_RE = re.compile(r'<span[^>]*market-id-last[^>]*>([^<]+)</span>', re.I)
TABLE_LAST_RE = re.compile(
    r'>Last<\s*/(?:th|td)>\s*<td[^>]*>\s*([^<\s][^<]*?)\s*</td>',
    re.I,
)

# Broad description-based value patterns. Order matters: most specific first.
PATTERNS = [
    # "advanced by 5.8% year-on-year"
    re.compile(r'(?:advanced|grew|expanded|rose|increased|jumped|edged up|climbed|surged|fell|declined|dropped|decreased|slid|contracted|shrank|narrowed|widened|slowed|sped)\s+by\s+(-?\d[\d,]*\.?\d*)\s*%', re.I),
    # "rose to 5.8%" / "stood at 5.8 percent"
    re.compile(r'(?:stood|equal(?:led|s)?|amounted to|came in at|was last (?:reported|recorded) at|was reported at|reached|recorded)\s+(?:at\s+)?(-?\d[\d,]*\.?\d*)\s*(?:percent|%|points|EUR|HRK|million|billion|years|cars|persons|people)', re.I),
    # "increased to 5.8%"
    re.compile(r'(?:increased|decreased|rose|fell|jumped|surged|climbed|dropped|advanced|edged) to (?:a record |an all-time |around )?(-?\d[\d,]*\.?\d*)', re.I),
    # "remained unchanged at 5.8" / "stands at 5.8"
    re.compile(r'(?:remained (?:unchanged|stable) at|stands at|holds at|is set at)\s+(-?\d[\d,]*\.?\d*)', re.I),
    # "X percent in <month> of <year>"
    re.compile(r'increased\s+(-?\d[\d,]*\.?\d*)\s+percent', re.I),
    # equal to X percent
    re.compile(r'equal to\s+(-?\d[\d,]*\.?\d*)\s*(?:percent|%)', re.I),
    # "worth X billion US dollars"
    re.compile(r'worth\s+(-?\d[\d,]*\.?\d*)\s+billion', re.I),
    # "estimated at X million"
    re.compile(r'estimated at\s+(-?\d[\d,]*\.?\d*)\s+million', re.I),
    # "scored X points"
    re.compile(r'scored\s+(-?\d[\d,]*\.?\d*)\s*points', re.I),
    # "is the X least corrupt"
    re.compile(r'is the\s+(\d+)\s+least', re.I),
    # "decreased by X EUR million"
    re.compile(r'(?:decreased|increased) by\s+(-?\d[\d,]*\.?\d*)\s+EUR', re.I),
    # "registered/posted X"
    re.compile(r'(?:registered|posted)\s+(-?\d[\d,]*\.?\d*)', re.I),
    # Fallback: first "<num> percent/points" in sentence beginning
    re.compile(r'^\s*[A-Z][^.]{0,200}?(-?\d[\d,]*\.?\d*)\s+(?:percent|points|EUR|million|billion)', re.I),
]

# Slug-specific custom extractors
def extract_credit_rating(html: str) -> dict:
    """Credit rating page has S&P/Moody's/Fitch ratings. Return dict."""
    out = {}
    m = re.search(r"Standard\s*&(?:amp;)?\s*Poor[^.]*?stands at\s+(\S+)\s+with\s+(\w+)", html, re.I)
    if m: out["sp"] = (m.group(1), m.group(2))
    m = re.search(r"Moody[^.]*?(?:was last set at|stands at)\s+(\S+)\s+with\s+(\w+)", html, re.I)
    if m: out["moodys"] = (m.group(1), m.group(2))
    m = re.search(r"DBRS[^.]*?at\s+(\S+)\s+with\s+(\w+)", html, re.I)
    if m: out["dbrs"] = (m.group(1), m.group(2))
    return out


def parse_te(slug: str, html: str) -> dict:
    src_match = SOURCE_RE.search(html)
    src_url = src_match.group(1) if src_match else ""
    src_label = src_match.group(2).strip() if src_match else ""
    desc = DESC_RE.search(html)
    desc_text = re.sub(r"<[^>]+>", " ", desc.group(1)).strip() if desc else ""
    # if no <a> source link, try inline source label inside description
    if not src_label and desc_text:
        m = INLINE_SOURCE_RE.search(desc_text)
        if m:
            src_label = m.group(1).strip().rstrip(".")

    # value extraction
    val = None
    m = LAST_SPAN_RE.search(html)
    if m:
        try:
            val = float(m.group(1).replace(",", ""))
        except ValueError:
            pass
    if val is None:
        m = TABLE_LAST_RE.search(html)
        if m:
            try:
                val = float(m.group(1).replace(",", "").split()[0])
            except (ValueError, IndexError):
                pass
    if val is None and desc_text:
        for pat in PATTERNS:
            m = pat.search(desc_text)
            if m:
                try:
                    val = float(m.group(1).replace(",", ""))
                    break
                except ValueError:
                    continue

    extras = {}
    if slug == "credit-rating":
        extras = extract_credit_rating(html)

    return {
        "te_source_label": src_label,
        "te_source_url": src_url,
        "te_value": val,
        "desc_snippet": desc_text[:400],
        "extras": extras,
    }


def main():
    results = {}
    for fp in sorted(HTML_DIR.glob("*.html")):
        slug = fp.stem
        html = fp.read_text(encoding="utf-8", errors="ignore")
        results[slug] = parse_te(slug, html)
    out = pathlib.Path("docs/_audit_hr_te_parsed.json")
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Parsed {len(results)} slugs -> {out}")
    for slug, r in sorted(results.items()):
        print(f"{slug:35} val={str(r['te_value']):>10}  src='{r['te_source_label']}'")


if __name__ == "__main__":
    main()
