"""Parse TE source-name, value, unit and last update from cached CN HTML.
Output: docs/_audit_cn_te_parsed.json
"""
import json, re, os, sys
sys.stdout.reconfigure(encoding='utf-8')

CACHE = 'docs/_audit_cn_te_html'
slugs = json.load(open('docs/_audit_all_remaining_slugs.json'))['CN']

SRC_RE = re.compile(r"source:\s*<a class='source-name'[^>]*href\s*=\s*'([^']*)'[^>]*>([^<]+)</a>", re.I)
# Value+unit usually in hero stat block; multiple patterns
HERO_RE = re.compile(r'<div class="hero-value[^"]*"[^>]*>([^<]+)</div>', re.S)
# Description block contains "China X was reported at Y in MMM/YYYY"
DESC_META_RE = re.compile(r'<meta\s+name=["\']description["\']\s+content=["\']([^"\']+)["\']', re.I)
TITLE_RE = re.compile(r'<title>([^<]+)</title>', re.I)
# OG description
OG_DESC_RE = re.compile(r'<meta\s+property=["\']og:description["\']\s+content=["\']([^"\']+)["\']', re.I)

# Try to grab the calendar/last-value table
# class="te-h1-value" or "te-h1" - older
TE_H1_RE = re.compile(r'<span[^>]*class="te-h1[^"]*"[^>]*>([^<]+)</span>', re.I)
# value table row
VAL_TABLE_RE = re.compile(r'<td[^>]*>\s*Last\s*</td>\s*<td[^>]*>([^<]+)</td>', re.I)

out = {}
for slug in slugs:
    path = os.path.join(CACHE, f'{slug}.html')
    html = open(path, 'r', encoding='utf-8', errors='ignore').read()

    src = SRC_RE.search(html)
    src_url, src_name = (src.group(1), src.group(2).strip()) if src else (None, None)

    meta = DESC_META_RE.search(html)
    meta_desc = meta.group(1) if meta else None
    title = TITLE_RE.search(html)
    title_txt = title.group(1) if title else None
    og = OG_DESC_RE.search(html)
    og_desc = og.group(1) if og else None

    hero = HERO_RE.search(html)
    hero_val = hero.group(1).strip() if hero else None
    teh1 = TE_H1_RE.search(html)
    teh1_val = teh1.group(1).strip() if teh1 else None

    out[slug] = {
        'src_name': src_name,
        'src_url': src_url,
        'meta_desc': meta_desc,
        'og_desc': og_desc,
        'title': title_txt,
        'hero_val': hero_val,
        'teh1_val': teh1_val,
    }

json.dump(out, open('docs/_audit_cn_te_parsed.json','w',encoding='utf-8'), ensure_ascii=False, indent=2)

# Print summary
for slug, d in sorted(out.items()):
    print(f"{slug:38s} | src={d['src_name']!s:60s} | val={d['hero_val'] or d['teh1_val']!s:20s}")
