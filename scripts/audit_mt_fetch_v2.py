"""Fetch fresh TE HTML for MT — round 2 with correct slug overrides."""
import json, os, sys, io, subprocess
import concurrent.futures as cf
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

# Confirmed TE slug overrides for MT (from /malta/indicators inventory)
TE_SLUG_OVERRIDES = {
    "budget-deficit": "government-budget",
    "gdp-real": "gdp-growth-annual",
    "government-debt-total": "government-debt",
    "house-price-index": "housing-index",
    "ppi": "producer-prices",
    "trade-balance": "balance-of-trade",
    "unemployment": "unemployment-rate",
    "government-spending-eur": "government-spending",  # MT uses single slug
    "social-security-rate-companies": "social-security-rate-for-companies",
    "social-security-rate-employees": "social-security-rate-for-employees",
    "credit-rating": "rating",
    # MT-specific: TE only has retail-sales, not retail-sales-yoy
    "retail-sales": "retail-sales",
}

# slugs that simply do not exist on TE for Malta
NOT_ON_TE = {
    "core-cpi",
    "disposable-personal-income",
    "energy-inflation",
    "hospital-beds",
    "job-vacancies",
    "medical-doctors",
    "nurses",
    "services-inflation",
    "services-sentiment",
    "terrorism-index",
}

OUT_DIR = "docs/_audit_te_html/MT"
os.makedirs(OUT_DIR, exist_ok=True)

slugs = json.load(open("docs/_audit_all_remaining_slugs.json"))["MT"]
print(f"Refetching {len(slugs)} MT TE pages with correct slugs")

def fetch(slug):
    if slug in NOT_ON_TE:
        return slug, "not_on_te", 0
    te_slug = TE_SLUG_OVERRIDES.get(slug, slug)
    url = f"https://tradingeconomics.com/malta/{te_slug}"
    out_path = os.path.join(OUT_DIR, slug + ".html")
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

ok = sum(1 for _, st, _ in results if st == "ok")
nt = sum(1 for _, st, _ in results if st == "not_on_te")
print(f"\nDone: {ok} ok, {nt} not_on_te, {len(slugs)-ok-nt} fail")
for s, st, sz in sorted(results):
    if st not in ("ok", "not_on_te"):
        print(f"  FAIL {s}: {st} ({sz})")
