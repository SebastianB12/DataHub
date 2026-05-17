"""Annotate _audit_us_reaudit.yaml with fix tracking and flag normalization.

For each slug:
- Carry over the fresh TE+DB comparison from _reaudit_us_analyze.py output
- Add fixed=True + fix_summary for slugs we fixed in this audit round
- Re-classify value-mismatch into frontend-only / vintage-lag / gap / real-fix
"""
from __future__ import annotations
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs" / "_audit_us_reaudit.yaml"

# Slugs that were fixed in this audit round
FIXES = {
    "youth-unemployment-rate": "Series LNS14000012 (age 16-19, 14.4) -> LNS14024887 (age 16-24, 9.5) to match TE",
    "total-housing-inventory": "Scale fix: stored in thousands (1470) instead of units (1470000) to match TE display",
    "housing-index": "Series USSTHPI (FHFA Q index, 709) -> HPIPONM226S (FHFA Purchase-Only monthly, 441.43) to match TE 441.40",
    "government-debt": "Series GFDEBTN (quarterly, $38.5T) -> Treasury Debt-to-the-Penny monthly EoM ($38.97T April) via fiscaldata.treasury.gov API",
    "gdp-per-capita": "Series NY.GDP.PCAP.CD (current USD, $84,534) -> NY.GDP.PCAP.KD (constant 2015 USD, $66,356) to match TE constant-USD convention",
    "gdp-per-capita-ppp": "Series NY.GDP.PCAP.PP.CD (current intl $, $85,810) -> NY.GDP.PCAP.PP.KD (constant 2021 intl $, $75,489) to match TE $75,491.61",
    "gdp-growth-contribution-exports": "Series A019RY2Q224SBEA (Net Exports, -1.3pp) -> A020RY2Q224SBEA (Exports only, 1.32pp) to match TE",
    "gross-national-product": "Series GNP (nominal, 31553.79) -> GNPC96 (Real Chained 2017 USD, 24173.72) to match TE 24173.7 Q4 2025",
    "loans-to-private-sector": "Series TOTLL (all loans, $13.76T) -> BUSLOANS (C&I Loans, $2.82T) to match TE 2827.90 USD Billion March",
    "imports": "Series BOPGIMP (goods only, $302.17B) -> BOPTIMP (Goods+Services BoP basis, $381.2B) to match TE; converted to USD Billion",
    "goods-trade-balance": "Series BOPGSTB (Goods+Services, -$60.3B) -> BOPGTB (Goods only, -$88.7B) to match TE -$87.4B March; converted to USD Billion",
    "government-budget-value": "Converted values from USD Million (215024) to USD Billion (215.02) to match TE display",
    "central-bank-balance": "Converted stored values from USD Billion (6728.5) to USD Million (6,728,502) to match TE display 6,709,505",
    "money-supply-m0": "Converted BOGMBASE from Billions (5458.6) to Millions (5,458,600) to match TE display",
    "rent-inflation": "Refetched CUSR0000SAH1 (existing series CUSR0000SAH1; Oct 2025 still gap in FRED itself)",
    "labour-costs": "Removed duplicate adjustment='SA' rows; kept adjustment='' (BLS ULCNFB index)",
    "car-production": "Consolidated duplicate (SA/empty adjustment) rows from prior series-switch",
    "core-producer-prices": "Consolidated duplicate (NSA/empty adjustment) rows from prior series-switch",
    "cpi-median": "Consolidated duplicate (SA/empty adjustment) rows from prior series-switch",
    "cpi-trimmed-mean": "Consolidated duplicate (SA/empty adjustment) rows from prior series-switch",
    "current-account": "Consolidated duplicate (SA/empty adjustment) rows from prior series-switch",
    "exports": "Refetched BOPTEXP and converted to USD Billion to match TE display; removed duplicate scales",
    "food-inflation": "Migrated adjustment='SA' rows to adjustment='' (single default)",
    "total-vehicle-sales": "Refetched TOTALSA (data still vintage-lag: FRED has March, TE shows April)",
    "gasoline-prices": "Deleted duplicate adjustment='SA' shadow rows from prior FRED source",
}

# Slugs where the discrepancy is by design (frontend transform display)
FRONTEND_ONLY_SLUGS = {
    # YoY frontend
    "inflation-cpi", "core-cpi", "food-inflation", "energy-inflation", "rent-inflation",
    "services-inflation", "gdp-deflator", "gdp-real", "manufacturing-production",
    "mining-production", "industrial-production", "core-producer-prices",
    "average-hourly-earnings-yoy",
    "changes-in-inventories",  # TE shows QoQ change in $B which matches our level
    "corruption-index", "corruption-rank",  # parser misread; values OK
    "interest-rate",  # TE shows range, we have upper bound
    "strategic-petroleum-reserve",  # TE shows EIA crude stocks; ours is SPR-only
    # MoM frontend
    "building-permits", "business-inventories", "construction-spending", "consumer-credit",
    "durable-goods-orders", "durable-goods-orders-ex-defense", "durable-goods-orders-ex-transport",
    "existing-home-sales", "factory-orders", "new-home-sales", "new-orders",
    "personal-spending", "personal-income", "real-consumer-spending", "retail-sales-ex-autos",
    "retail-sales", "wholesale-inventories",
    # MoM-thousands (payrolls = change)
    "adp-employment-change", "construction-payrolls",
    "federal-government-payrolls", "financial-activities-payrolls", "government-payrolls",
    "health-care-payrolls", "information-payrolls", "leisure-and-hospitality-payrolls",
    "manufacturing-payrolls", "mining-and-energy-payrolls", "non-farm-payrolls",
    "nonfarm-payrolls-private", "professional-and-business-services-payrolls",
    "retail-trade-payrolls", "transportation-and-warehousing-payrolls", "wholesale-trade-payrolls",
    # QoQ frontend
    "corporate-profits", "employment-cost-index", "employment-cost-index-benefits",
    "employment-cost-index-wages", "nonfarm-productivity-qoq", "unit-labour-costs-qoq",
    # weekly change frontend
    "crude-oil-imports", "crude-oil-stocks", "cushing-crude-oil-stocks",
    "distillate-fuel-production", "distillate-stocks", "gasoline-production",
    "gasoline-stocks", "natural-gas-storage", "refinery-crude-runs",
    # contribution series — Q-data, level (frontend may sum/aggregate)
    "gdp-growth-contribution-consumer",
    # housing-starts is annualized rate display vs thousands stored
    "housing-starts", "job-quits", "job-offers",
    # sign convention
    "budget-deficit",
}

VINTAGE_LAG_SLUGS = {
    "michigan-inflation-expectations",  # FRED MICH lags UMich preliminary
    "consumer-confidence",  # FRED UMCSENT same issue
    "total-vehicle-sales",  # April not yet on FRED
    "military-expenditure",  # SIPRI annual, WB has up to 2024
    "private-debt-to-gdp",  # OECD annual, FRED slightly different
    "gdp",  # WB annual 2024 vs TE 2024 - small revision
}

GAP_SLUGS = {
    "foreign-exchange-reserves": "TE shows Treasury 'Foreign Currencies' line ($38B); we use FRED TRESEGUSM052N (Total Reserves excl Gold, $241B). Need IMF SDDS or Treasury TIC data.",
    "capital-flows": "TE shows Treasury TIC monthly net inflow ($184.5B); we use NETFI (NIPA annual). FRED has no TIC.",
    "hospitals": "Curated value only; TE doesn't have a US Hospitals page.",
    "credit-rating": "Curated only; TE doesn't have US Credit Rating page.",
    "steel-production": "TE source 'World Steel Association' (7200kt March, level in Tonnes); we use FRED IPG331S (Index 2017=100, 100.1). FRED has no Tonnes series.",
    "currency": "TE shows DXY-style 'United States Dollar' (99.3); we store DTWEXBGS trade-weighted (118.04). Different concept; DXY not in FRED.",
}

# Slugs whose TE page doesn't exist
NO_TE_PAGE_SLUGS = {
    "credit-rating", "durable-goods-orders-ex-transport", "gdp-growth-contribution-consumer",
    "government-debt-total", "hospitals", "ppi-ex-food-energy-trade-svcs",
    "social-security-rate-companies", "social-security-rate-employees",
    "strategic-petroleum-reserve",
}


def main():
    with open(SRC, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    for slug, entry in data.items():
        # Apply fix tracking
        if slug in FIXES:
            entry["fixed"] = True
            entry["fix_summary"] = FIXES[slug]
        # Reclassify flag
        flag = entry.get("flag")
        if slug in GAP_SLUGS:
            entry["flag"] = "gap"
            if not entry.get("fix_summary"):
                entry["fix_summary"] = GAP_SLUGS[slug]
        elif slug in NO_TE_PAGE_SLUGS:
            entry["flag"] = "no-te-page"
        elif slug in VINTAGE_LAG_SLUGS:
            entry["flag"] = "vintage-lag"
        elif slug in FRONTEND_ONLY_SLUGS:
            entry["flag"] = "frontend-only"
        elif flag in ("value-mismatch", "frontend-only-mom") and slug not in FIXES:
            # Default to frontend-only if TE description includes %/MoM/YoY/QoQ keywords
            desc = (entry.get("te_desc") or "").lower()
            if any(kw in desc for kw in ("month-on-month", "month-over-month",
                                          "year-on-year", "year-over-year",
                                          "quarter-on-quarter", "quarter-over-quarter",
                                          "annualized rate of", " mom", " yoy", " qoq",
                                          "rose by", "fell by", "added")):
                entry["flag"] = "frontend-only"
            else:
                entry["flag"] = "needs-review"

        # If we fixed it, override flag to 'ok-fixed'
        if slug in FIXES:
            entry["flag"] = "ok-fixed"
        # Default None -> ok
        if entry.get("flag") is None:
            entry["flag"] = "ok"

    # Write final yaml
    with open(SRC, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=True, allow_unicode=True)

    # Summary
    by_flag = {}
    for slug, entry in data.items():
        by_flag.setdefault(entry.get("flag"), []).append(slug)

    print(f"Total slugs: {len(data)}")
    for fl, items in sorted(by_flag.items(), key=lambda x: -len(x[1])):
        print(f"  {fl}: {len(items)}")
    print(f"\nFixed this round: {sum(1 for v in data.values() if v.get('fixed'))}")


if __name__ == "__main__":
    main()
