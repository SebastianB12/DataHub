"""Fetch fresh TE HTML for all 67 MT slugs in parallel."""
import json, os, sys, io, time
import concurrent.futures as cf
import subprocess
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

# TE slug overrides (where the EconPulse slug differs from TE URL slug)
TE_SLUG_OVERRIDES = {
    "budget-deficit": "government-budget",
    "core-cpi": "core-inflation-rate",
    "gdp-real": "gdp-growth-annual",
    "government-debt-total": "government-debt",
    "house-price-index": "housing-index",
    "ppi": "producer-prices",
    "retail-sales": "retail-sales-yoy",
    "trade-balance": "balance-of-trade",
    "unemployment": "unemployment-rate",
    "energy-inflation": "energy-inflation",
    "services-inflation": "services-inflation",
    "food-inflation": "food-inflation",
    "long-term-unemployment-rate": "long-term-unemployment-rate",
    "labor-force-participation-rate": "labor-force-participation-rate",
    "job-vacancies": "job-vacancies",
}

OUT_DIR = "docs/_audit_te_html/MT"
os.makedirs(OUT_DIR, exist_ok=True)

slugs = json.load(open("docs/_audit_all_remaining_slugs.json"))["MT"]
print(f"Fetching {len(slugs)} MT TE pages")

def fetch(slug):
    te_slug = TE_SLUG_OVERRIDES.get(slug, slug)
    url = f"https://tradingeconomics.com/malta/{te_slug}"
    out_path = os.path.join(OUT_DIR, slug + ".html")
    if os.path.exists(out_path) and os.path.getsize(out_path) > 5000:
        return slug, "cached", len(open(out_path, encoding="utf-8", errors="ignore").read())
    try:
        r = subprocess.run(
            ["curl", "-s", "-A", UA, "--max-time", "30", url],
            capture_output=True, timeout=40
        )
        html = r.stdout.decode("utf-8", errors="ignore")
        if len(html) < 2000:
            return slug, "short", len(html)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)
        return slug, "ok", len(html)
    except Exception as e:
        return slug, f"err:{e}", 0

results = []
with cf.ThreadPoolExecutor(max_workers=6) as ex:
    futs = {ex.submit(fetch, s): s for s in slugs}
    for f in cf.as_completed(futs):
        results.append(f.result())

ok = sum(1 for _, st, _ in results if st in ("ok", "cached"))
print(f"\nDone: {ok}/{len(slugs)} ok")
for s, st, sz in sorted(results):
    if st not in ("ok", "cached"):
        print(f"  FAIL {s}: {st} ({sz})")
