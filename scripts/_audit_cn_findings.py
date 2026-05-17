"""Build per-slug findings YAML for CN re-audit. Match TE source + value vs DB."""
import json, re, os, sys
sys.stdout.reconfigure(encoding='utf-8')

from pipeline.db import supabase as sb

CACHE = 'docs/_audit_cn_te_html'
slugs = json.load(open('docs/_audit_all_remaining_slugs.json'))['CN']

SRC_RE = re.compile(r"<a class='source-name'[^>]*href\s*=\s*'([^']*)'[^>]*>([^<]+)</a>", re.I)

# Narrative patterns
PATTERNS = [
    # increased/decreased/remained to/at N UNIT in PERIOD
    re.compile(r'in China (?:increased|decreased|rose|fell|jumped|dropped|widened|narrowed|grew|contracted|was estimated|was worth|was last recorded|was last reported)\s+(?:at|to)?\s*([\-+]?[\d,]+\.?\d*)\s*([A-Za-z%$€¥/ ]*?)\s+(?:in|by|during|of)\s+([A-Za-z]+(?: of \d{4})?(?: \d{4})?)', re.I),
    # remained unchanged at N pct in MONTH
    re.compile(r'in China remained unchanged at\s+([\-+]?[\d,]+\.?\d*)\s*([A-Za-z%$€¥ ]*?)\s+(?:in|on)\s+([A-Za-z]+[\w ,]+)', re.I),
    # "in China increased N percent in MONTH"
    re.compile(r'in China (?:increased|decreased|rose|fell|grew)\s+([\-+]?[\d,]+\.?\d*)\s*([A-Za-z%$€¥/ ]*?)\s+in\s+([A-Za-z]+[\w ,]+)', re.I),
    # "was last recorded at N percent."
    re.compile(r'in China was last recorded at\s+([\-+]?[\d,]+\.?\d*)\s*([A-Za-z%$€¥/ ]*)', re.I),
    # Population: "was estimated at N million people in YEAR"
    re.compile(r'population in China was estimated at\s+([\-+]?[\d,]+\.?\d*)\s*(million people|million)\s+in\s+(\d{4})', re.I),
    # "was worth N billion US dollars in YEAR"
    re.compile(r'in China was worth\s+([\-+]?[\d,]+\.?\d*)\s*(billion US dollars|US dollars)\s+in\s+(\d{4})', re.I),
    # GDP per Capita PPP: "in China was last recorded at N US dollars in YEAR"
    re.compile(r'in China was last recorded at\s+([\-+]?[\d,]+\.?\d*)\s*([A-Za-z\s]+?)\s+in\s+(\d{4})', re.I),
]


def parse_value(html):
    for pat in PATTERNS:
        m = pat.search(html)
        if m:
            val = m.group(1).replace(',','').strip()
            try:
                val_f = float(val)
            except Exception:
                continue
            unit = m.group(2).strip() if m.lastindex >= 2 else ''
            period = m.group(3).strip() if m.lastindex >= 3 else ''
            return val_f, unit, period
    return None, None, None


def parse_source(html):
    m = SRC_RE.search(html)
    if not m:
        return None, None
    return m.group(2).strip(), m.group(1).strip()


# Authoritative CN source→fetch-channel map (Hard constraint)
SOURCE_MAP = {
    "National Bureau of Statistics of China": "akshare",
    "National Bureau of Statistics": "akshare",
    "NBS": "akshare",
    "People's Bank of China": "akshare",
    "People&#39;s Bank of China": "akshare",
    "PBoC": "akshare",
    "General Administration of Customs": "gacc",
    "General Administration of Customs of China": "gacc",
    "GACC": "gacc",
    "State Administration of Foreign Exchange": "akshare",
    "SAFE": "akshare",
    "Federal Reserve": "fred",
    "World Bank": "worldbank",
    "Conference Board": "curated",
    "Transparency International": "curated",
    "S&P Global": "curated",     # Caixin/S&P PMI licensed
    "S&P Markit": "curated",
    "Caixin": "curated",
    "OECD": "curated",
    "Institute for Economics and Peace": "curated",
    "SIPRI": "curated",
    "Bank for International Settlements": "fred",   # BIS series via FRED Quarterly
    "BIS": "fred",
    "World Gold Council": "curated",   # WGC paid licensing → curated for now
    "State Administration of Taxation": "curated",  # tax rates only → static curated OK
}

# DB
rows = {r['indicator']: r for r in sb.table('indicator_sources').select('*').eq('country','CN').eq('is_default',True).execute().data}
dp_rows = sb.table('data_points').select('indicator,date,value,unit').eq('country','CN').execute().data
latest_dp = {}
for r in dp_rows:
    cur = latest_dp.get(r['indicator'])
    if not cur or r['date'] > cur['date']:
        latest_dp[r['indicator']] = r


def compute_status(slug, te_src, te_val, db_src, db_val, db_note=''):
    # Source check
    expected_src = SOURCE_MAP.get(te_src) if te_src else None
    src_ok = (expected_src == db_src) if expected_src else None
    # Value check (±5%)
    val_ok = None
    if te_val is not None and db_val is not None:
        try:
            te_f = float(te_val); db_f = float(db_val)
            if abs(te_f) < 1e-9 and abs(db_f) < 1e-9:
                val_ok = True
            elif te_f == 0:
                val_ok = abs(db_f) < 1e-9
            else:
                val_ok = abs(db_f - te_f) / abs(te_f) <= 0.05
        except Exception:
            val_ok = None
    return src_ok, val_ok, expected_src


findings = {}
for slug in slugs:
    html = open(os.path.join(CACHE, f'{slug}.html'),'r',encoding='utf-8',errors='ignore').read()
    te_src, te_url = parse_source(html)
    te_val, te_unit, te_period = parse_value(html)
    db = rows.get(slug, {})
    dp = latest_dp.get(slug, {})
    src_ok, val_ok, expected_src = compute_status(
        slug, te_src, te_val,
        db.get('source'), dp.get('value'), db.get('note','')
    )
    findings[slug] = {
        'te': {
            'source_name': te_src,
            'source_url': te_url,
            'latest_value': te_val,
            'latest_unit': te_unit,
            'latest_period': te_period,
        },
        'db': {
            'source': db.get('source'),
            'series_id': db.get('series_id'),
            'note': (db.get('note') or '')[:200],
            'latest_date': str(dp.get('date')) if dp.get('date') else None,
            'latest_value': dp.get('value'),
            'latest_unit': dp.get('unit'),
        },
        'status': {
            'expected_source': expected_src,
            'source_ok': src_ok,
            'value_ok': val_ok,
        },
    }

json.dump(findings, open('docs/_audit_cn_findings.json','w',encoding='utf-8'), ensure_ascii=False, indent=2, default=str)

# Print compact summary
print(f"{'slug':40s} | {'src_ok':6s} | {'val_ok':6s} | TE={'src':20s} val={'':10s}| DB={'src':12s} val={'':10s}")
print('-'*140)
issues = []
for slug in sorted(findings):
    f = findings[slug]
    te_src = (f['te']['source_name'] or '-')[:20]
    te_val = f['te']['latest_value']
    db_src = f['db']['source']
    db_val = f['db']['latest_value']
    so = f['status']['source_ok']
    vo = f['status']['value_ok']
    so_s = 'OK' if so else ('--' if so is None else 'NO')
    vo_s = 'OK' if vo else ('--' if vo is None else 'NO')
    print(f"{slug:40s} | {so_s:6s} | {vo_s:6s} | TE={te_src:20s} val={te_val!s:10s}| DB={db_src:12s} val={db_val!s:10s}")
    if so is False or vo is False:
        issues.append(slug)

print('\nISSUES:', len(issues))
for s in issues:
    print(' -', s)
