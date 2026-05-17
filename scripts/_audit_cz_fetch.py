"""Fetch all CZ TE pages for re-audit."""
import os, sys, subprocess, json, time, pathlib

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

SLUG_TO_TE = {
    "inflation-cpi": "inflation-cpi",
    "core-cpi": "core-inflation-rate",
    "ppi": "producer-prices",
    "industrial-production": "industrial-production",
    "manufacturing-production": "manufacturing-production",
    "mining-production": "mining-production",
    "unemployment": "unemployment-rate",
    "employed-persons": "employed-persons",
    "unemployed-persons": "unemployed-persons",
    "employment-rate": "employment-rate",
    "labor-force-participation-rate": "labor-force-participation-rate",
    "youth-unemployment-rate": "youth-unemployment-rate",
    "long-term-unemployment-rate": "long-term-unemployment-rate",
    "job-vacancies": "job-vacancies",
    "labour-costs": "labour-costs",
    "minimum-wages": "minimum-wages",
    "retail-sales": "retail-sales-yoy",
    "consumer-spending": "consumer-spending",
    "consumer-confidence": "consumer-confidence",
    "business-confidence": "business-confidence",
    "capacity-utilization": "capacity-utilization",
    "changes-in-inventories": "changes-in-inventories",
    "gdp-real": "gdp-growth-annual",
    "gdp": "gdp",
    "gdp-per-capita": "gdp-per-capita",
    "gdp-per-capita-ppp": "gdp-per-capita-ppp",
    "gross-fixed-capital-formation": "gross-fixed-capital-formation",
    "government-spending": "government-spending",
    "government-spending-eur": "government-spending",
    "government-debt": "government-debt",
    "government-debt-total": "government-debt-to-gdp",
    "current-account": "current-account",
    "current-account-to-gdp": "current-account-to-gdp",
    "exports": "exports",
    "imports": "imports",
    "budget-deficit": "government-budget",
    "population": "population",
    "food-inflation": "food-inflation",
    "services-inflation": "services-inflation",
    "energy-inflation": "energy-inflation",
    "cpi-food": "cpi-food",
    "cpi-clothing": "cpi-clothing",
    "cpi-housing-utilities": "cpi-housing-utilities",
    "cpi-transportation": "cpi-transportation",
    "cpi-recreation-and-culture": "cpi-recreation-and-culture",
    "cpi-education": "cpi-education",
    "disposable-personal-income": "disposable-personal-income",
    "corporate-tax-rate": "corporate-tax-rate",
    "personal-income-tax-rate": "personal-income-tax-rate",
    "sales-tax-rate": "sales-tax-rate",
    "social-security-rate": "social-security-rate",
    "social-security-rate-companies": "social-security-rate-companies",
    "social-security-rate-employees": "social-security-rate-employees",
    "corruption-index": "corruption-index",
    "corruption-rank": "corruption-rank",
    "credit-rating": "rating",
    "hospital-beds": "hospital-beds",
    "house-price-index": "housing-index",
    "medical-doctors": "medical-doctors",
    "nurses": "nurses",
    "terrorism-index": "terrorism-index",
    "retirement-age-men": "retirement-age-men",
    "retirement-age-women": "retirement-age-women",
    "services-sentiment": "services-sentiment",
    "productivity": "productivity",
}


def fetch(slug, te_slug):
    out = pathlib.Path(f"docs/_audit_te_html/CZ/{slug}.html")
    if out.exists() and out.stat().st_size > 1000:
        return "cached"
    url = f"https://tradingeconomics.com/czech-republic/{te_slug}"
    r = subprocess.run(
        ["curl", "-s", "-A", UA, "--max-time", "30", url],
        capture_output=True, timeout=40)
    out.write_bytes(r.stdout)
    return f"fetched {len(r.stdout)} bytes"


def main():
    with open("docs/_audit_all_remaining_slugs.json", encoding="utf-8") as f:
        slugs = json.load(f)["CZ"]
    for i, s in enumerate(slugs):
        te = SLUG_TO_TE.get(s, s)
        try:
            r = fetch(s, te)
            print(f"[{i+1}/{len(slugs)}] {s} -> {te}: {r}")
        except Exception as e:
            print(f"[{i+1}/{len(slugs)}] {s} -> {te}: ERR {e}")
        time.sleep(0.5)


if __name__ == "__main__":
    main()
