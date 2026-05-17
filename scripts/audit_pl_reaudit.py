"""Fresh PL re-audit against Trading Economics.

For each PL slug in docs/_audit_all_remaining_slugs.json key PL:
  1. Fetch the TE page via curl (cached under docs/_audit_te_html/pl_reaudit/)
  2. Extract source attribution + headline value + period
  3. Compare to DB indicator_sources + latest data_point
  4. Map TE label -> internal source code
  5. Write findings to docs/_audit_pl_reaudit.yaml

Source-Label rule: technical fetch-source. eurostat==eurostat (even when TE
attributes upstream e.g. GUS or NBP).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.db import supabase as sb  # noqa: E402

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
CACHE_DIR = ROOT / "docs/_audit_te_html/pl_reaudit"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

SOURCE_RE = re.compile(
    r"source:\s*<a class='source-name'[^>]*href\s*=\s*'([^']*)'[^>]*>([^<]+)</a>",
    re.I,
)
DESC_RE = re.compile(r'<h2 id="description"[^>]*>(.*?)</h2>', re.S)
VALUE_RE = re.compile(
    r"(?:to|at|of|reached|stood at|was|by|hit)\s+(-?\d[\d,\.]*)\s*"
    r"(?:%|percent|billion|million|thousand|points|index|USD|EUR|PLN|persons|barrels|beds)",
    re.I,
)
PERIOD_RE = re.compile(
    r"in\s+(January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Q[1-4]|the\s+(?:first|second|third|fourth)\s+quarter)\s*(?:of\s+)?(\d{4})?",
    re.I,
)

# PL-specific TE label -> internal source mapping
LABEL_TO_CODE = [
    ("Statistics Poland", "gus_pl"),
    ("Central Statistical Office of Poland", "gus_pl"),
    ("Główny Urząd Statystyczny", "gus_pl"),
    ("Glowny Urzad Statystyczny", "gus_pl"),
    ("National Bank of Poland", "nbp_pl"),  # provider doesn't exist yet
    ("Narodowy Bank Polski", "nbp_pl"),
    ("NBP", "nbp_pl"),
    ("Ministry of Finance, Poland", "curated"),
    ("Republic of Poland", "curated"),
    ("Eurostat", "eurostat"),
    ("EUROSTAT", "eurostat"),
    ("European Commission", "eurostat"),
    ("European Central Bank", "ecb"),
    ("ECB", "ecb"),
    ("World Bank", "worldbank"),
    ("Transparency International", "curated"),
    ("Conference Board", "curated"),
    ("OECD", "curated"),
    ("World Health Organization", "curated"),
    ("WHO", "curated"),
    ("SIPRI", "curated"),
    ("Stockholm International Peace", "curated"),
    ("Institute for Economics and Peace", "curated"),
]

# Slug -> TE URL path mapping (some slugs differ on TE)
SLUG_TO_TE = {
    "inflation-cpi": "inflation-cpi",
    "core-cpi": "core-inflation-rate",
    "ppi": "producer-prices-change",
    "industrial-production": "industrial-production",
    "manufacturing-production": "manufacturing-production",
    "mining-production": "mining-production",
    "unemployment": "unemployment-rate",
    "unemployment-rate-registered": "unemployment-rate",  # PL TE labels this differently
    "employed-persons": "employed-persons",
    "unemployed-persons": "unemployed-persons",
    "employment-rate": "employment-rate",
    "labor-force-participation-rate": "labor-force-participation-rate",
    "youth-unemployment-rate": "youth-unemployment-rate",
    "long-term-unemployment-rate": "long-term-unemployment-rate",
    "job-vacancies": "job-vacancies",
    "labour-costs": "labour-costs",
    "minimum-wages": "minimum-wages",
    "retail-sales": "retail-sales-annual",
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
    "government-spending-eur": "government-spending-value",
    "government-debt": "government-debt-to-gdp",
    "government-debt-total": "government-debt",
    "current-account": "current-account",
    "current-account-to-gdp": "current-account-to-gdp",
    "exports": "exports",
    "imports": "imports",
    "budget-deficit": "government-budget",
    "population": "population",
    "food-inflation": "food-inflation",
    "services-inflation": "services-inflation",
    "energy-inflation": "energy-inflation",
    "cpi-food": "cpi-housing-utilities",  # PL has cpi-food but uses this category
    "cpi-clothing": "cpi-transportation",
    "cpi-housing-utilities": "cpi-housing-utilities",
    "cpi-transportation": "cpi-transportation",
    "cpi-recreation-and-culture": "cpi-recreation-and-culture",
    "cpi-education": "cpi-education",
    "disposable-personal-income": "disposable-personal-income",
    "corporate-tax-rate": "corporate-tax-rate",
    "personal-income-tax-rate": "personal-income-tax-rate",
    "sales-tax-rate": "sales-tax-rate",
    "social-security-rate": "social-security-rate",
    "social-security-rate-companies": "social-security-rate-for-companies",
    "social-security-rate-employees": "social-security-rate-for-employees",
    "corruption-index": "corruption-index",
    "corruption-rank": "corruption-rank",
    "credit-rating": "rating",
    "retirement-age-men": "retirement-age-men",
    "retirement-age-women": "retirement-age-women",
    "hospital-beds": "hospital-beds",
    "medical-doctors": "medical-doctors",
    "nurses": "nurses",
    "terrorism-index": "terrorism-index",
    "productivity": "productivity",
    "house-price-index": "housing-index",
    "services-sentiment": "services-sentiment",
}


def label_to_code(label: str):
    if not label:
        return None
    low = label.lower()
    for pat, code in LABEL_TO_CODE:
        if pat.lower() in low:
            return code
    return None


def fetch_te(slug: str) -> tuple[int, str, str]:
    te_slug = SLUG_TO_TE.get(slug, slug)
    url = f"https://tradingeconomics.com/poland/{te_slug}"
    cache = CACHE_DIR / f"{slug}.html"
    if cache.exists() and cache.stat().st_size > 1000:
        return 200, cache.read_text(encoding="utf-8", errors="ignore"), url
    try:
        r = subprocess.run(
            ["curl", "-s", "-A", UA, "--max-time", "30",
             "-w", "\n__HTTP__%{http_code}", url],
            capture_output=True, timeout=40,
        )
    except subprocess.TimeoutExpired:
        return 0, "", url
    body = r.stdout.decode("utf-8", errors="ignore")
    m = re.search(r"__HTTP__(\d+)$", body)
    code = int(m.group(1)) if m else 0
    html = body[:m.start()] if m else body
    if code == 200 and html:
        cache.write_text(html, encoding="utf-8")
    return code, html, url


def parse_te(html: str) -> dict:
    out = {"te_label": None, "te_label_href": None, "te_value": None, "te_period": None, "te_desc": None}
    m = SOURCE_RE.search(html)
    if m:
        out["te_label_href"] = m.group(1)
        out["te_label"] = m.group(2).strip()
    m = DESC_RE.search(html)
    if m:
        desc = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        vm = VALUE_RE.search(desc)
        if vm:
            try:
                out["te_value"] = float(vm.group(1).replace(",", ""))
            except ValueError:
                pass
        pm = PERIOD_RE.search(desc)
        if pm:
            out["te_period"] = pm.group(0).strip()
        out["te_desc"] = desc[:500]
    if out["te_value"] is None:
        m2 = re.search(r'class="te-indicator-last"[^>]*>\s*([^<]+)<', html)
        if m2:
            try:
                out["te_value"] = float(m2.group(1).strip().replace(",", ""))
            except ValueError:
                pass
    return out


def audit_slug(slug: str) -> dict:
    code, html, url = fetch_te(slug)
    parsed = {"te_label": None, "te_value": None, "te_period": None, "te_desc": None}
    if code == 200 and html:
        parsed = parse_te(html)

    try:
        row_resp = (
            sb.table("indicator_sources")
            .select("*")
            .eq("country", "PL")
            .eq("indicator", slug)
            .eq("is_default", True)
            .execute()
        )
        row = row_resp.data[0] if row_resp.data else None
    except Exception as e:
        row = None
        print(f"  ERR row: {e}")

    try:
        q = sb.table("data_points").select("date,value,unit,source").eq("country", "PL").eq("indicator", slug)
        if row and row.get("source"):
            q = q.eq("source", row["source"])
        dp_resp = q.order("date", desc=True).limit(13).execute()
        dps = dp_resp.data or []
    except Exception as e:
        dps = []
        print(f"  ERR dp: {e}")

    latest = dps[0] if dps else None

    suggested = label_to_code(parsed.get("te_label") or "")
    our_source = row.get("source") if row else None
    our_series = row.get("series_id") if row else None
    our_value = latest["value"] if latest else None
    our_date = latest["date"] if latest else None

    # Source match: nbp_pl -> we accept eurostat as honest fallback
    if suggested == "nbp_pl" and our_source == "eurostat":
        source_match = "fallback_eurostat_for_nbp"
    elif suggested and our_source:
        source_match = (suggested == our_source)
    else:
        source_match = None

    te_v = parsed.get("te_value")
    value_match = None
    yoy_value = None
    if te_v is not None and our_value is not None:
        try:
            denom = abs(te_v) if abs(te_v) > 1e-9 else 1.0
            diff = abs(te_v - our_value) / denom
            value_match = diff <= 0.05
        except Exception:
            value_match = None
        if value_match is False and len(dps) >= 13:
            try:
                prior = dps[12]["value"]
                if prior:
                    yoy = (our_value - prior) / abs(prior) * 100
                    yoy_value = yoy
                    denom = abs(te_v) if abs(te_v) > 1e-9 else 1.0
                    if abs(te_v - yoy) / denom <= 0.05:
                        value_match = True
            except Exception:
                pass
        # Special: index value where our_value is "1xx.x" YoY-index but TE shows "x.x%"
        if value_match is False:
            try:
                if 80 <= our_value <= 130 and -10 <= te_v <= 30:
                    inferred = our_value - 100
                    denom = abs(te_v) if abs(te_v) > 1e-9 else 1.0
                    if abs(te_v - inferred) / denom <= 0.05:
                        value_match = "yoy_from_index"
                        yoy_value = inferred
            except Exception:
                pass

    return {
        "te_url": url,
        "te_http": code,
        "te_label": parsed.get("te_label"),
        "te_label_href": parsed.get("te_label_href"),
        "te_value": te_v,
        "te_period": parsed.get("te_period"),
        "te_desc": parsed.get("te_desc"),
        "our_source": our_source,
        "our_series": our_series,
        "our_value": our_value,
        "our_period": our_date,
        "suggested_source": suggested,
        "source_match": source_match,
        "value_match": value_match,
        "yoy_computed": yoy_value,
        "fixed": False,
        "fix_summary": None,
        "flag": None,
    }


def main():
    with open(ROOT / "docs/_audit_all_remaining_slugs.json", encoding="utf-8") as f:
        slugs = json.load(f)["PL"]
    print(f"Auditing {len(slugs)} PL slugs...")
    findings = {}
    for i, slug in enumerate(slugs, 1):
        cache = CACHE_DIR / f"{slug}.html"
        is_cached = cache.exists() and cache.stat().st_size > 1000
        f = audit_slug(slug)
        findings[slug] = f
        marker = "C" if is_cached else "F"
        match_str = f"src={f['source_match']} val={f['value_match']}"
        print(f"[{i}/{len(slugs)}] {marker} {slug}: te_label={(f['te_label'] or '')[:35]!r} te_v={f['te_value']} our_v={f['our_value']} ({match_str})")
        if not is_cached:
            time.sleep(8)
    out_path = ROOT / "docs/_audit_pl_reaudit.yaml"
    with open(out_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(findings, f, sort_keys=True, allow_unicode=True, width=200)
    print(f"\nWrote {out_path}")
    ok = sum(1 for v in findings.values() if v["source_match"] is True and v["value_match"] is True)
    src_miss = sum(1 for v in findings.values() if v["source_match"] is False)
    val_miss = sum(1 for v in findings.values() if v["value_match"] is False)
    no_dp = sum(1 for v in findings.values() if v["our_value"] is None)
    no_te = sum(1 for v in findings.values() if v["te_value"] is None)
    print(f"\nSummary: total={len(findings)} ok={ok} src_miss={src_miss} val_miss={val_miss} no_dp={no_dp} no_te={no_te}")


if __name__ == "__main__":
    main()
