"""Parse EE TE HTML for source attribution + latest value."""
import re, json, pathlib, sys

SOURCE_RE = re.compile(r"source:\s*<a class='source-name'[^>]*href\s*=\s*'([^']*)'[^>]*>([^<]+)</a>", re.I)
DESC_RE = re.compile(r'<h2 id="description"[^>]*>(.*?)</h2>', re.S)
# fallback: description suffix "source: Foo" (no anchor)
SOURCE_TEXT_RE = re.compile(r'source:\s*([A-Z][A-Za-z ,\.\-&]+?)(?:\s*</|\s*$|\s*<br)', re.I)
TITLE_RE = re.compile(r'<title>(.*?)</title>', re.I | re.S)
# value cards
LAST_RE = re.compile(r'<div class="te-card-text">([\d\.\,\-\+]+)</div>', re.I)
# typical TE: <span id="ctl00_..._actual">VALUE</span>
ACTUAL_RE = re.compile(r'id="[^"]*_actual"[^>]*>([^<]+)<', re.I)
# Big "data-element" hero value
HERO_RE = re.compile(r'<div[^>]*class="[^"]*te-card-text[^"]*"[^>]*>\s*([\d\.\,\-\+]+)\s*</div>', re.I)
# Header preview "Estonia X — Y was reported at Z in Mon Year"
TEXTVAL_RE = re.compile(
    r'(?:was|stood|reached|recorded|posted)\s+(?:at|to)?\s*([+-]?[\d\.,]+)\s*(?:percent|EUR|USD|points|index|million|billion|thousand|%)?',
    re.I,
)
# Sub-source in description like "Source: Statistics Estonia"
SUBSRC_RE = re.compile(r'Source:\s*([^\.<\n]+?)\.', re.I)

def parse(slug: str, html: str) -> dict:
    out = {"slug": slug, "raw_size": len(html)}
    if len(html) < 50_000:
        out["status"] = "too_small"
        return out

    m = SOURCE_RE.search(html)
    if m:
        out["te_source_url"] = m.group(1).strip()
        out["te_source_name"] = m.group(2).strip()
    m = DESC_RE.search(html)
    if m:
        desc_html = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        out["te_desc"] = desc_html[:600]
        # Look for trailing "source: X" in description text
        if not out.get("te_source_name"):
            ms = re.search(r'source:\s*([A-Z][A-Za-z ,\.\-&/]+?)(?:\.|$)', desc_html)
            if ms:
                out["te_source_name"] = ms.group(1).strip()
    m = SUBSRC_RE.search(html)
    if m and not out.get("te_source_name"):
        out["te_source_name"] = m.group(1).strip()
    m = TITLE_RE.search(html)
    if m:
        title = re.sub(r"\s+", " ", m.group(1)).strip()
        out["te_title"] = title[:200]
        # parse value from title: "Estonia Inflation Rate - 3.4 percent (Apr/26) Data"
        mt = re.search(r'-\s*([+-]?[\d,\.]+)\s*(percent|%|EUR|USD|points|index|million|billion|thousand|years|cars|bbl)?', title, re.I)
        if mt:
            out["te_val_title"] = mt.group(1).replace(",", "")
            out["te_unit_title"] = mt.group(2)

    m = ACTUAL_RE.search(html)
    if m:
        out["te_val_actual"] = m.group(1).strip()
    m = LAST_RE.search(html)
    if m:
        out["te_val_card"] = m.group(1).strip()

    # Find the "is forecast" / "was reported at" snippet for current value cross-check
    m = TEXTVAL_RE.search(html)
    if m:
        out["te_val_text"] = m.group(1).replace(",", "")

    # Meta description (most reliable)
    m = re.search(r'<meta\s+id="metaDesc"\s+name="description"\s+content="([^"]+)"', html, re.I)
    if m:
        meta = m.group(1)
        out["te_meta_desc"] = meta[:500]
        # Try multiple patterns
        val = None
        # 1) "decreased/increased/expanded X.YY percent" (yoy/mom)
        mv = re.search(r'(?:decreased|increased|expanded|contracted|grew|rose|fell|advanced|slowed|accelerated)\s+(?:by\s+)?(-?[\d,\.]+)\s*(percent|%|EUR|USD|points|index|million|billion|thousand)?', meta, re.I)
        if mv:
            val = mv.group(1)
            out["te_unit_meta"] = mv.group(2)
        # 2) "X to Y.YY percent" / "at Y.YY percent" / "was Y.YY"
        if not val:
            mv = re.search(r'(?:to|at|reached|stood at|was|recorded(?:\s+a\s+\w+\s+of)?|of)\s+(-?[\d,\.]+)\s*(percent|EUR|USD|points|index|million|billion|thousand|years|%)?', meta, re.I)
            if mv:
                val = mv.group(1)
                out["te_unit_meta"] = mv.group(2)
        # 3) "scored X points"
        if not val:
            mv = re.search(r'scored\s+(-?[\d,\.]+)\s*(points|index|out of)?', meta, re.I)
            if mv:
                val = mv.group(1)
                out["te_unit_meta"] = mv.group(2) or "points"
        # 4) "was worth X billion" or "worth X.XX billion"
        if not val:
            mv = re.search(r'worth\s+(-?[\d,\.]+)\s*(billion|million|trillion)?\s*(?:US dollars|EUR|euros)?', meta, re.I)
            if mv:
                val = mv.group(1)
                out["te_unit_meta"] = mv.group(2)
        # 5) "X.YY EUR Million" / "X.YY USD Million"
        if not val:
            mv = re.search(r'(-?[\d,\.]+)\s+(EUR|USD)\s+(Million|Billion|Thousand)', meta, re.I)
            if mv:
                val = mv.group(1)
                out["te_unit_meta"] = f"{mv.group(2)} {mv.group(3)}"
        # 6) Generic: first number in meta
        if not val:
            mv = re.search(r'(-?\d[\d,\.]*)', meta)
            if mv:
                val = mv.group(1)
        if val:
            out["te_val_meta"] = val.replace(",", "")
        # Period like "in April of 2026" or "in 2025"
        mp = re.search(r'in\s+(?:the\s+\w+\s+quarter\s+of\s+\d{4}|[A-Z][a-z]+\s+(?:of\s+)?\d{4}|\d{4})', meta)
        if mp:
            out["te_period_meta"] = mp.group(0)

    return out


def main():
    with open("docs/_audit_all_remaining_slugs.json", encoding="utf-8") as f:
        slugs = json.load(f)["EE"]
    results = {}
    for s in slugs:
        p = pathlib.Path(f"docs/_audit_te_html/EE/{s}.html")
        if not p.exists():
            results[s] = {"status": "missing"}
            continue
        html = p.read_text(encoding="utf-8", errors="ignore")
        results[s] = parse(s, html)
    pathlib.Path("docs/_audit_ee_te.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Parsed {len(results)} slugs -> docs/_audit_ee_te.json")
    # short summary
    for s, r in results.items():
        srcname = r.get("te_source_name", "?")
        val = r.get("te_val_meta") or r.get("te_val_title") or r.get("te_val_actual") or r.get("te_val_card") or r.get("te_val_text") or "?"
        print(f"  {s:35s} src='{srcname[:30]:30s}' val={val}")


if __name__ == "__main__":
    main()
