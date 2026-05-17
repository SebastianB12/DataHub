"""LU re-audit aggressive fixes (2026-05-17).

Fresh TE re-audit of all 66 LU slugs revealed:

A) Source moves (DB updates):
1. current-account: eurostat bop_c6_q -> statec_lu DF_E4202 (BCL upstream; STATEC
   compiles & publishes the BoP quarterly. TE attributes BCL but data flows via STATEC.)
2. government-debt: eurostat -> statec_lu DF_E3101/L14 (% of GDP, annual EDP)
3. minimum-wages: curated 2638 -> eurostat earn_mw_cur:LU:EUR (bi-annual; TE = EUROSTAT)

B) Curated value corrections (TE-conform):
4. corporate-tax-rate: 24.94 -> 23.87 % (TE current 2025-2026; lower band w/o solidarity)
5. social-security-rate: 25.94 -> 28.05 %
6. social-security-rate-companies: 13.05 -> 15.10 %
7. social-security-rate-employees: 12.89 -> 12.95 % (within tolerance, snap to TE)
8. corruption-index: 81 -> 78 (TI 2025 CPI for LU = 78)
9. corruption-rank: 9 -> 8

C) No-action (verified ok, technical fetch differs from TE upstream label):
- changes-in-inventories: stays eurostat namq_10_gdp:P52 (STATEC only publishes P5
  aggregate, not the inventories sub-component). te_label captures STATEC.
- exports/imports: stays eurostat (STATEC does not expose monthly foreign trade
  on lustat; the Eurostat ext_st* tables mirror Customs LU. TE attributes BCL.)
- job-vacancies: stays eurostat jvs_q_nace2 (ADEM publishes monthly count, but
  not via SDMX; we use the Eurostat job-vacancy *rate* which is methodologically
  comparable). te_label captures ADEM.

D) TE_NO_DATA (TE has no page-data block for LU; we keep our default):
- credit-rating (curated 96 ≈ AAA), terrorism-index (curated 0 — GTI score),
  hospital-beds/medical-doctors/nurses (OECD curated; TE actually has it for
  hospital-beds with newer date — refresh value), disposable-personal-income,
  energy-inflation, government-debt-total (% — kept STATEC L12 EUR mn),
  government-spending-eur, retail-sales, services-inflation, services-sentiment.

Source label = technical fetch quelle. Where TE attributes BCL/STATEC upstream
but we technically fetch from Eurostat, source stays 'eurostat'. te_label
in truth.yaml captures the upstream attribution.
"""
from pipeline.db import supabase as sb


def main():
    print("=== LU reaudit migration (081) ===")

    # --- A1: current-account: eurostat -> statec_lu DF_E4202 ---
    print("\n[A1] current-account: eurostat -> statec_lu DF_E4202")
    upd = sb.table("indicator_sources").update({
        "source": "statec_lu",
        "series_id": "STATEC/LU1,DF_E4202,1.0#B-CA",
        "extra_params": {},
        "freq_hint": "Q",
        "transform": "raw",
        "note": "STATEC DF_E4202 BPM6 quarterly current account balance (mln EUR); TE attributes BCL upstream.",
        "is_default": True,
        "active": True,
        "unit": "Million EUR",
        "adjustment": "NSA",
        "conversion": 1.0,
    }).eq("country", "LU").eq("indicator", "current-account").eq("is_default", True).execute()
    print(f"  + LU/current-account: rows updated={len(upd.data)}")
    sb.table("data_points").delete().eq("country", "LU").eq("indicator", "current-account").execute()
    print("  + LU/current-account: old data_points deleted (statec_lu will repopulate)")

    # --- A2: government-debt (% of GDP): eurostat -> statec_lu L14 ---
    print("\n[A2] government-debt: eurostat -> statec_lu DF_E3101/L14")
    upd = sb.table("indicator_sources").update({
        "source": "statec_lu",
        "series_id": "STATEC/LU1,DF_E3101,1.0#L14",
        "extra_params": {},
        "freq_hint": "A",
        "transform": "raw",
        "note": "STATEC DF_E3101 L14 General government consolidated gross debt in % of GDP (annual EDP); TE attributes STATEC.",
        "is_default": True,
        "active": True,
        "unit": "% of GDP",
        "adjustment": "NSA",
        "conversion": 1.0,
    }).eq("country", "LU").eq("indicator", "government-debt").eq("is_default", True).execute()
    print(f"  + LU/government-debt: rows updated={len(upd.data)}")
    sb.table("data_points").delete().eq("country", "LU").eq("indicator", "government-debt").execute()
    print("  + LU/government-debt: old data_points deleted (statec_lu will repopulate)")

    # --- A3: minimum-wages: curated -> eurostat earn_mw_cur ---
    print("\n[A3] minimum-wages: curated -> eurostat earn_mw_cur:LU:EUR")
    upd = sb.table("indicator_sources").update({
        "source": "eurostat",
        "series_id": "earn_mw_cur:LU:EUR",
        "extra_params": {"dataset": "earn_mw_cur", "params": {"currency": "EUR"}},
        "freq_hint": "S",
        "transform": "raw",
        "note": "Eurostat earn_mw_cur LU EUR (bi-annual); TE attributes EUROSTAT.",
        "is_default": True,
        "active": True,
        "unit": "EUR/Month",
        "adjustment": "",
        "conversion": 1.0,
    }).eq("country", "LU").eq("indicator", "minimum-wages").eq("source", "curated").execute()
    print(f"  + LU/minimum-wages: rows updated={len(upd.data)}")
    sb.table("data_points").delete().eq("country", "LU").eq("indicator", "minimum-wages").execute()
    print("  + LU/minimum-wages: old data_points deleted (eurostat will repopulate)")

    # --- B4..B9: curated value corrections ---
    fixes = [
        ("corporate-tax-rate", 23.87, "2026-12-31", "%"),
        ("social-security-rate", 28.05, "2026-12-31", "%"),
        ("social-security-rate-companies", 15.10, "2026-12-31", "%"),
        ("social-security-rate-employees", 12.95, "2026-12-31", "%"),
        ("corruption-index", 78, "2025-12-31", "Points"),
        ("corruption-rank", 8, "2025-12-31", "Rank"),
        ("hospital-beds", 3.94, "2023-12-31", "per 1000 people"),
    ]
    for i, (slug, val, dt, unit) in enumerate(fixes, start=4):
        print(f"\n[B{i}] curated value fix: {slug} -> {val} ({dt})")
        sb.table("data_points").delete().eq("country", "LU").eq("indicator", slug).execute()
        sb.table("data_points").upsert({
            "indicator": slug, "country": "LU", "date": dt,
            "value": val, "source": "curated", "unit": unit,
            "adjustment": "", "series_id": f"LU:{slug}",
        }, on_conflict="indicator,country,date,source,adjustment").execute()
        print(f"  + LU/{slug}: upserted {val}")

    print("\n=== Done LU 081 ===")


if __name__ == "__main__":
    main()
