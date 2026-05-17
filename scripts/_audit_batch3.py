"""Audit EA batch3 slugs."""
import json
import subprocess
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.db import supabase as sb  # noqa

BATCH3 = [
    "labor-force-participation-rate", "loans-to-private-sector",
    "long-term-unemployment-rate", "manufacturing-production",
    "mining-production", "money-supply-m1", "money-supply-m3",
    "personal-income-tax-rate", "population", "ppi", "productivity",
    "retail-sales", "sales-tax-rate", "services-inflation",
    "services-sentiment", "unemployed-persons", "unemployment",
    "youth-unemployment-rate",
]

# Slug-to-TE-page map
SLUG_TO_TE = {
    "unemployment": "unemployment-rate",
    "retail-sales": "retail-sales-yoy",
    "ppi": "producer-prices",
}

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"


def fetch_te(url):
    r = subprocess.run(["curl", "-s", "-A", UA, "--max-time", "30",
                        "-w", "\n__HTTP__%{http_code}", url],
                       capture_output=True, timeout=40)
    body = r.stdout.decode("utf-8", errors="ignore")
    m = re.search(r"__HTTP__(\d+)$", body)
    code = int(m.group(1)) if m else 0
    return code, body[:m.start()] if m else body


SOURCE_RE = re.compile(
    r"source:\s*<a class='source-name'[^>]*href\s*=\s*'([^']*)'[^>]*>([^<]+)</a>",
    re.I,
)
DESC_RE = re.compile(r'<h2 id="description"[^>]*>(.*?)</h2>', re.S)
VALUE_RE = re.compile(
    r"(?:to|at|of|reached|was)\s+(-?\d[\d,\.]*)\s*(?:%|percent|billion|million|points|index|EUR|USD)?",
    re.I,
)


def parse(html):
    out = {"label": None, "value": None, "url": None, "desc": None}
    m = SOURCE_RE.search(html)
    if m:
        out["url"] = m.group(1).strip()
        out["label"] = m.group(2).strip()
    dm = DESC_RE.search(html)
    desc = dm.group(1) if dm else html[:5000]
    desc_text = re.sub(r"<[^>]+>", " ", desc)
    desc_text = re.sub(r"\s+", " ", desc_text).strip()
    out["desc"] = desc_text[:400]
    vm = VALUE_RE.search(desc_text)
    if vm:
        try:
            out["value"] = float(vm.group(1).replace(",", ""))
        except ValueError:
            pass
    return out


def main():
    out = {}
    for slug in BATCH3:
        te_slug = SLUG_TO_TE.get(slug, slug)
        url = f"https://tradingeconomics.com/euro-area/{te_slug}"
        print(f"\n=== {slug} ({url}) ===")

        # DB row
        row = sb.table('indicator_sources').select('*').eq(
            'country', 'EA').eq('indicator', slug).eq(
            'is_default', True).eq('active', True).execute().data
        row = row[0] if row else None
        dp = sb.table('data_points').select('date, value').eq(
            'country', 'EA').eq('indicator', slug).order(
            'date', desc=True).limit(13).execute().data

        # TE fetch
        code, html = fetch_te(url)
        te = parse(html) if code == 200 else {"label": None, "value": None, "url": None, "desc": f"http={code}"}

        info = {
            "te_url": url,
            "te_http": code,
            "te_label": te["label"],
            "te_source_url": te["url"],
            "te_value": te["value"],
            "te_desc": te["desc"],
            "db_source": row.get("source") if row else None,
            "db_series_id": row.get("series_id") if row else None,
            "db_extra": row.get("extra_params") if row else None,
            "db_latest": dp[0] if dp else None,
            "db_count": len(dp),
        }
        if dp and len(dp) >= 13:
            # YoY
            try:
                latest = float(dp[0]["value"])
                prior = float(dp[12]["value"])
                if prior:
                    info["db_yoy"] = round((latest - prior) / prior * 100, 2)
            except Exception:
                pass
        out[slug] = info
        print(json.dumps(info, default=str, indent=2))

    with open(ROOT / "docs" / "_audit_ea_batch3_raw.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, default=str)
    print("\nWrote docs/_audit_ea_batch3_raw.json")


if __name__ == "__main__":
    main()
