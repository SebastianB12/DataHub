"""Parse all FR batch1 HTML for source label, value, period."""
import re, os, json

SOURCE_RE = re.compile(r"source:\s*<a class='source-name'[^>]*href\s*=\s*'([^']*)'[^>]*>([^<]+)</a>", re.I)
DESC_RE = re.compile(r'<h2 id="description"[^>]*>(.*?)</h2>', re.S)
# value formatted in main quote box: e.g. <span itemprop="ratingValue">76.95</span>
RATING_RE = re.compile(r'itemprop="ratingValue"[^>]*>([\-0-9\.,]+)<')
# latest value table near top - look for first big value in description, e.g. "rose to 102.26 in"
DESC_VAL_RE = re.compile(
    r"(?:to|at|of|reached)\s+(-?\d[\d,\.]*)\s*(?:%|percent|billion|million|points|Index|EUR|index)?",
    re.I,
)
PERIOD_RE = re.compile(
    r"in\s+(January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Q[1-4]|the\s+(?:first|second|third|fourth)\s+quarter)\s*(?:of\s+)?(\d{4})?",
    re.I,
)

DIR = "docs/_audit_te_html/FR"
results = {}
for fn in sorted(os.listdir(DIR)):
    if not fn.endswith(".html"): continue
    slug = fn[:-5]
    with open(f"{DIR}/{fn}", encoding="utf-8") as f:
        html = f.read()
    m = SOURCE_RE.search(html)
    src_url, src_label = (m.group(1), m.group(2).strip()) if m else (None, None)
    rating = RATING_RE.search(html)
    rating_val = rating.group(1) if rating else None
    desc = DESC_RE.search(html)
    desc_txt = re.sub(r"<[^>]+>", " ", desc.group(1)) if desc else ""
    desc_txt = re.sub(r"\s+", " ", desc_txt).strip()
    val_m = DESC_VAL_RE.search(desc_txt)
    val = val_m.group(1) if val_m else None
    per_m = PERIOD_RE.search(desc_txt)
    period = (per_m.group(1), per_m.group(2)) if per_m else None
    results[slug] = {
        "src_url": src_url,
        "src_label": src_label,
        "rating_val": rating_val,
        "desc_val": val,
        "period": period,
        "desc": desc_txt[:300],
    }

print(json.dumps(results, indent=2, ensure_ascii=False))
