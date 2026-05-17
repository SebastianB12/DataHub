"""Re-fetch remaining FALLBACK HU slugs."""
import os
import subprocess
import concurrent.futures

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
OUT = "docs/_audit_te_html/hu_reaudit"

VARIANTS = {
    "cpi-clothing": [
        "cpi-clothing", "clothing-cpi", "consumer-prices-clothing",
        "clothing-and-footwear", "cpi-clothing-and-footwear",
    ],
    "cpi-education": [
        "cpi-education", "education-cpi", "consumer-prices-education",
    ],
    "cpi-food": [
        "cpi-food", "food-cpi", "consumer-prices-food",
        "consumer-prices-food-and-non-alcoholic-beverages",
    ],
    "cpi-housing-utilities": [
        "cpi-housing-utilities", "housing-cpi", "cpi-housing",
        "consumer-prices-housing-water-electricity-gas-and-other-fuels",
        "consumer-prices-housing",
    ],
    "cpi-recreation-and-culture": [
        "cpi-recreation-and-culture", "cpi-recreation",
        "consumer-prices-recreation-and-culture",
    ],
    "credit-rating": [
        "credit-rating", "rating", "sovereign-credit-rating",
    ],
    "disposable-personal-income": [
        "disposable-personal-income", "disposable-income",
        "personal-disposable-income", "household-disposable-income",
    ],
    "energy-inflation": [
        "energy-inflation", "energy-cpi", "energy-prices",
        "consumer-prices-energy",
    ],
    "government-debt-total": [
        "government-debt", "central-government-debt",
        "general-government-gross-debt",
    ],
    "medical-doctors": [
        "medical-doctors", "doctors", "physicians",
    ],
    "nurses": [
        "nurses", "nursing-and-midwifery-personnel",
    ],
    "services-inflation": [
        "services-inflation", "services-cpi", "consumer-prices-services",
    ],
    "services-sentiment": [
        "services-sentiment", "services-pmi", "services-confidence",
        "service-sentiment",
    ],
    "social-security-rate-companies": [
        "social-security-rate-for-companies", "ssc-companies",
    ],
    "social-security-rate-employees": [
        "social-security-rate-for-employees", "ssc-employees",
    ],
}


def fetch(args):
    slug, variants = args
    for v in variants:
        url = f"https://tradingeconomics.com/hungary/{v}"
        r = subprocess.run(
            ["curl", "-s", "-A", UA, "--max-time", "30", url],
            capture_output=True, timeout=40,
        )
        body = r.stdout
        text = body.decode("utf-8", errors="ignore")
        fallback = "TRADING ECONOMICS | 20 Million" in text[:1500]
        has_source = "source-name" in text or "source-present" in text
        if has_source and not fallback:
            path = f"{OUT}/{slug}.html"
            with open(path, "wb") as f:
                f.write(body)
            return slug, v, "saved"
    return slug, None, "all_failed"


with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
    for slug, v, status in ex.map(fetch, VARIANTS.items()):
        print(f"{slug:<35} {status:<12} via={v}")
