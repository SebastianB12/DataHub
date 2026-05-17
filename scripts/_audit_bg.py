"""Aggregate BG audit findings.
Parse source name + latest value from each TE HTML, compare to DB, write report."""
import json, os, re
from pipeline.db import supabase as sb

SLUGS = json.load(open("docs/_audit_all_remaining_slugs.json"))["BG"]
SRC_DIR = "docs/_audit_te_html/bg"

# EP slug -> actual TE slug (used to refetch). Identity unless mapped.
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

# Slugs without a TE BG page — coverage gap
TE_NO_PAGE = {
    "services-inflation",
    "services-sentiment",
    "disposable-personal-income",
    "energy-inflation",
    "hospital-beds",
    "medical-doctors",
    "nurses",
}


def parse_source(html: str):
    """Return tuple (source_name, source_url). Source name may be None."""
    # Pattern 1: source: <a class='source-name' href='...'>Name</a>
    m = re.search(
        r"source:\s*<a class='source-name'[^>]*href\s*=\s*'([^']*)'[^>]*>([^<]+)</a>",
        html, flags=re.I,
    )
    if m:
        return (m.group(2).strip(), m.group(1))
    # Pattern 2: plain "source: <NAME></h2>"
    m = re.search(
        r'<h2[^>]*line-height[^>]*>\s*source:\s*([^<]+?)\s*</h2>',
        html, flags=re.I,
    )
    if m:
        return (m.group(1).strip(), None)
    # Pattern 3: simply 'source: NAME</span>'
    m = re.search(
        r'source:\s*([A-Z][A-Za-z][A-Za-z .,&;:\(\)\-]+?)(?:</h2>|<br|</span>|<a |\")',
        html,
    )
    if m:
        return (m.group(1).strip(), None)
    return (None, None)


def parse_latest(html: str):
    """Extract latest value/frequency/period if we can find it."""
    # Hero table row, e.g. <table class="table-heatmap..." or generic
    # Look for "X was Y in Month YYYY"
    m = re.search(
        r"<title[^>]*>\s*Bulgaria\s+([^<|]+?)\s*</title>",
        html, flags=re.S,
    )
    title = m.group(1).strip() if m else None
    # Find meta og:description with the headline value
    m = re.search(r'<meta\s+property="og:description"\s+content="([^"]+)"', html)
    og = m.group(1) if m else None
    # Find h1 + the value 'Bulgaria X — last value/value YYYY-MM-DD'
    return {"title": title, "og_desc": og}


def source_to_label(name: str | None) -> str | None:
    if not name:
        return None
    n = name.lower()
    if "national statistical institute" in n or "national statistical inst" in n or n.strip() == "nsi" or "nsi bulgaria" in n:
        return "nsi_bg"
    if "bulgarian national bank" in n or "bnb" in n.split():
        return "nsi_bg"  # we fetch via BNB SDDS for BoP
    if "eurostat" in n:
        return "eurostat"
    if n.strip().lower() == "ecb" or "european central bank" in n:
        return "ecb"
    if "world bank" in n:
        return "worldbank"
    if "imf" in n or "international monetary fund" in n:
        return "curated"
    if "european commission" in n:
        return "eurostat"  # business surveys via EC come through Eurostat BCS
    if any(s in n for s in (
        "transparency international", "ti ", "conference board",
        "oecd", "who", "world health", "sipri",
        "institute for economics and peace",
        "ministry of finance", "ministry of labour", "ministry of",
        "national revenue agency", "central bank")):
        return "curated"
    return None


def main():
    db_rows = sb.table("indicator_sources").select(
        "indicator,source,is_default,series_id,unit,adjustment"
    ).eq("country", "BG").eq("is_default", True).execute().data
    db = {r["indicator"]: r for r in db_rows}

    findings = {}
    for slug in SLUGS:
        path = os.path.join(SRC_DIR, f"{slug}.html")
        html = open(path, "rb").read().decode("utf-8", errors="ignore") if os.path.exists(path) else ""
        title_m = re.search(r"<title[^>]*>\s*([^<]+)\s*</title>", html)
        title = (title_m.group(1) if title_m else "").strip()

        te_slug = TE_SLUG_MAP.get(slug, slug)
        page_ok = "Bulgaria" in title

        src_name, src_url = parse_source(html) if page_ok else (None, None)
        suggested = source_to_label(src_name)
        cur = db.get(slug, {})
        cur_source = cur.get("source")

        verdict = "ok"
        notes = []
        if slug in TE_NO_PAGE:
            verdict = "te_no_page"
            notes.append("TE has no BG page for this EconPulse-internal slug")
        elif not page_ok:
            verdict = "te_404"
            notes.append(f"TE page for slug={te_slug} returned generic 404/landing")
        elif not src_name:
            verdict = "unparsed"
            notes.append("Could not parse TE source from page")
        else:
            if suggested == cur_source:
                verdict = "ok"
            elif suggested is None:
                verdict = "unknown_source"
                notes.append(f"unmapped TE source: {src_name!r}")
            else:
                verdict = "source_mismatch"
                notes.append(f"TE says {src_name!r} (suggest={suggested}), DB has {cur_source}")

        findings[slug] = {
            "slug": slug,
            "te_slug": te_slug,
            "te_url": f"https://tradingeconomics.com/bulgaria/{te_slug}",
            "te_title": title or None,
            "te_source_name": src_name,
            "te_source_url": src_url,
            "suggested_label": suggested,
            "db_source": cur_source,
            "db_series_id": cur.get("series_id"),
            "verdict": verdict,
            "notes": notes,
        }

    # Write yaml
    import yaml
    with open("docs/_audit_bg_reaudit.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(findings, f, sort_keys=True, allow_unicode=True, width=120)

    # Print summary
    by_v = {}
    for slug, f in findings.items():
        by_v.setdefault(f["verdict"], []).append(slug)
    print("\n=== BG re-audit summary ===")
    for v in sorted(by_v):
        print(f"  {v}: {len(by_v[v])}")
        for s in by_v[v]:
            print(f"    {s:35s} -> TE={findings[s]['te_source_name']!r}  DB={findings[s]['db_source']}")


if __name__ == "__main__":
    main()
