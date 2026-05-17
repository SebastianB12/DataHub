"""Parse TE HTML for batch3: source label + headline value + period."""
import re, json, os, glob

SOURCE_RE = re.compile(r"source:\s*<a class='source-name'[^>]*href\s*=\s*'([^']*)'[^>]*>([^<]+)</a>", re.I)
META_DESC = re.compile(r'<meta\s+id="metaDesc"\s+name="description"\s+content="([^"]+)"', re.I)

# Verbs preceding value
V = r"(?:reached|fell to|rose to|increased to|decreased to|stood at|was at|remained unchanged at|remains unchanged at|stands at|was|is)"
# Verb without trailing "to" – e.g., "increased by 115 thousand"
V2 = r"(?:increased by|decreased by|fell by|rose by)"
# Number
N = r"([\-+]?[0-9][0-9,\.]*)"
# Unit (greedy stopping before "in"/"to"/"from"/"during"/"on"/"."/period words)
U = r"([A-Za-z\%\$\.\s/]{0,40}?)"
# Period
P = r"(?:in\s+|during\s+|for\s+|on\s+)(the\s+(?:first|second|third|fourth)\s+quarter\s+of\s+\d{4}|Q[1-4]\s*\d{4}|[A-Z][a-z]+(?:\s+of)?\s*\d{4}|[A-Z][a-z]+|\d{4})"

PATTERNS = [
    re.compile(rf"{V}\s+{N}\s*{U}\s*{P}", re.I),
    re.compile(rf"{V2}\s+{N}\s*{U}\s*{P}", re.I),
    re.compile(rf"trade (?:deficit|surplus) of\s+{N}\s*{U}\s*{P}", re.I),
    re.compile(rf"{V}\s+{N}\s*{U}\.\s*$", re.I),  # no period word, just at end - "stands at 0 percent."
    re.compile(rf"{V}\s+{N}\s*{U}\s+from", re.I),  # trailing "from X in Y"
]

results = {}
files = sorted(glob.glob("docs/_audit_te_html/batch3/*.html"))
for fp in files:
    slug = os.path.basename(fp).replace(".html", "")
    with open(fp, encoding="utf-8") as f:
        h = f.read()
    src_label = None
    src_url = None
    m = SOURCE_RE.search(h)
    if m:
        src_url, src_label = m.group(1), m.group(2).strip()
    md = META_DESC.search(h)
    desc = (md.group(1) if md else "").strip()
    headline = None
    period = None
    unit = None
    for pat in PATTERNS:
        vp = pat.search(desc)
        if vp:
            gs = vp.groups()
            if len(gs) == 3:
                headline, unit, period = gs[0], gs[1].strip(), gs[2].strip()
            elif len(gs) == 2:
                headline, unit = gs[0], gs[1].strip()
            else:
                headline = gs[0]
            headline = headline.replace(",", "")
            break
    results[slug] = {
        "source_label": src_label,
        "source_url": src_url,
        "headline": headline,
        "unit": unit,
        "period": period,
        "desc": desc[:400],
    }

with open("docs/_audit_te_html/batch3/_parsed.json", "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2)
for s, r in results.items():
    print(f"{s} | {r['source_label']} | {r['headline']} {r['unit']} | {r['period']}")
