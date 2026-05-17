"""Re-fetch DE slugs that didn't return parseable TE content."""
import json
import re
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML_DIR = ROOT / "docs" / "_audit_te_html" / "de_reaudit"

UA_LIST = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
]

SOURCE_RE = re.compile(r"source:\s*<a class='source-name'", re.I)

slug_to_path = {}
slugs = json.loads((ROOT / "docs" / "_audit_5cc_slugs.json").read_text())["DE"]
for s in slugs:
    slug_to_path[s] = s
slug_to_path["credit-rating"] = "rating"

# Identify slugs that need re-fetch
needs_refetch = []
for p in sorted(HTML_DIR.glob("*.html")):
    html = p.read_text(encoding="utf-8", errors="ignore")
    if not SOURCE_RE.search(html):
        needs_refetch.append(p.stem)

# Known no-source (legit) slugs: credit-rating (composite), government-spending-eur (TE empty),
# hospitals (TE has no source tag), house-price-index (Europace - vendor), social-security-rate-companies
# (sub-page often shorter). Still try to refetch all.
print(f"Re-fetching {len(needs_refetch)} slugs...")
for i, slug in enumerate(needs_refetch, 1):
    path = slug_to_path[slug]
    out = HTML_DIR / f"{slug}.html"
    success = False
    for attempt, ua in enumerate(UA_LIST):
        url = f"https://tradingeconomics.com/germany/{path}"
        try:
            r = subprocess.run(
                ["curl", "-s", "-A", ua, "--compressed", "-H", "Accept-Language: en-US,en;q=0.9",
                 "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                 "--max-time", "40", url],
                capture_output=True,
                timeout=50,
            )
            content = r.stdout
            if SOURCE_RE.search(content.decode("utf-8", errors="ignore")):
                out.write_bytes(content)
                print(f"  [{i:2d}/{len(needs_refetch)}] {slug:40s} OK (ua{attempt}) {len(content)} bytes")
                success = True
                break
            else:
                # still save the latest
                if len(content) > out.stat().st_size:
                    out.write_bytes(content)
                time.sleep(1.2)
        except Exception as e:
            print(f"  [{i:2d}/{len(needs_refetch)}] {slug:40s} ERR: {e}")
    if not success:
        print(f"  [{i:2d}/{len(needs_refetch)}] {slug:40s} FAILED — no source-name after retries ({out.stat().st_size} bytes)")
    time.sleep(0.8)

print("Done.")
