"""Generate LV reaudit findings yaml.
Compare TE source/value vs DB indicator_sources + latest data_point.
"""
import json, re, pathlib, yaml
from pipeline.db import supabase as sb

# Source-name -> our internal source code
SOURCE_MAP = {
    # Latvia national
    "central statistical bureau of latvia": "csp_lv",
    "central statistical bureau Of latvia": "csp_lv",
    "csb": "csp_lv",
    "csp": "csp_lv",
    "bank of latvia": "bol_lv",
    "latvijas banka": "bol_lv",
    "state revenue service, latvia": "curated",
    "state revenue service - ministry of finance": "curated",
    "state social insurance agency, latvia": "curated",
    "state employment agency, latvia": "curated",
    # Eurostat / EU
    "eurostat": "eurostat",
    "european commission": "eurostat",   # DG ECFIN BCS data via Eurostat in our pipeline
    "european central bank": "ecb",
    "ecb": "ecb",
    # World institutions
    "world bank": "worldbank",
    "oecd": "curated",
    "imf": "curated",
    "who": "curated",
    "world health organization": "curated",
    "transparency international": "curated",
    "institute for economics and peace": "curated",
    "conference board": "curated",
}


def normalize_source_name(name):
    if not name:
        return None
    return SOURCE_MAP.get(name.strip().lower())


# Extract latest numeric value from TE description text
# Patterns: "increased to 224.02 points", "stands at 20 percent", "decreased to 6.7%", etc.
VALUE_RE = re.compile(
    r"(?:increased|decreased|rose|fell|eased|widened|narrowed|expanded|grew|declined|jumped|"
    r"climbed|dropped|edged|slowed|remained\s+unchanged\s+at|stands?\s+at|was\s+(?:last\s+)?"
    r"(?:set\s+at|recorded|reported|worth|estimated\s+at|estimated\s+at)|stood\s+at|"
    r"to\s+EUR|to\s+\$|equal\s+to|set\s+at|hit|reached|of|by|at)\s+"
    r"(?:[A-Z]{1,3}\$?\s*|EUR\s*|USD\s*|\$\s*|€\s*)?"
    r"(-?[\d,]+(?:\.\d+)?)\s*"
    r"(?:%|percent|points?|billion|million|thousand|EUR|USD|\$|points|/|per)",
    re.I
)


def parse_value_from_desc(desc):
    """Best-effort numeric extraction from TE description."""
    if not desc:
        return None
    # Direct simpler patterns
    candidates = []
    # "X decreased to Y in <period>"
    for pat in [
        r"(?:decreased|increased|rose|fell|eased|grew|declined|edged|jumped|dropped|widened|narrowed|expanded|climbed|slowed|hit|reached)\s+to\s+(?:EUR\s+|USD\s+|\$|€)?(-?[\d,]+(?:\.\d+)?)",
        r"(?:remained\s+unchanged\s+at|stands?\s+at|was\s+(?:last\s+)?(?:set\s+at|recorded|reported|estimated\s+at|worth)|stood\s+at|stand\s+at|set\s+at)\s+(?:EUR\s+|USD\s+|\$|€)?(-?[\d,]+(?:\.\d+)?)",
        r"(?:was\s+last\s+recorded\s+at|increased\s+(?:by\s+)?)(?:EUR\s+|USD\s+|\$|€)?(-?[\d,]+(?:\.\d+)?)",
        r"by\s+(-?[\d,]+(?:\.\d+)?)\s*%",
        r"of\s+(-?[\d,]+(?:\.\d+)?)\s*(?:percent|%)",
        r"deficit\s+(?:equal\s+to|of)\s+(-?[\d,]+(?:\.\d+)?)",
        r"surplus\s+(?:equal\s+to|of)\s+(-?[\d,]+(?:\.\d+)?)",
    ]:
        m = re.search(pat, desc, re.I)
        if m:
            try:
                v = float(m.group(1).replace(",", ""))
                candidates.append(v)
            except ValueError:
                pass
    # negative deficit
    if "deficit" in desc.lower() and candidates:
        # convert positive deficit value to negative if context is "balance"
        pass
    return candidates[0] if candidates else None


def main():
    parsed = json.loads(pathlib.Path("docs/_audit_lv_te_parsed.json").read_text(encoding="utf-8"))
    # DB rows
    is_rows = sb.table("indicator_sources").select("indicator,source,is_default,note,series_id").eq("country", "LV").eq("is_default", True).execute().data
    db_src = {r["indicator"]: r for r in is_rows}
    # latest data_point per indicator (using the DEFAULT source only)
    dp_rows = sb.table("data_points").select("indicator,date,value,source").eq("country", "LV").execute().data
    latest = {}
    for r in dp_rows:
        ind = r["indicator"]
        # filter to default source
        default_src = db_src.get(ind, {}).get("source")
        if default_src and r["source"] != default_src:
            continue
        if ind not in latest or r["date"] > latest[ind]["date"]:
            latest[ind] = r

    findings = {}
    for slug, te in sorted(parsed.items()):
        te_source_name = te.get("source_name")
        te_source_code = normalize_source_name(te_source_name)
        db_row = db_src.get(slug, {})
        db_source = db_row.get("source")
        dp = latest.get(slug, {})

        te_value = parse_value_from_desc(te.get("description"))

        source_match = None
        if te_source_code and db_source:
            source_match = (te_source_code == db_source)
        # Fall back: te_source_name None means TE-page has no source attribution; keep DB source
        if te_source_code is None and te_source_name is None:
            source_match = "unknown"

        value_match = None
        if te_value is not None and dp.get("value") is not None:
            try:
                db_v = float(dp["value"])
                if te_value == 0:
                    value_match = (db_v == 0)
                else:
                    pct = abs(db_v - te_value) / abs(te_value) * 100
                    value_match = pct <= 5.0
            except Exception:
                value_match = None

        findings[slug] = {
            "te_source_name": te_source_name,
            "te_source_code": te_source_code,
            "te_description": (te.get("description") or "")[:240],
            "te_value_extracted": te_value,
            "db_source": db_source,
            "db_latest_date": dp.get("date"),
            "db_latest_value": dp.get("value"),
            "db_latest_source": dp.get("source"),
            "source_match": source_match,
            "value_match": value_match,
        }

    out = pathlib.Path("docs/_audit_lv_reaudit.yaml")
    out.write_text(yaml.safe_dump(findings, sort_keys=True, allow_unicode=True), encoding="utf-8")
    print(f"WROTE {out} ({len(findings)} entries)")

    # summary
    mismatches_src = [s for s, v in findings.items() if v["source_match"] is False]
    mismatches_val = [s for s, v in findings.items() if v["value_match"] is False]
    no_te = [s for s, v in findings.items() if v["te_source_code"] is None and v["te_source_name"] is None]
    print(f"\nSOURCE MISMATCHES ({len(mismatches_src)}):")
    for s in mismatches_src:
        v = findings[s]
        print(f"  {s}: TE={v['te_source_code']} ({v['te_source_name']!r}) -> DB={v['db_source']}")
    print(f"\nVALUE MISMATCHES ({len(mismatches_val)}):")
    for s in mismatches_val:
        v = findings[s]
        print(f"  {s}: TE={v['te_value_extracted']} | DB={v['db_latest_value']} @ {v['db_latest_date']}")
    print(f"\nNO TE PAGE ({len(no_te)}):")
    for s in no_te:
        print(f"  {s} (DB source={findings[s]['db_source']})")


if __name__ == "__main__":
    main()
