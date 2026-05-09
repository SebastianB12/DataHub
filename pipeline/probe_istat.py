"""Probe-script: discover the right ISTAT series via DBnomics for IT slugs."""
import sys
sys.stdout.reconfigure(encoding="utf-8")
import requests

API = "https://api.db.nomics.world/v22"

def list_series(provider: str, dataset: str, q: str = None) -> list[dict]:
    url = f"{API}/series/{provider}/{dataset}?limit=500"
    if q:
        url += f"&q={q}"
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    docs = r.json().get("series", {}).get("docs", [])
    return docs

def find_dataset(provider: str, kw: str) -> list[dict]:
    r = requests.get(f"{API}/datasets/{provider}?limit=500", timeout=60)
    docs = r.json().get("datasets", {}).get("docs", [])
    return [d for d in docs if kw.lower() in (d.get("name") or "").lower()]

def latest_obs(provider: str, dataset: str, series: str):
    r = requests.get(f"{API}/series/{provider}/{dataset}/{series}?observations=1", timeout=60)
    s = r.json().get("series", {}).get("docs", [{}])[0]
    p = s.get("period", [])
    v = s.get("value", [])
    if p and v:
        return p[-1], v[-1]
    return None, None


# === ISTAT Italy probes ===
print("\n========== ISTAT (Italy) ==========\n")

# 1. CPI / inflation-cpi: NIC dataflow base 2020 should be the latest
print("--- NIC datasets ---")
for ds in find_dataset("ISTAT", "consumer prices"):
    print(f"  {ds['code']:<60} {ds['name']}")
print("--- prices indices ---")
for ds in find_dataset("ISTAT", "price index"):
    print(f"  {ds['code']:<60} {ds['name']}")
print("--- harmonised ---")
for ds in find_dataset("ISTAT", "harmonised"):
    print(f"  {ds['code']:<60} {ds['name']}")
print("--- inflation ---")
for ds in find_dataset("ISTAT", "inflation"):
    print(f"  {ds['code']:<60} {ds['name']}")
