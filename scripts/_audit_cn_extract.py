"""Extract source-name + latest-value narrative for each CN slug; combine with DB state."""
import json, re, os, sys
sys.stdout.reconfigure(encoding='utf-8')

from pipeline.db import supabase as sb

CACHE = 'docs/_audit_cn_te_html'
slugs = json.load(open('docs/_audit_all_remaining_slugs.json'))['CN']

SRC_RE = re.compile(r"<a class='source-name'[^>]*href\s*=\s*'([^']*)'[^>]*>([^<]+)</a>", re.I)

# Narrative: "X in China increased/decreased/rose/fell to N (unit?) in MONTH (of)? YEAR"
NARR_RE = re.compile(
    r'in China (?:increased|decreased|rose|fell|jumped|dropped|widened|narrowed|grew|contracted|was)\s+(?:to\s+)?([\-+]?[\d,]+\.?\d*)\s*([A-Za-z%$€¥ ]*?)\s+(?:in\s+|by\s+|during\s+|points\s+in\s+)([A-Za-z]+)\s+(?:of\s+)?(\d{4})',
    re.I
)
# Also "reported at"
NARR2_RE = re.compile(
    r'(?:China.*?was reported at|was last (?:reported|recorded) at|stood at|recorded a value of)\s+([\-+]?[\d,]+\.?\d*)\s*([A-Za-z%$€¥ ]*?)\s+(?:in\s+)?([A-Za-z]+)?\s*(\d{4})?',
    re.I
)

# Country-list value pattern as fallback
LATEST_RE = re.compile(r'class="latest-value"[^>]*>([^<]+)<', re.I)

def parse(html):
    src = SRC_RE.search(html)
    src_name = src.group(2).strip() if src else None
    src_url = src.group(1).strip() if src else None
    val = None; unit = None; period = None
    m = NARR_RE.search(html)
    if m:
        val = m.group(1).replace(',','').strip()
        unit = m.group(2).strip()
        period = f'{m.group(3)} {m.group(4)}'
    else:
        m = NARR2_RE.search(html)
        if m:
            val = m.group(1).replace(',','').strip()
            unit = (m.group(2) or '').strip()
            period = f"{m.group(3) or ''} {m.group(4) or ''}".strip()
    return src_name, src_url, val, unit, period

# DB rows
rows = {r['indicator']: r for r in sb.table('indicator_sources').select('*').eq('country','CN').eq('is_default',True).execute().data}

# latest data_points
dp_rows = sb.table('data_points').select('indicator,date,value,unit').eq('country','CN').execute().data
latest_dp = {}
for r in dp_rows:
    cur = latest_dp.get(r['indicator'])
    if not cur or r['date'] > cur['date']:
        latest_dp[r['indicator']] = r

out = {}
for slug in slugs:
    html = open(os.path.join(CACHE, f'{slug}.html'),'r',encoding='utf-8',errors='ignore').read()
    src_name, src_url, val, unit, period = parse(html)
    db = rows.get(slug, {})
    dp = latest_dp.get(slug, {})
    out[slug] = {
        'te_source_name': src_name,
        'te_source_url': src_url,
        'te_latest_value': val,
        'te_latest_unit': unit,
        'te_latest_period': period,
        'db_source': db.get('source'),
        'db_series_id': db.get('series_id'),
        'db_note': (db.get('note') or '')[:200],
        'db_latest_date': dp.get('date'),
        'db_latest_value': dp.get('value'),
        'db_latest_unit': dp.get('unit'),
        'page_size': os.path.getsize(os.path.join(CACHE,f'{slug}.html')),
    }

json.dump(out, open('docs/_audit_cn_te_extracted.json','w',encoding='utf-8'), ensure_ascii=False, indent=2, default=str)

for slug in sorted(out):
    d = out[slug]
    print(f"{slug:38s} | TE[{(d['te_source_name'] or '-')[:25]:25s} | {(d['te_latest_value'] or '-')[:10]:10s} {d['te_latest_period'] or ''}] DB[{d['db_source']:10s} | {d['db_latest_value']!s:10s}]")
