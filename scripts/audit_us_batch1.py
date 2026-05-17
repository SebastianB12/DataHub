"""Audit US Batch 1 indicators against Trading Economics.

For each slug in docs/_audit_us_batches.json:batch1:
  1. Fetch the TE page via curl
  2. Extract source attribution + headline value + period
  3. Compare to our indicator_sources row + latest data_point
  4. Write findings to docs/_audit_us_batch1_findings.yaml
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, date
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
# value: try to capture the first numeric in description after "to|at|of|reached|stood at"
VALUE_RE = re.compile(
    r"(?:to|at|of|reached|stood at|was|by)\s+(-?\d[\d,\.]*)\s*(?:%|percent|billion|million|points|index|USD|barrels)",
    re.I,
)
PERIOD_RE = re.compile(
    r"in\s+(January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Q[1-4]|the\s+(?:first|second|third|fourth)\s+quarter)\s*(?:of\s+)?(\d{4})?",
    re.I,
)

LABEL_TO_CODE = [
    ("Federal Reserve", "fred"),
    ("FRED", "fred"),
    ("Bureau of Labor Statistics", "fred"),
    ("Bureau of Economic Analysis", "fred"),
    ("U.S. Census Bureau", "fred"),
    ("Census Bureau", "fred"),
    ("Freddie Mac", "fred"),
    ("U.S. Department of Energy", "eia"),
    ("Energy Information Administration", "eia"),
    ("U.S. Treasury", "fred"),
    ("Department of the Treasury", "fred"),
    ("Automatic Data Processing", "fred"),
    ("S&P", "fred"),  # Case-Shiller comes via FRED
    ("Standard & Poor", "fred"),
    ("Conference Board", "curated"),
    ("Transparency International", "curated"),
    ("Federal Open Market Committee", "fred"),
    ("World Bank", "worldbank"),
    ("Institute for Supply Management", "curated"),
    ("National Association of Realtors", "fred"),
    ("Mortgage Bankers Association", "fred"),
    ("University of Michigan", "fred"),
    ("Manheim", "curated"),
    ("Atlanta Fed", "fred"),
    ("Dallas Fed", "fred"),
    ("Philadelphia Fed", "fred"),
    ("New York Fed", "fred"),
    ("Chicago Fed", "fred"),
    ("Energy Information", "eia"),
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
    out = {"te_label": None, "te_label_href": None, "te_value": None, "te_period": None}
    m = SOURCE_RE.search(html)
    if m:
        out["te_label_href"] = m.group(1)
        out["te_label"] = m.group(2).strip()
    m = DESC_RE.search(html)
    if m:
        desc = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        # value
        vm = VALUE_RE.search(desc)
        if vm:
            try:
                out["te_value"] = float(vm.group(1).replace(",", ""))
            except ValueError:
                pass
        pm = PERIOD_RE.search(desc)
        if pm:
            out["te_period"] = pm.group(0).strip()
        out["te_desc"] = desc[:400]
    # fallback: look for headline value in <span ... last-value ...> blocks
    if out["te_value"] is None:
        m2 = re.search(r'class="te-indicator-last"[^>]*>\s*([^<]+)<', html)
        if m2:
            try:
                out["te_value"] = float(m2.group(1).strip().replace(",", ""))
            except ValueError:
                pass
    return out


def fmt_dp(d):
    if d is None:
        return None
    return {"date": d["date"], "value": d["value"]}


def audit_slug(slug: str, inv_entry: dict) -> dict:
    te_page = (inv_entry or {}).get("te_page") or f"https://tradingeconomics.com/united-states/{slug}"
    code, html = fetch_te(te_page)
    parsed = {"te_label": None, "te_value": None, "te_period": None}
    if code == 200 and html:
        parsed = parse_te(html)

    # DB row
    try:
        row_resp = (
            sb.table("indicator_sources")
            .select("*")
            .eq("country", "US")
            .eq("indicator", slug)
            .eq("is_default", True)
            .eq("active", True)
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
            .select("date,value")
            .eq("country", "US")
            .eq("indicator", slug)
            .order("date", desc=True)
            .limit(13)
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

    source_match = (suggested == our_source) if (suggested and our_source) else None

    te_v = parsed.get("te_value")
    value_match = None
    yoy_value = None
    if te_v is not None and our_value is not None:
        # Direct match within 5%
        try:
            denom = abs(te_v) if abs(te_v) > 1e-9 else 1.0
            diff = abs(te_v - our_value) / denom
            value_match = diff <= 0.05
        except Exception:
            value_match = None
        if value_match is False and len(dps) >= 13:
            # compute YoY
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

    finding = {
        "te_label": parsed.get("te_label"),
        "te_value": te_v,
        "te_period": parsed.get("te_period"),
        "te_http": code,
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
    return finding


def main():
    with open(ROOT / "docs/_audit_us_batches.json", encoding="utf-8") as f:
        batches = json.load(f)
    slugs = batches["batch1"]

    inv_path = ROOT / "docs/_te_inventory/US.yaml"
    with open(inv_path, encoding="utf-8") as f:
        inv = yaml.safe_load(f) or {}

    findings = {}
    for i, slug in enumerate(slugs, 1):
        print(f"[{i}/{len(slugs)}] {slug}")
        finding = audit_slug(slug, inv.get(slug, {}))
        findings[slug] = finding
        s = "OK" if (finding["source_match"] and finding["value_match"]) else "?"
        print(f"   te_label={finding['te_label']!r:60s} te_v={finding['te_value']} our_src={finding['our_source']} our_v={finding['our_value']} match=(src={finding['source_match']}, val={finding['value_match']}) {s}")

    out_path = ROOT / "docs/_audit_us_batch1_findings.yaml"
    with open(out_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(findings, f, sort_keys=True, allow_unicode=True, width=200)
    print(f"\nWrote {out_path}")

    ok = sum(1 for v in findings.values() if v["source_match"] and v["value_match"])
    src_miss = sum(1 for v in findings.values() if v["source_match"] is False)
    val_miss = sum(1 for v in findings.values() if v["value_match"] is False)
    no_dp = sum(1 for v in findings.values() if v["our_value"] is None)
    no_te = sum(1 for v in findings.values() if v["te_value"] is None)
    print(f"\nSummary: total={len(findings)} ok={ok} src_miss={src_miss} val_miss={val_miss} no_dp={no_dp} no_te_value={no_te}")


if __name__ == "__main__":
    main()
