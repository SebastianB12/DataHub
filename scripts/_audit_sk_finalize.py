"""Build the final SK audit YAML by combining TE pages, alt-slug pages, and DB state.

Maps TE upstream sources to our internal source label and recommends per-slug actions.
"""
import json
import re
import os
import yaml
from pipeline.db import supabase as sb


DESC_RE = re.compile(r'<h2 id="description"[^>]*>(.*?)</h2>', re.S)
SOURCE_RE = re.compile(r"source:\s*<a class='source-name'[^>]*href\s*=\s*'([^']*)'[^>]*>([^<]+)</a>", re.I)
SOURCE_TEXT_RE = re.compile(r"<span class='source-present'>\s*source:\s*(.*?)</span>", re.I | re.S)


def parse_html(p):
    if not os.path.exists(p):
        return {}
    html = open(p, encoding='utf-8').read()
    src = SOURCE_RE.search(html)
    src_url, src_name = (None, None)
    if src:
        src_url, src_name = src.group(1), src.group(2).strip()
    else:
        m = SOURCE_TEXT_RE.search(html)
        if m:
            raw = m.group(1)
            stripped = re.sub(r'<[^>]+>', '', raw).strip()
            src_name = stripped
    desc = DESC_RE.search(html)
    return {
        'source_url': src_url,
        'source_name': src_name,
        'description': desc.group(1).strip() if desc else None,
    }


def parse_first_value(desc: str | None) -> tuple[str | None, str | None]:
    """Extract (value, unit) from TE description."""
    if not desc:
        return None, None
    pats = [
        (r'([\-0-9]+(?:\.[0-9]+)?)\s*percent', '%'),
        (r'([\-0-9]+(?:\.[0-9]+)?)\s*EUR Million', 'EUR Million'),
        (r'([\-0-9]+(?:\.[0-9]+)?)\s*USD Million', 'USD Million'),
        (r'([\-0-9]+(?:\.[0-9]+)?)\s*USD', 'USD'),
        (r'([\-0-9]+(?:\.[0-9]+)?)\s*EUR', 'EUR'),
        (r'([\-0-9]+(?:\.[0-9]+)?)\s*Index', 'Index'),
        (r'([\-0-9]+(?:\.[0-9]+)?)\s*points', 'points'),
        (r'rose to ([\-0-9]+(?:\.[0-9]+)?)\s*%', '%'),
        (r'fell to ([\-0-9]+(?:\.[0-9]+)?)\s*%', '%'),
        (r'(\-?\d+(?:\.\d+)?)\s*(?:thousand|Thousand)', 'thousand'),
    ]
    for p, u in pats:
        m = re.search(p, desc)
        if m:
            return m.group(1), u
    return None, None


def map_source(te_name: str | None) -> str:
    if not te_name:
        return '?'
    n = te_name.lower()
    if 'statistical office' in n or 'štatistický' in n:
        return 'susr_sk'
    if 'eurostat' in n:
        return 'eurostat'
    if 'world bank' in n or 'worldbank' in n:
        return 'worldbank'
    if 'european central bank' in n or n.strip() == 'ecb':
        return 'ecb'
    if 'national bank of slovakia' in n or 'národná banka slovenska' in n or 'nbs' in n or 'rodn' in n.lower():
        return 'nbs (use ecb fallback)'  # mark for closer look
    if 'ministry of finance' in n or 'ministry of labour' in n or 'social affairs and family' in n:
        return 'curated'  # OR scrape; for non-Eurostat ministries, curated is honest
    if 'tax directorate' in n or 'social insurance agency' in n:
        return 'curated'
    if 'conference board' in n or 'transparency international' in n or 'oecd' in n or 'who' in n or 'sipri' in n:
        return 'curated'
    if 'imf' in n or 'international monetary fund' in n:
        return 'imf'
    return 'curated'


def main():
    slugs = json.load(open('docs/_audit_all_remaining_slugs.json'))['SK']
    alt_results = json.load(open('docs/_audit_sk_te_alt.json'))

    # Re-parse alt HTML to get proper sources (the alt fetch script used a narrower regex)
    for slug, entries in alt_results.items():
        for entry in entries:
            html_path = f'docs/_audit_te_html/SK_alt/{slug}__{entry["alt"]}.html'
            parsed = parse_html(html_path)
            if parsed.get('source_name'):
                entry['src'] = parsed['source_name']

    # DB state
    db_def = {}
    r = sb.table('indicator_sources').select('indicator,source,is_default').eq('country', 'SK').eq('is_default', True).execute()
    for row in r.data:
        db_def[row['indicator']] = row['source']

    # latest data point per slug
    latest = {}
    r = sb.table('data_points').select('indicator,date,value,source').eq('country', 'SK').order('date', desc=True).execute()
    for row in r.data:
        if row['indicator'] not in latest:
            latest[row['indicator']] = row
    counts = {}
    r = sb.table('data_points').select('indicator', count='exact').eq('country', 'SK').execute()
    # this returns each row not count; recount
    cnts = {}
    rr = sb.table('data_points').select('indicator').eq('country', 'SK').execute()
    for row in rr.data:
        cnts[row['indicator']] = cnts.get(row['indicator'], 0) + 1

    findings = {}
    for slug in slugs:
        # 1) prefer canonical TE page if it has description
        canon = parse_html(f'docs/_audit_te_html/SK/{slug}.html')
        canon_desc = canon.get('description') or ''
        used = None
        if 'id="description"' in canon_desc or canon.get('description'):
            used = {'slug_used': slug, **canon}
        else:
            # try alt
            for alt_entry in alt_results.get(slug, []):
                if alt_entry.get('desc'):
                    used = {
                        'slug_used': alt_entry['alt'],
                        'source_url': None,
                        'source_name': alt_entry.get('src'),
                        'description': alt_entry.get('desc'),
                    }
                    break

        if used is None:
            # no TE page found at all
            findings[slug] = {
                'te_status': 'no_te_page',
                'db_default_source': db_def.get(slug, '(none)'),
                'db_row_count': cnts.get(slug, 0),
                'db_latest': latest.get(slug),
            }
            continue

        te_value, te_unit = parse_first_value(used.get('description'))
        te_src_name = used.get('source_name')
        te_mapped = map_source(te_src_name)

        db_src = db_def.get(slug, '(none)')
        l = latest.get(slug, {})
        match = (db_src == te_mapped) or (te_mapped.startswith('nbs') and db_src in ('ecb', 'curated'))

        findings[slug] = {
            'te_slug_used': used['slug_used'],
            'te_source_name': te_src_name,
            'te_mapped': te_mapped,
            'te_value': te_value,
            'te_unit': te_unit,
            'te_desc_excerpt': (used.get('description') or '')[:280].replace('<', '&lt;'),
            'db_default_source': db_src,
            'db_row_count': cnts.get(slug, 0),
            'db_latest_value': l.get('value'),
            'db_latest_date': l.get('date'),
            'db_latest_source': l.get('source'),
            'source_match': bool(match),
        }

    with open('docs/_audit_sk_reaudit.yaml', 'w', encoding='utf-8') as f:
        yaml.safe_dump(findings, f, allow_unicode=True, sort_keys=True, width=200)

    n = len(findings)
    n_match = sum(1 for v in findings.values() if v.get('source_match'))
    print(f"\nTotal: {n}, source_match: {n_match}, mismatches/uncertain: {n - n_match}")
    print(f"\nFindings with action needed:")
    for slug, v in sorted(findings.items()):
        if v.get('te_status') == 'no_te_page':
            print(f"  NO_TE_PAGE: {slug:30s} db={v.get('db_default_source')} rows={v.get('db_row_count')}")
        elif not v.get('source_match'):
            te_name = v.get('te_source_name') or '(none)'
            print(f"  MISMATCH:   {slug:30s} db={v['db_default_source']:10s} te_says={te_name[:50]:50s} -> {v['te_mapped']}")


if __name__ == '__main__':
    main()
