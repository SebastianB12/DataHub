"""Re-fetch failed HU slugs using TE-variant names."""
import json
import os
import subprocess
import concurrent.futures

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
OUT = "docs/_audit_te_html/hu_reaudit"

# Map econPulse slug -> list of TE URL variants to try
VARIANTS = {
    "budget-deficit": ["government-budget"],
    "business-confidence": ["business-confidence-survey"],
    "consumer-confidence": ["consumer-confidence-survey", "consumer-confidence-index"],
    "core-cpi": ["core-inflation-rate", "core-consumer-prices", "core-cpi-rate"],
    "corruption-index": ["corruption-index"],
    "corruption-rank": ["corruption-rank"],
    "cpi-clothing": ["cpi-clothing-footwear"],
    "cpi-education": ["cpi-education"],
    "cpi-food": ["cpi-food"],
    "cpi-housing-utilities": ["cpi-housing-utilities"],
    "cpi-recreation-and-culture": ["cpi-recreation-and-culture"],
    "credit-rating": ["rating"],
    "disposable-personal-income": ["disposable-personal-income"],
    "energy-inflation": ["energy-inflation"],
    "gdp-real": ["gdp-growth-annual", "real-gdp"],
    "government-debt-total": ["government-debt"],
    "government-debt": ["government-debt-to-gdp"],
    "government-spending-eur": ["government-spending"],
    "hospital-beds": ["hospital-beds"],
    "house-price-index": ["housing-index"],
    "medical-doctors": ["medical-doctors"],
    "nurses": ["nurses"],
    "ppi": ["producer-prices", "producer-prices-change"],
    "services-inflation": ["services-inflation"],
    "services-sentiment": ["services-sentiment"],
    "social-security-rate-companies": ["social-security-rate-for-companies"],
    "social-security-rate-employees": ["social-security-rate-for-employees"],
    "social-security-rate": ["social-security-rate"],
    "terrorism-index": ["terrorism-index"],
    "trade-balance": ["balance-of-trade"],
    "unemployment": ["unemployment-rate"],
    "youth-unemployment-rate": ["youth-unemployment-rate"],
}


def fetch(args):
    slug, variants = args
    results = []
    for v in variants:
        url = f"https://tradingeconomics.com/hungary/{v}"
        r = subprocess.run(
            ["curl", "-s", "-A", UA, "--max-time", "30", url],
            capture_output=True, timeout=40,
        )
        body = r.stdout
        text = body.decode("utf-8", errors="ignore")
        fallback = "TRADING ECONOMICS | 20 Million" in text[:1500]
        has_source = "source-name" in text
        if has_source and not fallback:
            # Save under canonical slug
            path = f"{OUT}/{slug}.html"
            with open(path, "wb") as f:
                f.write(body)
            return slug, v, "saved", len(body)
        results.append((v, has_source, fallback, len(body)))
    return slug, None, "all_failed", results


with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
    for slug, v, status, info in ex.map(fetch, VARIANTS.items()):
        if status == "saved":
            print(f"{slug:<35} OK via '{v}' ({info} bytes)")
        else:
            print(f"{slug:<35} FAIL: {info}")
