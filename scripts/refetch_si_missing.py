"""Refetch any SI TE pages that came back as the generic landing page."""
import json
import re
import subprocess
import time
from pathlib import Path

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
OUTDIR = Path("docs/_audit_si_te_html")
GENERIC_MARKER = "20 Million Indicators for 196 Countries"

slugs_all = json.load(open("docs/_audit_all_remaining_slugs.json"))["SI"]
bad = []
for s in slugs_all:
    p = OUTDIR / f"{s}.html"
    if not p.exists():
        bad.append(s); continue
    html = p.read_text(encoding="utf-8", errors="ignore")
    t = re.search(r"<title>([^<]+)</title>", html)
    if t and GENERIC_MARKER in t.group(1):
        bad.append(s)
        continue
    if "source-name" not in html and "Eurostat" not in html and "Statistical Office" not in html and "World Bank" not in html and "OECD" not in html:
        bad.append(s)

print(f"Re-fetch {len(bad)}: {bad}")
for i, s in enumerate(bad, 1):
    url = f"https://tradingeconomics.com/slovenia/{s}"
    for attempt in range(3):
        try:
            r = subprocess.run(
                ["curl", "-sL", "-A", UA, "--max-time", "40", url],
                capture_output=True, timeout=50,
            )
            html = r.stdout.decode("utf-8", errors="ignore")
            if GENERIC_MARKER not in html[:5000]:
                (OUTDIR / f"{s}.html").write_text(html, encoding="utf-8")
                print(f"  [{i}/{len(bad)}] {s}: OK {len(html)} bytes (try {attempt+1})")
                break
            time.sleep(2 + 1.5*attempt)
        except Exception as e:
            print(f"  attempt {attempt+1} fail: {e}")
            time.sleep(3)
    else:
        print(f"  [{i}/{len(bad)}] {s}: STILL GENERIC")
    time.sleep(1.5)
