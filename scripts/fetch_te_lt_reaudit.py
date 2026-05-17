"""Fetch fresh TE HTML for all 66 LT slugs."""
import json, os, subprocess, time, sys

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
OUT_DIR = r"C:\Users\sb\source\tradingEconomics\docs\_audit_te_html\LT"
os.makedirs(OUT_DIR, exist_ok=True)

slugs = json.load(open(r"C:\Users\sb\source\tradingEconomics\docs\_audit_all_remaining_slugs.json"))["LT"]
print(f"Fetching {len(slugs)} TE pages for LT...", flush=True)

for i, slug in enumerate(slugs, 1):
    out_path = os.path.join(OUT_DIR, f"{slug}.html")
    if os.path.exists(out_path) and os.path.getsize(out_path) > 5000:
        print(f"  [{i}/{len(slugs)}] {slug} (cached, {os.path.getsize(out_path)})", flush=True)
        continue
    url = f"https://tradingeconomics.com/lithuania/{slug}"
    try:
        r = subprocess.run(["curl", "-s", "-A", UA, "--max-time", "30", url],
                           capture_output=True, timeout=40)
        body = r.stdout
        with open(out_path, "wb") as f:
            f.write(body)
        print(f"  [{i}/{len(slugs)}] {slug}: {len(body)} bytes", flush=True)
    except Exception as e:
        print(f"  [{i}/{len(slugs)}] {slug}: FAIL {e}", flush=True)
    time.sleep(0.4)

print("Done.")
