"""Fetch fresh TE HTML for all CN slugs and cache to docs/_audit_cn_te_html/."""
import json, subprocess, os, sys, time

sys.stdout.reconfigure(encoding='utf-8')

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
CACHE = 'docs/_audit_cn_te_html'
os.makedirs(CACHE, exist_ok=True)

slugs = json.load(open('docs/_audit_all_remaining_slugs.json'))['CN']
country = 'china'

results = {}
for i, slug in enumerate(slugs, 1):
    out = os.path.join(CACHE, f'{slug}.html')
    if os.path.exists(out) and os.path.getsize(out) > 1000:
        results[slug] = 'cached'
        continue
    url = f'https://tradingeconomics.com/{country}/{slug}'
    try:
        r = subprocess.run(
            ["curl","-s","-A",UA,"--max-time","30","-o",out,url],
            capture_output=True, timeout=40
        )
        size = os.path.getsize(out) if os.path.exists(out) else 0
        results[slug] = f'fetched ({size}b)'
        print(f'[{i:>2}/{len(slugs)}] {slug:40s} {results[slug]}')
        time.sleep(0.3)
    except Exception as e:
        results[slug] = f'ERR: {e}'
        print(f'[{i:>2}/{len(slugs)}] {slug:40s} {results[slug]}')

print('\nDone:', len(results), 'slugs')
