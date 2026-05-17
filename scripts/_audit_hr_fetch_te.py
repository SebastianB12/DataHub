"""Fetch all TE pages for HR re-audit. Map slug -> TE path-name."""
import subprocess, pathlib, time, sys

# slug -> TE URL slug under /croatia/
TE_PATHS = {
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
    "energy-inflation": "energy-inflation",
    "exports": "exports",
    "food-inflation": "food-inflation",
    "gdp": "gdp",
    "gdp-per-capita": "gdp-per-capita",
    "gdp-per-capita-ppp": "gdp-per-capita-ppp",
    "gdp-real": "gdp-growth-annual",
    "government-debt": "government-debt",
    "government-debt-total": "government-debt-to-gdp",
    "government-spending": "government-spending",
    "government-spending-eur": "government-spending-value",
    "gross-fixed-capital-formation": "gross-fixed-capital-formation",
    "hospital-beds": "hospital-beds",
    "house-price-index": "housing-index",
    "imports": "imports",
    "industrial-production": "industrial-production",
    "inflation-cpi": "inflation-cpi",
    "interest-rate": "interest-rate",
    "job-vacancies": "job-vacancies",
    "labor-force-participation-rate": "labor-force-participation-rate",
    "labour-costs": "labour-costs",
    "long-term-unemployment-rate": "long-term-unemployment-rate",
    "manufacturing-production": "manufacturing-production",
    "medical-doctors": "medical-doctors",
    "minimum-wages": "minimum-wages",
    "mining-production": "mining-production",
    "nurses": "nurses",
    "personal-income-tax-rate": "personal-income-tax-rate",
    "population": "population",
    "ppi": "producer-prices",
    "productivity": "productivity",
    "retail-sales": "retail-sales-annual",
    "retirement-age-men": "retirement-age-men",
    "retirement-age-women": "retirement-age-women",
    "sales-tax-rate": "sales-tax-rate",
    "services-inflation": "services-inflation",
    "services-sentiment": "services-sentiment",
    "social-security-rate": "social-security-rate",
    "social-security-rate-companies": "social-security-rate-for-companies",
    "social-security-rate-employees": "social-security-rate-for-employees",
    "terrorism-index": "terrorism-index",
    "unemployed-persons": "unemployed-persons",
    "unemployment": "unemployment-rate",
    "youth-unemployment-rate": "youth-unemployment-rate",
}

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
OUT = pathlib.Path("docs/_audit_te_html/HR")
OUT.mkdir(parents=True, exist_ok=True)

force = "--force" in sys.argv
slugs = sorted(TE_PATHS.keys())
for slug in slugs:
    path = TE_PATHS[slug]
    out = OUT / f"{slug}.html"
    if out.exists() and out.stat().st_size > 5000 and not force:
        print(f"SKIP {slug} (cached)")
        continue
    url = f"https://tradingeconomics.com/croatia/{path}"
    r = subprocess.run(
        ["curl", "-s", "-A", UA, "--max-time", "30", "-L", url],
        capture_output=True, timeout=45,
    )
    body = r.stdout
    out.write_bytes(body)
    print(f"OK   {slug:35} {len(body):>8} bytes")
    time.sleep(0.6)
print("DONE")
