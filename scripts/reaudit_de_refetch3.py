"""Re-fetch DE slugs with corrected TE URL slugs."""
import json
import re
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
HTML_DIR = ROOT / "docs" / "_audit_te_html" / "de_reaudit"

SLUG_TO_TEPATH = {
    "budget-deficit": "government-budget",
    "central-bank-balance": "central-bank-balance-sheet",
    "core-cpi": "core-consumer-prices",
    "credit-rating": "rating",
    "gdp-real": "gdp-growth-annual",
    "government-debt-total": "government-debt",
    "government-spending-eur": "government-spending",
    "hospital-beds": "hospitals",  # try the indicator listing
    "hospitals": "number-of-hospitals",
    "house-price-index": "housing-index",
    "nurses": "nurses",
    "ppi": "producer-prices",
    "social-security-rate-companies": "social-security-rate-for-companies",
    "social-security-rate-employees": "social-security-rate-for-employees",
    "trade-balance": "balance-of-trade",
    "unemployment": "unemployment-rate",
}

sess = requests.Session()
H = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

for slug, tepath in SLUG_TO_TEPATH.items():
    url = f"https://tradingeconomics.com/germany/{tepath}"
    out = HTML_DIR / f"{slug}.html"
    try:
        r = sess.get(url, headers=H, timeout=40)
        size = len(r.content)
        out.write_bytes(r.content)
        has_src = "source-name" in r.text
        print(f"  {slug:40s} {tepath:40s} {size:>7d} bytes src={has_src}")
    except Exception as e:
        print(f"  {slug:40s} ERR: {e}")
    time.sleep(1.0)

print("Done.")
