"""Fetch fresh TE HTML for all HU slugs (parallel)."""
import json
import os
import subprocess
import concurrent.futures

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
OUT = "docs/_audit_te_html/hu_reaudit"
os.makedirs(OUT, exist_ok=True)

with open("docs/_audit_all_remaining_slugs.json", "r", encoding="utf-8") as f:
    slugs = json.load(f)["HU"]


def fetch(slug):
    path = f"{OUT}/{slug}.html"
    if os.path.exists(path) and os.path.getsize(path) > 5000:
        return slug, "cached", os.path.getsize(path)
    url = f"https://tradingeconomics.com/hungary/{slug}"
    r = subprocess.run(
        ["curl", "-s", "-A", UA, "--max-time", "40", url],
        capture_output=True, timeout=50,
    )
    body = r.stdout
    with open(path, "wb") as f:
        f.write(body)
    return slug, "fetched", len(body)


with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
    for slug, status, sz in ex.map(fetch, slugs):
        print(f"{slug:<35} {status:<8} {sz}")
