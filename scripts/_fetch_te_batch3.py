"""Fetch TE pages for batch3 US slugs in parallel."""
import subprocess, re, json, os
from concurrent.futures import ThreadPoolExecutor, as_completed

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

# slug -> te-path mapping (from inventory)
TE_PATHS = {
    "medical-doctors": "medical-doctors",
    "michigan-inflation-expectations": "michigan-inflation-expectations",
    "military-expenditure": "military-expenditure",
    "minimum-wages": "minimum-wages",
    "mining-and-energy-payrolls": "mining-and-energy-payrolls",
    "mining-production": "mining-production",
    "money-supply-m0": "money-supply-m0",
    "money-supply-m1": "money-supply-m1",
    "money-supply-m2": "money-supply-m2",
    "natural-gas-storage": "natural-gas-storage",
    "new-home-sales": "new-home-sales",
    "new-orders": "new-orders",
    "non-farm-payrolls": "non-farm-payrolls",
    "nonfarm-payrolls-private": "nonfarm-payrolls-private",
    "nonfarm-productivity-qoq": "nonfarm-productivity-qoq",
    "nurses": "nurses",
    "ny-empire-state-manufacturing-index": "ny-empire-state-manufacturing-index",
    "part-time-employment": "part-time-employment",
    "pce-price-index": "pce-price-index",
    "personal-income": "personal-income",
    "personal-income-tax-rate": "personal-income-tax-rate",
    "personal-savings": "personal-savings",
    "personal-spending": "personal-spending",
    "philadelphia-fed-manufacturing-index": "philadelphia-fed-manufacturing-index",
    "population": "population",
    "ppi": "producer-prices",
    "ppi-ex-food-energy-trade-svcs": "ppi-ex-food-energy-trade-svcs",
    "private-debt-to-gdp": "private-debt-to-gdp",
    "private-sector-credit": "private-sector-credit",
    "productivity": "productivity",
    "professional-and-business-services-payrolls": "professional-and-business-services-payrolls",
    "real-consumer-spending": "real-consumer-spending",
    "refinery-crude-runs": "refinery-crude-runs",
    "rent-inflation": "rent-inflation",
    "retail-sales-ex-autos": "retail-sales-ex-autos",
    "retail-trade-payrolls": "retail-trade-payrolls",
    "retirement-age-men": "retirement-age-men",
    "retirement-age-women": "retirement-age-women",
    "sales-tax-rate": "sales-tax-rate",
    "secured-overnight-financing-rate": "secured-overnight-financing-rate",
    "services-inflation": "services-inflation",
    "social-security-rate": "social-security-rate",
    "social-security-rate-companies": "social-security-rate-companies",
    "social-security-rate-employees": "social-security-rate-employees",
    "steel-production": "steel-production",
    "strategic-petroleum-reserve": "strategic-petroleum-reserve",
    "terrorism-index": "terrorism-index",
    "total-housing-inventory": "total-housing-inventory",
    "total-vehicle-sales": "total-vehicle-sales",
    "trade-balance": "balance-of-trade",
    "transportation-and-warehousing-payrolls": "transportation-and-warehousing-payrolls",
    "u6-unemployment-rate": "u6-unemployment-rate",
    "unemployed-persons": "unemployed-persons",
    "unemployment": "unemployment-rate",
    "unit-labour-costs-qoq": "unit-labour-costs-qoq",
    "wages": "wages",
    "wages-in-manufacturing": "wages-in-manufacturing",
    "weapons-sales": "weapons-sales",
    "weekly-crude-oil-production": "weekly-crude-oil-production",
    "weekly-economic-index": "weekly-economic-index",
    "wholesale-inventories": "wholesale-inventories",
    "wholesale-trade-payrolls": "wholesale-trade-payrolls",
    "withholding-tax-rate": "withholding-tax-rate",
    "youth-unemployment-rate": "youth-unemployment-rate",
}


def fetch(slug):
    path = TE_PATHS[slug]
    url = f"https://tradingeconomics.com/united-states/{path}"
    try:
        r = subprocess.run(
            ["curl", "-s", "-A", UA, "--max-time", "30", "-w", "\n__HTTP__%{http_code}", url],
            capture_output=True, timeout=40,
        )
        body = r.stdout.decode("utf-8", errors="ignore")
        m = re.search(r"__HTTP__(\d+)$", body)
        code = int(m.group(1)) if m else 0
        b = body[:m.start()] if m else body
        return slug, code, b
    except Exception as e:
        return slug, 0, f"ERR: {e}"


os.makedirs("docs/_audit_te_html/batch3", exist_ok=True)
results = {}
with ThreadPoolExecutor(max_workers=8) as ex:
    futs = {ex.submit(fetch, s): s for s in TE_PATHS}
    for f in as_completed(futs):
        slug, code, body = f.result()
        results[slug] = code
        with open(f"docs/_audit_te_html/batch3/{slug}.html", "w", encoding="utf-8") as fp:
            fp.write(body)
        print(slug, code, len(body))
print("DONE", len(results))
with open("docs/_audit_te_html/batch3/_status.json", "w") as f:
    json.dump(results, f, indent=2)
