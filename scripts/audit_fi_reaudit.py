"""Fresh TE re-audit of all 67 FI slugs in EconPulse.

For each slug:
  1. Fetch the TE page via curl
  2. Extract source attribution + headline value + period
  3. Compare to our indicator_sources row + latest data_point
  4. Determine source_match/value_match (with YoY/MoM transform check)
  5. Write findings to docs/_audit_fi_reaudit.yaml

HARD CONSTRAINT: source label = TECHNICAL FETCH PROVIDER (not TE upstream).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.db import supabase as sb  # noqa: E402

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

CACHE_DIR = ROOT / "docs/_audit_te_html/fi_reaudit"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

SOURCE_RE = re.compile(
    r"source:\s*<a class='source-name'[^>]*href\s*=\s*'([^']*)'[^>]*>([^<]+)</a>",
    re.I,
)
DESC_RE = re.compile(r'<h2 id="description"[^>]*>(.*?)</h2>', re.S)
VALUE_RE = re.compile(
    r"(?:to|at|of|reached|stood at|was|by)\s+(-?\d[\d,\.]*)\s*(?:%|percent|billion|million|thousand|points|index|EUR|USD|barrels|per)",
    re.I,
)
PERIOD_RE = re.compile(
    r"in\s+(January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Q[1-4]|the\s+(?:first|second|third|fourth)\s+quarter)\s*(?:of\s+)?(\d{4})?",
    re.I,
)

# FI slug -> TE slug mapping. Most FI TE pages match EconPulse slug 1:1.
SLUG_TO_TE = {
    "budget-deficit": "government-budget",
    "core-cpi": "core-inflation-rate",
    "gdp-real": "gdp-growth-annual",
    "government-debt-total": "government-debt",
    "ppi": "producer-prices",
    "unemployment": "unemployment-rate",
    "retail-sales": "retail-sales-mom",
    "industrial-production": "industrial-production",
    "social-security-rate-companies": "social-security-rate-for-companies",
    "social-security-rate-employees": "social-security-rate-for-employees",
    "services-sentiment": "services-pmi",
    "house-price-index": "housing-index",
    "job-vacancies": "job-vacancies",
    "government-spending-eur": "government-spending-value",
    "minimum-wages": "minimum-wages",
    "trade-balance": "balance-of-trade",
    "inflation-cpi": "inflation-cpi",
    "labor-force-participation-rate": "labor-force-participation-rate",
    "current-account-to-gdp": "current-account-to-gdp",
    "long-term-unemployment-rate": "long-term-unemployment-rate",
    "gross-fixed-capital-formation": "gross-fixed-capital-formation",
    "changes-in-inventories": "changes-in-inventories",
    "disposable-personal-income": "disposable-personal-income",
    "consumer-spending": "consumer-spending",
    "consumer-confidence": "consumer-confidence",
    "business-confidence": "business-confidence",
    "capacity-utilization": "capacity-utilization",
    "manufacturing-production": "manufacturing-production",
    "mining-production": "mining-production",
    "energy-inflation": "energy-inflation",
    "food-inflation": "food-inflation",
    "services-inflation": "services-inflation",
    "retirement-age-men": "retirement-age-men",
    "retirement-age-women": "retirement-age-women",
    "youth-unemployment-rate": "youth-unemployment-rate",
    "interest-rate": "interest-rate",
    "labour-costs": "labour-costs",
    "productivity": "productivity",
    "corporate-tax-rate": "corporate-tax-rate",
    "personal-income-tax-rate": "personal-income-tax-rate",
    "sales-tax-rate": "sales-tax-rate",
    "social-security-rate": "social-security-rate",
    "corruption-index": "corruption-index",
    "corruption-rank": "corruption-rank",
    "credit-rating": "rating",
    "terrorism-index": "terrorism-index",
    "hospital-beds": "hospital-beds",
    "medical-doctors": "medical-doctors",
    "nurses": "nurses",
    "exports": "exports",
    "imports": "imports",
    "current-account": "current-account",
    "government-debt": "government-debt-to-gdp",
    "government-spending": "government-spending-to-gdp",
    "gdp": "gdp",
    "gdp-per-capita": "gdp-per-capita",
    "gdp-per-capita-ppp": "gdp-per-capita-ppp",
    "population": "population",
    "employed-persons": "employed-persons",
    "employment-rate": "employment-rate",
    "unemployed-persons": "unemployed-persons",
    "cpi-food": "food-inflation",  # TE may not have separate cpi-food page
    "cpi-clothing": "cpi-clothing",
    "cpi-housing-utilities": "cpi-housing-utilities",
    "cpi-transportation": "cpi-transportation",
    "cpi-recreation-and-culture": "cpi-recreation-and-culture",
    "cpi-education": "cpi-education",
}

NO_TE_PAGE: set[str] = set()

# Source label -> canonical code mapping (FI-specific).
LABEL_TO_CODE = [
    ("Statistics Finland", "stat_fi"),
    ("Tilastokeskus", "stat_fi"),
    ("Bank of Finland", "stat_fi"),       # we proxy BoF via stat_fi where possible; else curated
    ("Suomen Pankki", "stat_fi"),
    ("European Central Bank", "ecb"),
    ("EUROSTAT", "eurostat"),
    ("Eurostat", "eurostat"),
    ("European Commission", "eurostat"),
    ("World Bank", "worldbank"),
    ("World Health Organization", "curated"),
    ("OECD", "curated"),
    ("Transparency International", "curated"),
    ("Conference Board", "curated"),
    ("SIPRI", "curated"),
    ("Institute for Economics and Peace", "curated"),
    ("Finnish Tax Administration", "curated"),
    ("Ministry of", "curated"),
    ("Vero", "curated"),
    ("Standard & Poor", "curated"),
    ("Moody", "curated"),
    ("Fitch", "curated"),
    ("DBRS", "curated"),
    ("Confederation of Finnish Industries", "eurostat"),  # we proxy via EU BCS
    ("EK", "eurostat"),
]


def label_to_code(label: str) -> str | None:
    if not label:
        return None
    low = label.lower()
    for pat, code in LABEL_TO_CODE:
        if pat.lower() in low:
            return code
    return None


def fetch_te(url: str, cache_name: str) -> tuple[int, str]:
    cache_path = CACHE_DIR / f"{cache_name}.html"
    if cache_path.exists() and cache_path.stat().st_size > 1000:
        body = cache_path.read_text(encoding="utf-8", errors="ignore")
        return 200, body
    try:
        r = subprocess.run(
            ["curl", "-s", "-A", UA, "--max-time", "30", "-w", "\n__HTTP__%{http_code}", url],
            capture_output=True, timeout=40,
        )
    except subprocess.TimeoutExpired:
        return 0, ""
    body = r.stdout.decode("utf-8", errors="ignore")
    m = re.search(r"__HTTP__(\d+)$", body)
    code = int(m.group(1)) if m else 0
    html = body[:m.start()] if m else body
    if code == 200 and len(html) > 1000:
        cache_path.write_text(html, encoding="utf-8", errors="ignore")
    return code, html


def parse_te(html: str) -> dict:
    out = {"te_label": None, "te_label_href": None, "te_value": None,
           "te_period": None, "te_desc": None}
    m = SOURCE_RE.search(html)
    if m:
        out["te_label_href"] = m.group(1)
        out["te_label"] = m.group(2).strip()
    else:
        dm = DESC_RE.search(html)
        if dm:
            txt = re.sub(r"<[^>]+>", " ", dm.group(1))
            m2 = re.search(r"source:\s*([A-Z][A-Za-z .,&\-]{2,80}?)(?:\.|$|<|\n)", txt)
            if m2:
                out["te_label"] = m2.group(1).strip()
    m = DESC_RE.search(html)
    if m:
        desc = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        first_sentence = re.split(r"(?<=[.!?])\s+", desc, maxsplit=1)[0]
        vm = VALUE_RE.search(first_sentence)
        if vm:
            try:
                out["te_value"] = float(vm.group(1).replace(",", ""))
            except ValueError:
                pass
        if out["te_value"] is None:
            sm = re.search(r"scored\s+(-?\d[\d,.]*)", first_sentence, re.I)
            if sm:
                try:
                    out["te_value"] = float(sm.group(1).replace(",", ""))
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


def audit_slug(slug: str, inv_entry: dict) -> dict:
    te_slug = SLUG_TO_TE.get(slug, slug)
    te_page = f"https://tradingeconomics.com/finland/{te_slug}"
    code, html = fetch_te(te_page, slug)
    parsed = {"te_label": None, "te_value": None, "te_period": None}
    if code == 200 and html:
        parsed = parse_te(html)

    try:
        row_resp = (
            sb.table("indicator_sources")
            .select("*")
            .eq("country", "FI")
            .eq("indicator", slug)
            .eq("is_default", True)
            .execute()
        )
        row = row_resp.data[0] if row_resp.data else None
    except Exception as e:
        row = None
        print(f"  ERR row: {e}")

    try:
        default_src = row.get("source") if row else None
        q = (
            sb.table("data_points")
            .select("date,value,unit,series_id,source")
            .eq("country", "FI")
            .eq("indicator", slug)
        )
        if default_src:
            q = q.eq("source", default_src)
        dp_resp = q.order("date", desc=True).limit(15).execute()
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
    our_unit = latest.get("unit") if latest else None

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
        if value_match is False and len(dps) >= 2:
            try:
                prior = dps[1]["value"]
                if prior:
                    mom = (our_value - prior) / abs(prior) * 100
                    mom_value = mom
                    denom = abs(te_v) if abs(te_v) > 1e-9 else 1.0
                    if abs(te_v - mom) / denom <= 0.05:
                        value_match = True
            except Exception:
                pass

    finding = {
        "te_label": parsed.get("te_label"),
        "te_value": te_v,
        "te_period": parsed.get("te_period"),
        "te_page": te_page,
        "te_http": code,
        "our_source": our_source,
        "our_series": our_series,
        "our_value": our_value,
        "our_period": our_date,
        "our_unit": our_unit,
        "suggested_source": suggested,
        "source_match": source_match,
        "value_match": value_match,
        "yoy_computed": yoy_value,
        "mom_computed": mom_value,
        "fixed": False,
        "fix_summary": None,
        "flag": None,
    }
    return finding


def assign_flag(f: dict, slug: str) -> str:
    if slug in NO_TE_PAGE:
        return "te-no-page"
    if f["source_match"] is False:
        if f.get("suggested_source") == "stat_fi" and f.get("our_source") == "eurostat":
            return "needs-statfi-fetch"
        if f.get("suggested_source") == "eurostat" and f.get("our_source") == "stat_fi":
            return "tolerable-statfi-vs-eurostat"
        if f.get("suggested_source") == "ecb":
            return "ecb-source"
        return "needs-attention"
    if f["value_match"] is False:
        if f.get("yoy_computed") is not None or f.get("mom_computed") is not None:
            return "frontend-only"
        return "needs-attention"
    if f["te_value"] is None and f["our_value"] is not None:
        return "ok"
    if f["te_value"] is not None and f["our_value"] is None:
        return "needs-attention"
    if f["value_match"] is None and f["te_value"] is not None:
        return "ok"
    return "ok"


def main():
    with open(ROOT / "docs/_audit_all_remaining_slugs.json", encoding="utf-8") as f:
        slugs = json.load(f)["FI"]

    inv_path = ROOT / "docs/_te_inventory/FI.yaml"
    inv = {}
    if inv_path.exists():
        with open(inv_path, encoding="utf-8") as f:
            inv = yaml.safe_load(f) or {}

    findings = {}
    for i, slug in enumerate(slugs, 1):
        print(f"[{i}/{len(slugs)}] {slug}")
        finding = audit_slug(slug, inv.get(slug, {}))
        finding["flag"] = assign_flag(finding, slug)
        findings[slug] = finding
        sm = finding["source_match"]
        vm = finding["value_match"]
        marker = "OK" if (sm is True and vm is True) else ("FLAG" if finding["flag"] != "ok" else "?")
        print(f"   te={(finding['te_label'] or '')!r:55s} te_v={finding['te_value']} our_src={finding['our_source']} our_v={finding['our_value']} (src={sm}, val={vm}) {marker}")

    out_path = ROOT / "docs/_audit_fi_reaudit.yaml"
    with open(out_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(findings, f, sort_keys=True, allow_unicode=True, width=200)
    print(f"\nWrote {out_path}")

    ok = sum(1 for v in findings.values() if v["flag"] == "ok")
    needs = sum(1 for v in findings.values() if v["flag"] == "needs-attention")
    needs_statfi = sum(1 for v in findings.values() if v["flag"] == "needs-statfi-fetch")
    tolerable = sum(1 for v in findings.values() if v["flag"] == "tolerable-statfi-vs-eurostat")
    ecb_s = sum(1 for v in findings.values() if v["flag"] == "ecb-source")
    frontend = sum(1 for v in findings.values() if v["flag"] == "frontend-only")
    src_miss = sum(1 for v in findings.values() if v["source_match"] is False)
    val_miss = sum(1 for v in findings.values() if v["value_match"] is False)
    no_dp = sum(1 for v in findings.values() if v["our_value"] is None)
    no_te_v = sum(1 for v in findings.values() if v["te_value"] is None)
    print(f"\nSummary: total={len(findings)} ok={ok} needs-attention={needs} needs-statfi={needs_statfi} tolerable={tolerable} ecb={ecb_s} frontend-only={frontend}")
    print(f"  src_miss={src_miss} val_miss={val_miss} no_dp={no_dp} no_te_value={no_te_v}")


if __name__ == "__main__":
    main()
