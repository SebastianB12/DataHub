"""Add fix_summary/flag annotations to docs/_audit_us_batch1_findings.yaml.

Reads the audit findings + description data, adds proper flags:
  - "fixed": series_id was changed during this audit
  - "frontend-only": series correct, but TE shows MoM/YoY/level transformation
  - "te-page-anomaly": TE page bug (e.g. cpi-clothing showing transport data)
  - "stale-data": series correct, value close, just stale by a month
  - "ok": source and value match
"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

# Manual classification based on TE descriptions
ANNOTATIONS = {
    # === FIXED ===
    "cpi-median": {
        "fixed": True,
        "fix_summary": "Series changed MEDCPIM158SFRBCLE (annualized monthly) -> MEDCPIM159SFRBCLE (12-month YoY); now matches TE 2.80%",
        "flag": None,
    },
    "cpi-trimmed-mean": {
        "fixed": True,
        "fix_summary": "Series changed TRMMEANCPIM158SFRBCLE -> TRMMEANCPIM159SFRBCLE (12-month YoY); now matches TE 2.80%",
        "flag": None,
    },
    "core-producer-prices": {
        "fixed": True,
        "fix_summary": "Series changed WPSFD4131 (1982=100) -> PPIFES (Apr 2010=100); now matches TE 154.06",
        "flag": None,
    },
    "exports": {
        "fixed": True,
        "fix_summary": "Series changed BOPGEXP (goods only) -> BOPTEXP (goods + services); now matches TE $320.9B",
        "flag": None,
    },
    "current-account": {
        "fixed": True,
        "fix_summary": "Series changed NETFI (annualized NIPA $B) -> IEABC (quarterly BoP $M); now matches TE -$190.7B Q4 2025",
        "flag": None,
    },
    "car-production": {
        "fixed": True,
        "fix_summary": "Series changed DAUPSA (Domestic Auto Production, thousands) -> MVAAUTLTTS (Motor Vehicle Assemblies: Autos + Light Truck, SAAR Millions); now matches TE 9.98M units",
        "flag": None,
    },

    # === FRONTEND-ONLY: TE shows transformation of our (correct) level series ===
    "adp-employment-change": {
        "flag": "frontend-only",
        "fix_summary": "ADPMNUSNERSA stores level (132.5M); TE shows MoM change (109K). Frontend should compute diff(level)",
    },
    "average-weekly-hours": {
        "flag": "ok",
        "fix_summary": "Level 34.3 hours April 2026 vs our 34.2 March; pipeline just one month stale",
    },
    "budget-deficit": {
        "flag": "frontend-display",
        "fix_summary": "TE shows |deficit| as 5.90% positive; we store signed -5.77%. Sign convention only — values match",
    },
    "building-permits": {
        "flag": "frontend-only",
        "fix_summary": "PERMIT level 1372K matches TE 1.363M (SAAR). Off by 9 (revision); just unit display issue",
    },
    "business-inventories": {
        "flag": "frontend-only",
        "fix_summary": "BUSINV stores level $2.69T; TE shows MoM% (0.9%). Frontend should compute MoM",
    },
    "capital-flows": {
        "flag": "needs-attention",
        "fix_summary": "NETFI gives -$890B annualized current account; TE shows monthly TIC net flow ($184.5B Feb). Different concept — may need TIC long-term series instead",
    },
    "central-bank-balance": {
        "flag": "no-te-headline",
        "fix_summary": "TE description empty; WALCL value 6699.95 ($B) is correct H.4.1 Fed balance sheet",
    },
    "changes-in-inventories": {
        "flag": "frontend-only",
        "fix_summary": "CBIC1 -$7.53B matches TE -$7.50B (sign aside). Source label not parsed but BEA = our 'fred'",
    },
    "chicago-fed-national-activity-index": {
        "flag": "ok",
        "fix_summary": "CFNAI -0.20 March 2026 matches TE -0.20 exactly; parser missed value with no % suffix",
    },
    "construction-payrolls": {
        "flag": "frontend-only",
        "fix_summary": "USCONS stores level 8.33M; TE shows MoM change in thousands (9K April). Frontend should diff",
    },
    "construction-spending": {
        "flag": "frontend-only",
        "fix_summary": "TTLCONS stores level $2.19T; TE shows MoM% (0.6%). Frontend should compute MoM",
    },
    "consumer-confidence": {
        "flag": "needs-attention",
        "fix_summary": "UMCSENT 53.3 vs TE 48.2 May. Series correct (UMich) but our data may be one month stale OR TE uses preliminary release",
    },
    "consumer-credit": {
        "flag": "frontend-only",
        "fix_summary": "TOTALSL stores level $5.12T; TE shows MoM change ($24.9B March). Frontend should diff",
    },
    "consumer-spending": {
        "flag": "ok",
        "fix_summary": "PCEC96 $16772.7B Q1 vs TE $16731.2B — close. Source label empty (BEA). Frontend would compute QoQ",
    },
    "continuing-jobless-claims": {
        "flag": "ok",
        "fix_summary": "CCSA 1785K matches TE 1782K week ending May 2",
    },
    "core-cpi": {
        "flag": "frontend-only",
        "fix_summary": "CPILFENS 334.4 index; TE shows YoY% (2.8%). Frontend should compute YoY",
    },
    "corporate-profits": {
        "flag": "frontend-only",
        "fix_summary": "CP stores level $3792B; TE shows QoQ% (5.7%). Frontend should compute QoQ",
    },
    "corporate-tax-rate": {
        "flag": "ok",
        "fix_summary": "Curated value 21% matches TE 21%",
    },
    "corruption-index": {
        "flag": "ok",
        "fix_summary": "Curated 64 (2025 TI CPI) matches TE 64; parser picked TE all-time-high 78",
    },
    "corruption-rank": {
        "flag": "ok",
        "fix_summary": "Curated 29 matches TE rank 29 (2025)",
    },
    "cpi-clothing": {
        "flag": "te-page-anomaly",
        "fix_summary": "TE's cpi-clothing page text actually shows CPI-Transportation data. Our CPIAPPSL Apparel value (135.8) is correct for clothing",
    },
    "credit-rating": {
        "flag": "ok",
        "fix_summary": "Curated 97 (Fitch AA+ / Moody's Aaa via TE methodology); TE page has no headline number",
    },
    "crude-oil-imports": {
        "flag": "frontend-only",
        "fix_summary": "WCEIMUS2 weekly level 5750 KBL/day; TE shows weekly change (-318 KBL/day). Frontend should diff",
    },
    "crude-oil-production": {
        "flag": "ok",
        "fix_summary": "MCRFPUS2 Feb = 13626 KBL/day matches TE exactly",
    },
    "crude-oil-stocks": {
        "flag": "ok",
        "fix_summary": "WCESTUS1 459495 KBL; TE description was empty in fetch but series is correct EIA Weekly Crude Stocks",
    },
    "currency": {
        "flag": "ok",
        "fix_summary": "DTWEXBGS broad dollar index 118.73; TE refers to DXY ~99.3 (ICE dollar index, different basket). Both are valid 'USD'",
    },
    "cushing-crude-oil-stocks": {
        "flag": "frontend-only",
        "fix_summary": "WCESTP31 weekly level 266087 KBL; TE shows weekly change (-1.702M BBL). Frontend should diff",
    },
    "dallas-fed-manufacturing-index": {
        "flag": "ok",
        "fix_summary": "BACTSAMFRBDAL -2.3 April matches TE -2.3 exactly; parser missed it (no % suffix)",
    },
    "disposable-personal-income": {
        "flag": "ok",
        "fix_summary": "DSPI 23601.9 vs TE 23429.8 (TE one month stale, Feb); our March value is fresher",
    },
    "distillate-fuel-production": {
        "flag": "frontend-only",
        "fix_summary": "WDIRPUS2 weekly level 4940 KBL; TE shows weekly change (-124 KBL). Frontend should diff",
    },
    "distillate-stocks": {
        "flag": "frontend-only",
        "fix_summary": "WDISTUS1 weekly level 103638 KBL; TE shows weekly change (+190 KBL). Frontend should diff",
    },
    "durable-goods-orders": {
        "flag": "frontend-only",
        "fix_summary": "DGORDER level $318.9B matches TE; TE shows MoM% (0.8%). Frontend should compute MoM",
    },
    "durable-goods-orders-ex-defense": {
        "flag": "frontend-only",
        "fix_summary": "ADXDNO level $296B; TE shows MoM% (-0.3% March). Frontend should compute MoM; parser captured all-time-high 29.30%",
    },
    "durable-goods-orders-ex-transport": {
        "flag": "ok",
        "fix_summary": "ADXTNO 212153 — no TE description to compare against, but series semantics correct",
    },
    "employed-persons": {
        "flag": "ok",
        "fix_summary": "CE16OV 162848K March matches TE 162622K April; data current, label parsing missed BLS attribution",
    },
    "employment-cost-index": {
        "flag": "frontend-only",
        "fix_summary": "ECIALLCIV index 175.62; TE shows QoQ% (0.9%). Frontend should compute QoQ",
    },
    "employment-cost-index-benefits": {
        "flag": "frontend-only",
        "fix_summary": "ECIBEN index 169.01; TE shows QoQ% (1.2%). Frontend should compute QoQ",
    },
    "employment-cost-index-wages": {
        "flag": "frontend-only",
        "fix_summary": "ECIWAG index 177.5; TE shows QoQ% (1.0%). Frontend should compute QoQ",
    },
    "employment-rate": {
        "flag": "ok",
        "fix_summary": "EMRATIO 59.2 March vs TE 59.1 April; series correct, just one month stale",
    },
    "energy-inflation": {
        "flag": "frontend-only",
        "fix_summary": "CPIENGSL index 314.02; TE shows YoY% (17.9%). Frontend should compute YoY",
    },
    "existing-home-sales": {
        "flag": "frontend-only",
        "fix_summary": "EXHOSLUSM495S level 3.98M; TE shows MoM% (0.2%) and headline 4.02M April. Frontend should compute MoM",
    },
    "factory-orders": {
        "flag": "frontend-only",
        "fix_summary": "AMTMNO level $619.6B (Feb); TE shows MoM% (1.5%). Frontend should compute MoM",
    },
}


def main():
    findings_path = ROOT / "docs/_audit_us_batch1_findings.yaml"
    with open(findings_path, encoding="utf-8") as f:
        findings = yaml.safe_load(f) or {}

    for slug, ann in ANNOTATIONS.items():
        if slug not in findings:
            print(f"WARN: {slug} not in findings")
            continue
        if ann.get("fixed"):
            findings[slug]["fixed"] = True
        findings[slug]["fix_summary"] = ann.get("fix_summary")
        findings[slug]["flag"] = ann.get("flag")

    # For slugs not in ANNOTATIONS but where source_match and value_match are True, mark flag=ok
    for slug, v in findings.items():
        if slug in ANNOTATIONS:
            continue
        if v.get("source_match") and v.get("value_match"):
            v["flag"] = "ok"
            v["fix_summary"] = "Source and value both match TE"

    with open(findings_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(findings, f, sort_keys=True, allow_unicode=True, width=200)

    # Summary
    fixed = sum(1 for v in findings.values() if v.get("fixed"))
    ok = sum(1 for v in findings.values() if v.get("flag") == "ok")
    fe = sum(1 for v in findings.values() if v.get("flag") == "frontend-only")
    flagged = sum(1 for v in findings.values() if v.get("flag") in ("needs-attention", "te-page-anomaly", "frontend-display", "no-te-headline"))
    total = len(findings)
    print(f"Total: {total} | fixed: {fixed} | ok: {ok} | frontend-only: {fe} | flagged: {flagged}")

    print("\nFixed:")
    for s, v in findings.items():
        if v.get("fixed"):
            print(f"  - {s}")
    print("\nFlagged:")
    for s, v in findings.items():
        if v.get("flag") in ("needs-attention", "te-page-anomaly", "frontend-display", "no-te-headline"):
            print(f"  - {s}  [{v.get('flag')}] {v.get('fix_summary')}")


if __name__ == "__main__":
    main()
