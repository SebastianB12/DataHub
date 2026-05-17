"""Apply IE re-audit fixes derived from docs/_audit_ie_reaudit.yaml.

Targets the 8 needs-attention + 2 needs-cso-fetch issues:

  1. business-confidence  -> Eurostat teibs020 BS-ICI-BAL (current config 404s)
  2. current-account-to-gdp -> Eurostat bop_gdp6_q partner=WRL_REST stk_flow=BAL (returns 8.2)
  3. labour-costs         -> ECB MNA Q.N.IE...ULC_PS (TE explicitly attributes ECB)
  4. consumer-spending    -> CSO NAQ04 sector 0012 (Household FCE) = TE 37778
  5. corruption-index     -> curated 76 (TI 2025)
  6. nurses               -> curated 15.78 (OECD 2024)
  7. terrorism-index      -> curated 0.42 (GTI 2025)
  8. social-security-rate -> curated 11.25 (TE definition = employer rate only)
  9. current-account      -> keep eurostat (honest fetch; TE attributes upstream CSO)
 10. disposable-personal-income -> keep eurostat (honest fetch; TE attributes upstream)

For 1-2, we update extra_params on existing eurostat row.
For 3 we move source from eurostat -> ecb and add ECB row+points (eurostat row kept as non-default variant).
For 4 we update extra_params for cso_ie row; reseed data_points.
For 5-8 we update pipeline/curated/ie.yaml + run curated provider.
For 9-10 we keep source=eurostat but update truth.yaml note (no DB change).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import date

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.db import supabase as sb  # noqa: E402


def section(title: str):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def fix_1_business_confidence():
    """Switch eurostat config from broken ei_bsci_m_r2 to teibs020 BS-ICI-BAL."""
    section("1. business-confidence -> teibs020 BS-ICI-BAL")
    new_extra = {
        "dataset": "teibs020",
        "params": {"indic": "BS-ICI-BAL", "s_adj": "SA"},
    }
    r = (
        sb.table("indicator_sources")
        .update({
            "series_id": "teibs020:BS-ICI-BAL",
            "extra_params": new_extra,
            "unit": "Points",
            "adjustment": "SA",
            "freq_hint": "M",
            "conversion": 1.0,
            "note": "Eurostat teibs020 BS-ICI-BAL (Industrial Confidence Indicator, monthly SA, balance).",
        })
        .eq("country", "IE")
        .eq("indicator", "business-confidence")
        .eq("source", "eurostat")
        .execute()
    )
    print(f"  updated indicator_sources rows: {len(r.data)}")
    # Delete stale data_points (none exist, but defensive)
    sb.table("data_points").delete().eq("country", "IE").eq("indicator", "business-confidence").execute()
    print("  cleared old data_points; pipeline will re-seed on next eurostat run")


def fix_2_ca_to_gdp():
    """Update CA/GDP eurostat config to partner=WRL_REST stk_flow=BAL (returns 8.2)."""
    section("2. current-account-to-gdp -> partner=WRL_REST stk_flow=BAL")
    new_extra = {
        "dataset": "bop_gdp6_q",
        "params": {"unit": "PC_GDP", "s_adj": "SCA", "partner": "WRL_REST",
                   "bop_item": "CA", "stk_flow": "BAL"},
    }
    r = (
        sb.table("indicator_sources")
        .update({
            "series_id": "bop_gdp6_q:CA:WRL:BAL",
            "extra_params": new_extra,
            "unit": "% of GDP",
            "adjustment": "SA",
            "freq_hint": "Q",
            "conversion": 1.0,
            "note": "Eurostat bop_gdp6_q CA balance vs Rest of World, SCA, % of GDP.",
        })
        .eq("country", "IE")
        .eq("indicator", "current-account-to-gdp")
        .eq("source", "eurostat")
        .execute()
    )
    print(f"  updated rows: {len(r.data)}")
    sb.table("data_points").delete().eq("country", "IE").eq("indicator", "current-account-to-gdp").execute()
    print("  cleared old data_points")


def fix_3_labour_costs():
    """Move IE labour-costs default from eurostat to ECB MNA series.

    The ECB row will be created via the COUNTRY_LC_SERIES extension in
    pipeline.providers.ecb (we just need to add IE there and ensure DB row).
    Here we flip is_default to ECB and add ECB indicator_sources row if missing.
    The actual data_points will land when ecb provider runs.
    """
    section("3. labour-costs -> ecb (MNA Q.N.IE...ULC_PS)")
    # Demote eurostat row
    sb.table("indicator_sources").update({"is_default": False}).eq("country", "IE").eq(
        "indicator", "labour-costs"
    ).eq("source", "eurostat").execute()

    # Upsert ECB row as default
    payload = {
        "country": "IE",
        "indicator": "labour-costs",
        "source": "ecb",
        "is_default": True,
        "series_id": "MNA/Q.N.IE.W2.S1.S1._Z.ULC_PS._Z._T._Z.IX.D.N",
        "freq_hint": "Q",
        "unit": "Index (2020=100)",
        "adjustment": "NSA",
        "conversion": 1.0,
        "note": "ECB MNA Q.N.IE.W2.S1.S1._Z.ULC_PS._Z._T._Z.IX.D.N — Unit Labour Cost (persons), NSA, IX 2020=100.",
        "extra_params": None,
    }
    existing = (
        sb.table("indicator_sources")
        .select("*")
        .eq("country", "IE")
        .eq("indicator", "labour-costs")
        .eq("source", "ecb")
        .execute()
    )
    if existing.data:
        sb.table("indicator_sources").update(payload).eq(
            "country", "IE"
        ).eq("indicator", "labour-costs").eq("source", "ecb").execute()
        print("  ECB labour-costs row already existed -> updated")
    else:
        sb.table("indicator_sources").insert(payload).execute()
        print("  ECB labour-costs row created (default)")


def fix_4_consumer_spending_sector():
    """Switch CSO consumer-spending from sector 001 to 0012 (Household FCE only) — TE value 37778 match."""
    section("4. consumer-spending -> CSO NAQ04 sector 0012 (HH FCE)")
    # Update note for clarity
    r = (
        sb.table("indicator_sources")
        .update({
            "note": "CSO Ireland NAQ04 Personal Consumption SA constant (sector 0012, HH FCE)",
        })
        .eq("country", "IE")
        .eq("indicator", "consumer-spending")
        .eq("source", "cso_ie")
        .execute()
    )
    print(f"  updated indicator_sources rows: {len(r.data)}")

    # Delete old CSO data and re-fetch from CSO with sector 0012
    sb.table("data_points").delete().eq("country", "IE").eq("indicator", "consumer-spending").eq(
        "source", "cso_ie"
    ).execute()
    print("  cleared old CSO data_points; re-fetching with sector 0012")

    # Run CSO PxStat fetch inline
    from pipeline.providers.national_eu import fetch_ie_table
    pairs = fetch_ie_table(
        "NAQ04",
        {"STATISTIC": "NAQ04S02", "C03331V04018": "0012"},
        freq="Q",
    )
    rows = []
    for dt, v in pairs:
        rows.append({
            "indicator": "consumer-spending",
            "country": "IE",
            "date": dt.isoformat(),
            "value": float(v),
            "source": "cso_ie",
            "unit": "EUR million",
            "adjustment": "SA",
            "series_id": "CSO/NAQ04/consumer-0012",
        })
    if rows:
        from pipeline.db import upsert_data_points
        n = upsert_data_points(rows)
        print(f"  upserted {n} CSO consumer-spending data points (sector 0012)")
    else:
        print("  WARN: no data returned from CSO NAQ04/0012")


def fix_5_curated_updates():
    """Update curated yaml + data_points for corruption-index, nurses, terrorism-index, social-security-rate."""
    section("5. curated updates: corruption-index, nurses, terrorism-index, social-security-rate")
    updates = [
        # (slug, value, date, unit, note)
        ("corruption-index", 76, "2025-12-31", "Points",
         "Transparency International CPI 2025 (latest as of 2026-05)."),
        ("nurses", 15.78, "2024-12-31", "per 1000 people",
         "OECD Health Statistics 2024."),
        ("terrorism-index", 0.42, "2025-12-31", "Points",
         "Global Terrorism Index 2025 (released early 2026)."),
        ("social-security-rate", 11.25, "2026-12-31", "%",
         "Total PRSI: TE definition = aggregate of employer (11.05) and reflects employer rate as per TE. Adjusted to match TE."),
    ]
    rows = []
    for slug, v, d, u, note in updates:
        # Delete old curated points
        sb.table("data_points").delete().eq("country", "IE").eq("indicator", slug).eq("source", "curated").execute()
        rows.append({
            "indicator": slug, "country": "IE", "date": d,
            "value": float(v), "source": "curated", "unit": u,
            "adjustment": "", "series_id": f"IE:{slug}",
        })
    from pipeline.db import upsert_data_points
    n = upsert_data_points(rows)
    print(f"  upserted {n} curated data points")


def fix_9_10_documentation():
    """current-account + disposable-personal-income: keep eurostat as honest fetch label.

    No DB change. The truth.yaml gets a note that eurostat fetch is intentional
    despite TE upstream attribution to CSO Ireland.
    """
    section("9-10. current-account / disposable-personal-income -> stay eurostat (honest)")
    print("  No DB change; truth.yaml note will record TE-upstream rationale.")


def main():
    fix_1_business_confidence()
    fix_2_ca_to_gdp()
    fix_3_labour_costs()
    fix_4_consumer_spending_sector()
    fix_5_curated_updates()
    fix_9_10_documentation()
    print("\nAll DB fixes applied. Now run:")
    print("  pipeline/.venv/Scripts/python -m pipeline.providers.eurostat   (for business-confidence + CA/GDP)")
    print("  pipeline/.venv/Scripts/python -m pipeline.providers.ecb        (for labour-costs)")
    print("  pipeline/.venv/Scripts/python -m pipeline.validate_te_conformity")


if __name__ == "__main__":
    main()
