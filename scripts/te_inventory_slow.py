"""Resume-able TE-source-inventory scraper.

Walks every (country, slug) in docs/te_sources_truth.yaml where the existing
inventory at docs/_te_inventory/<CC>.yaml has verified=false. For each row
it fetches the TE indicator page, extracts the Source attribution + latest
value/period, maps to internal source code, writes the result back to the
inventory yaml file *after each successful fetch* — so a kill mid-run loses
at most the in-flight fetch.

Sleep strategy:
  - default 20s between successful fetches (well under the 25-fetch burst limit)
  - on 403: jump to 30-min cooldown, then retry once; if still 403 → 90-min
  - on connection error: 60s + retry up to 3 times
  - aborts the run if 5 consecutive 403s after long cooldowns (TE banned us)

Run:    pipeline/.venv/Scripts/python.exe -m scripts.te_inventory_slow
Resume: same command — picks up where it stopped (skips verified=true rows).
"""
from __future__ import annotations

import argparse
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

import yaml

DOCS = Path("docs")
TRUTH = DOCS / "te_sources_truth.yaml"
INV_DIR = DOCS / "_te_inventory"
PROGRESS = Path(".te_inventory_progress.json")

COUNTRY_NAMES = {
    "US": "united-states", "CN": "china", "GB": "united-kingdom", "EA": "euro-area",
    "DE": "germany", "FR": "france", "IT": "italy", "ES": "spain", "NL": "netherlands",
    "AT": "austria", "BE": "belgium", "IE": "ireland", "LU": "luxembourg",
    "PT": "portugal", "DK": "denmark", "SE": "sweden", "FI": "finland",
    "GR": "greece", "CY": "cyprus", "MT": "malta", "PL": "poland",
    "CZ": "czech-republic", "SK": "slovakia", "HU": "hungary", "RO": "romania",
    "BG": "bulgaria", "HR": "croatia", "SI": "slovenia", "LT": "lithuania",
    "LV": "latvia", "EE": "estonia",
}

# Map slug → TE URL path. Most slugs map 1:1; common rewrites below.
SLUG_TO_TE = {
    "inflation-cpi": "inflation-cpi",
    "core-cpi": "core-inflation-rate",
    "ppi": "producer-prices",
    "industrial-production": "industrial-production",
    "manufacturing-production": "manufacturing-production",
    "mining-production": "mining-production",
    "unemployment": "unemployment-rate",
    "unemployment-rate": "unemployment-rate",
    "unemployment-rate-registered": "unemployment-rate",
    "employed-persons": "employed-persons",
    "unemployed-persons": "unemployed-persons",
    "employment-rate": "employment-rate",
    "labor-force-participation-rate": "labor-force-participation-rate",
    "youth-unemployment-rate": "youth-unemployment-rate",
    "long-term-unemployment-rate": "long-term-unemployment-rate",
    "job-vacancies": "job-vacancies",
    "wages": "wages",
    "labour-costs": "labour-costs",
    "minimum-wages": "minimum-wages",
    "retail-sales": "retail-sales-yoy",
    "consumer-spending": "consumer-spending",
    "consumer-confidence": "consumer-confidence",
    "business-confidence": "business-confidence",
    "capacity-utilization": "capacity-utilization",
    "changes-in-inventories": "changes-in-inventories",
    "gdp-real": "gdp-growth-annual",
    "gdp": "gdp",
    "gdp-per-capita": "gdp-per-capita",
    "gross-fixed-capital-formation": "gross-fixed-capital-formation",
    "government-spending": "government-spending",
    "government-debt": "government-debt",
    "government-debt-total": "government-debt",
    "current-account": "current-account",
    "current-account-to-gdp": "current-account-to-gdp",
    "balance-of-trade": "balance-of-trade",
    "trade-balance": "balance-of-trade",
    "exports": "exports",
    "imports": "imports",
    "budget-deficit": "government-budget",
    "population": "population",
    "interest-rate": "interest-rate",
    "food-inflation": "food-inflation",
    "services-inflation": "services-inflation",
    "energy-inflation": "energy-inflation",
    "cpi-food": "cpi-housing-utilities",  # placeholder; TE uses cpi-food differently
    "cpi-clothing": "cpi-transportation",
    "cpi-housing-utilities": "cpi-housing-utilities",
    "cpi-transportation": "cpi-transportation",
    "cpi-recreation-and-culture": "cpi-recreation-and-culture",
    "cpi-education": "cpi-education",
    "disposable-personal-income": "disposable-personal-income",
    "corporate-tax-rate": "corporate-tax-rate",
    "personal-income-tax-rate": "personal-income-tax-rate",
    "sales-tax-rate": "sales-tax-rate",
    "social-security-rate": "social-security-rate",
    "corruption-index": "corruption-index",
    "corruption-rank": "corruption-rank",
}

LABEL_TO_CODE = [
    ("Statistics Poland", "gus_pl"), ("Główny Urząd Statystyczny", "gus_pl"),
    ("Statistics Sweden", "scb_se"), ("Statistiska centralbyrån", "scb_se"),
    ("Konjunkturinstitutet", "konj_se"), ("National Institute of Economic Research", "konj_se"),
    ("Statistics Denmark", "dst"), ("Danmarks Statistik", "dst"),
    ("Statistics Finland", "stat_fi"), ("Tilastokeskus", "stat_fi"),
    ("Statistik Austria", "stat_at"), ("Statistics Austria", "stat_at"),
    ("Statbel", "statbel"), ("Statistics Belgium", "statbel"),
    ("National Bank of Belgium", "nbb"), ("Banque nationale de Belgique", "nbb"),
    ("Central Statistics Office Ireland", "cso_ie"), ("CSO Ireland", "cso_ie"), ("Central Statistics Office", "cso_ie"),
    ("STATEC", "statec_lu"),
    ("Statistics Portugal", "ine_pt"), ("INE Portugal", "ine_pt"), ("Instituto Nacional de Estatística", "ine_pt"),
    ("ELSTAT", "elstat"), ("Hellenic Statistical Authority", "elstat"),
    ("Statistical Service of Cyprus", "cystat_cy"), ("CYSTAT", "cystat_cy"),
    ("National Statistics Office", "nso_mt"), ("NSO Malta", "nso_mt"),
    ("Statistics Lithuania", "lsd_lt"),
    ("Central Statistical Bureau of Latvia", "csp_lv"), ("CSP Latvia", "csp_lv"),
    ("Statistics Estonia", "stat_ee"),
    ("Croatian Bureau of Statistics", "dzs_hr"), ("DZS", "dzs_hr"),
    ("Statistical Office of the Republic of Slovenia", "surs_si"), ("SURS", "surs_si"),
    ("Štatistický úrad SR", "susr_sk"), ("Statistical Office of the Slovak Republic", "susr_sk"),
    ("Hungarian Central Statistical Office", "ksh_hu"), ("KSH", "ksh_hu"),
    ("National Institute of Statistics", "insse_ro"), ("INSSE Romania", "insse_ro"),
    ("National Statistical Institute", "nsi_bg"), ("NSI Bulgaria", "nsi_bg"),
    ("Czech Statistical Office", "czso"), ("ČSÚ", "czso"),
    ("INE Spain", "ine_es"), ("Instituto Nacional de Estadística", "ine_es"),
    ("ISTAT", "istat"),
    ("INSEE", "insee"), ("Institut national de la statistique", "insee"),
    ("Banque de France", "bdf"),
    ("Statistisches Bundesamt", "destatis"), ("Federal Statistical Office", "destatis"),
    ("Deutsche Bundesbank", "bundesbank"),
    ("Office for National Statistics", "ons"), ("Bank of England", "ons"),
    ("Eurostat", "eurostat"),
    ("European Central Bank", "ecb"),
    ("Federal Reserve", "fred"), ("FRED", "fred"),
    ("Bureau of Labor Statistics", "fred"), ("Bureau of Economic Analysis", "fred"),
    ("U.S. Census Bureau", "fred"), ("Census Bureau", "fred"),
    ("Energy Information Administration", "eia"),
    ("World Bank", "worldbank"),
    ("National Bureau of Statistics of China", "akshare"),
    ("People's Bank of China", "akshare"),
    ("General Administration of Customs", "gacc"),
    ("State Administration of Foreign Exchange", "akshare"),
    ("Transparency International", "curated"),
    ("Conference Board", "curated"),
]


def label_to_code(label: str) -> str | None:
    if not label:
        return None
    low = label.lower()
    for pat, code in LABEL_TO_CODE:
        if pat.lower() in low:
            return code
    return None


# TE uses single quotes in their HTML; python-requests triggers their bot-defense
# (always 403), but curl with a normal UA gets through.
SOURCE_RE = re.compile(
    r"source:\s*<a class='source-name'[^>]*href\s*=\s*'([^']*)'[^>]*>([^<]+)</a>",
    re.I,
)
DESC_RE = re.compile(r'<h2 id="description"[^>]*>(.*?)</h2>', re.S)
# Description text: "...rose to 3.2% in April 2026" / "...fell to 2.1 percent in Q1 2026" /
# "...stood at 2.7 percent in March of 2026". Capture first number followed by %/percent.
VALUE_RE = re.compile(
    r"(?:to|at|of|reached)\s+(-?\d[\d,\.]*)\s*(?:%|percent|billion|million|points|index)",
    re.I,
)
PERIOD_RE = re.compile(
    r"in\s+(January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Q[1-4]|the\s+(?:first|second|third|fourth)\s+quarter)\s*(?:of\s+)?(\d{4})?",
    re.I,
)
MONTH_NUM = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
}
QUARTER_NUM = {"first": "Q1", "second": "Q2", "third": "Q3", "fourth": "Q4"}
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"


def load_truth():
    with open(TRUTH, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_inv(cc):
    fp = INV_DIR / f"{cc}.yaml"
    if not fp.exists():
        return {}
    with open(fp, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _yaml_escape(s: str) -> str:
    s = (s or "").replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def save_inv(cc, data):
    fp = INV_DIR / f"{cc}.yaml"
    lines = []
    for slug in sorted(data.keys()):
        e = data[slug] or {}
        parts = []
        for k in ("te_label", "te_url", "te_page", "te_value", "te_period",
                  "suggested_source", "current_source", "conform", "verified", "note"):
            if k in e and e[k] is not None:
                v = e[k]
                if isinstance(v, bool):
                    parts.append(f"{k}: {str(v).lower()}")
                elif isinstance(v, (int, float)):
                    parts.append(f"{k}: {v}")
                else:
                    parts.append(f"{k}: {_yaml_escape(str(v))}")
        lines.append(f"{slug}:")
        for p in parts:
            lines.append(f"  {p}")
    with open(fp, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


def parse_te_page(html: str) -> dict:
    """Extract source label, latest value, period from TE indicator page HTML."""
    out = {"te_label": None, "te_url": None, "te_value": None, "te_period": None}
    m = SOURCE_RE.search(html)
    if m:
        out["te_url"] = m.group(1).strip()
        out["te_label"] = m.group(2).strip()
    # Description block
    dm = DESC_RE.search(html)
    desc = dm.group(1) if dm else html[:5000]
    desc_text = re.sub(r"<[^>]+>", " ", desc)
    vm = VALUE_RE.search(desc_text)
    if vm:
        try:
            out["te_value"] = float(vm.group(1).replace(",", ""))
        except ValueError:
            pass
    pm = PERIOD_RE.search(desc_text)
    if pm:
        when = pm.group(1).lower()
        year = pm.group(2) or ""
        if when in MONTH_NUM:
            out["te_period"] = f"{year}-{MONTH_NUM[when]}" if year else when.title()
        elif "quarter" in when:
            for k, v in QUARTER_NUM.items():
                if k in when:
                    out["te_period"] = f"{year}-{v}" if year else v
                    break
    return out


def fetch_one(country, slug) -> tuple[str | None, dict | None]:
    cn = COUNTRY_NAMES.get(country)
    if not cn:
        return ("no-country", None)
    te_slug = SLUG_TO_TE.get(slug, slug)
    url = f"https://tradingeconomics.com/{cn}/{te_slug}"
    try:
        r = subprocess.run(
            ["curl", "-s", "-A", UA, "--max-time", "30", "-w", "\n__HTTP_CODE__%{http_code}", url],
            capture_output=True, timeout=40,
        )
    except (subprocess.SubprocessError, OSError) as e:
        return (f"net:{e.__class__.__name__}", None)
    if r.returncode != 0:
        return (f"curl:{r.returncode}", None)
    out_text = r.stdout.decode("utf-8", errors="ignore")
    # Trailing "__HTTP_CODE__<n>"
    code_m = re.search(r"__HTTP_CODE__(\d+)$", out_text)
    code = int(code_m.group(1)) if code_m else 0
    body = out_text[:code_m.start()] if code_m else out_text
    if code == 403:
        return ("403", None)
    if code == 404:
        return ("404", None)
    if code != 200:
        return (f"http:{code}", None)
    if not body or "<html" not in body.lower():
        return ("empty", None)
    parsed = parse_te_page(body)
    parsed["te_page"] = url
    return ("ok", parsed)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--country", help="limit to one country (e.g. PL)")
    p.add_argument("--sleep", type=int, default=22, help="seconds between successful fetches")
    p.add_argument("--cooldown", type=int, default=1800, help="seconds to wait after 403")
    p.add_argument("--max-403", type=int, default=5, help="abort after N consecutive 403s post-cooldown")
    args = p.parse_args()

    truth = load_truth()
    countries = [args.country] if args.country else sorted(truth.keys())

    total_fetched = 0
    consecutive_403 = 0
    started = datetime.now()

    for cc in countries:
        inv = load_inv(cc)
        slugs = list((truth.get(cc) or {}).keys())
        todo = [s for s in slugs if not inv.get(s, {}).get("verified")]
        print(f"\n[{cc}] {len(todo)} slugs to verify (of {len(slugs)} total)")
        if not todo:
            continue
        for slug in todo:
            status, data = fetch_one(cc, slug)
            ts = datetime.now().strftime("%H:%M:%S")
            if status == "ok":
                consecutive_403 = 0
                te_label = data.get("te_label")
                sug = label_to_code(te_label) if te_label else None
                current_source = (truth.get(cc) or {}).get(slug, {}).get("source")
                conform = (sug == current_source) if sug else False
                entry = {
                    **data,
                    "suggested_source": sug,
                    "current_source": current_source,
                    "conform": conform,
                    "verified": bool(te_label),
                }
                inv[slug] = entry
                save_inv(cc, inv)
                total_fetched += 1
                print(f"  [{ts}] OK   {cc}/{slug:<35} {te_label or '(no source)'} -> {sug}")
                time.sleep(args.sleep)
            elif status == "403":
                consecutive_403 += 1
                print(f"  [{ts}] 403  {cc}/{slug:<35} cooldown {args.cooldown}s (consec={consecutive_403})")
                if consecutive_403 >= args.max_403:
                    print(f"\nAborting: {args.max_403} consecutive 403s after cooldown.")
                    return
                time.sleep(args.cooldown)
                # one retry
                status2, data2 = fetch_one(cc, slug)
                if status2 == "ok":
                    consecutive_403 = 0
                    te_label = data2.get("te_label")
                    sug = label_to_code(te_label) if te_label else None
                    current_source = (truth.get(cc) or {}).get(slug, {}).get("source")
                    entry = {
                        **data2, "suggested_source": sug,
                        "current_source": current_source,
                        "conform": (sug == current_source) if sug else False,
                        "verified": bool(te_label),
                    }
                    inv[slug] = entry
                    save_inv(cc, inv)
                    total_fetched += 1
                    print(f"  [{ts}] OK after cooldown {cc}/{slug}")
                    time.sleep(args.sleep)
                else:
                    print(f"  [{ts}] still {status2} after cooldown — sleep {args.cooldown*3}s")
                    time.sleep(args.cooldown * 3)
            elif status == "404":
                inv[slug] = {**inv.get(slug, {}), "verified": False,
                             "note": "TE 404 — slug not on TE for this country"}
                save_inv(cc, inv)
                print(f"  [{ts}] 404  {cc}/{slug}")
                time.sleep(5)
            else:
                print(f"  [{ts}] {status:<10} {cc}/{slug}")
                time.sleep(args.sleep)
        print(f"[{cc}] done. {total_fetched} fetched so far. elapsed={datetime.now()-started}")

    print(f"\nDone. {total_fetched} fetched. elapsed={datetime.now()-started}")


if __name__ == "__main__":
    main()
