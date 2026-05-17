"""Fetch all DE slugs from tradingeconomics.com and cache HTML locally."""
import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML_DIR = ROOT / "docs" / "_audit_te_html" / "de_reaudit"
HTML_DIR.mkdir(parents=True, exist_ok=True)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

slugs = json.loads((ROOT / "docs" / "_audit_5cc_slugs.json").read_text())["DE"]

# Special-case: credit-rating uses /<country>/rating
slug_to_path = {s: s for s in slugs}
slug_to_path["credit-rating"] = "rating"

print(f"Fetching {len(slugs)} DE slugs from tradingeconomics.com...")
for i, slug in enumerate(slugs, 1):
    out = HTML_DIR / f"{slug}.html"
    if out.exists() and out.stat().st_size > 1000:
        continue
    path = slug_to_path[slug]
    url = f"https://tradingeconomics.com/germany/{path}"
    try:
        r = subprocess.run(
            ["curl", "-s", "-A", UA, "--max-time", "30", url],
            capture_output=True,
            timeout=40,
        )
        out.write_bytes(r.stdout)
        size = len(r.stdout)
        print(f"  [{i:2d}/{len(slugs)}] {slug:35s} {size:>7d} bytes")
    except Exception as e:
        print(f"  [{i:2d}/{len(slugs)}] {slug:35s} ERROR: {e}")
    time.sleep(0.4)

print("Done.")
