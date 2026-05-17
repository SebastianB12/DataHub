"""Compare TE-fetched source/value with DB row/data for EE. Emit findings YAML."""
import json, yaml, sys, pathlib
from pipeline.db import supabase as sb


# Map TE source-name (lower case substring) -> our internal source key
def map_te_source_to_internal(name: str) -> str:
    if not name:
        return ""
    n = name.lower()
    if "statistics estonia" in n or "stat.ee" in n or "estonian statistics" in n:
        return "stat_ee"
    if "eesti pank" in n or "bank of estonia" in n:
        return "ecb"  # we use ECB SDMX for EE money/labour-cost; otherwise fallback
    if "eurostat" in n:
        return "eurostat"
    if "european commission" in n or "dg ecfin" in n:
        return "eurostat"  # commission BCS via Eurostat ei_bsXX series
    if "estonian institute of economic research" in n or "konjunktuuriinstituut" in n:
        return "eurostat"  # we get via Eurostat BCS
    if "european central bank" in n or "ecb" == n.strip().lower():
        return "ecb"
    if "world bank" in n:
        return "worldbank"
    if "transparency international" in n:
        return "curated"
    if "institute for economics and peace" in n or "vision of humanity" in n:
        return "curated"
    if "oecd" in n:
        return "curated"
    if "estonian tax and customs board" in n or "maksu" in n or "ministry of finance" in n:
        return "curated"  # tax rates / retirement ages — manual curated
    if "estonian unemployment insurance fund" in n or "töötukassa" in n:
        return "stat_ee"  # job vacancies via Stat Estonia or curated
    if "moody" in n or "s&p" in n or "fitch" in n or "rating" in n:
        return "curated"
    if "who" in n or "world health organization" in n:
        return "curated"
    if "sipri" in n:
        return "curated"
    if "conference board" in n:
        return "curated"
    return ""


def main():
    # Load TE results
    te = json.load(open("docs/_audit_ee_te.json", encoding="utf-8"))
    # Load current DB sources
    r = sb.table("indicator_sources").select(
        "indicator,source,series_id,transform,unit,freq_hint,extra_params,active,is_default,note"
    ).eq("country", "EE").eq("is_default", True).execute()
    db_srcs = {row["indicator"]: row for row in r.data}

    # Load latest DB values
    r = sb.table("data_points").select("indicator,date,value").eq("country", "EE").order(
        "date", desc=True
    ).limit(5000).execute()
    db_latest = {}
    for x in r.data:
        if x["indicator"] not in db_latest:
            db_latest[x["indicator"]] = (str(x["date"]), x["value"])

    findings = {}
    for slug, t in te.items():
        te_src_name = t.get("te_source_name", "")
        # Detect 404 / generic page
        is_404 = t.get("te_title", "").startswith("TRADING ECONOMICS") or "function (n)" in te_src_name
        if is_404:
            findings[slug] = {
                "te_status": "no_te_page",
                "te_size": t.get("raw_size"),
                "te_title": t.get("te_title", ""),
                "db_source": db_srcs.get(slug, {}).get("source", "MISSING"),
                "db_latest_date": db_latest.get(slug, ("", None))[0],
                "db_latest_value": db_latest.get(slug, ("", None))[1],
                "action": "keep_as_gap",
            }
            continue
        expected_src = map_te_source_to_internal(te_src_name)
        db_src = db_srcs.get(slug, {}).get("source", "MISSING")
        db_date, db_val = db_latest.get(slug, ("", None))
        te_val = t.get("te_val_meta")

        # Determine status
        status = []
        if not expected_src:
            status.append("unmapped_te_source")
        elif expected_src == db_src:
            status.append("source_ok")
        else:
            status.append(f"source_mismatch:{db_src}->{expected_src}")

        # Compare values
        val_match = None
        if te_val and db_val is not None:
            try:
                tv = float(te_val)
                dv = float(db_val)
                if tv != 0:
                    diff = abs(dv - tv) / abs(tv)
                else:
                    diff = abs(dv - tv)
                if diff <= 0.05:
                    val_match = "value_ok"
                elif diff <= 0.20:
                    val_match = f"value_drift:{round(diff*100,1)}%"
                else:
                    val_match = f"value_mismatch:{round(diff*100,1)}%"
                status.append(val_match)
            except (TypeError, ValueError):
                pass

        # Slugs where DB stores level/index but TE shows YoY/MoM/derived metric
        FRONTEND_ONLY_DERIVED = {
            "inflation-cpi", "core-cpi", "food-inflation", "energy-inflation",
            "services-inflation", "ppi", "industrial-production",
            "manufacturing-production", "mining-production", "retail-sales",
            "gdp-real", "house-price-index", "productivity", "labour-costs",
            "cpi-food", "cpi-clothing", "cpi-housing-utilities",
            "cpi-transportation", "cpi-recreation-and-culture", "cpi-education",
        }
        # Slugs where TE-meta has misleading "out of N" parsed as value
        REGEX_FALSE_POSITIVES = {
            "corruption-index", "corruption-rank", "budget-deficit",
        }
        # Slugs where DB unit differs (EUR Million vs Billion or chain-linked vs current)
        UNIT_DIFF = {
            "exports", "imports", "consumer-spending", "government-spending",
            "government-spending-eur", "gross-fixed-capital-formation",
            "changes-in-inventories", "government-debt", "government-debt-total",
            "current-account", "current-account-to-gdp",
        }

        # Determine action label
        action = "no_change"
        if "source_ok" in status[0] and ("value_ok" in status or len(status) == 1):
            action = "verified_ok"
        elif "source_mismatch" in status[0]:
            # technical-source-honest exceptions
            if (
                te_src_name in (
                    "Bank of Estonia", "European Central Bank", "Statistics Estonia",
                    "Estonian Unemployment Insurance Fund",
                )
                and db_src == "eurostat"
            ):
                action = "acceptable_with_note_eurostat_upstream"
            else:
                action = "needs_review"
        elif any("value_mismatch" in s for s in status):
            if slug in FRONTEND_ONLY_DERIVED:
                action = "frontend_only_yoy_mom"
            elif slug in REGEX_FALSE_POSITIVES:
                action = "regex_false_positive_value_ok"
            elif slug in UNIT_DIFF:
                action = "unit_difference_value_ok"
            elif slug == "consumer-confidence":
                action = "different_survey_methodology"
            else:
                action = "value_mismatch_review"
        elif any("value_drift" in s for s in status):
            action = "minor_value_drift_ok"

        findings[slug] = {
            "te_status": "ok",
            "te_source_name": te_src_name,
            "expected_internal_source": expected_src or "?",
            "te_value": te_val,
            "te_unit": t.get("te_unit_meta"),
            "te_period": t.get("te_period_meta"),
            "te_meta": t.get("te_meta_desc", "")[:200],
            "db_source": db_src,
            "db_series_id": db_srcs.get(slug, {}).get("series_id"),
            "db_latest_date": db_date,
            "db_latest_value": db_val,
            "status": status,
            "action": action,
        }

    out = pathlib.Path("docs/_audit_ee_reaudit.yaml")
    out.write_text(yaml.safe_dump(findings, sort_keys=True, allow_unicode=True), encoding="utf-8")
    print(f"Wrote findings to {out}")

    # Summary
    by_status = {}
    for slug, f in findings.items():
        if f.get("te_status") == "no_te_page":
            k = "no_te_page"
        else:
            stat = f["status"]
            if "source_ok" in stat:
                k = "source_ok"
            elif any("source_mismatch" in s for s in stat):
                k = "source_mismatch"
            elif "unmapped_te_source" in stat:
                k = "unmapped"
            else:
                k = "other"
        by_status.setdefault(k, []).append(slug)
    print("\n=== Summary ===")
    for k, v in by_status.items():
        print(f"  {k}: {len(v)}")
        for s in v[:20]:
            print(f"    - {s}")


if __name__ == "__main__":
    main()
