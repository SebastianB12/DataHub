# -*- coding: utf-8 -*-
"""Fetch fresh TE HTML for all 68 RO slugs, save to docs/_audit_te_html/RO/<slug>.html."""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "_audit_te_html" / "RO"
OUT.mkdir(parents=True, exist_ok=True)

# slug -> TE path (under /romania/)
TE_PATH = {
    "budget-deficit": "government-budget",
    "core-cpi": "core-inflation-rate",
    "cpi-clothing": "cpi-clothing",  # truth.yaml had a copy/paste typo; we use the real one
    "cpi-food": "cpi-food",          # ditto
    "current-account-to-gdp": "current-account-to-gdp",
    "gdp-real": "gdp-growth-annual",
    "gdp": "gdp",
    "gdp-per-capita": "gdp-per-capita",
    "gdp-per-capita-ppp": "gdp-per-capita-ppp",
    "government-debt": "government-debt-to-gdp",
    "government-debt-total": "government-debt",
    "government-spending": "government-spending",
    "government-spending-eur": "government-spending-eur",
    "house-price-index": "housing-index",
    "inflation-cpi": "inflation-cpi",
    "manufacturing-production": "manufacturing-production",
    "ppi": "producer-prices",
    "trade-balance": "balance-of-trade",
    "unemployment": "unemployment-rate",
    "unemployment-rate-registered": "unemployment-rate-registered",
    "wages": "wages",
}


def fetch(slug: str, force: bool = False) -> Path:
    sub = TE_PATH.get(slug, slug)
    url = f"https://tradingeconomics.com/romania/{sub}"
    p = OUT / f"{slug}.html"
    if p.exists() and not force and p.stat().st_size > 1000:
        return p
    r = subprocess.run(
        ["curl", "-s", "-A", UA, "--max-time", "30", url],
        capture_output=True, timeout=40,
    )
    p.write_bytes(r.stdout)
    return p


def main():
    slugs = json.load(open(ROOT / "docs" / "_audit_all_remaining_slugs.json"))["RO"]
    print(f"Fetching {len(slugs)} TE pages for RO ...", flush=True)
    for i, slug in enumerate(slugs, 1):
        p = fetch(slug)
        size = p.stat().st_size if p.exists() else 0
        print(f"[{i:>2}/{len(slugs)}] {slug:<35} {size:>8} bytes", flush=True)
        time.sleep(0.4)
    print("Done.")


if __name__ == "__main__":
    main()
