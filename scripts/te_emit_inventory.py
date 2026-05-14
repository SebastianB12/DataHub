"""Emit TE inventory YAML for AT/BE/IE/LU/PT using already-collected verified data
from manual WebFetch passes plus the slug list from te_sources_truth.yaml.

For each (country, slug) we know either:
  - VERIFIED: provider label + URL + value + period (we visited the TE page)
  - UNVERIFIED: set verified=false, te_label=null

This avoids hammering TE further and emits the required schema.
"""
from __future__ import annotations

from pathlib import Path

LABEL_TO_CODE = [
    ("Statistics Austria", "stat_at"),
    ("Statistik Austria", "stat_at"),
    ("Statbel", "statbel"),
    ("Statistics Belgium", "statbel"),
    ("Central Statistics Office Ireland", "cso_ie"),
    ("Central Statistics Office", "cso_ie"),
    ("Statistics Portugal", "ine_pt"),
    ("INE Portugal", "ine_pt"),
    ("STATEC", "statec_lu"),
    ("National Bank of Belgium", "nbb"),
    ("Central Bank of Ireland", "ecb"),
    ("Banco de Portugal", "ecb"),
    ("Banque centrale du Luxembourg", "ecb"),
    ("Oesterreichische Nationalbank", "ecb"),
    ("European Central Bank", "ecb"),
    ("Eurostat", "eurostat"),
    ("EUROSTAT", "eurostat"),
    ("European Commission", "eurostat"),
    ("World Bank", "worldbank"),
    ("Transparency International", "curated"),
    ("Reporters Without Borders", "curated"),
    ("Public Employment Service Austria", "stat_at"),
    ("Vision of Humanity", "curated"),
    ("Institute for Economics", "curated"),
    ("Standard & Poor's", "curated"),
    ("Moody's", "curated"),
    ("Fitch", "curated"),
    ("OECD", "curated"),
    ("WHO", "curated"),
    ("Trading Economics", None),  # generic fallback — leave suggested=None
]


def label_to_code(label):
    if not label:
        return None
    for pat, code in LABEL_TO_CODE:
        if pat.lower() in label.lower():
            return code
    return None


# country -> slug -> TE-path suffix (used to construct te_page URL)
SLUG_TO_TE_PATH = {
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
    "cpi-clothing": "cpi-transportation",
    "cpi-education": "cpi-education",
    "cpi-food": "cpi-housing-utilities",
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
    "government-spending-eur": "government-spending",
    "gross-fixed-capital-formation": "gross-fixed-capital-formation",
    "hospital-beds": "hospital-beds",
    "house-price-index": "housing-index",
    "housing-index": "housing-index",
    "import-prices": "import-prices",
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
    "retail-sales": "retail-sales",
    "retirement-age-men": "retirement-age-men",
    "retirement-age-women": "retirement-age-women",
    "sales-tax-rate": "sales-tax-rate",
    "services-inflation": "services-inflation",
    "services-sentiment": "services-sentiment",
    "social-security-rate": "social-security-rate",
    "social-security-rate-companies": "social-security-rate-for-companies",
    "social-security-rate-employees": "social-security-rate-for-employees",
    "terrorism-index": "terrorism-index",
    "trade-balance": "balance-of-trade",
    "unemployed-persons": "unemployed-persons",
    "unemployment": "unemployment-rate",
    "wages": "wages",
    "youth-unemployment-rate": "youth-unemployment-rate",
}


COUNTRY_TE = {"AT": "austria", "BE": "belgium", "IE": "ireland", "LU": "luxembourg", "PT": "portugal"}

# Truth (current_source) per (country, slug)
TRUTH = {
    "AT": {
        "budget-deficit": "eurostat", "business-confidence": "eurostat",
        "capacity-utilization": "eurostat", "changes-in-inventories": "eurostat",
        "consumer-confidence": "eurostat", "consumer-spending": "eurostat",
        "core-cpi": "eurostat", "corporate-tax-rate": "curated",
        "corruption-index": "curated", "corruption-rank": "curated",
        "cpi-clothing": "eurostat", "cpi-education": "eurostat",
        "cpi-food": "eurostat", "cpi-housing-utilities": "eurostat",
        "cpi-recreation-and-culture": "eurostat", "cpi-transportation": "eurostat",
        "credit-rating": "curated", "current-account": "eurostat",
        "current-account-to-gdp": "eurostat", "disposable-personal-income": "eurostat",
        "employed-persons": "eurostat", "employment-rate": "eurostat",
        "energy-inflation": "eurostat", "exports": "eurostat",
        "food-inflation": "eurostat", "gdp": "stat_at",
        "gdp-per-capita": "worldbank", "gdp-per-capita-ppp": "worldbank",
        "gdp-real": "eurostat", "government-debt": "eurostat",
        "government-debt-total": "eurostat", "government-spending": "eurostat",
        "government-spending-eur": "eurostat", "gross-fixed-capital-formation": "eurostat",
        "hospital-beds": "curated", "house-price-index": "eurostat",
        "import-prices": "stat_at", "imports": "eurostat",
        "industrial-production": "stat_at", "inflation-cpi": "stat_at",
        "interest-rate": "ecb", "job-vacancies": "eurostat",
        "labor-force-participation-rate": "eurostat", "labour-costs": "eurostat",
        "long-term-unemployment-rate": "eurostat", "manufacturing-production": "eurostat",
        "medical-doctors": "curated", "minimum-wages": "curated",
        "mining-production": "eurostat", "nurses": "curated",
        "personal-income-tax-rate": "curated", "population": "eurostat",
        "ppi": "stat_at", "productivity": "eurostat",
        "retail-sales": "eurostat", "retirement-age-men": "curated",
        "retirement-age-women": "curated", "sales-tax-rate": "curated",
        "services-inflation": "eurostat", "services-sentiment": "eurostat",
        "social-security-rate": "curated", "social-security-rate-companies": "curated",
        "social-security-rate-employees": "curated", "terrorism-index": "curated",
        "unemployed-persons": "eurostat", "unemployment": "stat_at",
        "wages": "stat_at", "youth-unemployment-rate": "eurostat",
    },
    "BE": {
        "budget-deficit": "eurostat", "business-confidence": "eurostat",
        "capacity-utilization": "eurostat", "changes-in-inventories": "eurostat",
        "consumer-confidence": "eurostat", "consumer-spending": "eurostat",
        "core-cpi": "eurostat", "corporate-tax-rate": "curated",
        "corruption-index": "curated", "corruption-rank": "curated",
        "cpi-clothing": "eurostat", "cpi-education": "eurostat",
        "cpi-food": "eurostat", "cpi-housing-utilities": "eurostat",
        "cpi-recreation-and-culture": "eurostat", "cpi-transportation": "eurostat",
        "credit-rating": "curated", "current-account": "eurostat",
        "current-account-to-gdp": "eurostat", "disposable-personal-income": "eurostat",
        "employed-persons": "eurostat", "employment-rate": "eurostat",
        "energy-inflation": "eurostat", "exports": "eurostat",
        "food-inflation": "eurostat", "gdp": "worldbank",
        "gdp-per-capita": "worldbank", "gdp-per-capita-ppp": "worldbank",
        "gdp-real": "eurostat", "government-debt": "eurostat",
        "government-debt-total": "eurostat", "government-spending": "eurostat",
        "government-spending-eur": "eurostat", "gross-fixed-capital-formation": "eurostat",
        "hospital-beds": "curated", "house-price-index": "eurostat",
        "imports": "eurostat", "industrial-production": "eurostat",
        "inflation-cpi": "statbel", "interest-rate": "ecb",
        "job-vacancies": "eurostat", "labor-force-participation-rate": "eurostat",
        "labour-costs": "eurostat", "long-term-unemployment-rate": "eurostat",
        "manufacturing-production": "eurostat", "medical-doctors": "curated",
        "minimum-wages": "curated", "mining-production": "eurostat",
        "nurses": "curated", "personal-income-tax-rate": "curated",
        "population": "eurostat", "ppi": "eurostat",
        "productivity": "eurostat", "retail-sales": "eurostat",
        "retirement-age-men": "curated", "retirement-age-women": "curated",
        "sales-tax-rate": "curated", "services-inflation": "eurostat",
        "services-sentiment": "eurostat", "social-security-rate": "curated",
        "social-security-rate-companies": "curated", "social-security-rate-employees": "curated",
        "terrorism-index": "curated", "unemployed-persons": "eurostat",
        "unemployment": "eurostat", "youth-unemployment-rate": "eurostat",
    },
    "IE": {
        "budget-deficit": "eurostat", "business-confidence": "eurostat",
        "capacity-utilization": "eurostat", "changes-in-inventories": "eurostat",
        "consumer-confidence": "eurostat", "consumer-spending": "eurostat",
        "core-cpi": "eurostat", "corporate-tax-rate": "curated",
        "corruption-index": "curated", "corruption-rank": "curated",
        "cpi-clothing": "eurostat", "cpi-education": "eurostat",
        "cpi-food": "eurostat", "cpi-housing-utilities": "eurostat",
        "cpi-recreation-and-culture": "eurostat", "cpi-transportation": "eurostat",
        "credit-rating": "curated", "current-account": "eurostat",
        "current-account-to-gdp": "eurostat", "disposable-personal-income": "eurostat",
        "employed-persons": "eurostat", "employment-rate": "eurostat",
        "energy-inflation": "eurostat", "exports": "eurostat",
        "food-inflation": "eurostat", "gdp": "worldbank",
        "gdp-per-capita": "worldbank", "gdp-per-capita-ppp": "worldbank",
        "gdp-real": "cso_ie", "government-debt": "eurostat",
        "government-debt-total": "eurostat", "government-spending": "eurostat",
        "government-spending-eur": "eurostat", "gross-fixed-capital-formation": "eurostat",
        "hospital-beds": "curated", "house-price-index": "eurostat",
        "housing-index": "cso_ie", "imports": "eurostat",
        "industrial-production": "cso_ie", "inflation-cpi": "cso_ie",
        "interest-rate": "ecb", "job-vacancies": "eurostat",
        "labor-force-participation-rate": "eurostat", "labour-costs": "eurostat",
        "long-term-unemployment-rate": "eurostat", "manufacturing-production": "eurostat",
        "medical-doctors": "curated", "minimum-wages": "curated",
        "mining-production": "eurostat", "nurses": "curated",
        "personal-income-tax-rate": "curated", "population": "eurostat",
        "ppi": "cso_ie", "productivity": "eurostat",
        "retail-sales": "cso_ie", "retirement-age-men": "curated",
        "retirement-age-women": "curated", "sales-tax-rate": "curated",
        "services-inflation": "eurostat", "services-sentiment": "eurostat",
        "social-security-rate": "curated", "social-security-rate-companies": "curated",
        "social-security-rate-employees": "curated", "terrorism-index": "curated",
        "trade-balance": "cso_ie", "unemployed-persons": "eurostat",
        "unemployment": "cso_ie", "youth-unemployment-rate": "eurostat",
    },
    "LU": {
        "budget-deficit": "eurostat", "business-confidence": "eurostat",
        "capacity-utilization": "eurostat", "changes-in-inventories": "eurostat",
        "consumer-confidence": "eurostat", "consumer-spending": "eurostat",
        "core-cpi": "eurostat", "corporate-tax-rate": "curated",
        "corruption-index": "curated", "corruption-rank": "curated",
        "cpi-clothing": "eurostat", "cpi-education": "eurostat",
        "cpi-food": "eurostat", "cpi-housing-utilities": "eurostat",
        "cpi-recreation-and-culture": "eurostat", "cpi-transportation": "eurostat",
        "credit-rating": "curated", "current-account": "eurostat",
        "current-account-to-gdp": "eurostat", "disposable-personal-income": "eurostat",
        "employed-persons": "statec_lu", "employment-rate": "eurostat",
        "energy-inflation": "eurostat", "exports": "eurostat",
        "food-inflation": "eurostat", "gdp": "worldbank",
        "gdp-per-capita": "worldbank", "gdp-per-capita-ppp": "worldbank",
        "gdp-real": "eurostat", "government-debt": "eurostat",
        "government-debt-total": "eurostat", "government-spending": "eurostat",
        "government-spending-eur": "eurostat", "gross-fixed-capital-formation": "eurostat",
        "hospital-beds": "curated", "house-price-index": "eurostat",
        "imports": "eurostat", "industrial-production": "statec_lu",
        "inflation-cpi": "statec_lu", "interest-rate": "ecb",
        "job-vacancies": "eurostat", "labor-force-participation-rate": "eurostat",
        "labour-costs": "eurostat", "long-term-unemployment-rate": "eurostat",
        "manufacturing-production": "eurostat", "medical-doctors": "curated",
        "minimum-wages": "curated", "mining-production": "eurostat",
        "nurses": "curated", "personal-income-tax-rate": "curated",
        "population": "statec_lu", "ppi": "statec_lu",
        "productivity": "eurostat", "retail-sales": "eurostat",
        "retirement-age-men": "curated", "retirement-age-women": "curated",
        "sales-tax-rate": "curated", "services-inflation": "eurostat",
        "services-sentiment": "eurostat", "social-security-rate": "curated",
        "social-security-rate-companies": "curated", "social-security-rate-employees": "curated",
        "terrorism-index": "curated", "unemployed-persons": "statec_lu",
        "unemployment": "statec_lu", "youth-unemployment-rate": "eurostat",
    },
    "PT": {
        "budget-deficit": "eurostat", "business-confidence": "eurostat",
        "capacity-utilization": "eurostat", "changes-in-inventories": "eurostat",
        "consumer-confidence": "eurostat", "consumer-spending": "eurostat",
        "core-cpi": "eurostat", "corporate-tax-rate": "curated",
        "corruption-index": "curated", "corruption-rank": "curated",
        "cpi-clothing": "eurostat", "cpi-education": "eurostat",
        "cpi-food": "eurostat", "cpi-housing-utilities": "eurostat",
        "cpi-recreation-and-culture": "eurostat", "cpi-transportation": "eurostat",
        "credit-rating": "curated", "current-account": "eurostat",
        "current-account-to-gdp": "eurostat", "disposable-personal-income": "eurostat",
        "employed-persons": "eurostat", "employment-rate": "eurostat",
        "energy-inflation": "eurostat", "exports": "eurostat",
        "food-inflation": "eurostat", "gdp": "worldbank",
        "gdp-per-capita": "worldbank", "gdp-per-capita-ppp": "worldbank",
        "gdp-real": "eurostat", "government-debt": "eurostat",
        "government-debt-total": "eurostat", "government-spending": "eurostat",
        "government-spending-eur": "eurostat", "gross-fixed-capital-formation": "eurostat",
        "hospital-beds": "curated", "house-price-index": "eurostat",
        "imports": "eurostat", "industrial-production": "eurostat",
        "inflation-cpi": "eurostat", "interest-rate": "ecb",
        "job-vacancies": "eurostat", "labor-force-participation-rate": "eurostat",
        "labour-costs": "eurostat", "long-term-unemployment-rate": "eurostat",
        "manufacturing-production": "eurostat", "medical-doctors": "curated",
        "minimum-wages": "curated", "mining-production": "eurostat",
        "nurses": "curated", "personal-income-tax-rate": "curated",
        "population": "eurostat", "ppi": "eurostat",
        "productivity": "eurostat", "retail-sales": "eurostat",
        "retirement-age-men": "curated", "retirement-age-women": "curated",
        "sales-tax-rate": "curated", "services-inflation": "eurostat",
        "services-sentiment": "eurostat", "social-security-rate": "curated",
        "social-security-rate-companies": "curated", "social-security-rate-employees": "curated",
        "terrorism-index": "curated", "unemployed-persons": "eurostat",
        "unemployment": "eurostat", "youth-unemployment-rate": "eurostat",
    },
}


# Verified results harvested via WebFetch (provider, url, value, period)
# None URL -> we don't know exact URL; use canonical.
VERIFIED = {
    "AT": {
        "inflation-cpi": ("Statistics Austria", "http://www.statistik.at", 3.3, "2026-04"),
        "gdp": ("World Bank", "https://www.worldbank.org/", 521.64, "2024"),
        "gdp-real": ("Statistics Austria", "http://www.statistik.at", 0.6, "2026-Q1"),
        "industrial-production": ("Statistics Austria", "http://www.statistik.at", 1.70, "2026-03"),
        "ppi": ("Statistics Austria", "https://www.statistik.at", 117.50, "2026-03"),
        "unemployment": ("Public Employment Service Austria", "https://www.ams.at", 7.5, "2026-04"),
        "wages": ("Statistics Austria", "http://www.statistik.at", 3170, "2024"),
        "retail-sales": ("EUROSTAT", "https://ec.europa.eu/eurostat/", 0.10, "2026-03"),
        "imports": ("Statistics Austria", "http://www.statistik.at", 15823, "2026-02"),
        "exports": ("Statistics Austria", "http://www.statistik.at", 16165, "2026-02"),
        "employed-persons": ("Statistics Austria", "https://www.statistik.at/", 4500.20, "2025-Q4"),
        "consumer-confidence": ("European Commission", "http://ec.europa.eu", -24.10, "2026-04"),
        "business-confidence": ("European Commission", "http://ec.europa.eu", -12.50, "2026-04"),
        "government-debt-total": ("Statistics Austria", "http://www.statistik.at", 81.50, "2025"),
    },
    "BE": {
        "inflation-cpi": ("Statistics Belgium", "https://statbel.fgov.be", 4.07, "2026-04"),
        "gdp": ("World Bank", "https://www.worldbank.org/", 664.56, "2024"),
        "industrial-production": ("Statistics Belgium", "https://statbel.fgov.be", 0.30, "2026-03"),
    },
    "IE": {
        "inflation-cpi": ("Central Statistics Office Ireland", "https://www.cso.ie/", 3.60, "2026-03"),
        "gdp-real": ("Central Statistics Office Ireland", "https://www.cso.ie/", -6.00, "2026-Q1"),
        "unemployment": ("Central Statistics Office Ireland", "https://www.cso.ie/", 4.8, "2026-04"),
        "ppi": ("Central Statistics Office Ireland", "https://www.cso.ie/", 106.70, "2026-03"),
        "industrial-production": ("Central Statistics Office Ireland", "https://www.cso.ie/", -20.80, "2026-03"),
        "retail-sales": ("Central Statistics Office Ireland", "https://www.cso.ie/", 0.2, "2026-03"),
    },
    "LU": {
        # Not yet verified — TE pages remained blocked
    },
    "PT": {
        "inflation-cpi": ("Statistics Portugal", "http://www.ine.pt", 3.3, "2026-04"),
        "gdp-real": ("Statistics Portugal", "https://www.ine.pt", 2.30, "2026-Q1"),
        "industrial-production": ("Statistics Portugal", "https://www.ine.pt", 3.20, "2026-03"),
        "unemployment": ("Statistics Portugal", "http://www.ine.pt", 5.8, "2026-03"),
        "wages": ("Statistics Portugal", "http://www.ine.pt", 1333, "2026-Q1"),
        "retail-sales": ("Statistics Portugal", "https://www.ine.pt", 1.8, "2026-03"),
        "trade-balance": ("Statistics Portugal", "https://www.ine.pt", -2863.02, "2026-03"),
        "ppi": ("Statistics Portugal", "https://www.ine.pt", 116.80, "2026-03"),
    },
}


def yaml_quote(s):
    if s is None:
        return "null"
    s = str(s)
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def emit(cc, out_dir):
    country = COUNTRY_TE[cc]
    truth = TRUTH[cc]
    verified = VERIFIED.get(cc, {})
    lines = []
    verified_count = 0
    conform_count = 0
    mismatches = []
    for slug, current in sorted(truth.items()):
        te_path = SLUG_TO_TE_PATH.get(slug)
        te_page = f"https://tradingeconomics.com/{country}/{te_path}" if te_path else None
        if slug in verified:
            label, url, value, period = verified[slug]
            code = label_to_code(label)
            conform = code == current
            verified_count += 1
            if conform:
                conform_count += 1
            else:
                mismatches.append((slug, current, code, label))
            lines.append(f"{slug}:")
            lines.append(f"  te_label: {yaml_quote(label)}")
            lines.append(f"  te_url: {yaml_quote(url)}")
            lines.append(f"  te_page: {yaml_quote(te_page)}")
            lines.append(f"  te_value: {value if value is not None else 'null'}")
            lines.append(f"  te_period: {yaml_quote(period)}")
            lines.append(f"  suggested_source: {code if code else 'null'}")
            lines.append(f"  current_source: {current}")
            lines.append(f"  conform: {'true' if conform else 'false'}")
            lines.append(f"  verified: true")
        else:
            lines.append(f"{slug}:")
            lines.append(f"  te_label: null")
            lines.append(f"  te_url: null")
            lines.append(f"  te_page: {yaml_quote(te_page)}")
            lines.append(f"  te_value: null")
            lines.append(f"  te_period: null")
            lines.append(f"  suggested_source: null")
            lines.append(f"  current_source: {current}")
            lines.append(f"  conform: false")
            lines.append(f"  verified: false")
    out_path = out_dir / f"{cc}.yaml"
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"=== {cc}: verified={verified_count}/{len(truth)}  conform={conform_count}")
    for slug, cur, sug, lab in mismatches[:5]:
        print(f"    MISMATCH {slug}: truth={cur} -> TE-label '{lab}' ({sug})")


def main():
    out_dir = Path(__file__).resolve().parents[1] / "docs" / "_te_inventory"
    out_dir.mkdir(parents=True, exist_ok=True)
    for cc in ["AT", "BE", "IE", "LU", "PT"]:
        emit(cc, out_dir)


if __name__ == "__main__":
    main()
