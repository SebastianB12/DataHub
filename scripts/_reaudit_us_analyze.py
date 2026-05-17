"""Reaudit US: parse cached TE HTML, compare to DB, write docs/_audit_us_reaudit.yaml."""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.db import supabase as sb  # noqa: E402

SLUGS_FILE = ROOT / "docs" / "_audit_5cc_slugs.json"
HTML_DIR = ROOT / "docs" / "_audit_te_html" / "us_reaudit"
OUT_FILE = ROOT / "docs" / "_audit_us_reaudit.yaml"

SOURCE_RE = re.compile(
    r"source:\s*<a class='source-name'[^>]*href\s*=\s*'([^']*)'[^>]*>([^<]+)</a>",
    re.I,
)
DESC_RE = re.compile(r'<h2 id="description"[^>]*>(.*?)</h2>', re.S)
VALUE_RE = re.compile(
    r"(?:to|at|of|reached)\s+(-?\$?\d[\d,\.]*)\s*(%|percent|billion|million|points|index|thousand|USD|barrels|tonnes|jobs|units|hours|kbd|bcf|persons|points\.|million\s+tonnes)?",
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

# Map TE source label -> internal source code (US-specific).
# Per slug, accept multiple valid codes; this is an "allow-list" set.
def label_to_codes(label: str) -> set[str]:
    if not label:
        return set()
    low = label.lower()
    codes: set[str] = set()
    fred_labels = [
        "federal reserve", "fred", "bureau of labor statistics", "bureau of economic analysis",
        "u.s. census bureau", "census bureau", "conference board",
        "freddie mac", "national association of realtors", "national association of home builders",
        "automatic data processing", "adp", "american petroleum institute",
        "institute for supply management", "ism", "university of michigan",
        "national federation of independent business", "redbook research",
        "challenger, gray", "office of management and budget",
        "u.s. department of labor",  # ETA initial/continuing claims via FRED
    ]
    if any(k in low for k in fred_labels):
        codes.add("fred")
    if "energy information administration" in low or low == "eia":
        codes.add("eia")
    if "world bank" in low:
        codes.add("worldbank")
        codes.add("curated")  # legacy WB-derived values may live in curated
    # Curated (single-value indicators like tax rates, retirement ages, sentiment indices etc.)
    curated_labels = [
        "transparency international", "oecd", "who", "world health organization",
        "sipri", "imf", "international monetary fund", "wto", "fao",
        "institute for economics and peace",
        "internal revenue service", "social security administration",
        "department of labor",  # mostly minimum-wage curated
        "u.s. treasury", "treasury",  # gov-spending-to-gdp curated, debt-to-penny fred
    ]
    if any(k in low for k in curated_labels):
        codes.add("curated")
    if "treasury" in low:
        codes.add("fred")  # debt-to-penny stored as fred
    return codes


def label_to_code(label: str) -> str | None:
    s = label_to_codes(label)
    if not s: return None
    if len(s) == 1: return next(iter(s))
    # ambiguous; return the first (for display)
    return "/".join(sorted(s))


def parse_te_page(html: str) -> dict:
    out = {
        "te_label": None, "te_url": None, "te_value": None,
        "te_period": None, "te_unit": None, "te_desc": None,
    }
    m = SOURCE_RE.search(html)
    if m:
        out["te_url"] = m.group(1).strip()
        out["te_label"] = m.group(2).strip()
    dm = DESC_RE.search(html)
    desc = dm.group(1) if dm else html[:5000]
    desc_text = re.sub(r"<[^>]+>", " ", desc)
    desc_text = re.sub(r"\s+", " ", desc_text).strip()
    out["te_desc"] = desc_text[:600]
    # If SOURCE_RE didn't match, try plain-text "source: Transparency International" etc.
    if not out["te_label"]:
        m2 = re.search(r"\bsource:\s*([A-Z][A-Za-z\.,&\s]{3,60}?)(?:\s*\.\s|\.\Z|\Z| This\s)", desc_text)
        if m2:
            out["te_label"] = m2.group(1).strip().rstrip(".")
    # Fallback: "reported by X" or "according to X" common on curated pages
    if not out["te_label"]:
        for pat in [
            r"reported by ([A-Z][A-Za-z\s&]+)\.",
            r"according to (?:official data from )?(?:the )?([A-Z][A-Za-z\s&]+)\.",
            r"compiled by (?:the )?([A-Z][A-Za-z\s&]+)\.",
        ]:
            m3 = re.search(pat, desc_text)
            if m3:
                out["te_label"] = m3.group(1).strip()
                break
    vm = VALUE_RE.search(desc_text)
    if vm:
        try:
            raw = vm.group(1).lstrip("$").replace(",", "")
            out["te_value"] = float(raw)
            out["te_unit"] = vm.group(2)
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
        else:
            out["te_period"] = pm.group(0)
    return out


def fetch_db():
    """Return {slug: (source, series_id, latest_dp, prev_dp_12, all_dps_13)}."""
    rows = (
        sb.table("indicator_sources")
        .select("indicator,source,series_id,note")
        .eq("country", "US").eq("is_default", True).eq("active", True).execute().data
    )
    db = {}
    for r in rows:
        slug = r["indicator"]
        try:
            # Match indicator_sources.source so we don't grab old shadow data
            dp = (
                sb.table("data_points")
                .select("date,value,adjustment")
                .eq("country", "US").eq("indicator", slug)
                .eq("source", r["source"])
                .order("date", desc=True).limit(25).execute().data
            )
        except Exception:
            dp = []
        # Prefer adjustment='' (default), fall back to SA/NSA
        by_adj = {}
        for x in dp:
            by_adj.setdefault(x.get("adjustment") or "", []).append(x)
        # pick adjustment with most entries that has most-recent date
        if "" in by_adj and by_adj[""]:
            picked = by_adj[""]
        elif "SA" in by_adj:
            picked = by_adj["SA"]
        elif "NSA" in by_adj:
            picked = by_adj["NSA"]
        else:
            picked = sorted(dp, key=lambda x: x["date"], reverse=True) if dp else []
        # Dedupe by date keeping first encountered
        seen = set(); uniq = []
        for x in picked:
            if x["date"] in seen: continue
            seen.add(x["date"]); uniq.append(x)
        db[slug] = {
            "source": r["source"],
            "series_id": r.get("series_id"),
            "note": r.get("note"),
            "dps": uniq[:15],
        }
    return db


def value_match(te_value, te_unit, te_desc, our_value, dps):
    """Return (matched, computed_yoy_or_none, flag_hint)."""
    if te_value is None or our_value is None:
        return (None, None, None)
    # Direct match (within 5%)
    if te_value != 0:
        rel = abs(te_value - our_value) / abs(te_value)
    else:
        rel = abs(our_value - te_value)
    if rel <= 0.05:
        return (True, None, None)
    # Try YoY computation from our level data
    yoy = None
    if len(dps) >= 13:
        try:
            v0 = float(dps[0]["value"])
            v12 = float(dps[12]["value"])
            if v12 != 0:
                yoy = (v0 - v12) / abs(v12) * 100
                if te_value != 0 and abs(te_value - yoy) / abs(te_value) <= 0.10:
                    return (True, yoy, "yoy-computed")
                if abs(te_value - yoy) <= 0.5:  # absolute pp tolerance
                    return (True, yoy, "yoy-computed")
        except (KeyError, TypeError, ValueError):
            pass
    # MoM hint
    if len(dps) >= 2:
        try:
            v0 = float(dps[0]["value"]); v1 = float(dps[1]["value"])
            if v1 != 0:
                mom = (v0 - v1) / abs(v1) * 100
                if te_value != 0 and abs(te_value - mom) / abs(te_value) <= 0.10:
                    return (False, mom, "frontend-only-mom")
        except (KeyError, TypeError, ValueError):
            pass
    return (False, yoy, None)


def main():
    slugs = json.loads(SLUGS_FILE.read_text())["US"]
    db = fetch_db()
    out = {}
    for slug in slugs:
        html_path = HTML_DIR / f"{slug}.html"
        if not html_path.exists():
            out[slug] = {
                "te_label": None, "te_value": None, "te_period": None,
                "our_source": db.get(slug, {}).get("source"),
                "our_series": db.get(slug, {}).get("series_id"),
                "our_value": None, "our_period": None,
                "source_match": None, "value_match": None,
                "fixed": False, "fix_summary": None,
                "flag": "no-te-html",
            }
            continue
        html = html_path.read_text(encoding="utf-8")
        parsed = parse_te_page(html)
        dbr = db.get(slug, {})
        our_source = dbr.get("source")
        our_series = dbr.get("series_id")
        dps = dbr.get("dps") or []
        our_value = float(dps[0]["value"]) if dps else None
        our_period = dps[0]["date"] if dps else None

        # Source match: map TE label -> code-set, allow if our_source in set
        sug_set = label_to_codes(parsed.get("te_label"))
        sug = label_to_code(parsed.get("te_label"))
        if not sug_set:
            src_match = None  # unknown TE label
        else:
            src_match = (our_source in sug_set)

        # Value match
        val_match, yoy_computed, flag_hint = value_match(
            parsed.get("te_value"), parsed.get("te_unit"),
            parsed.get("te_desc"), our_value, dps,
        )

        flag = None
        if not html.strip() or "<html" not in html.lower():
            flag = "empty-html"
        elif parsed.get("te_label") is None:
            flag = "no-te-source-on-page"
        elif parsed.get("te_value") is None:
            flag = "no-te-headline"
        elif src_match is False:
            flag = "source-mismatch"
        elif val_match is False:
            flag = flag_hint or "value-mismatch"
        elif our_value is None:
            flag = "no-our-data"

        out[slug] = {
            "te_label": parsed.get("te_label"),
            "te_url": parsed.get("te_url"),
            "te_value": parsed.get("te_value"),
            "te_period": parsed.get("te_period"),
            "te_unit": parsed.get("te_unit"),
            "te_desc": parsed.get("te_desc"),
            "suggested_source": sug,
            "our_source": our_source,
            "our_series": our_series,
            "our_value": our_value,
            "our_period": our_period,
            "source_match": src_match,
            "value_match": val_match,
            "yoy_computed": yoy_computed,
            "fixed": False,
            "fix_summary": None,
            "flag": flag,
        }
    OUT_FILE.write_text(yaml.safe_dump(out, sort_keys=True, allow_unicode=True), encoding="utf-8")
    print(f"Wrote {OUT_FILE} ({len(out)} slugs)")
    # quick summary
    by_flag = {}
    for k, v in out.items():
        by_flag.setdefault(v.get("flag"), []).append(k)
    for f, items in by_flag.items():
        print(f"  {f}: {len(items)}")


if __name__ == "__main__":
    main()
