# -*- coding: utf-8 -*-
"""Parse fresh TE HTML for RO slugs and emit a JSON map slug -> {source, value, desc}."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "docs" / "_audit_te_html" / "RO"
OUT = ROOT / "docs" / "_audit_ro_te_parsed.json"

SOURCE_LINK_RE = re.compile(
    r"source:\s*<a class='source-name'[^>]*href\s*=\s*'([^']*)'[^>]*>([^<]+)</a>", re.I)
SOURCE_PLAIN_RE = re.compile(
    r"source-present'[^>]*>source:\s*([^<]+)</span>", re.I)
RATING_RE = re.compile(r"<span[^>]*class=['\"]rating-name['\"][^>]*>([^<]+)</span>", re.I)
DESC_RE = re.compile(r'<h2 id="description"[^>]*>(.*?)</h2>', re.S)
H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)

# Regex to extract "ROSE/FELL/INCREASED/DECREASED to X.Y in <month> <year>"
VAL_RE = re.compile(
    r"\b(?:rose|fell|increased|decreased|advanced|jumped|grew|dropped|surged|edged|climbed|reached|stood|was|remained|amounted|reverted|narrowed|widened|expanded|contracted)\b[^.]{0,200}?to\s+(-?[\d,]+\.?\d*)\s*(%|percent|RON|EUR|USD|points)?",
    re.I,
)


def strip_tags(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s or "").strip()


def parse_one(slug: str) -> dict:
    p = SRC_DIR / f"{slug}.html"
    if not p.exists():
        return {"missing": True}
    h = p.read_text(encoding="utf-8", errors="ignore")
    out = {"size": len(h)}
    if len(h) < 260000:
        # Generic homepage; no slug-specific data
        out["page_not_found"] = True

    m = SOURCE_LINK_RE.search(h)
    if m:
        out["source_url"] = m.group(1)
        out["source_label"] = m.group(2).strip()
    else:
        m2 = SOURCE_PLAIN_RE.search(h)
        if m2:
            out["source_label"] = m2.group(1).strip()
            out["source_url"] = None

    m = DESC_RE.search(h)
    if m:
        desc = strip_tags(m.group(1))
        # collapse whitespace
        desc = re.sub(r"\s+", " ", desc).strip()
        out["description"] = desc[:1200]
        v = VAL_RE.search(desc)
        if v:
            num = v.group(1).replace(",", "")
            try:
                out["value_first"] = float(num)
                out["value_unit"] = v.group(2)
            except ValueError:
                pass

    m = H1_RE.search(h)
    if m:
        out["h1"] = strip_tags(m.group(1))[:200]

    return out


def main():
    slugs = json.load(open(ROOT / "docs" / "_audit_all_remaining_slugs.json"))["RO"]
    result = {}
    for slug in slugs:
        result[slug] = parse_one(slug)
    OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {OUT}")
    # quick summary
    nosrc = [s for s, v in result.items() if "source_label" not in v]
    print("no source_label:", len(nosrc), "->", nosrc)


if __name__ == "__main__":
    main()
