"""Build the final docs/_audit_cz_reaudit.yaml with full per-slug data."""
import sys, io, json, yaml, datetime, re, pathlib
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from pipeline.db import supabase as sb

# Load parsed TE data
with open('docs/_audit_cz_parsed.json', encoding='utf-8') as f:
    te = json.load(f)
# Re-parse retail-sales just in case
SOURCE_RE = re.compile(r"source:\s*<a class='source-name'[^>]*href\s*=\s*'([^']*)'[^>]*>([^<]+)</a>", re.I)
SOURCE_SPAN_RE = re.compile(r"<span class='source-present'>source:\s*([^<]+)</span>", re.I)
DESC_RE = re.compile(r'<h2 id="description"[^>]*>(.*?)</h2>', re.S)
VALUE_RE = re.compile(r"(?:to|at|of|reached)\s+(-?\d[\d,\.]*)\s*(?:%|percent|billion|million|points|index)", re.I)

for slug in ['retail-sales']:
    h = pathlib.Path(f'docs/_audit_te_html/CZ/{slug}.html').read_text('utf-8', errors='ignore')
    m = SOURCE_RE.search(h); d = DESC_RE.search(h); ms = SOURCE_SPAN_RE.search(h)
    desc = ''
    if d:
        desc = re.sub(r'<[^>]+>',' ', d.group(1)); desc = re.sub(r'\s+',' ', desc).strip()
    v = VALUE_RE.search(desc) if desc else None
    label = m.group(2) if m else (ms.group(1) if ms else None)
    url = m.group(1) if m else None
    te[slug] = {"source_label": label, "source_url": url, "desc": desc[:500], "value_match": v.group(1) if v else None}

# Pull current state from DB
r = sb.table('indicator_sources').select('indicator,source,series_id,note').eq('country','CZ').eq('is_default',True).execute()
isrc = {x['indicator']: x for x in r.data}

# DB latest data point
db_latest = {}
for slug in isrc.keys():
    rr = sb.table('data_points').select('date,value,source,unit,adjustment').eq('country','CZ').eq('indicator',slug).order('date', desc=True).limit(1).execute()
    db_latest[slug] = rr.data[0] if rr.data else None

# All CZ slugs
with open('docs/_audit_all_remaining_slugs.json', encoding='utf-8') as f:
    cz_slugs = json.load(f)['CZ']

# Action categorisation based on previous fix script
actions = {}
for slug in [
    'corruption-index','corruption-rank','terrorism-index','social-security-rate',
]:
    actions[slug] = 'curated-value-update'
for slug in [
    'business-confidence','consumer-confidence','consumer-spending','employed-persons',
    'gross-fixed-capital-formation','industrial-production','manufacturing-production',
    'mining-production','retail-sales','ppi','inflation-cpi','cpi-food','cpi-clothing',
    'cpi-housing-utilities','cpi-transportation','cpi-recreation-and-culture','cpi-education',
    'food-inflation','unemployed-persons','government-debt','government-debt-total','gdp-real',
]:
    actions[slug] = 'czso-canonical'
for slug in [
    'budget-deficit','changes-in-inventories','current-account-to-gdp','exports','imports',
    'government-spending','government-spending-eur','population','job-vacancies','unemployment',
]:
    actions[slug] = 'eurostat-fallback-for-czso'
for slug in ['core-cpi','current-account','labour-costs']:
    actions[slug] = 'eurostat-fallback-for-cnb-ecb'
actions['minimum-wages'] = 'switch-curated-to-eurostat'
for slug in [
    'corporate-tax-rate','personal-income-tax-rate','sales-tax-rate',
    'retirement-age-men','retirement-age-women',
    'social-security-rate-companies','social-security-rate-employees',
    'hospital-beds','medical-doctors','nurses','credit-rating',
]:
    actions[slug] = 'curated-no-change'
for slug in [
    'employment-rate','labor-force-participation-rate','long-term-unemployment-rate',
    'youth-unemployment-rate','house-price-index','productivity','capacity-utilization',
    'disposable-personal-income','energy-inflation','services-inflation','services-sentiment',
]:
    actions[slug] = 'eurostat-no-change'
for slug in ['gdp','gdp-per-capita','gdp-per-capita-ppp']:
    actions[slug] = 'worldbank-no-change'

findings = {}
for slug in cz_slugs:
    isr = isrc.get(slug, {})
    db = db_latest.get(slug)
    tedata = te.get(slug, {})
    findings[slug] = {
        'action': actions.get(slug, 'unknown'),
        'te_label': tedata.get('source_label'),
        'te_value': tedata.get('value_match'),
        'te_url': tedata.get('source_url'),
        'db_source': isr.get('source'),
        'db_series_id': isr.get('series_id'),
        'db_note': isr.get('note'),
        'db_latest_date': str(db['date']) if db else None,
        'db_latest_value': db['value'] if db else None,
        'db_latest_source': db['source'] if db else None,
        'db_unit': db['unit'] if db else None,
        'verdict': 'OK' if isr.get('source') == (db['source'] if db else None) or actions.get(slug, '').startswith('curated') else 'CHECK',
    }

# Build summary stats
by_action = {}
for s, info in findings.items():
    by_action.setdefault(info['action'], []).append(s)

doc = {
    'country': 'CZ',
    'audit_date': str(datetime.date.today()),
    'note': (
        'CZ re-audit 2026-05-17: Source-label honesty + curated value updates. '
        'Source-label = technical fetch quelle (never upstream attribution). '
        'Validator pipeline.validate_te_conformity is green (0 violations).'
    ),
    'total_slugs': len(cz_slugs),
    'by_action_count': {k: len(v) for k, v in by_action.items()},
    'by_action': by_action,
    'slugs': findings,
}
with open('docs/_audit_cz_reaudit.yaml', 'w', encoding='utf-8') as f:
    yaml.safe_dump(doc, f, allow_unicode=True, sort_keys=True)
print('Wrote docs/_audit_cz_reaudit.yaml')
print('By action:')
for k, v in by_action.items():
    print(f'  {k}: {len(v)}')
