"""For SK slugs that returned empty TE pages, try alternative TE slug names."""
import json
import re
import subprocess
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

# Alt slugs to try for empty TE pages
ALT = {
    "budget-deficit": ["government-budget", "government-budget-value"],
    "core-cpi": ["core-inflation-rate", "core-consumer-prices"],
    "credit-rating": ["rating", "credit-rating"],
    "energy-inflation": ["cpi-housing-utilities", "energy"],
    "gdp-real": ["full-year-gdp-growth", "gdp-growth-annual", "gdp-constant-prices"],
    "government-debt-total": ["government-debt", "external-debt"],
    "government-spending-eur": ["government-spending", "government-spending-to-gdp"],
    "house-price-index": ["housing-index"],
    "job-vacancies": ["job-vacancies"],
    "ppi": ["producer-prices", "producer-prices-change"],
    "services-inflation": ["services-pmi"],
    "services-sentiment": ["services-sentiment", "services-pmi"],
    "social-security-rate-companies": ["social-security-rate-for-companies"],
    "social-security-rate-employees": ["social-security-rate-for-employees"],
    "trade-balance": ["balance-of-trade"],
    "unemployment": ["unemployed-persons", "unemployment-persons"],
}

SOURCE_RE = re.compile(r"source:\s*<a class='source-name'[^>]*href\s*=\s*'([^']*)'[^>]*>([^<]+)</a>", re.I)
DESC_RE = re.compile(r'<h2 id="description"[^>]*>(.*?)</h2>', re.S)


def fetch(slug):
    url = f'https://tradingeconomics.com/slovakia/{slug}'
    r = subprocess.run(["curl", "-s", "-A", UA, "--max-time", "30", url],
                       capture_output=True, timeout=40)
    html = r.stdout.decode("utf-8", errors="ignore")
    has_desc = 'id="description"' in html
    src = SOURCE_RE.search(html)
    desc = DESC_RE.search(html)
    return url, html, has_desc, (src.group(2).strip() if src else None), (desc.group(1).strip()[:300] if desc else None)


def main():
    out = {}
    os.makedirs("docs/_audit_te_html/SK_alt", exist_ok=True)
    tasks = []
    for slug, alts in ALT.items():
        for alt in alts:
            tasks.append((slug, alt))
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(fetch, alt): (slug, alt) for (slug, alt) in tasks}
        for fut in as_completed(futs):
            slug, alt = futs[fut]
            try:
                url, html, has_desc, src, desc = fut.result()
            except Exception as e:
                print(f"  FAIL {slug}/{alt}: {e}")
                continue
            if has_desc:
                with open(f"docs/_audit_te_html/SK_alt/{slug}__{alt}.html", "w", encoding="utf-8") as fh:
                    fh.write(html)
                out.setdefault(slug, []).append({"alt": alt, "url": url, "src": src, "desc": desc})
                print(f"  OK   {slug:30s} alt={alt:30s} src={src!s:50s}")
            else:
                pass
    with open("docs/_audit_sk_te_alt.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
