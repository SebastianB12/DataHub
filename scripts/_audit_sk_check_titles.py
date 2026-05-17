"""Identify which SK TE slugs return an empty/no-page (TE doesn't have this slug for SK)."""
import os
import re
import json

slugs = json.load(open('docs/_audit_all_remaining_slugs.json'))['SK']
report = {}
for slug in slugs:
    p = f'docs/_audit_te_html/SK/{slug}.html'
    if not os.path.exists(p):
        report[slug] = {'status': 'missing'}
        continue
    html = open(p, encoding='utf-8').read()
    title = re.search(r'<title[^>]*>\s*([^<]*?)\s*</title>', html, re.S)
    title_text = title.group(1).strip() if title else ''
    has_desc = 'id="description"' in html
    has_src = 'source-name' in html
    h2_desc = re.search(r'<h2 id="description"[^>]*>(.*?)</h2>', html, re.S)
    desc_text = h2_desc.group(1).strip()[:300] if h2_desc else None
    report[slug] = {
        'title': title_text,
        'has_desc': has_desc,
        'has_source_attr': has_src,
        'desc': desc_text,
    }
print(f"\nSlugs without TE description (TE has no data for SK):")
no_desc = []
for s, info in report.items():
    if not info.get('has_desc'):
        print(f"  {s}")
        no_desc.append(s)
print(f"\nTotal without TE page: {len(no_desc)}/{len(slugs)}")
with open('docs/_audit_sk_titles.json', 'w', encoding='utf-8') as f:
    json.dump(report, f, indent=2, ensure_ascii=False)
