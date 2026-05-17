"""Build docs/_audit_us_batch3_findings.yaml."""
import json, yaml, datetime as dt

LABEL_TO_CODE = [
    ("University of Michigan", "fred"),
    ("SIPRI", "worldbank"),
    ("Department of Labor", "curated"),
    ("Bureau of Labor Statistics", "fred"),
    ("U.S. Bureau of Labor Statistics", "fred"),
    ("Bureau of Economic Analysis", "fred"),
    ("U.S. Bureau of Economic Analysis", "fred"),
    ("Bureau of Economic Analysis (BEA)", "fred"),
    ("U.S. Census Bureau", "fred"),
    ("Federal Reserve", "fred"),
    ("Federal Reserve Bank of New York", "fred"),
    ("Federal Reserve Bank of Philadelphia", "fred"),
    ("Federal Reserve Bank of Dallas", "fred"),
    ("U.S. Energy Information Administration", "eia"),
    ("Energy Information Administration", "eia"),
    ("World Bank", "worldbank"),
    ("OECD", "curated"),
    ("Social Security Administration", "curated"),
    ("Internal Revenue Service", "curated"),
    ("World Steel Association", "curated"),
    ("National Association of Realtors", "fred"),
    ("Wards Intelligence", "fred"),
    ("Transparency International", "curated"),
    ("Conference Board", "curated"),
]


def label_to_code(label):
    if not label:
        return None
    for k, v in LABEL_TO_CODE:
        if k.lower() in label.lower():
            return v
    return None


parsed = json.load(open("docs/_audit_te_html/batch3/_parsed.json"))
current = json.load(open("docs/_audit_us_batch3_current.json"))

# Manual TE overrides for placeholder-desc pages
TE_OVERRIDES = {
    "natural-gas-storage": {"source_label": "U.S. Energy Information Administration", "headline": "85", "unit": "billion cubic feet (weekly change)", "period": "week ending May 8, 2026"},
    "ppi-ex-food-energy-trade-svcs": {"source_label": "U.S. Bureau of Labor Statistics", "headline": "5.20", "unit": "percent YoY", "period": "April 2026"},
    "social-security-rate-companies": {"source_label": "Social Security Administration", "headline": "7.65", "unit": "percent", "period": "2026"},
    "social-security-rate-employees": {"source_label": "Social Security Administration", "headline": "7.65", "unit": "percent", "period": "2026"},
    "strategic-petroleum-reserve": {"source_label": None, "headline": None, "unit": "Thousand Barrels", "period": None},  # no dedicated TE page
    "personal-income-tax-rate": {"source_label": "Internal Revenue Service", "headline": "37", "unit": "percent", "period": "2026"},
    "personal-income": {"source_label": "U.S. Bureau of Economic Analysis", "headline": "0.60", "unit": "percent MoM", "period": "March 2026"},
    "personal-spending": {"source_label": "U.S. Bureau of Economic Analysis", "headline": "0.90", "unit": "percent MoM", "period": "March 2026"},
    "wholesale-inventories": {"source_label": "U.S. Census Bureau", "headline": "1.30", "unit": "percent MoM", "period": "March 2026"},
    "sales-tax-rate": {"source_label": None, "headline": "0", "unit": "percent", "period": "2026"},
    "social-security-rate": {"source_label": "Social Security Administration", "headline": "15.30", "unit": "percent", "period": "2026"},
    "withholding-tax-rate": {"source_label": "Internal Revenue Service", "headline": "30", "unit": "percent", "period": "2026"},
    "population": {"source_label": "U.S. Census Bureau", "headline": "342.3", "unit": "million", "period": "2025"},
    "medical-doctors": {"source_label": "World Bank", "headline": "2.77", "unit": "per 1000 people", "period": "2019"},
    "nurses": {"source_label": "World Bank", "headline": "12.71", "unit": "per 1000 people", "period": "2024"},
    "mining-production": {"source_label": "Federal Reserve", "headline": "0.20", "unit": "percent YoY", "period": "April 2026"},
}

# Track fixes applied
FIXED = {
    "money-supply-m0": "Fixed conversion (0.001 -> 1.0); FRED BOGMBASE already in Billions USD, value was being divided by 1000",
    "ppi": "Series PPIACO -> PPIFIS (PPI Final Demand, TE headline). Refetched, now 156.5 matching TE 156.50",
    "philadelphia-fed-manufacturing-index": "Series MANEMP (placeholder) -> GACDFSA066MSFRBPHI (Philly Fed Manufacturing General Activity Diffusion Index). Now 26.7 matching TE 26.70",
    "wages": "Series CES0500000003 (AHE Total Private all employees, ~37.41) -> AHETPI (AHE Production+Nonsupervisory, TE headline 32.23). Now matches",
    "real-consumer-spending": "Series DPCERAM1M225NBEA (MoM%, value 0.2) -> DPCERL1Q225SBEA (Real PCE %chg ann. QoQ, value 1.6 matching TE 1.60%)",
    "private-debt-to-gdp": "Series QUSPAMUSDA (raw USD, 42637) -> QUSPAM770A (ratio to GDP %, 140.4 close to TE 142%)",
    "nonfarm-productivity-qoq": "Series OPHNFB (level index) -> PRS85006092 (QoQ % change ann., 0.8 matching TE 0.80%)",
    "new-home-sales": "Refetched stale data; HSN1F March 2026 = 682 matches TE 682",
    "new-orders": "Refetched stale data; AMTMNO March 2026 = 630448 matches TE 630448",
    "wages-in-manufacturing": "Refetched stale data; CES3000000008 April 2026 = 30.10 matches TE 30.10",
    "trade-balance": "Refetched stale data; BOPGSTB March 2026 = -60.31 matches TE -60.31",
}

# Manual TE values dict for value comparison
TE_VALS = {
    "medical-doctors": ("2.77", "2019", "World Bank"),
    "michigan-inflation-expectations": ("4.50", "May 2026", "University of Michigan"),
    "military-expenditure": ("954387", "2025", "SIPRI"),
    "minimum-wages": ("7.25", "2025", "Department of Labor"),
    "mining-and-energy-payrolls": ("2.50", "April 2026", "U.S. Bureau of Labor Statistics"),
    "mining-production": ("0.20", "April 2026", "Federal Reserve"),
    "money-supply-m0": ("5458600", "March 2026", "Federal Reserve"),
    "money-supply-m1": ("19531.40", "March 2026", "Federal Reserve"),
    "money-supply-m2": ("22442.10", "January 2026", "Federal Reserve"),
    "natural-gas-storage": ("85", "week ending May 8 2026", "U.S. Energy Information Administration"),
    "new-home-sales": ("682", "March 2026", "U.S. Census Bureau"),
    "new-orders": ("630448", "March 2026", "U.S. Census Bureau"),
    "non-farm-payrolls": ("115", "April 2026", "U.S. Bureau of Labor Statistics"),
    "nonfarm-payrolls-private": ("123", "April 2026", "U.S. Bureau of Labor Statistics"),
    "nonfarm-productivity-qoq": ("0.80", "Q1 2026", "U.S. Bureau of Labor Statistics"),
    "nurses": ("12.71", "2024", "World Bank"),
    "ny-empire-state-manufacturing-index": ("19.60", "May 2026", "Federal Reserve Bank of New York"),
    "part-time-employment": ("28413", "April 2026", "U.S. Bureau of Labor Statistics"),
    "pce-price-index": ("130.34", "March 2026", "U.S. Bureau of Economic Analysis"),
    "personal-income": ("0.60", "March 2026", "U.S. Bureau of Economic Analysis"),
    "personal-income-tax-rate": ("37", "2026", "Internal Revenue Service"),
    "personal-savings": ("3.60", "March 2026", "U.S. Bureau of Economic Analysis"),
    "personal-spending": ("0.90", "March 2026", "U.S. Bureau of Economic Analysis"),
    "philadelphia-fed-manufacturing-index": ("26.70", "April 2026", "Federal Reserve Bank of Philadelphia"),
    "population": ("342.3", "2025", "U.S. Census Bureau"),
    "ppi": ("156.50", "April 2026", "U.S. Bureau of Labor Statistics"),
    "ppi-ex-food-energy-trade-svcs": ("5.20", "April 2026", "U.S. Bureau of Labor Statistics"),
    "private-debt-to-gdp": ("142", "2024", "OECD"),
    "private-sector-credit": ("13626.91", "April 2026", "Federal Reserve"),
    "productivity": ("119.58", "Q1 2026", "U.S. Bureau of Labor Statistics"),
    "professional-and-business-services-payrolls": ("7", "April 2026", "U.S. Bureau of Labor Statistics"),
    "real-consumer-spending": ("1.60", "Q1 2026", "U.S. Bureau of Economic Analysis"),
    "refinery-crude-runs": ("370", "week ending May 8 2026", "U.S. Energy Information Administration"),
    "rent-inflation": ("3.30", "April 2026", "Bureau of Labor Statistics"),
    "retail-sales-ex-autos": ("0.70", "April 2026", "U.S. Census Bureau"),
    "retail-trade-payrolls": ("21.80", "April 2026", "U.S. Bureau of Labor Statistics"),
    "retirement-age-men": ("67", "2026", "Social Security Administration"),
    "retirement-age-women": ("67", "2026", "Social Security Administration"),
    "sales-tax-rate": ("0", "2026", "n/a"),
    "secured-overnight-financing-rate": ("3.56", "May 14 2026", "Federal Reserve Bank of New York"),
    "services-inflation": ("3.40", "April 2026", "Bureau of Labor Statistics"),
    "social-security-rate": ("15.30", "2026", "Social Security Administration"),
    "social-security-rate-companies": ("7.65", "2026", "Social Security Administration"),
    "social-security-rate-employees": ("7.65", "2026", "Social Security Administration"),
    "steel-production": ("7200", "March 2026", "World Steel Association"),
    "strategic-petroleum-reserve": (None, None, "U.S. Energy Information Administration"),
    "terrorism-index": ("4.52", "2025", "Institute for Economics and Peace"),
    "total-housing-inventory": ("1470", "April 2026", "National Association of Realtors"),
    "total-vehicle-sales": ("15.90", "April 2026", "Wards Intelligence"),
    "trade-balance": ("-60.31", "March 2026", "Bureau of Economic Analysis (BEA)"),
    "transportation-and-warehousing-payrolls": ("30.30", "April 2026", "U.S. Bureau of Labor Statistics"),
    "u6-unemployment-rate": ("8.20", "April 2026", "U.S. Bureau of Labor Statistics"),
    "unemployed-persons": ("7373", "April 2026", "U.S. Bureau of Labor Statistics"),
    "unemployment": ("4.30", "April 2026", "U.S. Bureau of Labor Statistics"),
    "unit-labour-costs-qoq": ("2.30", "Q1 2026", "U.S. Bureau of Labor Statistics"),
    "wages": ("32.23", "April 2026", "U.S. Bureau of Labor Statistics"),
    "wages-in-manufacturing": ("30.10", "April 2026", "U.S. Bureau of Labor Statistics"),
    "weapons-sales": ("13512", "2024", "SIPRI"),
    "weekly-crude-oil-production": ("13710", "week ending May 8 2026", "U.S. Energy Information Administration"),
    "weekly-economic-index": ("2.71", "May 2026", "Federal Reserve Bank of Dallas"),
    "wholesale-inventories": ("1.30", "March 2026", "U.S. Census Bureau"),
    "wholesale-trade-payrolls": ("6", "April 2026", "U.S. Bureau of Labor Statistics"),
    "withholding-tax-rate": ("30", "2026", "Internal Revenue Service"),
    "youth-unemployment-rate": ("9.50", "April 2026", "U.S. Bureau of Labor Statistics"),
}

# Build findings
out = {}
for slug, (te_val, te_period, te_label) in TE_VALS.items():
    cur = current.get(slug, {}) or {}
    src_row = cur.get("src")
    dp = cur.get("dp")
    our_source = src_row.get("source") if src_row else None
    our_series = src_row.get("series_id") if src_row else None
    our_value = dp.get("value") if dp else None
    our_period = dp.get("date") if dp else None
    expected_code = label_to_code(te_label)
    source_match = (expected_code is not None and expected_code == our_source) or our_source == "curated"
    # Determine value match: compute relative diff if both numeric
    value_match = None
    flag = None
    try:
        tv = float(te_val) if te_val is not None else None
        ov = float(our_value) if our_value is not None else None
        if tv is not None and ov is not None:
            # tolerance check for level alignment; some are MoM/YoY % so DB level won't match
            if abs(tv) < 0.01:
                value_match = abs(ov) < 0.01
            else:
                rel = abs(ov - tv) / abs(tv)
                value_match = rel <= 0.05
    except Exception:
        pass

    fixed = slug in FIXED
    fix_summary = FIXED.get(slug)
    # Set flag
    if slug == "strategic-petroleum-reserve":
        flag = "no-te-page"
    elif slug == "rent-inflation":
        flag = "needs-attention"  # CUSR0000SEHA gives 2.79% YoY; TE shows 3.30% (CPI Shelter not Rent of Primary Residence)
    elif slug == "services-inflation":
        flag = "frontend-only"  # we store level, TE shows YoY%; YoY computes correctly (3.37%)
    elif slug == "wholesale-inventories":
        flag = "frontend-only"  # WHLSLRIMSA correct level; TE shows MoM%
    elif slug == "mining-production":
        flag = "frontend-only"  # IPMINE level correct; TE shows YoY%
    elif slug == "personal-income":
        flag = "frontend-only"  # PI level correct; TE shows MoM%
    elif slug == "personal-spending":
        flag = "frontend-only"  # PCE level correct; TE shows MoM%
    elif slug == "retail-sales-ex-autos":
        flag = "frontend-only"  # RSFSXMV level; TE shows MoM%
    elif slug == "non-farm-payrolls":
        flag = "frontend-only"  # PAYEMS level; TE shows MoM change
    elif slug == "nonfarm-payrolls-private":
        flag = "frontend-only"
    elif slug in ("mining-and-energy-payrolls","professional-and-business-services-payrolls","retail-trade-payrolls","transportation-and-warehousing-payrolls","wholesale-trade-payrolls"):
        flag = "frontend-only"  # level vs MoM thousand change
    elif slug == "ppi-ex-food-energy-trade-svcs":
        flag = "frontend-only"  # WPSFD49116 level; TE shows YoY%
    elif slug == "military-expenditure":
        flag = "vintage-lag"  # WB 2024 vs SIPRI 2025
    elif slug == "steel-production":
        flag = "source-mismatch"  # TE uses World Steel Association (thousand tonnes), we use FRED IPG331S (index)
    elif slug == "private-debt-to-gdp":
        flag = "vintage-lag"  # BIS 2025Q3 = 140.4% vs TE 142% (2024 figure)
    elif slug == "total-vehicle-sales":
        flag = "vintage-lag"  # TOTALSA March=16.7 latest from FRED; TE shows 15.9 April from Wards (not yet on FRED)

    out[slug] = {
        "te_label": te_label,
        "te_value": te_val,
        "te_period": te_period,
        "our_source": our_source,
        "our_series": our_series,
        "our_value": our_value,
        "our_period": our_period,
        "source_match": bool(source_match),
        "value_match": value_match,
        "fixed": fixed,
        "fix_summary": fix_summary,
        "flag": flag,
    }

with open("docs/_audit_us_batch3_findings.yaml", "w", encoding="utf-8") as f:
    yaml.safe_dump(out, f, sort_keys=False, allow_unicode=True)

# Summary
ok = sum(1 for s, v in out.items() if v["source_match"] and (v["value_match"] is True or v["flag"] in ("frontend-only",)))
fixed_n = sum(1 for s, v in out.items() if v["fixed"])
flagged = [s for s, v in out.items() if v["flag"] and v["flag"] not in ("frontend-only",)]
print(f"Total: {len(out)}, OK: {ok}, Fixed: {fixed_n}, Flagged: {len(flagged)}")
print("Fixed slugs:", [s for s,v in out.items() if v["fixed"]])
print("Flagged:", flagged)
