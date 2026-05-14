"""Drive TE inventory for DK/SE/FI/GR/CY/MT and write YAML outputs.

Reads docs/te_sources_truth.yaml, fetches each TE indicator page, maps
TE label -> internal source code, and writes docs/_te_inventory/<CC>.yaml.
"""
import os
import sys
import re
import json
import time
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRUTH = ROOT / "docs" / "te_sources_truth.yaml"
OUT_DIR = ROOT / "docs" / "_te_inventory"
OUT_DIR.mkdir(parents=True, exist_ok=True)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

COUNTRY_NAME = {
    "DK": "denmark",
    "SE": "sweden",
    "FI": "finland",
    "GR": "greece",
    "CY": "cyprus",
    "MT": "malta",
}

SLUG_TO_TE = {
    "trade-balance": "balance-of-trade",
    "house-price-index": "housing-index",
    "ppi": "producer-prices",
    "government-debt-total": "government-debt",
    "industrial-production-yoy": "industrial-production",
    "retail-sales-yoy": "retail-sales",
    "gdp-growth-rate": "gdp-growth",
}

# slugs without TE pages — curated reference data
CURATED_SLUGS = {
    "corporate-tax-rate", "personal-income-tax-rate", "sales-tax-rate",
    "social-security-rate", "social-security-rate-companies",
    "social-security-rate-employees", "withholding-tax-rate",
    "corruption-index", "corruption-rank", "credit-rating",
    "hospital-beds", "hospitals", "medical-doctors", "nurses",
    "retirement-age-men", "retirement-age-women", "terrorism-index",
    "weapons-sales", "military-expenditure", "minimum-wages",
    "government-spending-to-gdp",
}

SOURCE_RE = re.compile(
    r"source:\s*<a class='source-name'[^>]*href\s*=\s*'([^']*)'[^>]*>([^<]+)</a>",
    re.I,
)
DESC_RE = re.compile(r'<h2 id="description"[^>]*>(.*?)</h2>', re.S)

MONTH_NUM = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
}
QUARTER_NUM = {"first": "Q1", "second": "Q2", "third": "Q3", "fourth": "Q4"}


def fetch(url, retries=5):
    for attempt in range(retries):
        try:
            r = subprocess.run(
                ["curl", "-s", "-A", UA, "--max-time", "30",
                 "-w", "\n__HTTP_STATUS__:%{http_code}", url],
                capture_output=True, timeout=35,
            )
            if r.returncode == 0 and r.stdout:
                body = r.stdout.decode("utf-8", errors="replace")
                # check status
                m = re.search(r"__HTTP_STATUS__:(\d+)$", body)
                status = int(m.group(1)) if m else 0
                if m:
                    body = body[: m.start()]
                if status == 200 and "source-name" in body:
                    return body
                if status == 200:
                    return body  # page may legitimately lack a source
                # 403 / 5xx → backoff
                wait = 30 * (attempt + 1)
                time.sleep(wait)
                continue
        except Exception:
            time.sleep(15)
    return None


def extract_period(desc):
    m = re.search(
        r"in\s+(January|February|March|April|May|June|July|August|September|October|November|December)(?:\s+of)?\s+(\d{4})",
        desc, re.I,
    )
    if m:
        return f"{m.group(2)}-{MONTH_NUM[m.group(1).lower()]}"
    m = re.search(
        r"the\s+(first|second|third|fourth)\s+quarter\s+of\s+(\d{4})",
        desc, re.I,
    )
    if m:
        return f"{m.group(2)}-{QUARTER_NUM[m.group(1).lower()]}"
    m = re.search(r"in\s+(\d{4})\b", desc)
    if m:
        return m.group(1)
    return None


def extract_value(desc):
    m = re.search(r"(?:to|was)\s+(-?\d[\d,\.]+)", desc)
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            return None
    return None


def scrape(country_name, slug):
    te_slug = SLUG_TO_TE.get(slug, slug)
    url = f"https://tradingeconomics.com/{country_name}/{te_slug}"
    html = fetch(url)
    if html is None:
        return {"te_page": url, "te_label": None, "te_url": None,
                "te_value": None, "te_period": None, "verified": False}
    src_m = SOURCE_RE.search(html)
    desc = DESC_RE.search(html).group(1) if DESC_RE.search(html) else ""
    if not src_m:
        return {"te_page": url, "te_label": None, "te_url": None,
                "te_value": extract_value(desc), "te_period": extract_period(desc),
                "verified": False}
    return {
        "te_page": url,
        "te_label": src_m.group(2).strip(),
        "te_url": src_m.group(1).strip(),
        "te_value": extract_value(desc),
        "te_period": extract_period(desc),
        "verified": True,
    }


def map_label_to_source(label, country_code):
    """Map TE source label -> internal source code."""
    if not label:
        return None
    L = label.lower()
    if "eurostat" in L:
        return "eurostat"
    if "european commission" in L:
        # DG ECFIN business/consumer surveys — we ingest via Eurostat
        return "eurostat"
    if "world bank" in L:
        return "worldbank"
    if "european central bank" in L:
        return "ecb"
    if "international monetary fund" in L or "imf" in L:
        return "curated"
    if "oecd" in L:
        return "curated"
    if "transparency international" in L:
        return "curated"
    # National stats agencies — per country
    if "statistics denmark" in L or L == "danmarks statistik":
        return "dst"
    if "danmarks nationalbank" in L or "national bank of denmark" in L:
        return None  # no internal code for DNB; flag as unmapped
    if "statistics sweden" in L or "statistiska centralbyrån" in L or L.strip() == "scb":
        return "scb_se"
    if "sveriges riksbank" in L or "swedish riksbank" in L:
        return None  # no internal code for Riksbank; flag as unmapped
    if "statistics finland" in L or "tilastokeskus" in L:
        return "stat_fi"
    if "bank of finland" in L:
        return "stat_fi"
    if "elstat" in L or "hellenic statistical authority" in L:
        return "elstat"
    if "national statistical service of greece" in L:
        return "elstat"
    if "bank of greece" in L:
        return "elstat"
    if "national institute of economic research" in L and "sweden" in L:
        # NIER (Konjunkturinstitutet) — no internal code, gap
        return None
    if "confederation of finnish industries" in L or L.strip() == "ek":
        return None
    if ("statistical service of cyprus" in L or "cystat" in L
            or "republic of cyprus" in L):
        return "cystat_cy"
    if "central bank of cyprus" in L:
        return "cystat_cy"
    if "national statistics office" in L or "nso malta" in L:
        return "nso_mt"
    if "central bank of malta" in L:
        return "nso_mt"
    return None


# parse truth.yaml for our countries
def parse_truth():
    text = TRUTH.read_text(encoding="utf-8")
    countries = {}
    current = None
    for line in text.splitlines():
        if re.match(r"^([A-Z]{2}):\s*$", line):
            current = line.rstrip(":").strip()
            countries[current] = {}
            continue
        if current and current in COUNTRY_NAME:
            m = re.match(r"^  ([a-z0-9\-]+):\s*\{\s*source:\s*([a-z_]+)", line)
            if m:
                countries[current][m.group(1)] = m.group(2)
        if line.startswith(" ") is False and current and not line.startswith("#"):
            # new top-level — only reset if matches country pattern
            pass
    return {cc: countries.get(cc, {}) for cc in COUNTRY_NAME}


def yaml_escape(s):
    if s is None:
        return "null"
    s = str(s).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def write_yaml(cc, entries):
    """entries: dict slug -> dict"""
    out = OUT_DIR / f"{cc}.yaml"
    lines = []
    for slug in sorted(entries.keys()):
        e = entries[slug]
        lines.append(f"{slug}:")
        lines.append(f"  te_label: {yaml_escape(e.get('te_label'))}")
        lines.append(f"  te_url: {yaml_escape(e.get('te_url'))}")
        lines.append(f"  te_page: {yaml_escape(e.get('te_page'))}")
        v = e.get("te_value")
        lines.append(f"  te_value: {('null' if v is None else v)}")
        lines.append(f"  te_period: {yaml_escape(e.get('te_period'))}")
        ss = e.get("suggested_source")
        lines.append(f"  suggested_source: {('null' if ss is None else ss)}")
        cs = e.get("current_source")
        lines.append(f"  current_source: {('null' if cs is None else cs)}")
        lines.append(f"  conform: {str(e.get('conform', False)).lower()}")
        lines.append(f"  verified: {str(e.get('verified', False)).lower()}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  wrote {out} ({len(entries)} entries)")


def main():
    truth = parse_truth()
    target = sys.argv[1] if len(sys.argv) > 1 else None

    for cc, country_slug_map in truth.items():
        if target and cc != target:
            continue
        print(f"=== {cc} ({COUNTRY_NAME[cc]}) — {len(country_slug_map)} slugs ===")
        country_name = COUNTRY_NAME[cc]
        entries = {}

        for i, (slug, current) in enumerate(sorted(country_slug_map.items()), 1):
            if slug in CURATED_SLUGS:
                # Skip TE fetch — curated source, mark conform=true if current==curated
                entries[slug] = {
                    "te_label": None, "te_url": None,
                    "te_page": f"https://tradingeconomics.com/{country_name}/{slug}",
                    "te_value": None, "te_period": None,
                    "suggested_source": "curated",
                    "current_source": current,
                    "conform": current == "curated",
                    "verified": False,  # not actively verified via web fetch
                }
                continue
            print(f"  [{i:>2}/{len(country_slug_map)}] {slug} ...", flush=True)
            res = scrape(country_name, slug)
            suggested = map_label_to_source(res.get("te_label"), cc)
            conform = (suggested == current) if suggested else False
            entries[slug] = {
                **res,
                "suggested_source": suggested,
                "current_source": current,
                "conform": conform,
            }
            time.sleep(0.3)
        write_yaml(cc, entries)


if __name__ == "__main__":
    main()
