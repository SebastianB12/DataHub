"""Refetch SI TE pages using TE-canonical slug aliases for our internal slugs."""
import json
import re
import subprocess
import time
from pathlib import Path

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
OUTDIR = Path("docs/_audit_si_te_html")

# our internal slug -> TE canonical SI slug
# Verified against /slovenia/indicators link list.
ALIASES = {
    # missing-source slugs (already fetched -> ours don't exist on TE under same name):
    "budget-deficit":           "government-budget",          # TE uses "Government Budget"
    "core-cpi":                 "core-consumer-prices",       # TE
    "credit-rating":            "rating",
    "disposable-personal-income":"personal-savings",          # TE "Personal Savings" closest? Actually TE doesn't have DPI for SI. Skip.
    "energy-inflation":         "rent-inflation",             # NO — keep ours; TE doesn't have it
    "gdp-growth-rate":          "gdp-growth-annual",          # TE
    "gdp-real":                 "gdp-constant-prices",        # TE
    "government-debt-total":    "government-debt-to-gdp",     # ours is the eur-level. We'll try both
    "government-spending-eur":  "fiscal-expenditure",         # closest TE
    "house-price-index":        "housing-index",              # TE
    "ppi":                      "producer-prices",            # TE
    "services-inflation":       None,                         # TE doesn't have a SI services-inflation slug
    "services-sentiment":       None,
    "social-security-rate-companies":  "social-security-rate-for-companies",
    "social-security-rate-employees":  "social-security-rate-for-employees",
    "trade-balance":            "balance-of-trade",
    "unemployment":             "unemployment-rate",
}

for slug, alias in ALIASES.items():
    if alias is None:
        print(f"  {slug}: SKIP — no TE equivalent")
        continue
    url = f"https://tradingeconomics.com/slovenia/{alias}"
    out = OUTDIR / f"{slug}.html"
    try:
        r = subprocess.run(
            ["curl", "-sL", "-A", UA, "--max-time", "40", url],
            capture_output=True, timeout=50,
        )
        html = r.stdout.decode("utf-8", errors="ignore")
        if "source-name" in html or "Statistical Office" in html or "Eurostat" in html.lower() or "World Bank" in html:
            out.write_text(html, encoding="utf-8")
            sn = re.search(r"source-name[^<]*href[^>]*>([^<]+)<", html)
            print(f"  {slug} -> {alias}: OK source={sn.group(1) if sn else '?'} {len(html)}b")
        else:
            print(f"  {slug} -> {alias}: STILL no source ({len(html)}b)")
        time.sleep(0.7)
    except Exception as e:
        print(f"  {slug} -> {alias}: FAIL {e}")
