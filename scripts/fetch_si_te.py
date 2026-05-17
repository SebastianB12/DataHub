"""Fetch all 68 SI TE pages and store raw HTML for parsing.
Most pages live at /slovenia/<slug>. Some have aliases (e.g. ".../indicators").
"""
import json
import os
import subprocess
import time
from pathlib import Path

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
OUTDIR = Path("docs/_audit_si_te_html")
OUTDIR.mkdir(parents=True, exist_ok=True)


def main():
    data = json.load(open("docs/_audit_all_remaining_slugs.json"))
    slugs = data["SI"]
    print(f"Fetching {len(slugs)} SI TE pages...")
    for i, slug in enumerate(slugs, 1):
        out = OUTDIR / f"{slug}.html"
        if out.exists() and out.stat().st_size > 1000:
            print(f"  [{i:2d}/{len(slugs)}] {slug}: cached ({out.stat().st_size} bytes)")
            continue
        url = f"https://tradingeconomics.com/slovenia/{slug}"
        try:
            r = subprocess.run(
                ["curl", "-s", "-A", UA, "--max-time", "30", url],
                capture_output=True, timeout=40,
            )
            html = r.stdout.decode("utf-8", errors="ignore")
            out.write_text(html, encoding="utf-8")
            print(f"  [{i:2d}/{len(slugs)}] {slug}: {len(html)} bytes")
            time.sleep(0.6)
        except Exception as e:
            print(f"  [{i:2d}/{len(slugs)}] {slug}: FAIL {e}")


if __name__ == "__main__":
    main()
