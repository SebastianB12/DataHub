"""Write docs/_audit_si_reaudit.yaml: full SI re-audit per fresh TE fetch."""
import json
import sys
from datetime import date
from pathlib import Path

import yaml

sys.stdout.reconfigure(encoding="utf-8")

from pipeline.db import supabase as sb

OUTFILE = Path("docs/_audit_si_reaudit.yaml")

NAME_TO_SRC = {
    "Statistical Office of the Republic of Slovenia": "surs_si",
    "Bank of Slovenia": "eurostat",  # fallback (no BS provider integrated)
    "Eurostat": "eurostat", "EUROSTAT": "eurostat",
    "European Commission": "eurostat",
    "European Central Bank": "ecb",
    "World Bank": "worldbank",
    "OECD": "curated",
    "Transparency International": "curated",
    "Tax Administration of the Republic of Slovenia": "curated",
    "Ministry of Finance, Republic of Slovenia": "curated",
    "Institute for Economics and Peace": "curated",
    "Employment Service of Slovenia": "eurostat",  # fallback
}

NO_TE_PAGE = {"disposable-personal-income", "energy-inflation", "services-inflation",
              "services-sentiment", "government-spending-eur"}
TE_AGGREGATE = {"credit-rating"}


def main():
    parsed = json.loads(Path("docs/_audit_si_te_parsed.json").read_text(encoding="utf-8"))
    slugs = json.loads(Path("docs/_audit_all_remaining_slugs.json").read_text(encoding="utf-8"))["SI"]

    rows_def = {r["indicator"]: r for r in sb.table("indicator_sources").select(
        "indicator,source,is_default,active").eq("country", "SI").eq("is_default", True).execute().data}

    audit = {
        "country": "SI",
        "te_path": "slovenia",
        "audit_date": str(date.today()),
        "n_slugs": len(slugs),
        "summary": {},
        "slugs": {},
    }

    counters = {"OK": 0, "HONEST_PASSTHROUGH": 0, "MISMATCH": 0, "VALUE_DIFF": 0,
                "NO_TE_PAGE": 0, "TE_AGGREGATE": 0, "FRONTEND_ONLY": 0}

    # Honest-passthrough: TE attributes SURS / Banka Slovenije / ESS upstream, but the value
    # is technically fetched from Eurostat's harmonized release of the same upstream data.
    # Per CLAUDE.md: source-label = technical fetch quelle. Eurostat is the honest label.
    PASSTHROUGH_OK = {
        ("eurostat", "Statistical Office of the Republic of Slovenia"),
        ("eurostat", "Bank of Slovenia"),
        ("eurostat", "Banka Slovenije"),
        ("eurostat", "Employment Service of Slovenia"),
        ("eurostat", "European Commission"),
        # surs_si may serve a series that TE attributes to ESS only on registered unemployment
        ("surs_si",  "Employment Service of Slovenia"),
    }

    for slug in slugs:
        te = parsed.get(slug, {})
        te_src_name = te.get("te_source_name")
        te_meta = te.get("te_meta_desc", "")
        # latest data point
        dp_r = sb.table("data_points").select("date,value,source,unit,series_id").eq(
            "country", "SI").eq("indicator", slug).order("date", desc=True).limit(1).execute()
        dp = dp_r.data[0] if dp_r.data else None
        db_src = rows_def.get(slug, {}).get("source", "NONE")

        entry = {
            "te_source_name": te_src_name,
            "te_meta_desc_preview": te_meta[:200],
            "db_default_source": db_src,
            "db_latest_date": dp["date"] if dp else None,
            "db_latest_value": dp["value"] if dp else None,
            "db_latest_source": dp["source"] if dp else None,
            "db_unit": dp["unit"] if dp else None,
            "db_series_id": dp["series_id"] if dp else None,
        }

        if slug in NO_TE_PAGE:
            entry["status"] = "NO_TE_PAGE"
            entry["note"] = "EconPulse-internal slug, no TE indicator page"
            counters["NO_TE_PAGE"] += 1
        elif slug in TE_AGGREGATE:
            entry["status"] = "TE_AGGREGATE"
            entry["note"] = "Curated TE aggregate (S&P/Moody's/Fitch rating)"
            counters["TE_AGGREGATE"] += 1
        elif not te_src_name:
            entry["status"] = "NO_TE_PAGE"
            entry["note"] = "TE page returned generic landing — likely no SI page"
            counters["NO_TE_PAGE"] += 1
        else:
            expected = NAME_TO_SRC.get(te_src_name, "unknown")
            if db_src == expected:
                entry["status"] = "OK"
                counters["OK"] += 1
            elif (db_src, te_src_name) in PASSTHROUGH_OK:
                entry["status"] = "HONEST_PASSTHROUGH"
                entry["te_upstream"] = te_src_name
                entry["note"] = (f"TE attributes {te_src_name} upstream; we fetch from {db_src} "
                                 f"(EU-harmonized passthrough). Honest source label per CLAUDE.md.")
                counters["HONEST_PASSTHROUGH"] += 1
            else:
                entry["status"] = "MISMATCH"
                entry["expected_source"] = expected
                entry["note"] = (f"db_source={db_src} but TE attributes {te_src_name}"
                                 f" -> expected our label = {expected}")
                counters["MISMATCH"] += 1

        audit["slugs"][slug] = entry

    audit["summary"] = counters
    OUTFILE.write_text(
        yaml.safe_dump(audit, allow_unicode=True, sort_keys=False, width=200),
        encoding="utf-8",
    )
    print(f"Wrote {OUTFILE}")
    print(f"Summary: {counters}")


if __name__ == "__main__":
    main()
