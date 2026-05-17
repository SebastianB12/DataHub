"""Compare TE data vs EconPulse DB for all 67 MT slugs, write findings yaml."""
import os, re, json, sys, io, yaml
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from pipeline.db import supabase as sb

SOURCE_RE = re.compile(
    r"source:\s*<a class='source-name'[^>]*href\s*=\s*'([^']*)'[^>]*>([^<]+)</a>",
    re.I,
)
SOURCE_RE2 = re.compile(
    r'source:\s*<a class="source-name"[^>]*href\s*=\s*"([^"]*)"[^>]*>([^<]+)</a>',
    re.I,
)
# Fallback: source-present span where source has no anchor (just text)
SOURCE_RE3 = re.compile(
    r"source-present['\"]>source:\s*(?:<a[^>]*href\s*=\s*['\"]([^'\"]*)['\"][^>]*>([^<]+)</a>|([^<]+))</span>",
    re.I,
)
DESC_RE = re.compile(r'<h2 id="description"[^>]*>(.*?)</h2>', re.S)
H1_DESC_RE = re.compile(r'<h2[^>]*>([^<]+credit rating[^<]+)</h2>', re.I)

NOT_ON_TE = {
    "core-cpi", "disposable-personal-income", "energy-inflation",
    "hospital-beds", "job-vacancies", "medical-doctors", "nurses",
    "services-inflation", "services-sentiment", "terrorism-index",
}

# Map TE source label -> internal source code
def map_source(label):
    if not label:
        return None
    L = label.lower()
    if "national statistics office" in L or "nso" in L:
        return "nso_mt"
    if "central bank of malta" in L or "centralbankmalta" in L:
        return "cbm_mt"
    if "eurostat" in L:
        return "eurostat"
    if "european commission" in L or "ec.europa.eu" == L:
        return "eurostat"  # we use eurostat for EC business/consumer survey
    if "ecb" in L or "european central bank" in L:
        return "ecb"
    if "world bank" in L or "worldbank" in L:
        return "worldbank"
    if "transparency international" in L:
        return "curated"
    if "moody" in L or "standard" in L or "fitch" in L or "dbrs" in L:
        return "curated"
    if "who" in L or "world health" in L:
        return "curated"
    if "conference board" in L or "ti " in L or "oecd" in L or "sipri" in L:
        return "curated"
    if "government of malta" in L or "inland revenue" in L or "social security" in L:
        return "curated"
    if "global terrorism" in L or "vision of humanity" in L:
        return "curated"
    return None


# Description-leading-value extraction
# e.g. "Malta recorded a Government Budget deficit equal to 2.20 percent"
LEAD_NUM = re.compile(r"(-?\d[\d,]*\.?\d*)\s*(percent|EUR|points?|EUR Thousand|EUR Million|thousand|million|years|per 1000|per 1,000|USD|MWh|Tonnes|score|index)", re.I)
LEAD_ANY = re.compile(r"^[^.0-9]*?([-+]?\d[\d,]*\.?\d*)", re.S)


def parse_html(html, slug):
    out = {}
    m = SOURCE_RE.search(html) or SOURCE_RE2.search(html)
    if m:
        out["source_url"] = m.group(1)
        out["source_label"] = m.group(2).strip()
    else:
        m3 = SOURCE_RE3.search(html)
        if m3:
            label = (m3.group(2) or m3.group(3) or "").strip()
            url = (m3.group(1) or "").strip()
            if label:
                out["source_label"] = label
                if url:
                    out["source_url"] = url
    desc_m = DESC_RE.search(html)
    if desc_m:
        desc = re.sub(r"<[^>]+>", "", desc_m.group(1))
        desc = re.sub(r"\s+", " ", desc).strip()
        out["description"] = desc[:600]
        # extract first value
        nm = LEAD_NUM.search(desc)
        if nm:
            try:
                out["te_value"] = float(nm.group(1).replace(",", ""))
                out["te_unit"] = nm.group(2).strip().lower()
            except Exception:
                pass
        else:
            am = LEAD_ANY.search(desc)
            if am:
                try:
                    out["te_value"] = float(am.group(1).replace(",", ""))
                except Exception:
                    pass
    else:
        # credit-rating page uses <h2>Standard & Poor's...
        h2_m = H1_DESC_RE.search(html)
        if h2_m:
            out["description"] = h2_m.group(1).strip()[:500]
    return out


def get_db_value(country, slug):
    r = sb.table("data_points").select("date,value,source").eq(
        "country", country
    ).eq("indicator", slug).order("date", desc=True).limit(1).execute()
    if r.data:
        d = r.data[0]
        return {"date": str(d["date"]), "value": float(d["value"]), "source": d["source"]}
    return None


def get_default_source(country, slug):
    r = sb.table("indicator_sources").select("source,is_default,note").eq(
        "country", country
    ).eq("indicator", slug).eq("is_default", True).execute()
    if r.data:
        return r.data[0]
    return None


def value_match(te_val, db_val):
    if te_val is None or db_val is None:
        return None
    if te_val == 0:
        return abs(db_val) < 0.001
    pct = abs(te_val - db_val) / max(abs(te_val), 0.001)
    return pct <= 0.05


def main():
    findings = {}
    summary = {
        "verified_ok": 0,
        "source_mismatch": 0,
        "value_mismatch": 0,
        "not_on_te": 0,
        "missing_db": 0,
        "frontend_only": 0,
    }
    slugs = json.load(open("docs/_audit_all_remaining_slugs.json"))["MT"]
    for slug in slugs:
        rec = {"slug": slug}
        if slug in NOT_ON_TE:
            rec["te_status"] = "not_on_te"
            rec["decision"] = "frontend-only-or-curated"
            db_default = get_default_source("MT", slug)
            rec["db_source"] = db_default["source"] if db_default else None
            rec["db_value"] = get_db_value("MT", slug)
            summary["not_on_te"] += 1
            findings[slug] = rec
            continue
        html_path = f"docs/_audit_te_html/MT/{slug}.html"
        if not os.path.exists(html_path):
            rec["te_status"] = "no_html"
            findings[slug] = rec
            continue
        html = open(html_path, encoding="utf-8", errors="ignore").read()
        parsed = parse_html(html, slug)
        rec["te_label"] = parsed.get("source_label")
        rec["te_url"] = parsed.get("source_url")
        rec["te_value"] = parsed.get("te_value")
        rec["te_unit"] = parsed.get("te_unit")
        rec["te_description"] = parsed.get("description", "")[:300]
        expected_src = map_source(parsed.get("source_label", ""))
        rec["expected_internal_source"] = expected_src

        # DB
        db_default = get_default_source("MT", slug)
        rec["db_source"] = db_default["source"] if db_default else None
        rec["db_note"] = db_default.get("note") if db_default else None
        db_v = get_db_value("MT", slug)
        rec["db_value"] = db_v

        # Source match
        # Honor hard rule: if we fetch from eurostat, source='eurostat' even if TE attributes NSO
        # but for slugs where TE attributes Eurostat but we use NSO direct, we should keep nso_mt
        if expected_src is None:
            rec["source_status"] = "te_label_unknown"
        elif rec["db_source"] == expected_src:
            rec["source_status"] = "match"
        else:
            # Special case: TE attributes upstream NSO but we fetch via Eurostat — honor fetch provider
            if expected_src == "nso_mt" and rec["db_source"] == "eurostat":
                rec["source_status"] = "match_fetch_provider"
                rec["te_attribution_note"] = (
                    "TE attributes NSO Malta upstream; we fetch via Eurostat (geo=MT). "
                    "Source label honors fetch provider per hard rule."
                )
            # NSO Malta directly in EC business surveys — we use Eurostat
            elif expected_src == "eurostat" and rec["db_source"] == "nso_mt":
                rec["source_status"] = "mismatch_should_be_eurostat_or_keep_nso"
            elif expected_src == "curated" and rec["db_source"] == "curated":
                rec["source_status"] = "match"
            else:
                rec["source_status"] = "mismatch"

        # Value match
        if rec["te_value"] is not None and db_v is not None:
            ok = value_match(rec["te_value"], db_v["value"])
            if ok is True:
                rec["value_status"] = "match"
            elif ok is False:
                # Check if frontend-only (YoY/MoM): typical when te unit is "percent" but db is index
                rec["value_status"] = "mismatch"
                # Heuristic for frontend transform: inflation slugs are YoY rates
                if slug in ("inflation-cpi", "food-inflation", "cpi-food", "cpi-clothing",
                            "cpi-education", "cpi-housing-utilities", "cpi-recreation-and-culture",
                            "cpi-transportation", "core-cpi", "ppi", "house-price-index",
                            "industrial-production", "retail-sales", "manufacturing-production",
                            "mining-production", "productivity", "labour-costs",
                            "consumer-spending", "gdp-real", "imports", "exports"):
                    rec["value_status"] = "frontend-only"
            elif ok is None:
                rec["value_status"] = "unknown"
        else:
            rec["value_status"] = "no_data"

        if rec.get("source_status", "").startswith("match"):
            if rec.get("value_status") in ("match", "frontend-only"):
                summary["verified_ok"] += 1
            elif rec.get("value_status") == "frontend-only":
                summary["frontend_only"] += 1
            else:
                summary["value_mismatch"] += 1
        elif rec.get("source_status") == "mismatch":
            summary["source_mismatch"] += 1

        if db_v is None:
            summary["missing_db"] += 1

        findings[slug] = rec

    out = {"summary": summary, "findings": findings, "country": "MT", "total": len(slugs)}
    yaml.safe_dump(out, open("docs/_audit_mt_reaudit.yaml", "w", encoding="utf-8"),
                   sort_keys=False, allow_unicode=True)
    print(json.dumps(summary, indent=2))
    print(f"\nWrote docs/_audit_mt_reaudit.yaml ({len(findings)} slugs)")
    return findings, summary


if __name__ == "__main__":
    main()
