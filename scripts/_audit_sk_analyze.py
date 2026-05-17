"""Analyze SK TE pages + DB state, build consolidated audit findings.

Produces docs/_audit_sk_reaudit.yaml with per-slug: TE source/name, mapped source,
DB current default source, latest DB value/date, and recommended action.
"""
import json
import re
import os
import yaml
from pipeline.db import supabase as sb


SOURCE_RE = re.compile(r"source:\s*<a class='source-name'[^>]*href\s*=\s*'([^']*)'[^>]*>([^<]+)</a>", re.I)
DESC_RE = re.compile(r'<h2 id="description"[^>]*>(.*?)</h2>', re.S)
# Extract first numeric value from description
NUM_RE = re.compile(r'(-?[0-9]+(?:[.,][0-9]+)?)\s*(?:%|percent|EUR|USD|million|billion|points)?')


# Map TE upstream source names -> our internal source labels
def map_source(te_name: str, te_url: str | None = None) -> str:
    if not te_name:
        return "?"
    n = te_name.lower()
    if "statistical office of the slovak" in n or "statistical office" in n or "štatistický" in n:
        return "susr_sk"
    if "national bank of slovakia" in n or "nbs" in n:
        # NBS data — we don't have an nbs_sk provider; closest is ECB
        return "ecb"
    if "eurostat" in n:
        return "eurostat"
    if "world bank" in n:
        return "worldbank"
    if "conference board" in n or "transparency international" in n or "oecd" in n or "who" in n or "sipri" in n:
        return "curated"
    if "ministry of finance" in n:
        # Treasury data - source it via Eurostat (gov_10dd_edpt1) which covers same series
        return "eurostat"
    if "ministry of labour" in n or "tax directorate" in n or "social insurance agency" in n:
        return "curated"
    if "international monetary fund" in n:
        return "imf"
    return "curated"


def parse_desc_value(desc: str) -> str | None:
    if not desc:
        return None
    # Try several patterns
    pats = [
        r'rose to ([0-9.,]+)%',
        r'increased to ([0-9.,]+)%',
        r'fell to ([0-9.,]+)%',
        r'decreased to ([0-9.,]+)%',
        r'stood at ([0-9.,]+)%',
        r'reached ([0-9.,]+)%',
        r'recorded ([0-9.,]+)%',
        r'(-?[0-9]+\.[0-9]+)\s*%',
        r'([0-9.,]+)\s*(?:EUR|points|billion|million)',
    ]
    for p in pats:
        m = re.search(p, desc)
        if m:
            return m.group(1)
    return None


def latest_db(slug: str):
    r = sb.table('data_points').select('date,value,source').eq('country', 'SK').eq('indicator', slug).order('date', desc=True).limit(1).execute()
    if r.data:
        return r.data[0]
    return None


def main():
    with open('docs/_audit_sk_te_raw.json', encoding='utf-8') as f:
        te_raw = json.load(f)

    # DB defaults
    r = sb.table('indicator_sources').select('indicator,source,is_default').eq('country', 'SK').eq('is_default', True).execute()
    defaults = {row['indicator']: row['source'] for row in r.data}

    findings = {}
    for slug, te in te_raw.items():
        if 'error' in te:
            findings[slug] = {'status': 'fetch_fail', 'te': te}
            continue
        te_name = te.get('source_name')
        te_url = te.get('source_url')
        mapped = map_source(te_name, te_url)
        db_src = defaults.get(slug, '(none)')
        latest = latest_db(slug)
        desc = te.get('description') or ''
        te_value = te.get('te_value') or parse_desc_value(desc)

        match = (db_src == mapped)
        findings[slug] = {
            'te_source_name': te_name,
            'te_source_url': te_url,
            'te_mapped': mapped,
            'te_value': te_value,
            'description_excerpt': desc[:200] if desc else None,
            'db_default_source': db_src,
            'db_latest_value': latest.get('value') if latest else None,
            'db_latest_date': latest.get('date') if latest else None,
            'db_latest_source': latest.get('source') if latest else None,
            'source_match': match,
            'action': 'OK' if match else f'switch_default {db_src} -> {mapped}',
        }

    os.makedirs('docs', exist_ok=True)
    with open('docs/_audit_sk_reaudit.yaml', 'w', encoding='utf-8') as f:
        yaml.safe_dump(findings, f, allow_unicode=True, sort_keys=True)
    # Summary
    n_total = len(findings)
    n_match = sum(1 for v in findings.values() if v.get('source_match'))
    n_mismatch = n_total - n_match
    print(f"\nTotal: {n_total}, source_match: {n_match}, mismatches: {n_mismatch}")
    print("\nMismatches:")
    for slug, v in sorted(findings.items()):
        if not v.get('source_match'):
            te_says = v.get('te_source_name') or '(no source attribution)'
            print(f"  {slug:40s} DB={v['db_default_source']:12s} TE_says={te_says:60s} -> mapped={v['te_mapped']}")


if __name__ == "__main__":
    main()
