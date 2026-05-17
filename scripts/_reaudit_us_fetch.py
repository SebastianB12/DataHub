"""Fresh re-audit fetcher for US slugs.

Fetches TE pages for every US slug, caches HTML to disk so a kill
mid-run loses at most the in-flight fetch. Parses source label,
description-block value, and headline period.

Usage:
    pipeline/.venv/Scripts/python.exe scripts/_reaudit_us_fetch.py
    pipeline/.venv/Scripts/python.exe scripts/_reaudit_us_fetch.py --resume
"""
from __future__ import annotations
import argparse
import json
import re
import subprocess
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SLUGS_FILE = ROOT / "docs" / "_audit_5cc_slugs.json"
HTML_DIR = ROOT / "docs" / "_audit_te_html" / "us_reaudit"
HTML_DIR.mkdir(parents=True, exist_ok=True)
STATUS_FILE = HTML_DIR / "_status.json"
PARSED_FILE = HTML_DIR / "_parsed.json"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

# SLUG_TO_TE rewrites copied from scripts/te_inventory_slow.py + US-specific
SLUG_TO_TE = {
    "inflation-cpi": "inflation-cpi",
    "core-cpi": "core-inflation-rate",
    "ppi": "producer-prices",
    "unemployment": "unemployment-rate",
    "unemployment-rate": "unemployment-rate",
    "retail-sales": "retail-sales-yoy",
    "gdp-real": "gdp-growth-annual",
    "trade-balance": "balance-of-trade",
    "budget-deficit": "government-budget",
    "natural-gas-storage": "natural-gas-stocks-change",  # TE's weekly EIA storage report
    "strategic-petroleum-reserve": "crude-oil-stocks-change",  # TE doesn't have SPR page
    "central-bank-balance": "central-bank-balance-sheet",  # TE adds -sheet suffix
    "initial-jobless-claims": "jobless-claims",  # TE uses shorter name
    "crude-oil-stocks": "crude-oil-stocks-change",  # TE shows weekly change
    "gasoline-stocks": "gasoline-stocks-change",  # if exists, else use as-is
    # Note: most US slugs map 1:1 to TE
}

SOURCE_RE = re.compile(
    r"source:\s*<a class='source-name'[^>]*href\s*=\s*'([^']*)'[^>]*>([^<]+)</a>",
    re.I,
)
DESC_RE = re.compile(r'<h2 id="description"[^>]*>(.*?)</h2>', re.S)
VALUE_RE = re.compile(
    r"(?:to|at|of|reached)\s+(-?\$?\d[\d,\.]*)\s*(%|percent|billion|million|points|index|thousand|USD|barrels|tonnes|jobs)?",
    re.I,
)
PERIOD_RE = re.compile(
    r"in\s+(January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Q[1-4]|the\s+(?:first|second|third|fourth)\s+quarter)\s*(?:of\s+)?(\d{4})?",
    re.I,
)
MONTH_NUM = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
}
QUARTER_NUM = {"first": "Q1", "second": "Q2", "third": "Q3", "fourth": "Q4"}


def parse_te_page(html: str) -> dict:
    out = {"te_label": None, "te_url": None, "te_value": None, "te_period": None, "te_unit": None}
    m = SOURCE_RE.search(html)
    if m:
        out["te_url"] = m.group(1).strip()
        out["te_label"] = m.group(2).strip()
    dm = DESC_RE.search(html)
    desc = dm.group(1) if dm else html[:5000]
    desc_text = re.sub(r"<[^>]+>", " ", desc)
    desc_text = re.sub(r"\s+", " ", desc_text).strip()
    out["te_desc"] = desc_text[:600]
    vm = VALUE_RE.search(desc_text)
    if vm:
        try:
            raw = vm.group(1).lstrip("$").replace(",", "")
            out["te_value"] = float(raw)
            out["te_unit"] = vm.group(2)
        except ValueError:
            pass
    pm = PERIOD_RE.search(desc_text)
    if pm:
        when = pm.group(1).lower()
        year = pm.group(2) or ""
        if when in MONTH_NUM:
            out["te_period"] = f"{year}-{MONTH_NUM[when]}" if year else when.title()
        elif "quarter" in when:
            for k, v in QUARTER_NUM.items():
                if k in when:
                    out["te_period"] = f"{year}-{v}" if year else v
                    break
        else:
            out["te_period"] = pm.group(0)
    return out


def fetch_one(slug: str) -> tuple[int, str]:
    te_slug = SLUG_TO_TE.get(slug, slug)
    url = f"https://tradingeconomics.com/united-states/{te_slug}"
    try:
        r = subprocess.run(
            ["curl", "-s", "-A", UA, "--max-time", "30",
             "-w", "\n__HTTP_CODE__%{http_code}", url],
            capture_output=True, timeout=40,
        )
    except (subprocess.SubprocessError, OSError) as e:
        return (-1, f"net:{e.__class__.__name__}")
    out_text = r.stdout.decode("utf-8", errors="ignore")
    code_m = re.search(r"__HTTP_CODE__(\d+)$", out_text)
    code = int(code_m.group(1)) if code_m else 0
    body = out_text[:code_m.start()] if code_m else out_text
    return (code, body)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--resume", action="store_true", help="skip slugs already cached")
    p.add_argument("--sleep", type=int, default=12, help="seconds between fetches")
    p.add_argument("--max", type=int, default=0, help="max slugs this run (0=all)")
    args = p.parse_args()

    slugs = json.loads(SLUGS_FILE.read_text())["US"]
    status = json.loads(STATUS_FILE.read_text()) if STATUS_FILE.exists() else {}

    consec_403 = 0
    fetched = 0
    for slug in slugs:
        html_path = HTML_DIR / f"{slug}.html"
        if args.resume and html_path.exists() and status.get(slug, {}).get("code") == 200:
            continue
        if args.max and fetched >= args.max:
            break
        code, body = fetch_one(slug)
        ts = time.strftime("%H:%M:%S")
        if code == 200 and body and "<html" in body.lower():
            html_path.write_text(body, encoding="utf-8")
            status[slug] = {"code": 200, "len": len(body)}
            consec_403 = 0
            fetched += 1
            print(f"[{ts}] OK   {slug}")
        elif code == 403:
            consec_403 += 1
            status[slug] = {"code": 403}
            print(f"[{ts}] 403  {slug} (consec={consec_403})")
            if consec_403 >= 3:
                cooldown = 1800
                print(f"  cooldown {cooldown}s")
                time.sleep(cooldown)
                consec_403 = 0
            else:
                time.sleep(60)
        elif code == 404:
            status[slug] = {"code": 404}
            print(f"[{ts}] 404  {slug}")
        else:
            status[slug] = {"code": code, "note": "non-200"}
            print(f"[{ts}] HTTP {code} {slug}")
        STATUS_FILE.write_text(json.dumps(status, indent=2))
        time.sleep(args.sleep)

    print(f"\nDone. fetched={fetched}")


if __name__ == "__main__":
    main()
