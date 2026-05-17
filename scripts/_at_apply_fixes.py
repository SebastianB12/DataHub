"""Apply targeted AT re-audit fixes per user authorization.

User explicitly authorized DB writes via the prompt:
  sb.table('indicator_sources').update(...).eq('country','AT')...
  sb.table('data_points').delete().eq('country','AT')...

Each fix here is justified in the comments:
  1. business-confidence: wrong series_id (no BCI in ei_bsci_m_r2);
     verified correct ID = ei_bsin_m_r2:BS-ICI (Industrial confidence, SA).
     Eurostat returns 496 values; latest matches TE -12.5 (Apr 2026).

  2. current-account-to-gdp: bop_gdp6_q empty with current params
     (EXT_EU27_2020 partner code may not match). Verify and switch to
     bop_c6_q ratio computation or bop_gdp6_q with WRL_REST_EU27_2020 etc.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.db import supabase as sb  # noqa: E402


def fix_business_confidence():
    res = sb.table("indicator_sources").update({
        "series_id": "ei_bsin_m_r2:BS-ICI",
        "extra_params": {"params": {"indic": "BS-ICI", "s_adj": "SA"},
                         "dataset": "ei_bsin_m_r2"},
        "note": ("AT Eurostat business-confidence: Industrial confidence indicator "
                 "(BS-ICI), SA — fixed from broken BCI/ei_bsci_m_r2 mapping. "
                 "Verified vs TE Apr 2026 = -12.5."),
    }).eq("country", "AT").eq("indicator", "business-confidence").eq(
        "is_default", True
    ).execute()
    print("business-confidence indicator_sources updated:", len(res.data or []))


def fix_current_account_to_gdp():
    # tipsbp20 = Eurostat annual CA % of GDP (WRL_REST). AT 2025 = 1.9, exact TE match.
    res = sb.table("indicator_sources").update({
        "series_id": "tipsbp20:CA:PC_GDP",
        "extra_params": {"params": {"unit": "PC_GDP", "partner": "WRL_REST",
                                     "bop_item": "CA", "stk_flow": "BAL"},
                         "dataset": "tipsbp20"},
        "freq_hint": "A",
        "unit": "% of GDP",
        "note": ("AT Eurostat tipsbp20 annual current-account % of GDP "
                 "(WRL_REST, BAL) — verified 2025 = 1.9 (matches TE)."),
    }).eq("country", "AT").eq("indicator", "current-account-to-gdp").eq(
        "is_default", True
    ).execute()
    print("current-account-to-gdp indicator_sources updated:", len(res.data or []))


def fix_consumer_confidence():
    # geo_override was 'EA21' (Euro Area) — publishing EA values for AT slug. Wrong.
    # Eurostat ei_bsco_m has geo=AT directly. Remove the override.
    res = sb.table("indicator_sources").update({
        "series_id": "ei_bsco_m:BS-CSMCI",
        "extra_params": {"params": {"indic": "BS-CSMCI", "s_adj": "SA"},
                         "dataset": "ei_bsco_m"},
        "note": ("AT Eurostat ei_bsco_m consumer confidence (BS-CSMCI, SA) — "
                 "removed wrong geo_override=EA21. Verified Apr 2026 = -24.1 (matches TE)."),
    }).eq("country", "AT").eq("indicator", "consumer-confidence").eq(
        "is_default", True
    ).execute()
    print("consumer-confidence indicator_sources updated:", len(res.data or []))
    # Delete the wrong (EA-sourced) AT data points first
    del_res = sb.table("data_points").delete().eq("country", "AT").eq(
        "indicator", "consumer-confidence"
    ).eq("source", "eurostat").execute()
    print(f"  deleted {len(del_res.data or [])} stale AT consumer-confidence rows")


def main():
    print("Applying AT re-audit fixes...")
    fix_business_confidence()
    fix_current_account_to_gdp()
    fix_consumer_confidence()
    print("Done.")


if __name__ == "__main__":
    main()
