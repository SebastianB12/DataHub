"""Parse TE HTML for FR slugs: extract source, current value, period from description."""
import json, os, re
from bs4 import BeautifulSoup

slugs = json.load(open('docs/_audit_5cc_slugs.json'))['FR']
in_dir = 'docs/_audit_fr_te_html'

SOURCE_RE = re.compile(r"source:\s*<a class='source-name'[^>]*href\s*=\s*'([^']*)'[^>]*>([^<]+)</a>", re.I)
SOURCE_RE2 = re.compile(r"source:\s*<a[^>]*>([^<]+)</a>", re.I)
DESC_RE = re.compile(r'<h2 id="description"[^>]*>(.*?)</h2>', re.S)
# Value in title block (key facts table)
HERO_VAL_RE = re.compile(r'<div class="te-hero-data-num"[^>]*>([^<]+)</div>', re.I)
# Generic last-value attempt
LAST_VAL_RE = re.compile(r'data-symbol-original-format="[^"]*"[^>]*>([^<]+)</span>', re.I)

out = {}
for slug in slugs:
    p = os.path.join(in_dir, f'{slug}.html')
    if not os.path.exists(p):
        out[slug] = {'error': 'no html'}
        continue
    html = open(p, encoding='utf-8').read()

    src_match = SOURCE_RE.search(html)
    if src_match:
        src_href = src_match.group(1)
        src_text = src_match.group(2).strip()
    else:
        src_match = SOURCE_RE2.search(html)
        src_href = ''
        src_text = src_match.group(1).strip() if src_match else ''

    desc_match = DESC_RE.search(html)
    desc = ''
    if desc_match:
        # Strip HTML tags
        desc_html = desc_match.group(1)
        desc = BeautifulSoup(desc_html, 'html.parser').get_text(' ', strip=True)

    # Try to find first numeric value in description (current value)
    num_in_desc = None
    if desc:
        m = re.search(r'\b([-+]?\d+(?:[\.,]\d+)?)\s*(?:percent|%|EUR|Million|points|Index|Thousand|Billion|per cent)', desc, re.I)
        if m:
            num_in_desc = m.group(1).replace(',', '.')

    out[slug] = {
        'source_text': src_text,
        'source_href': src_href,
        'description': desc[:1200],
        'value_in_desc': num_in_desc,
    }

with open('docs/_audit_fr_te_parsed.json', 'w', encoding='utf-8') as f:
    json.dump(out, f, indent=2, ensure_ascii=False)
print(f'Parsed {len(out)} slugs')
