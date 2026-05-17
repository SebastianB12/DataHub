"""Extract TE latest value + period for BG slugs; compare to DB latest data_point."""
import json, os, re, sys
from pipeline.db import supabase as sb

SLUGS = json.load(open("docs/_audit_all_remaining_slugs.json"))["BG"]
SRC_DIR = "docs/_audit_te_html/bg"

TE_SLUG_MAP = {
    "budget-deficit": "government-budget-value",
    "core-cpi": "core-inflation-rate",
    "credit-rating": "rating",
    "gdp-real": "gdp-growth-annual",
    "government-debt-total": "government-debt",
    "government-spending-eur": "government-spending",
    "house-price-index": "housing-index",
    "ppi": "producer-prices",
    "social-security-rate-companies": "social-security-rate-for-companies",
    "social-security-rate-employees": "social-security-rate-for-employees",
    "unemployment": "unemployment-rate",
}
TE_NO_PAGE = {
    "services-inflation","services-sentiment","disposable-personal-income",
    "energy-inflation","hospital-beds","medical-doctors","nurses",
}


VAL_PATTERNS = [
    # Heatmap last value cell (preferred for indicator pages)
    re.compile(r'<td[^>]*class="[^"]*last[^"]*"[^>]*>\s*([\-+]?[\d,\.]+)\s*</td>', re.I),
    # ctl00 hero last value
    re.compile(r'<span id="ctl00_ContentPlaceHolder1_ctl\d+_LastValue"[^>]*>\s*([\-+]?[\d,\.]+)', re.I),
]

# meta og:description or page-header text e.g. "Bulgaria Inflation Rate eased to 4.50 percent in March 2026 from 4.60 percent in February 2026..."
META_RE = re.compile(r'name="description"\s+content="([^"]+)"', re.I)
# Robust headline extractor: "X (verb) (to|by) NUMBER (units) in MONTH/QUARTER of YEAR"
HEADLINE_RE = re.compile(
    r"(?:eased|fell|rose|increased|decreased|jumped|advanced|edged|expanded|contracted|stood|reached|surged|dropped|slipped|grew|widened|narrowed|climbed|plunged|softened|accelerated|slowed|was)\s+(?:to|at|worth|by)?\s*([\-+]?[\d,\.]+)\s+([A-Za-z%€$\(\) ]{0,40}?)\s+in\s+(?:the\s+(first|second|third|fourth)\s+quarter\s+of\s+(\d{4})|([A-Za-z]+)\s+(?:of\s+)?(\d{4}))",
    re.I,
)
# Alternative "was X in Month YYYY"
WAS_RE = re.compile(r"was\s+([\-+]?[\d,\.]+)\s*([^<,]*?)\s+in\s+([A-Za-z]+)\s+(?:of\s+)?(\d{4})", re.I)
# fallback: "(metric) in Bulgaria (verb) to X percent in MONTH from"
FROM_RE = re.compile(
    r"(?:percent|points|EUR|BGN|Million|Bn|thousand|index)?\s*in\s+Bulgaria\s+(?:eased|fell|rose|increased|decreased|jumped|advanced|edged|expanded|contracted|stood|reached|surged|dropped|slipped|grew|widened|narrowed|climbed|plunged|softened|accelerated|slowed)\s+to\s+([\-+]?[\d,\.]+)",
    re.I,
)


def parse_te_latest(html: str):
    m_meta = META_RE.search(html)
    desc = m_meta.group(1) if m_meta else ""
    val = None; unit_hint = None; mon = None; yr = None
    if desc:
        m = HEADLINE_RE.search(desc)
        if m:
            try:
                val = float(m.group(1).replace(",", ""))
            except Exception:
                val = None
            unit_hint = (m.group(2) or "").strip()
            # group3 = quarter ord, group4 = quarter year, group5 = month, group6 = month-year
            if m.group(3):
                mon = f"Q{ {'first':1,'second':2,'third':3,'fourth':4}[m.group(3).lower()] }"
                yr = int(m.group(4))
            else:
                mon = m.group(5)
                yr = int(m.group(6))
    return {"value": val, "month": mon, "year": yr, "unit_hint": unit_hint, "headline": desc[:300]}


def db_latest(slug):
    rows = sb.table("data_points").select("date,value,source,unit").eq("country", "BG").eq("indicator", slug).order("date", desc=True).limit(1).execute().data
    return rows[0] if rows else None


def main():
    out = {}
    for slug in SLUGS:
        te_slug = TE_SLUG_MAP.get(slug, slug)
        html_path = os.path.join(SRC_DIR, f"{slug}.html")
        html = open(html_path, "rb").read().decode("utf-8", errors="ignore") if os.path.exists(html_path) else ""
        title_m = re.search(r"<title[^>]*>\s*([^<]+)\s*</title>", html)
        title = (title_m.group(1) if title_m else "").strip()
        page_ok = "Bulgaria" in title
        te_info = parse_te_latest(html) if page_ok else {"value": None, "month": None, "year": None, "unit_hint": None, "headline": ""}
        db = db_latest(slug)
        out[slug] = {
            "te_slug": te_slug,
            "te_title": title,
            "te_latest_value": te_info["value"],
            "te_period": f"{te_info['month']} {te_info['year']}" if te_info["month"] else None,
            "te_unit_hint": te_info["unit_hint"],
            "te_headline": te_info["headline"],
            "db_latest_date": db["date"] if db else None,
            "db_latest_value": db["value"] if db else None,
            "db_source": db["source"] if db else None,
            "db_unit": db["unit"] if db else None,
        }
    json.dump(out, open("docs/_audit_bg_te_values.json","w",encoding="utf-8"), indent=2, default=str)
    print("BG value audit written.")
    # Print short table
    for slug, d in out.items():
        te = d["te_latest_value"]
        db = d["db_latest_value"]
        date = d["db_latest_date"]
        period = d["te_period"]
        print(f"  {slug:35s} TE={te!s:>10} ({period or '?'})  DB={db!s:>10} ({date or '?'})")


if __name__ == "__main__":
    main()
