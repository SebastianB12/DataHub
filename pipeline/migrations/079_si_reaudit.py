"""SI re-audit aggressive fixes (2026-05-17).

Per fresh TE re-audit of all 68 SI slugs:
1. minimum-wages: curated 1278 EUR -> eurostat earn_mw_cur (bi-annual, EUR, TE attributes Eurostat)
2. gdp: switch default to worldbank (TE shows WB annual USD as headline, not SURS quarterly EUR)
3. retirement-age-men/women: align to TE = 60 Years (early retirement age) instead of curated 65
4. truth.yaml: already updated with verified te_labels in scripts/update_si_truth.py

Source label honest: technical fetch quelle. Where TE attributes BS / ESS / SURS upstream
but we fetch from Eurostat with the same methodology, source stays 'eurostat'. te_label
captures the upstream attribution.
"""
from pipeline.db import supabase as sb


def main():
    print("=== SI reaudit migration ===")

    # --- 1. minimum-wages: curated -> eurostat ---
    print("\n[1/3] minimum-wages: curated -> eurostat earn_mw_cur")
    # Demote existing curated row (keep but not default)
    cur_old = sb.table("indicator_sources").select("*").eq("country", "SI").eq(
        "indicator", "minimum-wages").execute().data
    print(f"  current rows: {len(cur_old)} -> {[r['source'] for r in cur_old]}")
    # Switch the existing curated row's source/series_id to eurostat
    upd = sb.table("indicator_sources").update({
        "source": "eurostat",
        "series_id": "earn_mw_cur:SI:EUR",
        "extra_params": {"dataset": "earn_mw_cur", "params": {"currency": "EUR"}},
        "freq_hint": "S",
        "transform": "raw",
        "note": "Eurostat earn_mw_cur SI EUR (bi-annual); TE attributes EUROSTAT.",
        "is_default": True,
        "active": True,
        "unit": "EUR/Month",
    }).eq("country", "SI").eq("indicator", "minimum-wages").eq("source", "curated").execute()
    print(f"  + SI/minimum-wages: updated rows={len(upd.data)}")

    # --- 2. gdp: switch default to worldbank ---
    print("\n[2/3] gdp: default surs_si -> worldbank (TE attribution + headline value)")
    # Demote surs_si row (keep for archival series but not default)
    sb.table("indicator_sources").update({"is_default": False}).eq(
        "country", "SI").eq("indicator", "gdp").eq("source", "surs_si").execute()
    # Promote worldbank row
    upd = sb.table("indicator_sources").update({"is_default": True}).eq(
        "country", "SI").eq("indicator", "gdp").eq("source", "worldbank").execute()
    print(f"  + SI/gdp: worldbank promoted, surs_si demoted")

    # --- 3. retirement-age-men/women: 65 -> 60 (TE early retirement age) ---
    print("\n[3/3] retirement-age-men/women: 65 -> 60 (TE early retirement age)")
    for slug in ("retirement-age-men", "retirement-age-women"):
        # delete old data_points
        sb.table("data_points").delete().eq("country", "SI").eq("indicator", slug).execute()
        # upsert 60 Years 2025-12-31
        sb.table("data_points").upsert({
            "indicator": slug, "country": "SI", "date": "2025-12-31",
            "value": 60, "source": "curated", "unit": "Years", "adjustment": "",
            "series_id": f"SI:{slug}",
        }, on_conflict="indicator,country,date").execute()
        print(f"  + SI/{slug}: 60 Years 2025-12-31")

    print("\n=== Done ===")


if __name__ == "__main__":
    main()
