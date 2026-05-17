"""Fresh CY re-audit of all 67 slugs vs Trading Economics.

For each slug in docs/_audit_all_remaining_slugs.json key 'CY':
  1. Fetch the TE page (cyprus/<te-slug>) via curl.
  2. Parse source-name + headline value + period.
  3. Compare to indicator_sources row + latest data_point.
  4. Honest source-label = technical fetch (cystat_cy/eurostat/ecb/curated/worldbank).
  5. Write findings to docs/_audit_cy_reaudit.yaml.
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

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

TE_COUNTRY = "cyprus"
HTML_DIR = ROOT / "docs/_audit_te_html/cy_reaudit"
HTML_DIR.mkdir(parents=True, exist_ok=True)

CY_SLUG_TO_TE = {
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
    "cpi-clothing": "cpi-clothing",
    "cpi-education": "cpi-education",
    "cpi-food": "cpi-food",
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
    "government-debt": "government-debt-to-gdp",
    "government-debt-total": "government-debt",
    "government-spending": "government-spending",
    "government-spending-eur": "government-spending-value",
    "gross-fixed-capital-formation": "gross-fixed-capital-formation",
    "hospital-beds": "hospital-beds",
    "house-price-index": "housing-index",
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
    "youth-unemployment-rate": "youth-unemployment-rate",
}

# Map TE source labels -> our internal source code (technical fetch label).
LABEL_TO_CODE = [
    ("Statistical Service of the Republic of Cyprus", "cystat_cy"),
    ("Statistical Service of Cyprus", "cystat_cy"),
    ("Statistical Service of Republic of Cyprus", "cystat_cy"),
    ("CYSTAT", "cystat_cy"),
    ("Statistics of Cyprus", "cystat_cy"),
    ("Cystat", "cystat_cy"),
    ("Central Bank of Cyprus", "ecb"),  # CBC publishes via ECB SDW for harmonised rates; for CY specifics use cbc
    ("Eurostat", "eurostat"),
    ("European Commission", "eurostat"),  # BCS surveys
    ("European Central Bank", "ecb"),
    ("ECB", "ecb"),
    ("World Bank", "worldbank"),
    ("Federal Reserve", "fred"),
    ("FRED", "fred"),
    ("OECD", "curated"),
    ("Transparency International", "curated"),
    ("Conference Board", "curated"),
    ("Institute for Economics and Peace", "curated"),
    ("Standard & Poors", "curated"),
    ("Standard & Poor", "curated"),
    ("Moody", "curated"),
    ("Fitch", "curated"),
    ("WHO", "curated"),
    ("World Health Organization", "curated"),
    ("SIPRI", "curated"),
    ("Markit", "curated"),
    ("S&P", "curated"),
    ("ICRG", "curated"),
    ("Ministry of Finance", "curated"),
    ("Tax Department", "curated"),
    ("PwC", "curated"),
    ("KPMG", "curated"),
]

SOURCE_RE = re.compile(
    r"source:\s*<a class='source-name'[^>]*href\s*=\s*'([^']*)'[^>]*>([^<]+)</a>",
    re.I,
)
DESC_RE = re.compile(r'<h2 id="description"[^>]*>(.*?)</h2>', re.S)
VALUE_RE = re.compile(
    r"(?:to|at|of|reached|stood at|was|by|rose to|fell to|increased to|decreased to|"
    r"climbed to|edged up to|edged down to)\s+(-?\d[\d,\.]*)",
    re.I,
)
PERIOD_RE = re.compile(
    r"in\s+(January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Q[1-4]|the\s+(?:first|second|third|fourth)\s+quarter)\s*(?:of\s+)?(\d{4})?",
    re.I,
)


def label_to_code(label: str) -> str | None:
    if not label:
        return None
    low = label.lower()
    for pat, code in LABEL_TO_CODE:
        if pat.lower() in low:
            return code
    return None


def fetch_te(slug: str) -> tuple[int, str, str]:
    te_slug = CY_SLUG_TO_TE.get(slug, slug)
    url = f"https://tradingeconomics.com/{TE_COUNTRY}/{te_slug}"
    cache = HTML_DIR / f"{slug}.html"
    if cache.exists() and cache.stat().st_size > 1000:
        return 200, cache.read_text("utf-8", errors="ignore"), url
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
    if code == 200 and len(html) > 1000:
        cache.write_text(html, "utf-8")
    return code, html, url


def parse_te(html: str) -> dict:
    out: dict = {"te_label": None, "te_label_href": None,
                 "te_value": None, "te_period": None, "te_desc": None}
    m = SOURCE_RE.search(html)
    if m:
        out["te_label_href"] = m.group(1)
        out["te_label"] = m.group(2).strip()
    m_meta = re.search(r'metaDesc[^>]*content="([^"]+)"', html)
    if m_meta:
        meta = m_meta.group(1)
        vm = re.search(
            r"(?:scored|is the)\s+(-?\d[\d,\.]*)\s*(?:points|least|most)",
            meta, re.I,
        )
        if not vm:
            vm = re.search(
                r"(?:to|at|reached|stood at|hit|of|recorded at|was worth|"
                r"was last recorded at|increased to|decreased to|rose to|"
                r"fell to|set at|scored)\s+"
                r"(?:[A-Z]{3}\s+)?"
                r"(-?\d[\d,\.]*)\s*"
                r"(?:%|percent|points|index|million|billion|thousand|EUR|USD|"
                r"US dollars|dollars|per\s+\d+|years?|months?|Million|Billion|"
                r"Thousand|per 1000 people|per 1,000 people)",
                meta,
            )
        if vm:
            try:
                out["te_value"] = float(vm.group(1).replace(",", ""))
            except ValueError:
                pass
        pm = re.search(
            r"in\s+(January|February|March|April|May|June|July|August|"
            r"September|October|November|December|Q[1-4]|"
            r"the\s+(?:first|second|third|fourth)\s+quarter)\s*"
            r"(?:of\s+)?(\d{4})?",
            meta,
        )
        if pm:
            out["te_period"] = pm.group(0).strip()
        out["te_desc"] = meta[:400]
    m = DESC_RE.search(html)
    if m:
        desc = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        if not out.get("te_desc"):
            out["te_desc"] = desc[:400]
        if out["te_value"] is None:
            vm = VALUE_RE.search(desc)
            if vm:
                try:
                    out["te_value"] = float(vm.group(1).replace(",", ""))
                except ValueError:
                    pass
        if not out.get("te_period"):
            pm = PERIOD_RE.search(desc)
            if pm:
                out["te_period"] = pm.group(0).strip()
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
            .eq("country", "CY")
            .eq("indicator", slug)
            .eq("is_default", True)
            .execute()
        )
        row = row_resp.data[0] if row_resp.data else None
    except Exception as e:
        row = None
        print(f"  ERR row: {e}")

    try:
        dp_q = (
            sb.table("data_points")
            .select("date,value,source")
            .eq("country", "CY")
            .eq("indicator", slug)
        )
        if row and row.get("source"):
            dp_q = dp_q.eq("source", row["source"])
        dp_resp = dp_q.order("date", desc=True).limit(13).execute()
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

    source_match = (suggested == our_source) if (suggested and our_source) else None

    te_v = parsed.get("te_value")
    value_match = None
    yoy_value = None
    mom_value = None
    if te_v is not None and our_value is not None:
        try:
            denom = abs(te_v) if abs(te_v) > 1e-9 else 1.0
            diff = abs(te_v - our_value) / denom
            value_match = diff <= 0.05
        except Exception:
            value_match = None
        if value_match is False and len(dps) >= 2:
            for lag in (12, 4, 1):
                if len(dps) > lag:
                    try:
                        prior = dps[lag]["value"]
                        if prior:
                            yoy = (our_value - prior) / abs(prior) * 100
                            denom = abs(te_v) if abs(te_v) > 1e-9 else 1.0
                            if abs(te_v - yoy) / denom <= 0.05:
                                value_match = True
                                yoy_value = yoy
                                break
                    except Exception:
                        pass
            if value_match is False and len(dps) >= 2:
                try:
                    prior = dps[1]["value"]
                    if prior:
                        mom = (our_value - prior) / abs(prior) * 100
                        denom = abs(te_v) if abs(te_v) > 1e-9 else 1.0
                        if abs(te_v - mom) / denom <= 0.05:
                            value_match = True
                            mom_value = mom
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
        "mom_computed": mom_value,
        "fixed": False,
        "fix_summary": None,
        "flag": None,
    }


def main():
    with open(ROOT / "docs/_audit_all_remaining_slugs.json", encoding="utf-8") as f:
        slugs = json.load(f)["CY"]

    findings: dict = {}
    for i, slug in enumerate(slugs, 1):
        print(f"[{i}/{len(slugs)}] {slug}")
        finding = audit_slug(slug)
        findings[slug] = finding
        ok = "OK" if (finding["source_match"] and finding["value_match"]) else "?"
        print(f"   te_label={(finding['te_label'] or '')[:40]:40s} "
              f"te_v={finding['te_value']} our_src={finding['our_source']} "
              f"our_v={finding['our_value']} match=(src={finding['source_match']}, "
              f"val={finding['value_match']}) {ok}")
        time.sleep(0.4)

    out_path = ROOT / "docs/_audit_cy_reaudit.yaml"
    with open(out_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(findings, f, sort_keys=True, allow_unicode=True, width=200)
    print(f"\nWrote {out_path}")

    ok = sum(1 for v in findings.values() if v["source_match"] and v["value_match"])
    src_miss = sum(1 for v in findings.values() if v["source_match"] is False)
    val_miss = sum(1 for v in findings.values() if v["value_match"] is False)
    no_dp = sum(1 for v in findings.values() if v["our_value"] is None)
    no_te = sum(1 for v in findings.values() if v["te_value"] is None)
    no_te_label = sum(1 for v in findings.values() if v["te_label"] is None)
    print(f"\nSummary: total={len(findings)} ok={ok} "
          f"src_miss={src_miss} val_miss={val_miss} "
          f"no_dp={no_dp} no_te_value={no_te} no_te_label={no_te_label}")


if __name__ == "__main__":
    main()
