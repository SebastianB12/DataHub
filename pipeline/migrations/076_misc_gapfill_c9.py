"""Phase C9 — misc TE-conformity gap-fill across 11 small EU countries.

Scope: HR, CY, MT, PL, HU, SI, FR, LV, EE, LT, SK
Trigger: post-migration scan against docs/_te_inventory/<CC>.yaml flagged ~90
remaining slugs with current_source=eurostat but suggested_source=<national>.

Findings after audit (2026-05-15) of indicator_sources + data_points:
  - Most flagged slugs are already PROMOTED (national source default + data
    flowing); inventory yamls are stale snapshots predating C8 migrations.
  - Real residual gaps fall in two buckets:

    A) HU + SK: provider configured 20+ slugs each but `unemployment-rate`
       FK-violation poisoned every batch — no rows landed.
       FIX (pipeline/providers/national_eu.py): rename slug→`unemployment` in
       both HU_SERIES (mun0098) and SK_SERIES (pr1802qs). After provider rerun
       this migration promotes ~36 slugs from eurostat → ksh_hu / susr_sk.

    B) HR, CY, MT, PL, SI, FR, LV, EE, LT: 30-40 slugs across countries where
       provider has no SERIES entry. Most need significant per-table research
       (SDMX dimension discovery, PxWeb table mapping). Documented as deferred
       gaps in docs/te_coverage_gaps.yaml — they continue to serve from the
       Eurostat fallback (which is itself a TE-acceptable source for many).

This migration is *idempotent*:
  - upsert_indicator_source() pattern: delete then insert the (slug, country,
    source) row, then demote all sibling rows is_default=False.
  - The promotions only fire for (slug, country, source) tuples where the
    *target* source has data_points rows — verified via a pre-check.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

from pipeline.db import supabase as sb


# -----------------------------------------------------------------------------
# Bucket A — HU + SK promotions (data ingested after slug-bug fix)
# -----------------------------------------------------------------------------

HU_PROMOTIONS = [
    # (slug, series_id, freq, unit, adjustment, conversion, note)
    ("unemployment", "KSH/mun0098", "M", "%", "NSA", 1.0,
     "KSH STADAT 20.2.1.3 mun0098 col 8 LFS unemployment rate 15-64 Total"),
    ("changes-in-inventories", "KSH/gdp0094", "Q", "Million HUF (current prices)", "NSA", 1.0,
     "KSH STADAT GDP expenditure component P52 — gdp0094 changes in inventories"),
    ("consumer-spending", "KSH/gdp0094", "Q", "Million HUF (current prices)", "NSA", 1.0,
     "KSH STADAT GDP expenditure household final consumption — gdp0094 P31_S14"),
    ("cpi-transportation", "KSH/ara0042", "M", "Index (prev year=100)", "NSA", 1.0,
     "KSH STADAT 3.6.1 ara0042 CPI COICOP transport, prev year =100"),
    ("employed-persons", "KSH/mun0099", "M", "Thousand persons", "NSA", 1.0,
     "KSH STADAT 20.2.1.3 mun0099 LFS employed persons 15-74 Total"),
    ("employment-rate", "KSH/mun0099", "M", "%", "NSA", 1.0,
     "KSH STADAT 20.2.1.3 mun0099 LFS employment rate 15-64 Total"),
    ("food-inflation", "KSH/ara0040", "M", "Index (prev year=100)", "NSA", 1.0,
     "KSH STADAT 3.6.1 ara0040 CPI Food YoY index (prev year=100)"),
    ("government-spending", "KSH/gdp0094", "Q", "Million HUF (current prices)", "NSA", 1.0,
     "KSH STADAT GDP expenditure P3_S13 — gdp0094 government final consumption"),
    ("gross-fixed-capital-formation", "KSH/gdp0094", "Q", "Million HUF (current prices)", "NSA", 1.0,
     "KSH STADAT GDP expenditure P51G — gdp0094 GFCF"),
    ("industrial-production", "KSH/ipa0072", "M", "Index (prev year=100, WDA)", "WDA", 1.0,
     "KSH STADAT 13.2.3.1 ipa0072 IPI Hungary working-day adjusted YoY index"),
    ("job-vacancies", "KSH/mun0159", "Q", "Thousand vacancies", "NSA", 0.001,
     "KSH STADAT mun0159 job vacancy count, Total"),
    ("labor-force-participation-rate", "KSH/mun0099", "M", "%", "NSA", 1.0,
     "KSH STADAT mun0099 LFS labour force participation rate"),
    ("manufacturing-production", "KSH/ipa0072", "M", "Index (prev year=100, WDA)", "WDA", 1.0,
     "KSH STADAT 13.2.3.1 ipa0072 IPI Manufacturing WDA YoY"),
    ("mining-production", "KSH/ipa0072", "M", "Index (prev year=100, WDA)", "WDA", 1.0,
     "KSH STADAT 13.2.3.1 ipa0072 IPI Mining WDA YoY"),
    ("population", "KSH/nep0001", "A", "Million persons", "NSA", 1e-6,
     "KSH STADAT 22.1.1.1 nep0001 mid-year population total"),
    ("retail-sales", "KSH/ob0004ms", "M", "Index (volume YoY)", "NSA", 1.0,
     "KSH STADAT ob0004ms retail trade turnover index Total (NACE 47), volume YoY"),
    ("gdp-real", "KSH/gdp0086", "Q", "Million HUF (constant 2015 prices)", "NSA", 1.0,
     "KSH STADAT gdp0086 GDP B1GQ constant 2015 prices, quarterly"),
    ("trade-balance", "KSH/kkr_synthetic", "M", "Million EUR", "NSA", 1.0,
     "KSH STADAT kkr0001/kkr0002 — derived monthly exports minus imports"),
]

SK_PROMOTIONS = [
    ("unemployment", "SUSR/pr1802qs/MJ_VPC/U_PR_0003", "Q", "%", "NSA", 1.0,
     "SUSR pr1802qs LFS unemployment rate 15-74 Total"),
    ("business-confidence", "SUSR/kp0022ms", "M", "Balance (pts)", "NSA", 1.0,
     "SUSR kp0022ms business confidence indicator Total"),
    ("consumer-confidence", "SUSR/kp0022ms", "M", "Balance (pts)", "NSA", 1.0,
     "SUSR kp0022ms consumer confidence indicator Total"),
    ("changes-in-inventories", "SUSR/nu1807qs_synthetic", "Q", "Million EUR (chain 2020)", "NSA", 1.0,
     "SUSR nu1807qs P5−P51G derived changes in inventories real chain 2020"),
    ("consumer-spending", "SUSR/nu1807qs", "Q", "Million EUR (chain 2020)", "NSA", 1.0,
     "SUSR nu1807qs P31_S14 household final consumption chain 2020"),
    ("cpi-clothing", "SUSR/sp2038ms/CP03", "M", "Index (2015=100)", "NSA", 1.0,
     "SUSR sp2038ms CPI sub-index CP03 Clothing & footwear"),
    ("cpi-education", "SUSR/sp2038ms/CP10", "M", "Index (2015=100)", "NSA", 1.0,
     "SUSR sp2038ms CPI sub-index CP10 Education"),
    ("cpi-food", "SUSR/sp2038ms/CP01", "M", "Index (2015=100)", "NSA", 1.0,
     "SUSR sp2038ms CPI sub-index CP01 Food & non-alc bev"),
    ("cpi-housing-utilities", "SUSR/sp2038ms/CP04", "M", "Index (2015=100)", "NSA", 1.0,
     "SUSR sp2038ms CPI sub-index CP04 Housing/water/electricity/gas"),
    ("cpi-recreation-and-culture", "SUSR/sp2038ms/CP09", "M", "Index (2015=100)", "NSA", 1.0,
     "SUSR sp2038ms CPI sub-index CP09 Recreation & culture"),
    ("cpi-transportation", "SUSR/sp2038ms/CP07", "M", "Index (2015=100)", "NSA", 1.0,
     "SUSR sp2038ms CPI sub-index CP07 Transport"),
    ("employed-persons", "SUSR/pr2035qs", "Q", "Thousand persons", "NSA", 1.0,
     "SUSR pr2035qs LFS employed persons 15-89 Total"),
    ("gdp-real", "SUSR/nu0004qs", "Q", "Million EUR (chain 2020)", "NSA", 1.0,
     "SUSR nu0004qs GDP B1GQ chain 2020, quarterly"),
    ("government-spending", "SUSR/nu1807qs", "Q", "Million EUR (chain 2020)", "NSA", 1.0,
     "SUSR nu1807qs P3_S13 general government chain 2020"),
    ("gross-fixed-capital-formation", "SUSR/nu1807qs", "Q", "Million EUR (chain 2020)", "NSA", 1.0,
     "SUSR nu1807qs P51G GFCF chain 2020"),
    ("imports", "SUSR/zo0001ms", "M", "Million EUR", "NSA", 1.0,
     "SUSR zo0001ms foreign trade imports total mEUR"),
    ("industrial-production", "SUSR/pm0042ms", "M", "Index", "NSA", 1.0,
     "SUSR pm0042ms IPI total industry"),
    ("labor-force-participation-rate", "SUSR/pr2035qs", "Q", "%", "NSA", 1.0,
     "SUSR pr2035qs LFS labour force participation rate 15-64"),
    ("manufacturing-production", "SUSR/pm0042ms", "M", "Index", "NSA", 1.0,
     "SUSR pm0042ms IPI manufacturing C"),
    ("mining-production", "SUSR/pm0042ms", "M", "Index", "NSA", 1.0,
     "SUSR pm0042ms IPI mining B"),
    ("population", "SUSR/om7102rr", "A", "Million persons", "NSA", 1e-6,
     "SUSR om7102rr resident population mid-year total"),
    ("ppi", "SUSR/sp1804ms", "M", "Index (2015=100)", "NSA", 1.0,
     "SUSR sp1804ms PPI industry total domestic market"),
    ("retail-sales", "SUSR/ob0004ms", "M", "Index", "NSA", 1.0,
     "SUSR ob0004ms retail trade index Total NACE 47"),
    ("trade-balance", "SUSR/zo_trade_balance_synthetic", "M", "Million EUR", "NSA", 1.0,
     "SUSR vy0001ms − zo0001ms derived exports minus imports mEUR"),
]


def upsert_indicator_source(slug: str, country: str, src: str,
                            series_id: str, freq: str, unit: str,
                            adj: str, conv: float, note: str) -> None:
    """Idempotent: delete (slug, country, src) then insert as default,
    demoting any sibling rows for the same (slug, country)."""
    sb.table("indicator_sources").delete().eq(
        "indicator", slug
    ).eq("country", country).eq("source", src).execute()
    # Demote everything for (slug, country)
    sb.table("indicator_sources").update({"is_default": False}).eq(
        "indicator", slug
    ).eq("country", country).execute()
    sb.table("indicator_sources").insert({
        "indicator": slug,
        "country": country,
        "source": src,
        "series_id": series_id,
        "is_default": True,
        "transform": "raw",
        "conversion": conv,
        "unit": unit,
        "adjustment": adj,
        "freq_hint": freq,
        "extra_params": None,
        "active": True,
        "note": note,
    }).execute()


def has_data(country: str, slug: str, src: str) -> bool:
    r = sb.table("data_points").select("date", count="exact").eq(
        "indicator", slug
    ).eq("country", country).eq("source", src).limit(1).execute()
    return (r.count or 0) > 0


def main() -> None:
    promoted = 0
    skipped: list[str] = []

    for slug, sid, freq, unit, adj, conv, note in HU_PROMOTIONS:
        if has_data("HU", slug, "ksh_hu"):
            upsert_indicator_source(slug, "HU", "ksh_hu", sid, freq, unit, adj, conv, note)
            promoted += 1
            print(f"  + HU/{slug:<32} | ksh_hu  | {sid}")
        else:
            skipped.append(f"HU/{slug} (no data yet; rerun provider after slug fix)")

    for slug, sid, freq, unit, adj, conv, note in SK_PROMOTIONS:
        if has_data("SK", slug, "susr_sk"):
            upsert_indicator_source(slug, "SK", "susr_sk", sid, freq, unit, adj, conv, note)
            promoted += 1
            print(f"  + SK/{slug:<32} | susr_sk | {sid}")
        else:
            skipped.append(f"SK/{slug} (no data yet; rerun provider after slug fix)")

    print()
    print(f"Promoted: {promoted}")
    if skipped:
        print(f"Skipped (no data yet): {len(skipped)}")
        for s in skipped[:20]:
            print(f"   - {s}")

    # Deferred gaps for which provider has no series_id mapping yet.
    # These continue to serve from eurostat fallback. Documented separately in
    # docs/te_coverage_gaps.yaml; this migration only records them in stdout.
    deferred = {
        "HR": ["core-cpi", "employed-persons", "imports", "manufacturing-production",
               "mining-production", "unemployed-persons", "unemployment"],
        "CY": ["current-account", "food-inflation", "house-price-index",
               "job-vacancies", "labor-force-participation-rate",
               "manufacturing-production", "mining-production", "unemployed-persons"],
        "MT": ["current-account", "food-inflation", "government-debt",
               "government-debt-total", "industrial-production",
               "manufacturing-production", "ppi"],
        "PL": ["job-vacancies", "labor-force-participation-rate",
               "unemployed-persons", "unemployment"],
        "SI": ["budget-deficit", "core-cpi", "gdp-real"],
        "FR": ["budget-deficit", "cpi-food", "government-debt",
               "government-debt-total", "long-term-unemployment-rate", "population"],
        "LV": ["government-debt-total", "ppi"],
        "EE": ["business-confidence", "consumer-confidence", "food-inflation",
               "unemployed-persons"],
        "LT": ["government-debt-total"],
    }
    total_deferred = sum(len(v) for v in deferred.values())
    print(f"\nDeferred (kept on eurostat fallback; documented in te_coverage_gaps.yaml): "
          f"{total_deferred}")
    for cc, slugs in deferred.items():
        print(f"  {cc}: {', '.join(slugs)}")


if __name__ == "__main__":
    main()
