"""Final parser: combines primary + alt TE pages for LT slugs.

Outputs unified dict: slug -> {source_name, source_url, te_value, te_unit, te_period, te_url_used, description, status}
status: 'real' | 'stub' (no TE page at all) | 'alt' (used alternative TE slug)
"""
import json, os, re

HTML_DIR = r"C:\Users\sb\source\tradingEconomics\docs\_audit_te_html\LT"
OUT_JSON = r"C:\Users\sb\source\tradingEconomics\docs\_audit_lt_te_final.json"

SOURCE_RE = re.compile(
    r"source:\s*<a class='source-name'[^>]*href\s*=\s*'([^']*)'[^>]*>([^<]+)</a>",
    re.I,
)
SOURCE_PRESENT_RE = re.compile(
    r"<span class='source-present'>source:\s*([^<]+)</span>",
    re.I,
)
META_DESC_RE = re.compile(r'<meta\s+name="description"\s+content="([^"]+)"', re.I)
H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
DESC_RE = re.compile(r'<h2 id="description"[^>]*>(.*?)</h2>', re.S)

# Last-value patterns:
#   <h2 class="last-value-stats">X.X percent in <Month YYYY>. <span...>source: ...</span></h2>
LASTVAL_RE = re.compile(
    r'<h2[^>]*>([^<]{3,400}?)<span\s+class=[\'"]source[-_]present',
    re.I,
)


def parse_html(body: str) -> dict:
    out = {}
    sm = SOURCE_RE.search(body)
    if sm:
        out["source_url"] = sm.group(1)
        out["source_name"] = sm.group(2).strip()
    else:
        sp = SOURCE_PRESENT_RE.search(body)
        if sp:
            out["source_name"] = sp.group(1).strip()
    md = META_DESC_RE.search(body)
    if md:
        out["meta_desc"] = md.group(1).strip()[:600]
    dm = DESC_RE.search(body)
    if dm:
        out["description"] = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", dm.group(1))).strip()[:600]
    h1 = H1_RE.search(body)
    if h1:
        out["h1"] = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h1.group(1))).strip()
    lv = LASTVAL_RE.search(body)
    if lv:
        out["last_value_text"] = lv.group(1).strip()
    return out


slugs = json.load(open(r"C:\Users\sb\source\tradingEconomics\docs\_audit_all_remaining_slugs.json"))["LT"]

final = {}
for slug in slugs:
    primary_path = os.path.join(HTML_DIR, f"{slug}.html")
    primary_body = ""
    if os.path.exists(primary_path):
        primary_body = open(primary_path, "rb").read().decode("utf-8", errors="ignore")

    primary = parse_html(primary_body)
    if "source_name" in primary:
        primary["status"] = "real"
        primary["te_url_used"] = f"https://tradingeconomics.com/lithuania/{slug}"
        final[slug] = primary
        continue

    # Try alternatives
    alts = sorted([f for f in os.listdir(HTML_DIR) if f.startswith(f"{slug}__alt__")])
    best = None
    for alt_file in alts:
        alt_body = open(os.path.join(HTML_DIR, alt_file), "rb").read().decode("utf-8", errors="ignore")
        alt = parse_html(alt_body)
        if "source_name" in alt:
            alt_slug = alt_file.replace(f"{slug}__alt__", "").replace(".html", "")
            alt["status"] = "alt"
            alt["te_url_used"] = f"https://tradingeconomics.com/lithuania/{alt_slug}"
            alt["alt_slug"] = alt_slug
            best = alt
            break
    if best:
        final[slug] = best
    else:
        # No TE page at all
        primary["status"] = "no_te_page"
        primary["te_url_used"] = f"https://tradingeconomics.com/lithuania/{slug}"
        final[slug] = primary

with open(OUT_JSON, "w") as f:
    json.dump(final, f, indent=2, ensure_ascii=False)
print(f"Wrote {OUT_JSON}")

status_counts = {}
src_counts = {}
for s, e in final.items():
    st = e.get("status", "unknown")
    status_counts[st] = status_counts.get(st, 0) + 1
    src = e.get("source_name", "NONE")
    src_counts[src] = src_counts.get(src, 0) + 1

print("\nStatus:")
for st, n in status_counts.items():
    print(f"  {n:3d}  {st}")
print("\nSources detected:")
for src, n in sorted(src_counts.items(), key=lambda x: -x[1]):
    print(f"  {n:3d}  {src}")

print("\nNo TE page:")
for s, e in final.items():
    if e.get("status") == "no_te_page":
        print(f"  {s}")
