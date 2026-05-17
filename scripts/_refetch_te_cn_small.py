"""Refetch small (placeholder) CN TE pages with cache-busting + retries."""
import json, subprocess, os, sys, time
sys.stdout.reconfigure(encoding='utf-8')
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
CACHE = 'docs/_audit_cn_te_html'
slugs = json.load(open('docs/_audit_all_remaining_slugs.json'))['CN']
small = [s for s in slugs if os.path.getsize(os.path.join(CACHE,f'{s}.html')) < 270000]
print('small:', small)

for slug in small:
    out = os.path.join(CACHE, f'{slug}.html')
    for attempt in range(3):
        bust = int(time.time()*1000) + attempt
        url = f'https://tradingeconomics.com/china/{slug}?_={bust}'
        r = subprocess.run(
            ["curl","-s","-A",UA,"--max-time","45",
             "-H","Cache-Control: no-cache",
             "-H","Pragma: no-cache",
             "-o",out,url],
            capture_output=True, timeout=60
        )
        size = os.path.getsize(out) if os.path.exists(out) else 0
        print(f'  {slug} attempt {attempt+1}: {size}b')
        if size > 270000:
            break
        time.sleep(1.5)
