"""Build docs/_audit_de_reaudit.yaml by parsing cached TE HTML and comparing to DB."""
import json
import re
from datetime import datetime
from pathlib import Path

import yaml

from pipeline.db import supabase as sb

ROOT = Path(__file__).resolve().parents[1]
HTML_DIR = ROOT / "docs" / "_audit_te_html" / "de_reaudit"
OUT = ROOT / "docs" / "_audit_de_reaudit.yaml"

SOURCE_RE = re.compile(
    r"source:\s*<a class='source-name'[^>]*href\s*=\s*'([^']*)'[^>]*>([^<]+)</a>", re.I
)
DESC_RE = re.compile(r'<h2 id="description"[^>]*>(.*?)</h2>', re.S)
H1_RE = re.compile(r'<h1[^>]*>(.*?)</h1>', re.S)
MONTH = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
PERIOD_FRAG = (
    MONTH + r"\s+(?:of\s+)?\d{4}"
    + r"|" + MONTH + r"(?=\s+from)"
    + r"|" + MONTH
    + r"|the\s+(?:first|second|third|fourth)\s+quarter\s+of\s+\d{4}"
    + r"|Q\d\s+\d{4}"
    + r"|\d{4}"
)
# Pattern A: "X in Germany increased/decreased to <num> <unit> in <period>"
VAL_RE_A = re.compile(
    r"(?:increased|decreased|remained\s+unchanged|stood|was\s+last\s+recorded|was\s+estimated|increased\s+by|decreased\s+by)"
    r"\s+(?:at\s+)?(?:to\s+)?(-?[\d,]+(?:\.\d+)?)\s*"
    r"(%|per\s+1000\s+people|per\s+1,?000\s+people|percent\s+of\s+GDP|EUR\s+Million|EUR\s+Billion|USD\s+Million|USD\s+Billion|million\s+people|Thousand|Companies|points|percent|EUR/Month|USD/Month|EUR/Hour|USD/Hour|per\s+1000\s+live\s+births|per\s+cent|Years?|SIPRI\s+TIV\s+Million)"
    r"\s+in\s+(" + PERIOD_FRAG + r")",
    re.I,
)
# Pattern B: "X dropped/jumped/rose/fell N% YoY/MoM/yoy/mom in <period>"
VAL_RE_B = re.compile(
    r"(?:dropped|fell|rose|jumped|surged|gained|edged|grew|increased|decreased|contracted|expanded)\s+(?:by\s+)?(-?[\d,]+(?:\.\d+)?)\s*%\s*"
    r"(?:year[-\s]on[-\s]year|yoy|month[-\s]on[-\s]month|month[-\s]over[-\s]month|mom|m/m|y/y)?\s*"
    r"in\s+(" + PERIOD_FRAG + r")",
    re.I,
)
# Pattern C: "<Topic> N% in <period>"
VAL_RE_C = re.compile(
    r"^[A-Z][A-Za-z ]+?\s+in\s+Germany\s+(?:increased|decreased)\s+(-?[\d,]+(?:\.\d+)?)%\s+in\s+(" + PERIOD_FRAG + r")",
    re.I,
)
# Pattern D: "population was estimated at N million people in YYYY"
VAL_RE_D = re.compile(
    r"was\s+(?:estimated\s+at|last\s+recorded\s+at)\s+(-?[\d,]+(?:\.\d+)?)\s+"
    r"([A-Za-z][A-Za-z /%\.,0-9]*?)"
    r"\s+(?:in\s+)?(" + PERIOD_FRAG + r")",
    re.I,
)
# Pattern E: "stands at N percent"
VAL_RE_E = re.compile(
    r"stands\s+at\s+(-?[\d,]+(?:\.\d+)?)\s*(percent|%|EUR|years?)",
    re.I,
)
# Pattern F: "deficit equal to N percent ... in YYYY" OR "surplus of N percent ... in YYYY"
VAL_RE_F = re.compile(
    r"(?:deficit\s+equal\s+to|surplus\s+of|deficit\s+of)\s+(-?[\d,]+(?:\.\d+)?)\s+percent\s+of[^.]+?\s+in\s+(" + PERIOD_FRAG + r")",
    re.I,
)
# Pattern G: "scored N points"
VAL_RE_G = re.compile(
    r"scored\s+(-?[\d,]+(?:\.\d+)?)\s+points?\s+out\s+of\s+\d+\s+on\s+the\s+(\d{4})",
    re.I,
)
# Pattern H: "narrowed/widened/surged ... to ... <currency-symbol>N <unit> in <period>"
# Handles €23.6 billion, $135.8 billion etc.
VAL_RE_H = re.compile(
    r"(?:to|of|reached)\s+(?:[$€\xa3]|EUR\s|USD\s)?\s*(-?[\d,]+(?:\.\d+)?)\s+(billion|million|trillion|thousand)\s+in\s+(" + PERIOD_FRAG + r")",
    re.I,
)
# Pattern I: "expanded/grew/contracted by N% year over year in <quarter>"
VAL_RE_I = re.compile(
    r"(?:expanded|grew|contracted|shrank|rose|increased|decreased|fell|dropped)\s+(?:by\s+)?(-?[\d,]+(?:\.\d+)?)\s*%\s+(?:year[-\s]?over[-\s]?year|year[-\s]on[-\s]year|yoy|annually|year[-\s]on[-\s]year|y/y)?\s*(?:in\s+)?(" + PERIOD_FRAG + r")",
    re.I,
)
# Pattern J: "was worth N (billion|...) US dollars in YYYY"
VAL_RE_J = re.compile(
    r"was\s+worth\s+(-?[\d,]+(?:\.\d+)?)\s+(billion|million|trillion)\s+US\s+dollars?\s+in\s+(" + PERIOD_FRAG + r")",
    re.I,
)
# Pattern K: "rose|fell|increased by N,000 ... to N million in <period>"
VAL_RE_K = re.compile(
    r"to\s+(-?[\d,]+(?:\.\d+)?)\s+(million|thousand|billion)\s+in\s+(" + PERIOD_FRAG + r")",
    re.I,
)
# Pattern L: "accelerated to N% in <period>"
VAL_RE_L = re.compile(
    r"(?:accelerated|slowed|eased|jumped|fell|rose|increased|decreased|edged|surged|narrowed|widened|advanced|gained)\s+(?:slightly\s+)?to\s+(-?[\d,]+(?:\.\d+)?)\s*%\s+in\s+(" + PERIOD_FRAG + r")",
    re.I,
)

# Pattern M: "is the N least/most corrupt"
VAL_RE_M = re.compile(
    r"is\s+the\s+(-?\d+)(?:st|nd|rd|th)?\s+(?:least|most)\s+corrupt",
    re.I,
)

ALL_PATTERNS_PERCENT = [VAL_RE_B, VAL_RE_C, VAL_RE_I, VAL_RE_L, VAL_RE_F]
ALL_PATTERNS_LEVEL = [VAL_RE_A, VAL_RE_D, VAL_RE_E, VAL_RE_G, VAL_RE_J, VAL_RE_H, VAL_RE_K, VAL_RE_M]

# Source line in plain text
SRC_TEXT_RE = re.compile(r"source:\s*([A-Za-z][A-Za-z0-9 /,&\(\)\.\-]+)", re.I)

SOURCE_MAP = {
    "statistisches bundesamt": "destatis",
    "destatis": "destatis",
    "federal statistical office": "destatis",
    "deutsche bundesbank": "bundesbank",
    "bundesbank": "bundesbank",
    "european central bank": "bundesbank",  # DE route ECB rates through bundesbank
    "ecb": "bundesbank",
    "eurostat": "eurostat",
    "european commission": "eurostat",
    "world bank": "worldbank",
    "conference board": "curated",
    "ifo": "curated",
    "ifo institute": "curated",
    "gfk": "curated",
    "zew": "curated",
    "sipri": "curated",
    "transparency international": "curated",
    "oecd": "curated",
    "who": "curated",
    "world health organization": "curated",
    "institute for economics and peace": "curated",
    "iep": "curated",
    "bundeszentralamt für steuern": "curated",
    "bundesagentur für arbeit": "curated",
    "europace ag": "curated",
    "europace ag, germany": "curated",
    "ministry of finance": "curated",
    "ministry of labour": "curated",
}


def normalize_source(label: str) -> str | None:
    if not label:
        return None
    key = label.strip().lower()
    if key in SOURCE_MAP:
        return SOURCE_MAP[key]
    for needle, val in SOURCE_MAP.items():
        if needle in key:
            return val
    return None


def parse_te_html(slug: str, html: str) -> dict:
    out = {
        "te_label": None,
        "te_source_url": None,
        "te_value": None,
        "te_unit": None,
        "te_period": None,
        "te_normalized_source": None,
    }
    m = SOURCE_RE.search(html)
    if m:
        out["te_source_url"] = m.group(1)
        out["te_label"] = m.group(2).strip()
        out["te_normalized_source"] = normalize_source(out["te_label"])
    # Description block
    md = DESC_RE.search(html)
    desc_text = ""
    if md:
        desc_text = re.sub(r"<[^>]+>", " ", md.group(1))
        desc_text = re.sub(r"\s+", " ", desc_text).strip()
        # Source line within description (fallback)
        if not out["te_label"]:
            mst = SRC_TEXT_RE.search(desc_text)
            if mst:
                out["te_label"] = mst.group(1).strip().rstrip(".")
                out["te_normalized_source"] = normalize_source(out["te_label"])
        # Value/unit/period: try patterns in order
        # Take only the first sentence to avoid matching "averaged X from..." or "all time high"
        first_sentence = re.split(r"(?<=\.)\s+(?=[A-Z])", desc_text, maxsplit=1)[0]
        matched = False
        for pat in ALL_PATTERNS_LEVEL:
            mv = pat.search(first_sentence)
            if mv:
                try:
                    out["te_value"] = float(mv.group(1).replace(",", ""))
                except ValueError:
                    continue
                groups = mv.groups()
                out["te_unit"] = groups[1].strip() if len(groups) > 1 and groups[1] else None
                out["te_period"] = groups[-1].strip() if len(groups) >= 3 else None
                matched = True
                break
        if not matched:
            for pat in ALL_PATTERNS_PERCENT:
                mv = pat.search(first_sentence)
                if mv:
                    try:
                        out["te_value"] = float(mv.group(1).replace(",", ""))
                    except ValueError:
                        continue
                    out["te_unit"] = "%"
                    out["te_period"] = mv.group(2).strip() if len(mv.groups()) >= 2 else None
                    matched = True
                    break
    return out


def fmt_period(period: str | None) -> str | None:
    if not period:
        return None
    month_map = {
        "January": "01", "February": "02", "March": "03", "April": "04",
        "May": "05", "June": "06", "July": "07", "August": "08",
        "September": "09", "October": "10", "November": "11", "December": "12",
    }
    p = period.strip()
    # "April 2026"
    m = re.match(r"([A-Z][a-z]+)\s+(?:of\s+)?(\d{4})$", p)
    if m and m.group(1) in month_map:
        return f"{m.group(2)}-{month_map[m.group(1)]}"
    # "April of 2026"
    m = re.match(r"([A-Z][a-z]+)\s+of\s+(\d{4})$", p)
    if m and m.group(1) in month_map:
        return f"{m.group(2)}-{month_map[m.group(1)]}"
    # "the fourth quarter of 2025"
    quarters = {"first":"Q1","second":"Q2","third":"Q3","fourth":"Q4"}
    m = re.match(r"the\s+(\w+)\s+quarter\s+of\s+(\d{4})$", p)
    if m and m.group(1) in quarters:
        return f"{m.group(2)}-{quarters[m.group(1)]}"
    # "Q4 2025"
    m = re.match(r"Q(\d)\s+(\d{4})$", p)
    if m:
        return f"{m.group(2)}-Q{m.group(1)}"
    # "2024" bare
    if re.match(r"^\d{4}$", p):
        return p
    return p


def fetch_db_rows(slug: str) -> dict:
    # indicator_sources row
    src = sb.table("indicator_sources").select(
        "indicator,source,series_id,is_default,note,unit,conversion,transform"
    ).eq("country", "DE").eq("indicator", slug).eq("is_default", True).execute()
    src_row = src.data[0] if src.data else None
    # latest data_point — match the default source
    if src_row:
        dp = sb.table("data_points").select(
            "indicator,source,date,value,unit"
        ).eq("country", "DE").eq("indicator", slug).eq("source", src_row["source"]).order(
            "date", desc=True
        ).limit(1).execute()
    else:
        dp = sb.table("data_points").select(
            "indicator,source,date,value,unit"
        ).eq("country", "DE").eq("indicator", slug).order("date", desc=True).limit(1).execute()
    dp_row = dp.data[0] if dp.data else None
    return {"src": src_row, "dp": dp_row}


def values_match(te: float | None, db: float | None, tol: float = 0.05) -> bool | None:
    if te is None or db is None:
        return None
    if te == 0 and db == 0:
        return True
    if te == 0 or db == 0:
        return abs(te - db) < 0.5
    rel = abs(te - db) / abs(te)
    if rel <= tol:
        return True
    # Try common scale conversions (Million<->Billion, sign-flips for deficit)
    for k in (1000, 0.001, -1, -1000, -0.001):
        v = db * k
        if abs(te - v) / abs(te) <= tol:
            return True
    return False


def main():
    slugs = json.loads((ROOT / "docs" / "_audit_5cc_slugs.json").read_text())["DE"]
    out = {}
    for slug in slugs:
        html_path = HTML_DIR / f"{slug}.html"
        html = html_path.read_text(encoding="utf-8", errors="ignore") if html_path.exists() else ""
        te = parse_te_html(slug, html)
        db = fetch_db_rows(slug)
        src_row = db["src"]
        dp_row = db["dp"]
        our_source = src_row["source"] if src_row else None
        our_series = src_row["series_id"] if src_row else None
        our_value = dp_row["value"] if dp_row else None
        our_period = str(dp_row["date"]) if dp_row else None

        # Source match
        if te["te_normalized_source"] is None:
            source_match = None
        elif our_source == te["te_normalized_source"]:
            source_match = True
        else:
            source_match = False

        # Value match
        vm = values_match(te["te_value"], our_value)

        entry = {
            "te_label": te["te_label"],
            "te_normalized_source": te["te_normalized_source"],
            "te_value": te["te_value"],
            "te_unit": te["te_unit"],
            "te_period": fmt_period(te["te_period"]),
            "our_source": our_source,
            "our_series": our_series,
            "our_value": float(our_value) if our_value is not None else None,
            "our_period": our_period,
            "source_match": source_match,
            "value_match": vm,
            "fixed": False,
            "fix_summary": None,
            "flag": None,
        }
        out[slug] = entry
    OUT.write_text(
        yaml.safe_dump(out, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
