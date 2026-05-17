"""Parse TE HTML for HU — robust parser handling source-name + source-present."""
import json
import os
import re

IN_DIR = "docs/_audit_te_html/hu_reaudit"
OUT = "docs/_audit_hu_te_parsed.json"

# Pattern 1: <a class='source-name' href='URL'>NAME</a>
SOURCE_NAME_RE = re.compile(
    r"source:\s*<a class='source-name'[^>]*href\s*=\s*'([^']*)'[^>]*>([^<]+)</a>",
    re.I,
)
# Pattern 2: <span class='source-present'>source: NAME</span>
SOURCE_PRESENT_RE = re.compile(
    r"<span class='source-present'>source:\s*(.+?)</span>",
    re.S,
)
DESC_RE = re.compile(r'<h2 id="description"[^>]*>(.*?)</h2>', re.S)
META_RE = re.compile(
    r'<meta[^>]+name="description"[^>]+content="([^"]+)"',
    re.I,
)
H1_RE = re.compile(r"<h1[^>]*>([^<]+)</h1>")

# Match "X stands at Y", "was Y", "amounted to Y", "reached Y", "increased to Y", "decreased to Y"
VAL_RE = re.compile(
    r"(?:stands at|stood at|was|amounted to|reached|increased to|decreased to|"
    r"rose to|fell to|came in at|posted|recorded|registered|hit|equalled|"
    r"declined to|advanced to|edged up to|edged down to|expanded\s+(?:by\s+)?)"
    r"\s+(-?[0-9][0-9,]*\.?[0-9]*)",
    re.I,
)
# "X of Y percent"
VAL_OF_RE = re.compile(
    r"(?:rate|index|deficit|surplus|growth)\s+(?:in [A-Z]\w+\s+)?of\s+(-?[0-9][0-9,]*\.?[0-9]*)\s*(?:percent|%)?",
    re.I,
)

with open("docs/_audit_all_remaining_slugs.json", "r", encoding="utf-8") as f:
    slugs = json.load(f)["HU"]

results = {}
for slug in slugs:
    path = f"{IN_DIR}/{slug}.html"
    if not os.path.exists(path):
        results[slug] = {"error": "no_html"}
        continue
    with open(path, "rb") as f:
        html = f.read().decode("utf-8", errors="ignore")
    fallback = "TRADING ECONOMICS | 20 Million" in html[:1500]
    if fallback:
        results[slug] = {"te_status": "no_page", "source_name": None, "value": None}
        continue
    sn_match = SOURCE_NAME_RE.search(html)
    sp_match = SOURCE_PRESENT_RE.search(html)
    h1 = H1_RE.search(html)
    desc = DESC_RE.search(html)
    meta = META_RE.search(html)
    desc_text = desc.group(1) if desc else ""
    meta_text = meta.group(1) if meta else ""
    # Strip HTML in desc for cleaner regex
    desc_plain = re.sub(r"<[^>]+>", " ", desc_text)
    val_match = VAL_RE.search(desc_plain) or VAL_RE.search(meta_text) or VAL_OF_RE.search(desc_plain) or VAL_OF_RE.search(meta_text)
    source_name = None
    if sn_match:
        source_name = sn_match.group(2).strip()
    elif sp_match:
        # may contain <a> or plain text
        s = re.sub(r"<[^>]+>", "", sp_match.group(1)).strip()
        source_name = s
    results[slug] = {
        "te_status": "ok",
        "h1": h1.group(1).strip() if h1 else None,
        "source_name": source_name,
        "value": val_match.group(1).replace(",", "") if val_match else None,
        "desc": desc_plain[:400] if desc_plain else None,
        "meta": meta_text[:400] if meta_text else None,
    }

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)

print(f"Wrote {OUT}\n")
for slug in slugs:
    r = results[slug]
    if r.get("te_status") == "no_page":
        print(f"{slug:<35} TE_NO_PAGE")
    elif r.get("error"):
        print(f"{slug:<35} ERROR {r['error']}")
    else:
        sn = (r.get("source_name") or "?")[:40]
        v = r.get("value") or "?"
        print(f"{slug:<35} src={sn:<40} val={v}")
