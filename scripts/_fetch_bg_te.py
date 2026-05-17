"""Fetch all BG TE pages to docs/_audit_te_html/bg/<slug>.html."""
import json, os, subprocess, time, sys
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

slugs = json.load(open("docs/_audit_all_remaining_slugs.json"))["BG"]
out_dir = "docs/_audit_te_html/bg"
os.makedirs(out_dir, exist_ok=True)

for i, slug in enumerate(slugs):
    out_path = os.path.join(out_dir, f"{slug}.html")
    if os.path.exists(out_path) and os.path.getsize(out_path) > 5000:
        print(f"[{i+1}/{len(slugs)}] {slug} cached ({os.path.getsize(out_path)} B)")
        continue
    url = f"https://tradingeconomics.com/bulgaria/{slug}"
    try:
        r = subprocess.run(["curl","-s","-A",UA,"--max-time","45",url],
                           capture_output=True, timeout=60)
        body = r.stdout
        with open(out_path, "wb") as f:
            f.write(body)
        print(f"[{i+1}/{len(slugs)}] {slug} {len(body)} B")
    except Exception as e:
        print(f"[{i+1}/{len(slugs)}] {slug} FAIL {e}")
    time.sleep(0.4)
