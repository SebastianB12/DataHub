"""Parse all LV TE HTMLs into structured JSON: source, description, latest value."""
import re, json, pathlib

SOURCE_RE = re.compile(r"source:\s*<a class='source-name'[^>]*href\s*=\s*'([^']*)'[^>]*>([^<]+)</a>", re.I)
SOURCE_TEXT_RE = re.compile(r"class='source-present'\s*>source:\s*([^<]+)<", re.I)
DESC_RE = re.compile(r'<h2 id="description"[^>]*>(.*?)</h2>', re.S)
TITLE_RE = re.compile(r'<title>([^<]+)</title>', re.I)


def parse_html(path):
    data = path.read_text(encoding="utf-8", errors="ignore")
    src = SOURCE_RE.search(data)
    src2 = SOURCE_TEXT_RE.search(data)
    desc = DESC_RE.search(data)
    title = TITLE_RE.search(data)
    return {
        "source_url": src.group(1) if src else None,
        "source_name": (src.group(2).strip() if src else (src2.group(1).strip() if src2 else None)),
        "description": (desc.group(1).strip().replace('\r','').replace('\n',' ') if desc else None),
        "title": title.group(1).strip() if title else None,
        "size": len(data),
    }


def main():
    base = pathlib.Path("docs/_audit_te_html/LV")
    out = {}
    for f in sorted(base.glob("*.html")):
        slug = f.stem
        out[slug] = parse_html(f)
    pathlib.Path("docs/_audit_lv_te_parsed.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"parsed {len(out)} slugs")
    # Print source mapping
    for s, v in sorted(out.items()):
        print(f"{s:40s} | {v['source_name']!r:60s} | {v['description'][:80] if v['description'] else 'no desc'}")


if __name__ == "__main__":
    main()
