"""Parse BG TE HTML files: source, latest value, latest period, frequency, unit."""
import json, os, re

slugs = json.load(open("docs/_audit_all_remaining_slugs.json"))["BG"]
src_dir = "docs/_audit_te_html/bg"

SOURCE_RE = re.compile(
    r"source:\s*<a class='source-name'[^>]*href\s*=\s*'([^']*)'[^>]*>([^<]+)</a>",
    re.I,
)
# Hero card on TE country indicator page often contains <span class='te-value'> ... </span>
HERO_VAL_RE = re.compile(r'<span class="value">([\d.,\-]+)</span>', re.I)
LAST_RE = re.compile(r'<span id="ctl00_ContentPlaceHolder1_ctl\d+_LastValue"[^>]*>([^<]+)</span>', re.I)
# Generic 1st table row
TABLE_ROW_RE = re.compile(r'<tr[^>]*>\s*<td[^>]*>\s*<b>([^<]+)</b>.*?<td[^>]*>([\d.,\-]+)</td>\s*<td[^>]*>([\d.,\-]+)</td>\s*<td[^>]*>([^<]+)</td>\s*<td[^>]*>([^<]+)</td>', re.S)

# Description block (good for sanity)
DESC_RE = re.compile(r'<h2 id="description"[^>]*>(.*?)</h2>', re.S)
# meta-description usually has the headline value
META_DESC_RE = re.compile(r'<meta name="description" content="([^"]+)"', re.I)

# Heading right under hero with "Bulgaria CPI" and large number
H1_RE = re.compile(r'<h1[^>]*>([^<]+)</h1>', re.I)


def parse(slug, html):
    m_src = SOURCE_RE.search(html)
    source_url, source_name = (m_src.group(1), m_src.group(2).strip()) if m_src else (None, None)
    m_meta = META_DESC_RE.search(html)
    meta_desc = m_meta.group(1) if m_meta else ""
    # last value: look for "increased/decreased to X in MMM YYYY"
    return {
        "slug": slug,
        "te_source_name": source_name,
        "te_source_url": source_url,
        "meta_desc": meta_desc[:400],
    }


def main():
    out = {}
    for slug in slugs:
        p = os.path.join(src_dir, f"{slug}.html")
        if not os.path.exists(p):
            out[slug] = {"slug": slug, "error": "missing"}
            continue
        html = open(p, "rb").read().decode("utf-8", errors="ignore")
        info = parse(slug, html)
        out[slug] = info
    with open("docs/_audit_bg_te_parsed.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    # summary
    for slug in slugs:
        info = out[slug]
        print(f"{slug:40s} src={(info.get('te_source_name') or '?')[:30]:30s}  desc={(info.get('meta_desc') or '')[:80]}")


if __name__ == "__main__":
    main()
