"""EE re-audit aggressive fixes (2026-05-17).

Per fresh TE re-audit of all 66 EE slugs:

Source moves (DB updates):
1. minimum-wages: curated 886 EUR -> eurostat earn_mw_cur:EE:EUR (bi-annual, TE attributes EUROSTAT)
2. government-spending-eur: eurostat namq_10_gdp -> stat_ee STATEE/RAA0061/K2 (TE = Statistics Estonia)

Curated value corrections (TE-conform):
3. hospital-beds: 4.6 -> 4.12 per 1000 people (TE 2023 value)
4. social-security-rate: 35 -> 37.40 % (TE current)
5. social-security-rate-employees: 1.6 -> 3.60 % (TE current; was likely wrong)
   social-security-rate-companies stays 33.80 (already matches TE)

No-action (verified ok, frontend handles YoY/MoM):
- food-inflation: stays eurostat HICP index (TE shows YoY %, frontend computes)
- gdp-real: stays stat_ee level (TE shows YoY %, frontend computes)
- unemployed-persons: stays eurostat (drift < 20%, different methodology)
- current-account / current-account-to-gdp: stays eurostat (BoE is upstream)
- labour-costs: stays eurostat (ECB is upstream; value_ok)
- job-vacancies: stays eurostat % rate (UIF reports absolute count, different concept)

True coverage gaps (TE 404, no national source readily available):
- credit-rating (curated text-derived), disposable-personal-income (no TE page),
  energy-inflation (no TE page), medical-doctors (no TE page),
  nurses (no TE page), services-inflation (no TE page),
  services-sentiment (no TE page)

Source label honest: technical fetch quelle. Where TE attributes Bank of Estonia /
Statistics Estonia upstream but we fetch from Eurostat with the same methodology,
source stays 'eurostat'. te_label captures the upstream attribution.
"""
from datetime import date
from pipeline.db import supabase as sb


def main():
    print("=== EE reaudit migration (080) ===")

    # --- 1. minimum-wages: curated -> eurostat ---
    print("\n[1/5] minimum-wages: curated -> eurostat earn_mw_cur")
    cur_old = sb.table("indicator_sources").select("*").eq(
        "country", "EE").eq("indicator", "minimum-wages").execute().data
    print(f"  current rows: {[r['source'] for r in cur_old]}")
    upd = sb.table("indicator_sources").update({
        "source": "eurostat",
        "series_id": "earn_mw_cur:EE:EUR",
        "extra_params": {"dataset": "earn_mw_cur", "params": {"currency": "EUR"}},
        "freq_hint": "S",
        "transform": "raw",
        "note": "Eurostat earn_mw_cur EE EUR (bi-annual); TE attributes EUROSTAT.",
        "is_default": True,
        "active": True,
        "unit": "EUR/Month",
    }).eq("country", "EE").eq("indicator", "minimum-wages").eq("source", "curated").execute()
    print(f"  + EE/minimum-wages: rows updated={len(upd.data)}")
    # Delete old curated points so eurostat fetch re-populates cleanly
    sb.table("data_points").delete().eq("country", "EE").eq("indicator", "minimum-wages").execute()
    print("  + EE/minimum-wages: old data_points deleted (will be repopulated by eurostat provider)")

    # --- 2. government-spending-eur: eurostat -> stat_ee ---
    print("\n[2/5] government-spending-eur: eurostat -> stat_ee STATEE/RAA0061/K2")
    upd = sb.table("indicator_sources").update({
        "source": "stat_ee",
        "series_id": "STATEE/RAA0061/K2",
        "extra_params": {},
        "freq_hint": "Q",
        "transform": "raw",
        "note": "Statistics Estonia RAA0061 government final consumption expenditure (chain-linked, mln EUR); TE attributes Statistics Estonia.",
        "is_default": True,
        "active": True,
        "unit": "Million EUR (2020 chain-linked)",
        "conversion": 1.0,
    }).eq("country", "EE").eq("indicator", "government-spending-eur").eq("source", "eurostat").execute()
    print(f"  + EE/government-spending-eur: rows updated={len(upd.data)}")
    # Delete eurostat points so stat_ee writes cleanly
    sb.table("data_points").delete().eq("country", "EE").eq(
        "indicator", "government-spending-eur").execute()
    print("  + EE/government-spending-eur: old data_points deleted (will be repopulated)")

    # --- 3. hospital-beds: 4.6 -> 4.12 ---
    print("\n[3/5] hospital-beds: curated 4.6 -> 4.12 (TE 2023)")
    sb.table("data_points").delete().eq("country", "EE").eq("indicator", "hospital-beds").execute()
    sb.table("data_points").upsert({
        "indicator": "hospital-beds", "country": "EE", "date": "2023-12-31",
        "value": 4.12, "source": "curated", "unit": "per 1000 people",
        "adjustment": "", "series_id": "EE:hospital-beds",
    }, on_conflict="indicator,country,date,source,adjustment").execute()
    print("  + EE/hospital-beds: upserted 4.12 (2023-12-31)")

    # --- 4. social-security-rate: 35 -> 37.40 ---
    print("\n[4/5] social-security-rate: curated 35 -> 37.40 (TE current)")
    sb.table("data_points").delete().eq("country", "EE").eq("indicator", "social-security-rate").execute()
    sb.table("data_points").upsert({
        "indicator": "social-security-rate", "country": "EE", "date": "2026-12-31",
        "value": 37.40, "source": "curated", "unit": "%",
        "adjustment": "", "series_id": "EE:social-security-rate",
    }, on_conflict="indicator,country,date,source,adjustment").execute()
    print("  + EE/social-security-rate: upserted 37.40")

    # --- 5. social-security-rate-employees: 1.6 -> 3.60 ---
    print("\n[5/5] social-security-rate-employees: curated 1.6 -> 3.60 (TE current)")
    sb.table("data_points").delete().eq("country", "EE").eq(
        "indicator", "social-security-rate-employees").execute()
    sb.table("data_points").upsert({
        "indicator": "social-security-rate-employees", "country": "EE",
        "date": "2026-12-31", "value": 3.60, "source": "curated", "unit": "%",
        "adjustment": "", "series_id": "EE:social-security-rate-employees",
    }, on_conflict="indicator,country,date,source,adjustment").execute()
    print("  + EE/social-security-rate-employees: upserted 3.60")

    print("\n=== Done ===")


if __name__ == "__main__":
    main()
