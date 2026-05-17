"""Re-fetch DE slugs using Python requests with longer sleeps and varied headers."""
import json
import re
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
HTML_DIR = ROOT / "docs" / "_audit_te_html" / "de_reaudit"

SOURCE_RE = re.compile(r"source-name", re.I)
GENERIC_TITLE = "20 Million Indicators"

UA_LIST = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36 Edg/127.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
]

slugs = json.loads((ROOT / "docs" / "_audit_5cc_slugs.json").read_text())["DE"]
slug_to_path = {s: s for s in slugs}
slug_to_path["credit-rating"] = "rating"

needs = []
for p in sorted(HTML_DIR.glob("*.html")):
    html = p.read_text(encoding="utf-8", errors="ignore")
    if not SOURCE_RE.search(html):
        needs.append(p.stem)

print(f"Refetch {len(needs)} slugs...")
sess = requests.Session()
sess.headers.update({"Accept-Language": "en-US,en;q=0.9"})

for i, slug in enumerate(needs, 1):
    path = slug_to_path[slug]
    out = HTML_DIR / f"{slug}.html"
    url = f"https://tradingeconomics.com/germany/{path}"
    success = False
    for attempt, ua in enumerate(UA_LIST):
        try:
            r = sess.get(url, headers={
                "User-Agent": ua,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "Referer": "https://tradingeconomics.com/germany/indicators",
                "Cache-Control": "no-cache",
            }, timeout=40)
            content = r.content
            text = r.text
            if SOURCE_RE.search(text) and "Germany" in text[:5000]:
                out.write_bytes(content)
                print(f"  [{i:2d}/{len(needs)}] {slug:40s} OK ua{attempt} {len(content)} bytes")
                success = True
                break
            else:
                if len(content) > out.stat().st_size:
                    out.write_bytes(content)
                time.sleep(2)
        except Exception as e:
            print(f"  [{i:2d}/{len(needs)}] {slug:40s} ERR ua{attempt}: {e}")
            time.sleep(1)
    if not success:
        print(f"  [{i:2d}/{len(needs)}] {slug:40s} STILL FAILED ({out.stat().st_size} bytes)")
    time.sleep(1.5)

print("Done.")
