"""Fetch alternative TE URLs for LT stub slugs."""
import json, os, subprocess, time

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
OUT_DIR = r"C:\Users\sb\source\tradingEconomics\docs\_audit_te_html\LT"

# Map our slug -> list of candidate TE URLs to try
ALT_MAP = {
    "budget-deficit": ["government-budget", "budget"],
    "core-cpi": ["core-inflation-rate", "core-consumer-prices"],
    "credit-rating": ["rating"],
    "disposable-personal-income": ["disposable-personal-income", "personal-income"],
    "energy-inflation": ["energy-inflation", "cpi-energy"],
    "gdp-real": ["gdp-growth", "gdp-growth-rate"],
    "government-debt-total": ["government-debt"],
    "government-spending-eur": ["government-spending"],
    "house-price-index": ["housing-index"],
    "ppi": ["producer-prices", "producer-prices-change"],
    "services-inflation": ["inflation-rate-services", "cpi-services"],
    "services-sentiment": ["services-pmi", "services-pmi"],
    "social-security-rate-companies": ["social-security-rate-for-companies"],
    "social-security-rate-employees": ["social-security-rate-for-employees"],
    "unemployment": ["unemployment-rate"],
}

for slug, alts in ALT_MAP.items():
    for alt in alts:
        out_path = os.path.join(OUT_DIR, f"{slug}__alt__{alt}.html")
        if os.path.exists(out_path) and os.path.getsize(out_path) > 5000:
            continue
        url = f"https://tradingeconomics.com/lithuania/{alt}"
        try:
            r = subprocess.run(["curl", "-s", "-A", UA, "--max-time", "30", url],
                               capture_output=True, timeout=40)
            with open(out_path, "wb") as f:
                f.write(r.stdout)
            sz = len(r.stdout)
            has_src = b"source-present" in r.stdout or b"source-name" in r.stdout
            print(f"  {slug} -> {alt}: {sz} bytes, has_source={has_src}")
        except Exception as e:
            print(f"  {slug} -> {alt}: FAIL {e}")
        time.sleep(0.3)
print("Done.")
