"""Parse TE HTML for LT slugs: source, value, last update, description."""
import json, os, re

HTML_DIR = r"C:\Users\sb\source\tradingEconomics\docs\_audit_te_html\LT"
OUT_JSON = r"C:\Users\sb\source\tradingEconomics\docs\_audit_lt_te_parsed.json"

# Two source patterns:
SOURCE_RE = re.compile(
    r"source:\s*<a class='source-name'[^>]*href\s*=\s*'([^']*)'[^>]*>([^<]+)</a>",
    re.I,
)
# Alternative: <span class='source-present'>source: EUROSTAT</span>
SOURCE_PRESENT_RE = re.compile(
    r"<span class='source-present'>source:\s*([^<]+)</span>",
    re.I,
)
# Hero value snippet
HERO_VALUE_RE = re.compile(
    r'<div class="data card-data"[^>]*>\s*([0-9.\-+,\sA-Za-z%]+?)\s*</div>',
    re.S,
)

# Look for "<value> <unit>" near "source-present" tag in <h2 class="last-value-stats">
H2_LASTVALUE_RE = re.compile(
    r'<h2[^>]*>(.*?source[-:][^<]*</[^>]+>)\s*</h2>',
    re.S | re.I,
)

META_DESC_RE = re.compile(r'<meta\s+name="description"\s+content="([^"]+)"', re.I)
H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
DESC_RE = re.compile(r'<h2 id="description"[^>]*>(.*?)</h2>', re.S)

# Latest table value
VALUE_RE = re.compile(r"<td[^>]*data-symbol[^>]*>\s*([0-9.\-,]+)\s*</td>", re.S)

slugs = json.load(open(r"C:\Users\sb\source\tradingEconomics\docs\_audit_all_remaining_slugs.json"))["LT"]

# Alt fetched pages map: actual TE slug used
ALT_HTML_MAP = {}
# (we'll fold them in via separate fetch later)

parsed = {}
for slug in slugs:
    path = os.path.join(HTML_DIR, f"{slug}.html")
    if not os.path.exists(path):
        parsed[slug] = {"error": "missing_html"}
        continue
    body = open(path, "rb").read().decode("utf-8", errors="ignore")
    entry = {"size": len(body)}
    # source via primary pattern
    sm = SOURCE_RE.search(body)
    if sm:
        entry["source_url"] = sm.group(1)
        entry["source_name"] = sm.group(2).strip()
    else:
        sp = SOURCE_PRESENT_RE.search(body)
        if sp:
            entry["source_name"] = sp.group(1).strip()
    # description
    md = META_DESC_RE.search(body)
    if md:
        entry["meta_desc"] = md.group(1).strip()[:600]
    dm = DESC_RE.search(body)
    if dm:
        entry["description"] = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", dm.group(1))).strip()[:600]
    h1 = H1_RE.search(body)
    if h1:
        entry["h1"] = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h1.group(1))).strip()
    vm = VALUE_RE.search(body)
    if vm:
        entry["table_value"] = vm.group(1).strip()

    # Try to extract last value text from "h2 class=last-value-stats" (often shows "X.X percent in <month>")
    lv = re.search(r'<h2[^>]*>([^<]*?(percent|points|EUR|USD|index|persons|Thousand|Million)[^<]*?)<span', body, re.I)
    if lv:
        entry["last_value_text"] = lv.group(1).strip()
    else:
        lv2 = re.search(r'<h2[^>]*>([^<]{5,300}?)<span', body)
        if lv2:
            entry["last_value_text"] = lv2.group(1).strip()
    # try to find hero h1 + last-value
    parsed[slug] = entry

with open(OUT_JSON, "w") as f:
    json.dump(parsed, f, indent=2, ensure_ascii=False)
print(f"Parsed {len(parsed)} slugs.")

src_counts = {}
for s, e in parsed.items():
    src = e.get("source_name", "UNKNOWN")
    src_counts[src] = src_counts.get(src, 0) + 1
print("\nSources detected:")
for src, n in sorted(src_counts.items(), key=lambda x: -x[1]):
    print(f"  {n:3d}  {src}")
