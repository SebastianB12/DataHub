"""Parse TE SI HTML pages -> {slug: {te_source_name, te_source_url, te_value, te_unit, te_period}}.

Outputs docs/_audit_si_te_parsed.json.
"""
import json
import re
from pathlib import Path

SRCDIR = Path("docs/_audit_si_te_html")

# Multiple patterns observed across TE pages.
SOURCE_RE = re.compile(
    r"source:\s*<a class=['\"]source-name['\"][^>]*href\s*=\s*['\"]([^'\"]*)['\"][^>]*>([^<]+)</a>",
    re.I,
)
# Fallback: bare "Source: <a>...</a>"
SOURCE_FALLBACK_RE = re.compile(
    r"Source[:\s]+<a[^>]*href=['\"]([^'\"]*)['\"][^>]*>([^<]+)</a>",
    re.I,
)
# Even barer: "Source: Eurostat" plain text
SOURCE_PLAIN_RE = re.compile(r"Source[:\s]+([A-Z][A-Za-z &.,()/'-]{2,80}?)(?:</|<br|\n|\s*\|)", re.I)

# Headline data line on TE: e.g. "<title>Slovenia Inflation Rate - April 2026</title>"
# Body table: <span class="te-indicator-headline">...</span>
HEADLINE_VAL_RE = re.compile(
    r'<th[^>]*colspan=\\?"\\?"[^>]*>([^<]+)</th>\s*<th[^>]*>([^<]+)</th>',
    re.I,
)
# Easier: title meta has the freshest figure
META_DESC_RE = re.compile(
    r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
    re.I,
)
# Body table — first table.table-hover row has "Last | Previous | Unit | Reference"
TABLE_ROW_RE = re.compile(
    r"<tr>\s*<td[^>]*><a[^>]*>([^<]+)</a></td>\s*<td[^>]*>([^<]+)</td>\s*<td[^>]*>([^<]+)</td>",
    re.I | re.S,
)
# Strongest: the big "value" displayed under indicator-headline
INLINE_VALUE_RE = re.compile(
    r'class=["\'][^"\']*headline[^"\']*["\'][^>]*>\s*([+\-0-9.,]+)\s*<',
    re.I,
)
# Description (page intro)
DESC_H1_RE = re.compile(r"<h1[^>]*>([^<]+)</h1>", re.I)


def parse_one(slug, html):
    out = {"slug": slug}
    # source attribution
    m = SOURCE_RE.search(html)
    if not m:
        m = SOURCE_FALLBACK_RE.search(html)
    if m:
        out["te_source_url"] = m.group(1).strip()
        out["te_source_name"] = m.group(2).strip()
    else:
        # plain text fallback
        m2 = SOURCE_PLAIN_RE.search(html)
        if m2:
            out["te_source_name"] = m2.group(1).strip()
            out["te_source_url"] = None
    # description meta
    md = META_DESC_RE.search(html)
    if md:
        out["te_meta_desc"] = md.group(1).strip()
    # try to extract value from meta desc, e.g. "GDP from Slovenia ... 18 271.40 EUR Million in Mar 2026"
    if "te_meta_desc" in out:
        text = out["te_meta_desc"]
        # find first number with optional decimal/comma
        vm = re.search(r"(-?\d{1,3}(?:[ ,]\d{3})*(?:\.\d+)?|\-?\d+\.?\d*)\s*([A-Za-z%/]*)", text)
        if vm:
            raw = vm.group(1).replace(" ", "").replace(",", "")
            try:
                out["te_value_meta"] = float(raw)
            except Exception:
                pass
    # h1 title
    mh = DESC_H1_RE.search(html)
    if mh:
        out["te_h1"] = mh.group(1).strip()
    # try the headline value (often appears in JS-rendered widgets, but raw HTML still has it)
    # pattern: <div class="te-indicator-headline">115.10</div> sometimes
    iv = re.search(
        r'<div[^>]*class=["\'][^"\']*indicator-data[^"\']*["\'][^>]*>\s*([+\-0-9.,]+)',
        html,
    )
    if iv:
        out["te_value_indicator_data"] = iv.group(1)
    return out


def main():
    parsed = {}
    for p in sorted(SRCDIR.glob("*.html")):
        slug = p.stem
        html = p.read_text(encoding="utf-8", errors="ignore")
        parsed[slug] = parse_one(slug, html)
    Path("docs/_audit_si_te_parsed.json").write_text(
        json.dumps(parsed, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    # Print summary
    print(f"Parsed {len(parsed)} slugs.")
    no_src = [s for s, v in parsed.items() if "te_source_name" not in v]
    print(f"No source extracted: {len(no_src)}")
    for s in no_src[:10]:
        print(f"  - {s}")
    # Source distribution
    sources = {}
    for v in parsed.values():
        sn = v.get("te_source_name", "<none>")
        sources[sn] = sources.get(sn, 0) + 1
    print("Source distribution:")
    for k, n in sorted(sources.items(), key=lambda x: -x[1]):
        print(f"  {n:3d}  {k}")


if __name__ == "__main__":
    main()
