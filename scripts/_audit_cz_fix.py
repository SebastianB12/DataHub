"""CZ re-audit fix script — applies fixes & writes audit findings."""
import sys, io, json, yaml, datetime
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from pipeline.db import supabase as sb

# ============================================================
# A. CURATED VALUE UPDATES (corruption, terrorism, ssr)
# ============================================================

CURATED_UPDATES = {
    'corruption-index': {'value': 59, 'date': '2025-12-31', 'unit': 'Points',
                         'note': 'TE 2025 Corruption Perceptions Index = 59 (Transparency International)'},
    'corruption-rank':  {'value': 39, 'date': '2025-12-31', 'unit': 'Rank',
                         'note': 'TE 2025 CPI rank = 39 of 180 (Transparency International)'},
    'terrorism-index':  {'value': 2.26, 'date': '2025-12-31', 'unit': 'Points',
                         'note': 'TE 2025 Global Terrorism Index = 2.26 (Institute for Economics and Peace)'},
    'social-security-rate': {'value': 45.4, 'date': '2026-12-31', 'unit': '%',
                             'note': 'TE Social Security Rate = 45.40% (Czech Social Security Administration)'},
}

def upsert_curated(slug, v, dt, unit, note):
    """Delete + insert curated single-point entries."""
    sb.table('data_points').delete().eq('country', 'CZ').eq('indicator', slug).execute()
    row = {
        'country': 'CZ', 'indicator': slug, 'date': dt, 'value': v,
        'source': 'curated', 'unit': unit, 'adjustment': '',
        'series_id': f'CZ:{slug}',
    }
    sb.table('data_points').upsert(row, on_conflict='indicator,country,date,source,adjustment').execute()
    sb.table('indicator_sources').update({
        'source': 'curated', 'series_id': f'CZ:{slug}', 'note': note,
    }).eq('country', 'CZ').eq('indicator', slug).eq('is_default', True).execute()
    print(f'  CURATED  {slug}: {v} ({dt})')


# ============================================================
# B. SOURCE-LABEL CORRECTIONS
#    For CZSO-attributed slugs where data is in CZSO already,
#    delete duplicate eurostat data so latest = czso. Update
#    indicator_sources note + series_id to be consistent.
#
#    For Eurostat-attributed slugs that already use eurostat,
#    just refresh indicator_sources note.
# ============================================================

# Slugs where TE attributes to a national source AND czso provider works:
# keep source=czso, delete eurostat data points for these.
DEFAULT_TO_CZSO = [
    # already czso but had duplicate eurostat data
    'business-confidence',
    'consumer-confidence',
    'consumer-spending',
    'employed-persons',
    'gross-fixed-capital-formation',
    'industrial-production',
    'manufacturing-production',
    'mining-production',
    'retail-sales',
    'ppi',
    'inflation-cpi',
    'cpi-food', 'cpi-clothing', 'cpi-housing-utilities',
    'cpi-transportation', 'cpi-recreation-and-culture', 'cpi-education',
    'food-inflation',
    'unemployed-persons',  # CZSO ZAM01/6284 exists
    'government-debt',
    'government-debt-total',
    'gdp-real',
]

# Slugs where TE says CZSO but only eurostat data exists
# (no CZSO provider implementation yet) — keep eurostat, add note.
DEFAULT_EUROSTAT_WITH_TE_CZSO_NOTE = {
    'budget-deficit':            'TE attributes CZSO; using Eurostat gov_10dd_edpt1 (B.9, % of GDP). Honest label = eurostat.',
    'changes-in-inventories':    'TE attributes CZSO; using Eurostat namq_10_gdp (P52, CZK billion equivalent). Honest label = eurostat.',
    'current-account-to-gdp':    'TE attributes CZSO; using Eurostat bop_gdp6_q. Honest label = eurostat.',
    'exports':                   'TE attributes CZSO; using Eurostat nama_10_exi (P6). Honest label = eurostat.',
    'imports':                   'TE attributes CZSO; using Eurostat nama_10_exi (P7). Honest label = eurostat.',
    'government-spending':       'TE attributes CZSO; using Eurostat namq_10_gdp (P3_S13). Honest label = eurostat.',
    'government-spending-eur':   'TE attributes CZSO; using Eurostat namq_10_gdp (P3_S13). Honest label = eurostat.',
    'population':                'TE attributes CZSO; using Eurostat demo_pjan (TOTAL). Honest label = eurostat.',
    'job-vacancies':             'TE attributes Labor Office of the Czech Republic; using Eurostat jvs_q_nace2 (JVR). Honest label = eurostat.',
    'unemployment':              'TE attributes Labor Office of CZ (registered rate). DB stores Eurostat ILO unemployment rate (ei_lmhr_m). Honest label = eurostat.',
}

# Slugs where TE attributes Eurostat and we use eurostat — already correct
ALREADY_OK_EUROSTAT = [
    'employment-rate', 'labor-force-participation-rate', 'long-term-unemployment-rate',
    'minimum-wages',  # TE says EUROSTAT 924 EUR/month — but our curated has 20800 CZK!
    'youth-unemployment-rate', 'house-price-index', 'productivity',
    'capacity-utilization', 'disposable-personal-income', 'energy-inflation',
    'services-inflation', 'services-sentiment',
]

# minimum-wages is special: TE says EUROSTAT 924 EUR/month, we have curated 20800 CZK/month.
# Both are correct in different units. TE source-label conformity demands eurostat.
# Switch to eurostat provider for this slug.

# Slugs where TE attributes CNB (Czech National Bank); we don't have a CNB
# provider, so use eurostat fallback w/ honest label.
DEFAULT_EUROSTAT_WITH_CNB_NOTE = {
    'core-cpi':         'TE attributes Czech National Bank; using Eurostat ei_cphi_m (HICP core ex food/energy). Honest label = eurostat.',
    'current-account':  'TE attributes Czech National Bank; using Eurostat bop_c6_q (CA). Honest label = eurostat.',
    'labour-costs':     'TE attributes European Central Bank; using Eurostat lc_lci_r2_q (I20). Honest label = eurostat.',
}

# Curated slugs that have no TE page or are correctly curated
CURATED_KEEP = [
    'corporate-tax-rate', 'personal-income-tax-rate', 'sales-tax-rate',
    'retirement-age-men', 'retirement-age-women',
    'social-security-rate-companies', 'social-security-rate-employees',
    'hospital-beds', 'medical-doctors', 'nurses',
    'credit-rating',
]


# ============================================================
# RUN
# ============================================================

findings = {}

print('=== A. CURATED VALUE UPDATES ===')
for slug, p in CURATED_UPDATES.items():
    upsert_curated(slug, p['value'], p['date'], p['unit'], p['note'])
    findings[slug] = {
        'action': 'curated-value-update',
        'new_value': p['value'], 'unit': p['unit'],
        'note': p['note'],
        'source': 'curated', 'series_id': f'CZ:{slug}',
    }

print('\n=== B. CZSO-DEFAULT cleanup ===')
for slug in DEFAULT_TO_CZSO:
    # Delete eurostat duplicate data points
    res = sb.table('data_points').delete().eq('country', 'CZ').eq('indicator', slug).eq('source', 'eurostat').execute()
    n_del = len(res.data) if res.data else 0
    # Ensure indicator_sources default = czso
    sb.table('indicator_sources').update({'is_default': False}).eq('country', 'CZ').eq('indicator', slug).eq('source', 'eurostat').execute()
    sb.table('indicator_sources').update({'is_default': True}).eq('country', 'CZ').eq('indicator', slug).eq('source', 'czso').execute()
    print(f'  CZSO {slug}: deleted {n_del} eurostat duplicate dp')
    findings[slug] = {
        'action': 'czso-canonical',
        'note': f'Deleted {n_del} eurostat duplicate data_points; CZSO is default',
        'source': 'czso',
    }

print('\n=== C. Eurostat-with-CZSO-note ===')
for slug, note in DEFAULT_EUROSTAT_WITH_TE_CZSO_NOTE.items():
    # Delete any czso-source data points (none likely, except unemployment)
    res = sb.table('data_points').delete().eq('country', 'CZ').eq('indicator', slug).eq('source', 'czso').execute()
    n_del = len(res.data) if res.data else 0
    # Set indicator_sources default to eurostat with note
    sb.table('indicator_sources').update({'is_default': False}).eq('country', 'CZ').eq('indicator', slug).eq('source', 'czso').execute()
    sb.table('indicator_sources').update({'is_default': True, 'note': note}).eq('country', 'CZ').eq('indicator', slug).eq('source', 'eurostat').execute()
    print(f'  EUROSTAT (TE=CZSO) {slug}: deleted {n_del} czso dp, note set')
    findings[slug] = {
        'action': 'eurostat-fallback-for-czso',
        'note': note,
        'source': 'eurostat',
    }

print('\n=== D. Eurostat-with-CNB-note ===')
for slug, note in DEFAULT_EUROSTAT_WITH_CNB_NOTE.items():
    sb.table('indicator_sources').update({'is_default': True, 'note': note}).eq('country', 'CZ').eq('indicator', slug).eq('source', 'eurostat').execute()
    print(f'  EUROSTAT (TE=CNB) {slug}: note set')
    findings[slug] = {
        'action': 'eurostat-fallback-for-cnb',
        'note': note,
        'source': 'eurostat',
    }

print('\n=== E. minimum-wages — switch to eurostat ===')
# Delete curated data, fetch eurostat earn_mw_cur, set as default
sb.table('data_points').delete().eq('country', 'CZ').eq('indicator', 'minimum-wages').eq('source', 'curated').execute()
# Insert eurostat indicator_sources row if not exists; composite key (indicator,country,source)
existing = sb.table('indicator_sources').select('indicator,country,source').eq('country', 'CZ').eq('indicator', 'minimum-wages').eq('source', 'eurostat').execute()
if not existing.data:
    sb.table('indicator_sources').insert({
        'country': 'CZ', 'indicator': 'minimum-wages', 'source': 'eurostat',
        'series_id': 'earn_mw_cur:NMW_LFT', 'is_default': True,
        'unit': 'EUR/Month', 'adjustment': '', 'freq_hint': 'S', 'transform': 'raw', 'conversion': 1.0, 'active': True,
        'note': 'TE attributes EUROSTAT minimum wage EUR/month (earn_mw_cur). Honest label = eurostat.',
    }).execute()
else:
    sb.table('indicator_sources').update({'is_default': True, 'note': 'TE attributes EUROSTAT minimum wage EUR/month (earn_mw_cur). Honest label = eurostat.'}).eq('country', 'CZ').eq('indicator', 'minimum-wages').eq('source', 'eurostat').execute()
# Demote curated row
sb.table('indicator_sources').update({'is_default': False}).eq('country', 'CZ').eq('indicator', 'minimum-wages').eq('source', 'curated').execute()
findings['minimum-wages'] = {
    'action': 'switch-curated-to-eurostat',
    'note': 'TE attributes EUROSTAT EUR/month minimum wage. Switching from curated CZK to eurostat earn_mw_cur.',
    'source': 'eurostat', 'series_id': 'earn_mw_cur:NMW_LFT',
}

print('\n=== F. Other-curated remain ===')
for slug in CURATED_KEEP:
    findings[slug] = {'action': 'no-change', 'source': 'curated',
                      'note': 'TE attributes non-data-API source (FA-CR, CSSA, agencies); curated remains'}

# remaining slugs already on eurostat and correct
for slug in ALREADY_OK_EUROSTAT:
    if slug == 'minimum-wages':
        continue
    findings[slug] = {'action': 'no-change', 'source': 'eurostat',
                      'note': 'TE attributes EUROSTAT; already correct'}

# gdp-* worldbank
for slug in ['gdp', 'gdp-per-capita', 'gdp-per-capita-ppp']:
    findings[slug] = {'action': 'no-change', 'source': 'worldbank',
                      'note': 'TE attributes World Bank; already correct'}

# Write findings YAML
findings_out = {
    'country': 'CZ',
    'audit_date': str(datetime.date.today()),
    'note': 'CZ re-audit 2026-05-17: Source-label honesty + curated value updates. ' \
            'Source-label = technical fetch quelle (never upstream attribution).',
    'slugs': findings,
}
import yaml as _yaml
with open('docs/_audit_cz_reaudit.yaml', 'w', encoding='utf-8') as f:
    _yaml.safe_dump(findings_out, f, allow_unicode=True, sort_keys=True)
print('\nWrote docs/_audit_cz_reaudit.yaml')
print(f'Total slugs processed: {len(findings)}')
