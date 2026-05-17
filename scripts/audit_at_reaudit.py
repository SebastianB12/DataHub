"""Fresh AT re-audit of all 69 slugs vs Trading Economics.

For each slug in docs/_audit_all_remaining_slugs.json key 'AT':
  1. Fetch the TE page via curl (slug mapped via SLUG_TO_TE).
  2. Parse source-name + headline value + period from the description.
  3. Compare to our indicator_sources row + latest data_point.
  4. Honest source-label policy: source = technical fetch (eurostat/stat_at/...).
  5. Write findings to docs/_audit_at_reaudit.yaml.

Slug map for AT specifics (in addition to scripts.te_inventory_slow.SLUG_TO_TE):
  inflation-cpi -> inflation-cpi (TE: inflation-cpi)
  budget-deficit -> government-budget
  unemployment -> unemployment-rate
  trade-balance -> balance-of-trade
  gdp-real -> gdp-growth-annual
  current-account -> current-account
  long-term-unemployment-rate -> long-term-unemployment-rate
  ...
"""
from __future__ import annotations

import json
import os
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

# TE country path for AT
TE_COUNTRY = "austria"

# AT-specific TE slug map (covers items not in the shared SLUG_TO_TE)
AT_SLUG_TO_TE = {
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
    "wages": "wages",
    "labour-costs": "labour-costs",
    "minimum-wages": "minimum-wages",
    "retail-sales": "retail-sales",  # AT TE page is /austria/retail-sales (MoM)
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
    "government-debt": "government-debt",
    "government-debt-total": "government-debt",
    "current-account": "current-account",
    "current-account-to-gdp": "current-account-to-gdp",
    "trade-balance": "balance-of-trade",
    "exports": "exports",
    "imports": "imports",
    "budget-deficit": "government-budget",
    "population": "population",
    "interest-rate": "interest-rate",
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
    "social-security-rate-companies": "social-security-rate-for-companies",
    "social-security-rate-employees": "social-security-rate-for-employees",
    "corruption-index": "corruption-index",
    "corruption-rank": "corruption-rank",
    "credit-rating": "rating",
    "hospital-beds": "hospital-beds",
    "house-price-index": "housing-index",
    "medical-doctors": "medical-doctors",
    "nurses": "nurses",
    "import-prices": "import-prices",
    "productivity": "productivity",
    "retirement-age-men": "retirement-age-men",
    "retirement-age-women": "retirement-age-women",
    "services-sentiment": "services-pmi",  # TE doesn't always have services-sentiment
    "terrorism-index": "terrorism-index",
}

# Map TE source labels -> our internal source code (technical fetch label)
LABEL_TO_CODE = [
    ("Statistik Austria", "stat_at"),
    ("Statistics Austria", "stat_at"),
    ("Oesterreichische Nationalbank", "oenb_at"),
    ("Austrian National Bank", "oenb_at"),
    ("OeNB", "oenb_at"),
    ("National Bank of Austria", "oenb_at"),
    ("Eurostat", "eurostat"),
    ("European Central Bank", "ecb"),
    ("ECB", "ecb"),
    ("European Commission", "eurostat"),  # Commission BCS surveys = eurostat fetch
    ("Federal Ministry of Finance", "curated"),
    ("Bundesministerium", "curated"),
    ("Federal Reserve", "fred"),
    ("FRED", "fred"),
    ("World Bank", "worldbank"),
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
    ("BMG", "curated"),
]


SOURCE_RE = re.compile(
    r"source:\s*<a class='source-name'[^>]*href\s*=\s*'([^']*)'[^>]*>([^<]+)</a>",
    re.I,
)
DESC_RE = re.compile(r'<h2 id="description"[^>]*>(.*?)</h2>', re.S)
# Generic numeric extractor — find first number near 'to|at|of|rose to|reached'
VALUE_RE = re.compile(
    r"(?:to|at|of|reached|stood at|was|by|rose to|fell to|increased to|decreased to|"
    r"climbed to|edged up to|edged down to)\s+(-?\d[\d,\.]*)",
    re.I,
)
# Period extractor like "in April 2026" or "in Q1 2026"
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
    te_slug = AT_SLUG_TO_TE.get(slug, slug)
    url = f"https://tradingeconomics.com/{TE_COUNTRY}/{te_slug}"
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
    return code, html, url


def parse_te(html: str) -> dict:
    out: dict = {"te_label": None, "te_label_href": None,
                 "te_value": None, "te_period": None, "te_desc": None}
    m = SOURCE_RE.search(html)
    if m:
        out["te_label_href"] = m.group(1)
        out["te_label"] = m.group(2).strip()
    # metaDesc is the most reliable single-line summary
    m_meta = re.search(r'metaDesc[^>]*content="([^"]+)"', html)
    if m_meta:
        meta = m_meta.group(1)
        # Patterns: "increased to 3.30 percent in April from", "to EUR 2.67 billion in Q4"
        # Special: "Austria scored 69 points out of 100" / "Austria is the 21 least corrupt"
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
        # extract period
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
    # Description (longer text) - use only if metaDesc didn't give us a value
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
            .eq("country", "AT")
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
            .eq("country", "AT")
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
            # YoY check (M=13, Q=5, A=2)
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
            # MoM check
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
        slugs = json.load(f)["AT"]

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
        # tiny pause to be polite
        time.sleep(0.4)

    out_path = ROOT / "docs/_audit_at_reaudit.yaml"
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
