import sys
sys.stdout.reconfigure(encoding="utf-8")
import requests, re
for jsf in ["scripts.js", "vendor.js"]:
    rj = requests.get(f"http://statistici.insse.ro:8077/tempo-online/{jsf}", timeout=60).text
    print(f"\n=== {jsf} ===")
    hits = sorted(set(re.findall(r'["\'](\/[a-z][a-zA-Z/_-]{6,80})["\']', rj)))
    print(f"  {len(hits)} URL strings")
    for h in hits[:30]:
        if "tempo" in h or "matrix" in h or "data" in h or "context" in h:
            print(" ", h)
    print("\n  --- matrix snippets ---")
    seen = set()
    for m in re.finditer(r'.{0,15}["\']/?[a-z]*matrix.{0,80}', rj, re.I):
        s = m.group(0)[:120]
        if s not in seen:
            seen.add(s)
            print(" ", s)
        if len(seen) > 10:
            break
