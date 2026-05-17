"""Build LU re-audit table: TE source vs DB default source.

Output: docs/_audit_lu_reaudit.yaml with all 66 slugs + verdict.
"""
import json
import os
import re
import yaml
from pathlib import Path

SRC_A = re.compile(
    r"source:\s*<a class='source-name'[^>]*href\s*=\s*'([^']*)'[^>]*>([^<]+)</a>",
    re.I,
)
SRC_B = re.compile(r"<span class='source-present'>source:\s*([^<]+)</span>", re.I)
META_DESC = re.compile(r'<meta\s+name="description"\s+content="([^"]+)"', re.I)
CANON_RE = re.compile(r'<link rel="canonical" href="([^"]+)"')
H1_RE = re.compile(r"<h1[^>]*>([^<]+)</h1>")
LAST_VAL_RE = re.compile(
    r"<th[^>]*>Last</th>\s*<th[^>]*>Previous</th>.{0,2000}?<td[^>]*>([0-9.,\-]+)</td>",
    re.S,
)

# Map our slug -> TE slug
TE_PATH = {
    "ppi": "producer-prices",
    "core-cpi": "core-inflation-rate",
    "gdp-real": "gdp-constant-prices",
    "government-spending-eur": "government-spending-value",
    "credit-rating": "rating",
    "house-price-index": "housing-index",
    "retail-sales": "retail-sales-mom",
    "unemployment": "unemployment-rate",
    "budget-deficit": "government-budget",
    "government-debt": "government-debt-to-gdp",
    "government-debt-total": "government-debt",
    "social-security-rate-companies": "social-security-rate-for-companies",
    "social-security-rate-employees": "social-security-rate-for-employees",
}

# Normalize TE source string -> our source label
def map_te_source(name: str | None) -> str | None:
    if not name:
        return None
    s = name.strip().rstrip(".")
    sl = s.lower()
    if "statec" in sl or "statistics luxembourg" in sl:
        return "statec_lu"
    if "banque centrale du luxembourg" in sl or sl == "bcl":
        return "bcl_lu"
    if "eurostat" in sl:
        return "eurostat"
    if "european commission" in sl or sl.startswith("ec "):
        return "eurostat"  # DG-ECFIN BCS surveys are mirrored in Eurostat
    if "european central bank" in sl or "ecb" in sl:
        return "ecb"
    if "world bank" in sl:
        return "worldbank"
    if "transparency international" in sl:
        return "curated"
    if "oecd" in sl:
        return "curated"
    if "conference board" in sl:
        return "curated"
    if "sipri" in sl:
        return "curated"
    if "who" in sl:
        return "curated"
    if "imf" in sl:
        return "curated"
    if "institute for economics" in sl:
        return "curated"  # terrorism-index
    if "moody" in sl or "s&p" in sl or "fitch" in sl:
        return "curated"
    if "administration des contributions" in sl:
        return "curated"  # tax rates
    if "caisse nationale" in sl:
        return "curated"  # retirement age
    if "agence pour le d" in sl or "adem" in sl:
        return "statec_lu"  # ADEM = LU national, but we use STATEC for unemployment series
    return None  # unmapped


def parse_html(html: str) -> dict:
    if not html:
        return {}
    src = None
    m = SRC_A.search(html)
    if m:
        src = m.group(2).strip()
    else:
        m = SRC_B.search(html)
        if m:
            src = m.group(1).strip()
    meta = META_DESC.search(html)
    canon = CANON_RE.search(html)
    h1 = H1_RE.search(html)
    last = LAST_VAL_RE.search(html)
    return {
        "te_src_name": src,
        "te_meta": (meta.group(1)[:300] if meta else None),
        "canonical": (canon.group(1) if canon else None),
        "h1": (h1.group(1).strip()[:80] if h1 else None),
        "last_value": (last.group(1) if last else None),
    }


def main():
    slugs = json.load(open("docs/_audit_all_remaining_slugs.json"))["LU"]
    db_latest = json.load(open("docs/_audit_lu_db_latest.json"))

    from pipeline.db import supabase as sb
    src_rows = sb.table("indicator_sources").select(
        "indicator,source,series_id,adjustment,unit"
    ).eq("country", "LU").eq("is_default", True).execute().data
    src_map = {r["indicator"]: r for r in src_rows}

    # Documented technical fetch exceptions where TE upstream label != our fetch
    # source, but truth.yaml & validator approve. These are NOT mismatches.
    DOC_EXCEPTIONS = {
        "changes-in-inventories",  # STATEC only publishes P5 aggregate
        "exports", "imports",       # STATEC has no monthly trade SDMX
        "job-vacancies",            # ADEM not in SDMX; Eurostat rate methodologically comparable
        "current-account",          # STATEC compiles/publishes BoP jointly with BCL; lustat.statec.lu hosts DF_E4202
    }

    findings = []
    summary = {"OK": 0, "MISMATCH": 0, "DOC_EXCEPTION": 0,
               "TE_NO_PAGE": 0, "TE_NO_SRC": 0}

    for slug in slugs:
        te_slug = TE_PATH.get(slug, slug)
        path = Path(f"docs/_audit_te_html/lu/_{te_slug}.html")
        if not path.exists():
            path = Path(f"docs/_audit_te_html/lu/{te_slug}.html")
        html = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
        parsed = parse_html(html)
        te_src_name = parsed.get("te_src_name")
        expected_source = map_te_source(te_src_name)

        db = src_map.get(slug, {})
        current_source = db.get("source")
        latest = db_latest.get(slug, {})

        # Status
        if not te_src_name and parsed.get("h1") and (parsed.get("te_meta") or "") == "":
            status = "TE_NO_DATA"
            summary["TE_NO_PAGE"] += 1
        elif not te_src_name:
            status = "TE_NO_SRC"
            summary["TE_NO_SRC"] += 1
        elif expected_source == current_source:
            status = "OK"
            summary["OK"] += 1
        elif slug in DOC_EXCEPTIONS:
            status = "DOC_EXCEPTION"
            summary["DOC_EXCEPTION"] += 1
        else:
            status = "MISMATCH"
            summary["MISMATCH"] += 1

        findings.append({
            "slug": slug,
            "te_slug": te_slug,
            "te_source_raw": te_src_name,
            "te_source_mapped": expected_source,
            "db_source": current_source,
            "db_series_id": db.get("series_id"),
            "db_unit": db.get("unit"),
            "db_latest_date": latest.get("date"),
            "db_latest_value": latest.get("value"),
            "db_latest_source": latest.get("source"),
            "status": status,
            "te_meta_desc": parsed.get("te_meta"),
        })

    out = {
        "country": "LU",
        "te_path": "luxembourg",
        "summary": summary,
        "findings": findings,
    }
    Path("docs/_audit_lu_reaudit.yaml").write_text(
        yaml.safe_dump(out, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    print(yaml.safe_dump({"summary": summary}, sort_keys=False))
    print(f"Wrote docs/_audit_lu_reaudit.yaml with {len(findings)} findings")
    print()
    print("MISMATCHES (need fix):")
    for f in findings:
        if f["status"] == "MISMATCH":
            print(f"  {f['slug']:36s} db={f['db_source']:12s} TE={f['te_source_mapped']:12s} (raw: {f['te_source_raw']!r})")
    print()
    print("DOC_EXCEPTIONS (technical fetch differs, documented in truth.yaml):")
    for f in findings:
        if f["status"] == "DOC_EXCEPTION":
            print(f"  {f['slug']:36s} db={f['db_source']:12s} TE-upstream={f['te_source_mapped']}")
    print()
    print("TE_NO_SRC / TE_NO_DATA (TE has no data for this LU slug):")
    for f in findings:
        if f["status"] in ("TE_NO_DATA", "TE_NO_SRC"):
            print(f"  {f['status']:12s} {f['slug']:36s} db={f['db_source']}")


if __name__ == "__main__":
    main()
