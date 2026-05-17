"""Parse TE HTML for MT, extract source label + latest value + description."""
import os, re, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

SOURCE_RE = re.compile(
    r"source:\s*<a class='source-name'[^>]*href\s*=\s*'([^']*)'[^>]*>([^<]+)</a>",
    re.I
)
# Fallback - sometimes <a class="source-name"> with double quotes
SOURCE_RE2 = re.compile(
    r'source:\s*<a class="source-name"[^>]*href\s*=\s*"([^"]*)"[^>]*>([^<]+)</a>',
    re.I
)
DESC_RE = re.compile(r'<h2 id="description"[^>]*>(.*?)</h2>', re.S)

# Various forms TE uses for the latest value display - top KPI tile
# e.g. <div class="te-page-stats-value">5.20</div>
VALUE_RE = re.compile(r'<div class="te-page-stats-value">\s*([^<]+?)\s*</div>')
# fallback: pageBoxes-title or first <td class="te-overview-stats-bold"> in the calendar table
KPI_RE = re.compile(
    r'<h4 class="d-flex align-items-center justify-content-between gap-3 mb-0 fw-bold[^"]*"[^>]*>([^<]+)</h4>',
    re.I
)

# Last/Previous overview row table common pattern - find leading number
META_VALUE_RE = re.compile(
    r'<meta itemprop="value"\s+content="([^"]+)"',
    re.I,
)

# title-based: e.g. "Malta Inflation Rate 0.50%"
TITLE_VAL_RE = re.compile(
    r'<title>\s*Malta\s+[^|<\d-]+\s*([-+]?\d[\d,\.]*)\s*[A-Z%a-z]*\s*[-|]',
    re.S,
)

# h1 sub-text "Last: 0.50 % | Previous: ..."
H1_LAST = re.compile(r'Last\s*[:=]\s*([-+]?\d[\d,\.]*)', re.I)


def parse(html):
    out = {}
    m = SOURCE_RE.search(html) or SOURCE_RE2.search(html)
    if m:
        out["source_url"] = m.group(1)
        out["source_label"] = m.group(2).strip()
    desc_m = DESC_RE.search(html)
    if desc_m:
        out["description"] = re.sub(r"\s+", " ", desc_m.group(1)).strip()[:500]
    val_m = VALUE_RE.search(html)
    if val_m:
        out["te_value_raw"] = val_m.group(1).strip()
    else:
        kpi_m = KPI_RE.search(html)
        if kpi_m:
            out["te_value_raw"] = kpi_m.group(1).strip()
        else:
            meta_m = META_VALUE_RE.search(html)
            if meta_m:
                out["te_value_raw"] = meta_m.group(1).strip()
    # title fallback
    if "te_value_raw" not in out:
        tm = TITLE_VAL_RE.search(html)
        if tm:
            out["te_value_raw"] = tm.group(1).strip()
    return out


def parse_num(s):
    if not s:
        return None
    s = s.strip().replace(",", "").replace("%", "").replace("EUR", "").replace("USD", "").strip()
    # remove any non numeric suffix
    m = re.match(r"^([-+]?\d+(?:\.\d+)?)", s)
    if m:
        try:
            return float(m.group(1))
        except Exception:
            return None
    return None


def parse_all():
    out = {}
    src = "docs/_audit_te_html/MT"
    for f in sorted(os.listdir(src)):
        if not f.endswith(".html"):
            continue
        slug = f[:-5]
        html = open(os.path.join(src, f), encoding="utf-8", errors="ignore").read()
        info = parse(html)
        out[slug] = info
    return out


if __name__ == "__main__":
    data = parse_all()
    json.dump(data, open("docs/_audit_mt_te_parsed.json", "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)
    print(f"Parsed {len(data)} slugs")
    miss_src = [k for k, v in data.items() if "source_label" not in v]
    miss_val = [k for k, v in data.items() if "te_value_raw" not in v]
    print(f"Missing source: {len(miss_src)}")
    if miss_src:
        print("  ", miss_src[:20])
    print(f"Missing value: {len(miss_val)}")
    if miss_val:
        print("  ", miss_val[:20])
    # show samples
    print("\nSamples:")
    for s in list(data)[:5]:
        print(s, "->", data[s])
