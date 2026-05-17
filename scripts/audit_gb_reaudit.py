"""Fresh TE re-audit of all 47 GB slugs in EconPulse.

For each slug:
  1. Fetch the TE page via curl (resolves both direct + mapped TE slugs)
  2. Extract source attribution + headline value + period
  3. Compare to our indicator_sources row + latest data_point
  4. Determine source_match/value_match (including YoY transform check)
  5. Write findings to docs/_audit_gb_reaudit.yaml
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.db import supabase as sb  # noqa: E402

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

SOURCE_RE = re.compile(
    r"source:\s*<a class='source-name'[^>]*href\s*=\s*'([^']*)'[^>]*>([^<]+)</a>",
    re.I,
)
DESC_RE = re.compile(r'<h2 id="description"[^>]*>(.*?)</h2>', re.S)
VALUE_RE = re.compile(
    r"(?:to|at|of|reached|stood at|was|by)\s+(-?\d[\d,\.]*)\s*(?:%|percent|billion|million|thousand|points|index|GBP|USD|barrels|per)",
    re.I,
)
PERIOD_RE = re.compile(
    r"in\s+(January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Q[1-4]|the\s+(?:first|second|third|fourth)\s+quarter)\s*(?:of\s+)?(\d{4})?",
    re.I,
)

# GB slug → TE slug mapping (used when direct slug 404s or returns wrong page)
SLUG_TO_TE = {
    "budget-deficit": "government-budget",
    "central-bank-balance": "central-bank-balance-sheet",
    "core-cpi": "core-inflation-rate",
    "gdp-real": "gdp-constant-prices",
    "government-debt": "government-debt",
    "inflation-cpi": "inflation-cpi",
    "interest-rate": "interest-rate",
    "labor-force-participation-rate": "labor-force-participation-rate",
    "ppi": "producer-prices",
    "retail-sales": "retail-sales",
    "social-security-rate-companies": "social-security-rate-for-companies",
    "social-security-rate-employees": "social-security-rate-for-employees",
    "trade-balance": "balance-of-trade",
    "unemployment": "unemployment-rate",
    "hospitals": "hospital",  # TE GB uses /hospital (singular)
}

LABEL_TO_CODE = [
    ("Office for National Statistics", "ons"),
    ("ONS", "ons"),
    ("Bank of England", "ons"),  # routed via ons provider
    ("HM Revenue", "curated"),
    ("HMRC", "curated"),
    ("Department for Work and Pensions", "curated"),
    ("Department for Education", "curated"),
    ("World Bank", "worldbank"),
    ("World Health Organization", "curated"),
    ("OECD", "curated"),
    ("Transparency International", "curated"),
    ("Conference Board", "curated"),
    ("SIPRI", "curated"),
    ("HM Treasury", "curated"),
]


def label_to_code(label: str) -> str | None:
    if not label:
        return None
    low = label.lower()
    for pat, code in LABEL_TO_CODE:
        if pat.lower() in low:
            return code
    return None


def fetch_te(url: str) -> tuple[int, str]:
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
    return code, (body[:m.start()] if m else body)


def parse_te(html: str) -> dict:
    out = {"te_label": None, "te_label_href": None, "te_value": None,
           "te_period": None, "te_desc": None}
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
    # Fallback for value in <span class="te-indicator-last">
    if out["te_value"] is None:
        m2 = re.search(r'class="te-indicator-last"[^>]*>\s*([^<]+)<', html)
        if m2:
            try:
                out["te_value"] = float(m2.group(1).strip().replace(",", ""))
            except ValueError:
                pass
    return out


def audit_slug(slug: str, inv_entry: dict) -> dict:
    # Build TE URL: prefer inventory te_page, else mapped slug
    te_slug = SLUG_TO_TE.get(slug, slug)
    te_page = (inv_entry or {}).get("te_page") or f"https://tradingeconomics.com/united-kingdom/{te_slug}"
    code, html = fetch_te(te_page)
    parsed = {"te_label": None, "te_value": None, "te_period": None}
    if code == 200 and html:
        parsed = parse_te(html)

    # DB row
    try:
        row_resp = (
            sb.table("indicator_sources")
            .select("*")
            .eq("country", "GB")
            .eq("indicator", slug)
            .eq("is_default", True)
            .execute()
        )
        row = row_resp.data[0] if row_resp.data else None
    except Exception as e:
        row = None
        print(f"  ERR row: {e}")

    # latest data points
    try:
        dp_resp = (
            sb.table("data_points")
            .select("date,value,unit,series_id,source")
            .eq("country", "GB")
            .eq("indicator", slug)
            .order("date", desc=True)
            .limit(15)
            .execute()
        )
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
        # if level doesn't match, try YoY and MoM transforms
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


def assign_flag(f: dict) -> str:
    if f["source_match"] is False:
        return "needs-attention"
    if f["value_match"] is False:
        return "needs-attention"
    if f["te_value"] is None and f["our_value"] is not None:
        # No TE value parsed but we have data; mark frontend-transform if it's an index slug
        return "ok"
    if f["te_value"] is not None and f["our_value"] is None:
        return "needs-attention"
    if f["value_match"] is None and f["te_value"] is not None:
        # both could be YoY/MoM frontend transforms
        return "frontend-only" if f.get("yoy_computed") is not None or f.get("mom_computed") is not None else "ok"
    return "ok"


def main():
    with open(ROOT / "docs/_audit_5cc_slugs.json", encoding="utf-8") as f:
        slugs = json.load(f)["GB"]

    inv_path = ROOT / "docs/_te_inventory/GB.yaml"
    with open(inv_path, encoding="utf-8") as f:
        inv = yaml.safe_load(f) or {}

    findings = {}
    for i, slug in enumerate(slugs, 1):
        print(f"[{i}/{len(slugs)}] {slug}")
        finding = audit_slug(slug, inv.get(slug, {}))
        finding["flag"] = assign_flag(finding)
        findings[slug] = finding
        sm = finding["source_match"]
        vm = finding["value_match"]
        marker = "OK" if (sm is True and vm is True) else ("FLAG" if finding["flag"] != "ok" else "?")
        print(f"   te={finding['te_label']!r:50s} te_v={finding['te_value']} our_src={finding['our_source']} our_v={finding['our_value']} (src={sm}, val={vm}) {marker}")

    out_path = ROOT / "docs/_audit_gb_reaudit.yaml"
    with open(out_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(findings, f, sort_keys=True, allow_unicode=True, width=200)
    print(f"\nWrote {out_path}")

    ok = sum(1 for v in findings.values() if v["flag"] == "ok")
    needs = sum(1 for v in findings.values() if v["flag"] == "needs-attention")
    frontend = sum(1 for v in findings.values() if v["flag"] == "frontend-only")
    src_miss = sum(1 for v in findings.values() if v["source_match"] is False)
    val_miss = sum(1 for v in findings.values() if v["value_match"] is False)
    no_dp = sum(1 for v in findings.values() if v["our_value"] is None)
    no_te_v = sum(1 for v in findings.values() if v["te_value"] is None)
    print(f"\nSummary: total={len(findings)} ok={ok} needs-attention={needs} frontend-only={frontend}")
    print(f"  src_miss={src_miss} val_miss={val_miss} no_dp={no_dp} no_te_value={no_te_v}")


if __name__ == "__main__":
    main()
