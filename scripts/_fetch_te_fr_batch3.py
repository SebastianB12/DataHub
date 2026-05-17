"""Fetch TE pages for batch3 FR slugs in parallel."""
import subprocess, re, json, os
from concurrent.futures import ThreadPoolExecutor, as_completed

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

# slug -> te-path mapping
TE_PATHS = {
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
    "retail-sales": "retail-sales-yoy",
    "retirement-age-men": "retirement-age-men",
    "retirement-age-women": "retirement-age-women",
    "sales-tax-rate": "sales-tax-rate",
    "services-inflation": "services-inflation",
    "social-security-rate": "social-security-rate",
    "social-security-rate-companies": "social-security-rate-companies",
    "social-security-rate-employees": "social-security-rate-employees",
    "terrorism-index": "terrorism-index",
    "unemployed-persons": "unemployed-persons",
    "unemployment": "unemployment-rate",
    "weapons-sales": "weapons-sales",
    "youth-unemployment-rate": "youth-unemployment-rate",
}


def fetch(slug):
    path = TE_PATHS[slug]
    url = f"https://tradingeconomics.com/france/{path}"
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


os.makedirs("docs/_audit_te_html/fr_batch3", exist_ok=True)
results = {}
with ThreadPoolExecutor(max_workers=8) as ex:
    futs = {ex.submit(fetch, s): s for s in TE_PATHS}
    for f in as_completed(futs):
        slug, code, body = f.result()
        results[slug] = code
        with open(f"docs/_audit_te_html/fr_batch3/{slug}.html", "w", encoding="utf-8") as fp:
            fp.write(body)
        print(slug, code, len(body))
print("DONE", len(results))
with open("docs/_audit_te_html/fr_batch3/_status.json", "w") as f:
    json.dump(results, f, indent=2)
