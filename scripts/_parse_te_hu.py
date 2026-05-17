"""Parse TE HTML for source attribution + current value for HU slugs."""
import json
import os
import re

IN_DIR = "docs/_audit_te_html/hu_reaudit"
OUT = "docs/_audit_hu_te_parsed.json"

SOURCE_RE = re.compile(
    r"source:\s*<a class='source-name'[^>]*href\s*=\s*'([^']*)'[^>]*>([^<]+)</a>",
    re.I,
)
DESC_RE = re.compile(r'<h2 id="description"[^>]*>(.*?)</h2>', re.S)
# Current latest-value tile (varies). Look for "the most recent ... was" in description.
LAST_VAL_RE = re.compile(
    r"(?:was|stood at|reached|amounted to|recorded|increased to|decreased to|rose to|fell to|came in at|stood)\s+"
    r"(-?[0-9][0-9,\.]*)\s*(?:percent|%|points|EUR|HUF|USD|million|billion|thousand|persons|index|YoY|MoM|years|per\s*1000)?",
    re.I,
)
# Title-line value
TITLE_VAL_RE = re.compile(
    r"<title>[^<]*?(?:was|stood at|recorded)\s+(-?[0-9][0-9,\.]*)\s*",
    re.I,
)
# Meta description fallback
META_RE = re.compile(
    r'<meta[^>]+name="description"[^>]+content="([^"]+)"',
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
    src_match = SOURCE_RE.search(html)
    desc_match = DESC_RE.search(html)
    meta_match = META_RE.search(html)
    desc_text = desc_match.group(1) if desc_match else ""
    meta_text = meta_match.group(1) if meta_match else ""
    # Look for the latest value in description
    val_match = LAST_VAL_RE.search(desc_text) or LAST_VAL_RE.search(meta_text)
    results[slug] = {
        "source_url": src_match.group(1) if src_match else None,
        "source_name": src_match.group(2).strip() if src_match else None,
        "desc_h2": desc_text[:400] if desc_text else None,
        "meta_desc": meta_text[:400] if meta_text else None,
        "latest_value_guess": val_match.group(1) if val_match else None,
    }

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print(f"Wrote {OUT} with {len(results)} entries")
# print summary table
for slug in slugs:
    r = results[slug]
    sn = (r.get("source_name") or "?")[:40]
    lv = r.get("latest_value_guess") or "?"
    print(f"{slug:<35} src={sn:<40} val={lv}")
