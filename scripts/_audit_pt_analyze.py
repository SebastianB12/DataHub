"""Analyze fetched TE PT pages, compare to DB+truth, output reaudit yaml + fix-plan.

Outputs:
  docs/_audit_pt_reaudit.yaml — full findings per slug
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "docs" / "_audit_te_html" / "pt_reaudit"
SLUGS_JSON = ROOT / "docs" / "_audit_all_remaining_slugs.json"
INV_YAML = ROOT / "docs" / "_te_inventory" / "PT.yaml"
OUT_YAML = ROOT / "docs" / "_audit_pt_reaudit.yaml"

import sys
sys.path.insert(0, str(ROOT))
from pipeline.db import supabase as sb  # noqa: E402

# Map TE source label -> internal source code
LABEL_MAP = {
    "statistics portugal": "ine_pt",
    "ine portugal": "ine_pt",
    "instituto nacional de estatística": "ine_pt",
    "instituto nacional de estatistica": "ine_pt",
    "banco de portugal": "bdp_pt",  # we don't have provider; will fall back
    "eurostat": "eurostat",
    "european commission": "eurostat",  # via DG ECFIN BCS, exposed in Eurostat ei_bsXX
    "world bank": "worldbank",
    "european central bank": "ecb",
    "ecb": "ecb",
    "oecd": "curated",
    "transparency international": "curated",
    "institute for economics and peace": "curated",
    "iefp - institute of employment and professional formation, portugal": "iefp_pt",  # gap, no provider
    "instituto da segurança social": "curated",  # static rates
    "instituto da seguranca social": "curated",
    "autoridade tributária e aduaneira": "curated",
    "autoridade tributaria e aduaneira": "curated",
    "dgo - direccao geral do orcamento, portugal": "dgo_pt",  # gap, no provider yet
    "dgo - direção-geral do orçamento, portugal": "dgo_pt",
}

# Some TE labels carry diacritics that get mangled
def normalize_label(s: str) -> str:
    s = s.replace("Tribut�ria", "Tributaria").replace("Seguran�a", "Seguranca")
    s = s.replace("�", "")
    return s.strip().lower()


SOURCE_A = re.compile(
    r"source:\s*<a\s+class='source-name'[^>]*href\s*=\s*'([^']*)'[^>]*>([^<]+)</a>",
    re.I,
)
SOURCE_B = re.compile(
    r"<span\s+class='source-present'>source:\s*([^<]+)</span>", re.I
)
DESC_META = re.compile(r'<meta\s+name="description"\s+content="([^"]+)"', re.I)
OG_DESC = re.compile(r'<meta\s+property="og:description"\s+content="([^"]+)"', re.I)
H2_DESC = re.compile(r'<h2[^>]*itemprop="description"[^>]*>([\s\S]{0,1500}?)</h2>', re.I)


def parse_html(html: str) -> dict:
    out: dict = {}
    a = SOURCE_A.search(html)
    b = SOURCE_B.search(html)
    if a:
        out["te_source_url"] = a.group(1)
        out["te_source_label"] = a.group(2).strip()
    elif b:
        out["te_source_label"] = b.group(1).strip()
    desc = ""
    md = DESC_META.search(html)
    if md:
        desc = md.group(1)
    else:
        og = OG_DESC.search(html)
        if og:
            desc = og.group(1)
        else:
            h2 = H2_DESC.search(html)
            if h2:
                desc = re.sub(r"<[^>]+>", " ", h2.group(1))
    out["te_meta_desc"] = desc.strip()[:600] if desc else ""
    # Pull latest value & period from description
    if desc:
        # "Portugal X went up/down to Y units in MONTH YEAR"
        # extract first decimal number
        nm = re.search(
            r"(?:to|of|reaching|at)\s+([\-−]?\d{1,3}(?:[,]?\d{3})*(?:\.\d{1,4})?)\s*(percent|%|EUR|USD|Million|Billion|thousand|of GDP|index|points|points\.|Index|years)",
            desc,
            re.I,
        )
        if nm:
            out["te_value"] = nm.group(1).replace(",", ".").replace("−", "-")
            out["te_value_unit"] = nm.group(2)
        # period
        pm = re.search(
            r"in\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(?:of\s+)?(\d{4})",
            desc,
            re.I,
        )
        if pm:
            mo = {"January":1,"February":2,"March":3,"April":4,"May":5,"June":6,"July":7,"August":8,"September":9,"October":10,"November":11,"December":12}[pm.group(1)]
            out["te_period"] = f"{pm.group(2)}-{mo:02d}"
        qm = re.search(
            r"in\s+the\s+(first|second|third|fourth)\s+quarter\s+of\s+(\d{4})",
            desc,
            re.I,
        )
        if qm:
            qm_no = {"first":1,"second":2,"third":3,"fourth":4}[qm.group(1).lower()]
            out["te_period"] = f"{qm.group(2)}-Q{qm_no}"
        # annual
        am = re.search(r"in\s+(\d{4})(?:\s|\.|,)", desc)
        if am and "te_period" not in out:
            out["te_period"] = am.group(1)
    return out


def db_state() -> dict[str, list[dict]]:
    r = sb.table("indicator_sources").select(
        "indicator,source,series_id,is_default,active,unit,adjustment"
    ).eq("country", "PT").execute()
    d: dict[str, list[dict]] = {}
    for x in r.data:
        d.setdefault(x["indicator"], []).append(x)
    return d


def latest_dp(slug: str) -> dict | None:
    r = sb.table("data_points").select(
        "date,value,source,adjustment"
    ).eq("country", "PT").eq("indicator", slug).order(
        "date", desc=True
    ).limit(1).execute()
    return r.data[0] if r.data else None


def main():
    slugs = json.loads(SLUGS_JSON.read_text(encoding="utf-8"))["PT"]
    db = db_state()
    findings: dict[str, dict] = {}
    for slug in slugs:
        f: dict = {"slug": slug}
        html_path = CACHE_DIR / f"{slug}.html"
        if not html_path.exists() or html_path.stat().st_size < 5000:
            f["error"] = "no html cache"
            findings[slug] = f
            continue
        html = html_path.read_text(encoding="utf-8", errors="ignore")
        parsed = parse_html(html)
        f.update(parsed)
        # map label -> internal
        label = parsed.get("te_source_label", "")
        if label:
            key = normalize_label(label)
            mapped = LABEL_MAP.get(key)
            if not mapped:
                # try contains
                for k, v in LABEL_MAP.items():
                    if k in key:
                        mapped = v
                        break
            f["expected_source"] = mapped or "?"
        else:
            f["expected_source"] = ""

        # DB current
        rows = db.get(slug, [])
        default_row = next((r for r in rows if r["is_default"]), None)
        f["current_source"] = default_row["source"] if default_row else "(missing)"
        f["current_series_id"] = default_row["series_id"] if default_row else ""

        # latest DP
        dp = latest_dp(slug)
        if dp:
            f["latest_date"] = str(dp["date"])
            f["latest_value"] = dp["value"]
            f["latest_dp_source"] = dp["source"]

        # Conform?
        exp = f["expected_source"]
        cur = f["current_source"]
        if exp and exp == cur:
            f["conform"] = True
        elif not exp:
            f["conform"] = "unknown"
        else:
            f["conform"] = False

        findings[slug] = f

    # write yaml
    import yaml
    OUT_YAML.write_text(
        yaml.safe_dump(findings, sort_keys=True, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )

    # summary
    print(f"Wrote {OUT_YAML}")
    n_conform = sum(1 for f in findings.values() if f.get("conform") is True)
    n_mismatch = sum(1 for f in findings.values() if f.get("conform") is False)
    n_unknown = sum(1 for f in findings.values() if f.get("conform") == "unknown")
    print(f"conform={n_conform}, mismatch={n_mismatch}, unknown={n_unknown}, total={len(findings)}")
    print("\n=== Mismatches ===")
    for s, f in findings.items():
        if f.get("conform") is False:
            print(f"  {s:40s} cur={f.get('current_source','?'):12s} expect={f.get('expected_source','?'):12s}  te_label={f.get('te_source_label','?')}")
    print("\n=== Unknown TE source ===")
    for s, f in findings.items():
        if f.get("conform") == "unknown":
            print(f"  {s:40s} cur={f.get('current_source','?'):12s} (no TE source label)")


if __name__ == "__main__":
    main()
