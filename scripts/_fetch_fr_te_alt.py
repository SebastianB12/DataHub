"""Re-fetch FR TE pages using alternate URLs found via discovery."""
import json, subprocess, os, time

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

alt_urls = {
    'core-cpi': 'https://tradingeconomics.com/france/core-consumer-prices',
    'gdp-real': 'https://tradingeconomics.com/france/full-year-gdp-growth',
    'gdp-growth-rate': 'https://tradingeconomics.com/france/gdp-growth-annual',
    'house-price-index': 'https://tradingeconomics.com/france/housing-index',
    'ppi': 'https://tradingeconomics.com/france/producer-prices',
    'unemployment': 'https://tradingeconomics.com/france/unemployment-rate',
    'budget-deficit': 'https://tradingeconomics.com/france/government-budget',
    'social-security-rate-companies': 'https://tradingeconomics.com/france/social-security-rate-for-companies',
    'social-security-rate-employees': 'https://tradingeconomics.com/france/social-security-rate-for-employees',
    'cpi-food': 'https://tradingeconomics.com/france/food-inflation',
    'government-debt-total': 'https://tradingeconomics.com/france/external-debt',
    'government-spending-eur': 'https://tradingeconomics.com/france/government-spending-to-gdp',
}

out_dir = 'docs/_audit_fr_te_html'
for slug, url in alt_urls.items():
    out = os.path.join(out_dir, f'{slug}.html')
    r = subprocess.run(["curl","-s","-A",UA,"--max-time","30",url], capture_output=True, timeout=40)
    html = r.stdout.decode("utf-8", errors="ignore")
    with open(out, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'OK {slug} -> {url[-50:]} ({len(html)} bytes)')
    time.sleep(0.3)
