"""Fetch all SK TE pages in parallel and save raw HTML + parsed source/value."""
import json
import re
import subprocess
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

SOURCE_RE = re.compile(r"source:\s*<a class='source-name'[^>]*href\s*=\s*'([^']*)'[^>]*>([^<]+)</a>", re.I)
DESC_RE = re.compile(r'<h2 id="description"[^>]*>(.*?)</h2>', re.S)
# Try to extract current value from the TE summary table
LAST_RE = re.compile(r'<td>\s*Last\s*</td>\s*<td[^>]*>\s*([0-9.,\-]+)\s*</td>', re.I)
# Big number on the page
HEADING_NUM_RE = re.compile(r'<h2[^>]*>\s*<span[^>]*>([0-9.,\-]+)\s*</span>', re.I)


def fetch_te(te_slug):
    url = f'https://tradingeconomics.com/slovakia/{te_slug}'
    try:
        r = subprocess.run(
            ["curl", "-s", "-A", UA, "--max-time", "30", url],
            capture_output=True, timeout=40,
        )
        html = r.stdout.decode("utf-8", errors="ignore")
    except Exception as e:
        return te_slug, url, None, str(e)
    return te_slug, url, html, None


def parse(html):
    src_match = SOURCE_RE.search(html or "")
    src_url = src_match.group(1) if src_match else None
    src_name = src_match.group(2).strip() if src_match else None
    desc_match = DESC_RE.search(html or "")
    desc = desc_match.group(1).strip() if desc_match else None
    last_match = LAST_RE.search(html or "")
    last_val = last_match.group(1) if last_match else None
    if not last_val:
        h2 = HEADING_NUM_RE.search(html or "")
        last_val = h2.group(1) if h2 else None
    return {
        "source_url": src_url,
        "source_name": src_name,
        "te_value": last_val,
        "description": desc[:400] if desc else None,
    }


def main():
    with open("docs/_audit_all_remaining_slugs.json", encoding="utf-8") as f:
        data = json.load(f)
    slugs = data["SK"]
    print(f"Fetching {len(slugs)} SK TE pages...")
    out = {}
    os.makedirs("docs/_audit_te_html/SK", exist_ok=True)
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(fetch_te, s): s for s in slugs}
        for fut in as_completed(futs):
            slug, url, html, err = fut.result()
            if err or not html or len(html) < 1000:
                out[slug] = {"url": url, "error": err or "empty"}
                print(f"  FAIL {slug}: {err or 'empty'}")
                continue
            with open(f"docs/_audit_te_html/SK/{slug}.html", "w", encoding="utf-8") as fh:
                fh.write(html)
            parsed = parse(html)
            parsed["url"] = url
            out[slug] = parsed
            print(f"  OK {slug:35s} src={parsed['source_name']!s:40s} val={parsed['te_value']}")
    with open("docs/_audit_sk_te_raw.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\nSaved to docs/_audit_sk_te_raw.json")


if __name__ == "__main__":
    main()
