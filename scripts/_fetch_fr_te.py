"""Fetch all TE pages for FR slugs, save HTML to docs/_audit_fr_te_html/."""
import json, subprocess, os, time, sys

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

slugs = json.load(open('docs/_audit_5cc_slugs.json'))['FR']
out_dir = 'docs/_audit_fr_te_html'
os.makedirs(out_dir, exist_ok=True)

for slug in slugs:
    out = os.path.join(out_dir, f'{slug}.html')
    if os.path.exists(out) and os.path.getsize(out) > 1000:
        continue
    url = f'https://tradingeconomics.com/france/{slug}'
    try:
        r = subprocess.run(["curl","-s","-A",UA,"--max-time","30",url], capture_output=True, timeout=40)
        html = r.stdout.decode("utf-8", errors="ignore")
        with open(out, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f'OK {slug} ({len(html)} bytes)')
    except Exception as e:
        print(f'FAIL {slug}: {e}')
    time.sleep(0.3)

print('Done.')
