"""Apply LV re-audit fixes.

Phase 1: Source-label conformity (DB indicator_sources + truth.yaml)
Phase 2: Data refresh for inflation-cpi (conversion fix)
Phase 3: Minor value fixes (terrorism-index curated table)
"""
import yaml, pathlib
from pipeline.db import supabase as sb

# ===== Phase 1: Source code changes =====
# (slug, new_source, series_id, unit, conversion, adjustment, freq, transform, extra_params)
# Only the rows we explicitly switch the is_default for.

PHASE1_FIXES = [
    # government-spending-eur: alias of government-spending; switch to csp_lv (chain-linked SA, mln EUR)
    {
        "slug": "government-spending-eur",
        "new_source": "csp_lv",
        "series_id": "CSP/ISP050c/P3_S13",
        "unit": "Million EUR (2020 chained)",
        "conversion": 0.001,
        "adjustment": "SA",
        "freq": "Q",
        "transform": "raw",
        "extra_params": None,
        "note": "CSP Latvia ISP050c P3_S13 chain-linked 2020 SA (alias of government-spending; TE re-audit 2026-05-17)",
    },
    # minimum-wages: TE attributes to EUROSTAT (earn_mw_cur)
    {
        "slug": "minimum-wages",
        "new_source": "eurostat",
        "series_id": "earn_mw_cur:NMW",
        "unit": "EUR/Month",
        "conversion": 1.0,
        "adjustment": "NSA",
        "freq": "S",  # semester
        "transform": "raw",
        "extra_params": {"dataset": "earn_mw_cur", "params": {"indic_em": "MNMW", "currency": "EUR"}},
        "note": "Eurostat earn_mw_cur statutory minimum wages, EUR/month (TE re-audit 2026-05-17)",
    },
]


def main():
    print("=" * 70)
    print("LV RE-AUDIT APPLY")
    print("=" * 70)

    # --- Phase 1: indicator_sources changes ---
    for fix in PHASE1_FIXES:
        slug = fix["slug"]
        new_src = fix["new_source"]
        print(f"\n>>> {slug}: switch is_default to {new_src}")

        # set old default to is_default=False
        sb.table("indicator_sources").update({"is_default": False}).eq(
            "country", "LV"
        ).eq("indicator", slug).execute()

        # check if (LV, slug, new_src) row exists
        existing = sb.table("indicator_sources").select("*").eq(
            "country", "LV"
        ).eq("indicator", slug).eq("source", new_src).execute().data

        row_data = {
            "country": "LV",
            "indicator": slug,
            "source": new_src,
            "series_id": fix["series_id"],
            "unit": fix["unit"],
            "conversion": fix["conversion"],
            "adjustment": fix["adjustment"],
            "freq_hint": fix["freq"],
            "transform": fix["transform"],
            "extra_params": fix["extra_params"],
            "note": fix["note"],
            "active": True,
            "is_default": True,
        }
        if existing:
            sb.table("indicator_sources").update(row_data).eq("country", "LV").eq(
                "indicator", slug
            ).eq("source", new_src).execute()
            print(f"  updated existing row -> default=True")
        else:
            sb.table("indicator_sources").insert(row_data).execute()
            print(f"  inserted new row -> default=True")

        # delete old datapoints for this (LV, slug) so they get refetched
        del_resp = sb.table("data_points").delete().eq("country", "LV").eq(
            "indicator", slug
        ).execute()
        print(f"  deleted data_points (will be refetched)")

    # --- Phase 2: inflation-cpi conversion change ---
    # update existing csp_lv row's conversion
    print(f"\n>>> inflation-cpi: update conversion 1.0 -> 0.01")
    sb.table("indicator_sources").update({
        "conversion": 0.01,
        "note": "CSP Latvia PCI030m CPI Dec 1990=100 (raw int *0.01) — TE re-audit 2026-05-17"
    }).eq("country", "LV").eq("indicator", "inflation-cpi").eq("source", "csp_lv").execute()
    # delete the bad csp_lv datapoints; fetcher rewrites
    sb.table("data_points").delete().eq("country", "LV").eq("indicator", "inflation-cpi").eq("source", "csp_lv").execute()
    print(f"  conversion fixed; csp_lv datapoints deleted (will be refetched)")

    # --- Phase 3: terrorism-index value refresh ---
    # TE says 0.23 in 2025; DB has 0. Update curated value.
    print(f"\n>>> terrorism-index: update curated value 0 -> 0.23 (2025)")
    # delete and re-insert
    sb.table("data_points").delete().eq("country", "LV").eq("indicator", "terrorism-index").execute()
    sb.table("data_points").insert([
        {"country": "LV", "indicator": "terrorism-index", "date": "2025-12-31",
         "value": 0.23, "source": "curated", "adjustment": "", "unit": "Points"},
        {"country": "LV", "indicator": "terrorism-index", "date": "2024-12-31",
         "value": 0.42, "source": "curated", "adjustment": "", "unit": "Points"},
    ]).execute()
    print("  terrorism-index curated values inserted")

    print("\n" + "=" * 70)
    print("DB FIXES DONE")
    print("=" * 70)


if __name__ == "__main__":
    main()
