"""Fetch all TE pages for FR batch1 in parallel-ish (single curl each) and dump."""
import subprocess, re, json, os
from concurrent.futures import ThreadPoolExecutor, as_completed

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

# slug -> te path
SLUG_TO_TE = {
    "budget-deficit": "government-budget",
    "business-confidence": "business-confidence",
    "capacity-utilization": "capacity-utilization",
    "changes-in-inventories": "changes-in-inventories",
    "consumer-confidence": "consumer-confidence",
    "consumer-spending": "consumer-spending",
    "core-cpi": "core-inflation-rate",
    "corporate-tax-rate": "corporate-tax-rate",
    "corruption-index": "corruption-index",
    "corruption-rank": "corruption-rank",
    "cpi-clothing": "cpi-clothing",
    "cpi-education": "cpi-education",
    "cpi-food": "cpi-food",
    "cpi-housing-utilities": "cpi-housing-utilities",
    "cpi-recreation-and-culture": "cpi-recreation-and-culture",
    "cpi-transportation": "cpi-transportation",
    "credit-rating": "rating",
    "current-account": "current-account",
    "current-account-to-gdp": "current-account-to-gdp",
    "disposable-personal-income": "disposable-personal-income",
    "employed-persons": "employed-persons",
    "employment-rate": "employment-rate",
}

OUT_DIR = "docs/_audit_te_html/FR"
os.makedirs(OUT_DIR, exist_ok=True)

def fetch(slug, te_slug):
    url = f"https://tradingeconomics.com/france/{te_slug}"
    r = subprocess.run(["curl","-s","-A",UA,"--max-time","30","-w","\n__HTTP__%{http_code}",url],
                       capture_output=True, timeout=40)
    body = r.stdout.decode("utf-8", errors="ignore")
    m = re.search(r"__HTTP__(\d+)$", body)
    code = int(m.group(1)) if m else 0
    html = body[:m.start()] if m else body
    with open(f"{OUT_DIR}/{slug}.html", "w", encoding="utf-8") as f:
        f.write(html)
    return slug, code, len(html)

with ThreadPoolExecutor(max_workers=8) as ex:
    futs = [ex.submit(fetch, s, t) for s, t in SLUG_TO_TE.items()]
    for f in as_completed(futs):
        slug, code, ln = f.result()
        print(f"{slug:40s} {code} {ln}")
