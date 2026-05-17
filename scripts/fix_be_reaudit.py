"""Apply fixes from BE re-audit.

Per user constraint: source-label = technical fetch quote.
"""
from __future__ import annotations

import json

from pipeline.db import supabase as sb


def flip_default(country, ind, new_source, new_series_id, note,
                 extra_params=None, conversion=None, unit=None,
                 freq_hint=None, adjustment=None):
    """Make (country, ind, new_source, new_series_id) the default row.

    Handles three cases:
      A) the (new_source, new_series_id) row already exists → set is_default=True,
         flip the current default to False.
      B) row exists with new_source but different series_id → update series_id+meta on it,
         flip current default to False.
      C) brand-new combo → update the current default in place (no duplicate to flip).
    """
    rows = sb.table("indicator_sources").select(
        "indicator,country,source,series_id,is_default,extra_params"
    ).eq("country", country).eq("indicator", ind).execute().data

    cur_default = next((r for r in rows if r["is_default"]), None)
    target = next((r for r in rows if r["source"] == new_source), None)

    payload = {"note": note}
    if extra_params is not None:
        payload["extra_params"] = extra_params
    if conversion is not None:
        payload["conversion"] = conversion
    if unit is not None:
        payload["unit"] = unit
    if freq_hint is not None:
        payload["freq_hint"] = freq_hint
    if adjustment is not None:
        payload["adjustment"] = adjustment

    if target is None:
        # CASE C — update current default row to new source+series_id in place
        upd = {**payload, "source": new_source, "series_id": new_series_id}
        sb.table("indicator_sources").update(upd).eq(
            "country", country).eq("indicator", ind).eq(
            "is_default", True).execute()
        print(f"  REPLACE_DEFAULT {country}/{ind}: -> {new_source}/{new_series_id}")
        return

    # CASES A/B — there is already a row with the right source.
    # Flip default off the old, update target series_id+meta+is_default
    if cur_default and cur_default["source"] != new_source:
        sb.table("indicator_sources").update({"is_default": False}).eq(
            "country", country).eq("indicator", ind).eq(
            "source", cur_default["source"]).eq(
            "series_id", cur_default["series_id"]).execute()
        print(f"  FLIP_OFF        {country}/{ind} {cur_default['source']}/{cur_default['series_id']}")

    upd = {**payload, "series_id": new_series_id, "is_default": True}
    sb.table("indicator_sources").update(upd).eq(
        "country", country).eq("indicator", ind).eq(
        "source", new_source).eq("series_id", target["series_id"]).execute()
    print(f"  SET_DEFAULT     {country}/{ind} -> {new_source}/{new_series_id}")


def delete_dp(country, ind):
    sb.table("data_points").delete().eq("country", country).eq("indicator", ind).execute()
    print(f"  DEL  {country}/{ind} data_points")


def main():
    # ===== 1) CPI subgroups: Eurostat → Statbel =====
    cpi_subs = [
        ("cpi-clothing", "STATBEL/dfc2ab6f",
         "Statbel CPI by ECOICOP V2 13 groups — Clothing and footwear (03), national CPI index"),
        ("cpi-food", "STATBEL/dfc2ab6f",
         "Statbel CPI by ECOICOP V2 13 groups — Food and non-alcoholic beverages (01)"),
        ("cpi-housing-utilities", "STATBEL/dfc2ab6f",
         "Statbel CPI by ECOICOP V2 13 groups — Housing, water, electricity, gas and other fuels (04)"),
        ("cpi-transportation", "STATBEL/dfc2ab6f",
         "Statbel CPI by ECOICOP V2 13 groups — Transport (07), national CPI index"),
    ]
    for ind, sid, note in cpi_subs:
        flip_default("BE", ind, "statbel", sid, note,
                     extra_params=None,
                     conversion=1.0, unit="Index",
                     freq_hint="M", adjustment="NSA")
        delete_dp("BE", ind)

    # ===== 2) government-debt → eurostat % of GDP =====
    flip_default("BE", "government-debt", "eurostat", "gov_10dd_edpt1:GD",
                 "Eurostat gov_10dd_edpt1 General government gross debt as % of GDP (S13)",
                 extra_params={"dataset": "gov_10dd_edpt1",
                               "params": {"unit": "PC_GDP", "sector": "S13", "na_item": "GD"}},
                 conversion=1.0, unit="% of GDP",
                 freq_hint="A", adjustment="")
    delete_dp("BE", "government-debt")

    # ===== 3) government-spending-eur → nbb =====
    flip_default("BE", "government-spending-eur", "nbb",
                 "NBB/DF_QNA_DISS/Q.2.P3_S13.VZ.V.Y",
                 "NBB DF_QNA_DISS P.3 Final consumption of general government (S.13)",
                 extra_params=None, conversion=1.0, unit="EUR million",
                 freq_hint="Q", adjustment="SA")
    delete_dp("BE", "government-spending-eur")

    # ===== 4) labour-costs → eurostat D1_D4_MD5_XB CA (matches TE 119.32) =====
    flip_default("BE", "labour-costs", "eurostat",
                 "lc_lci_r2_q:D1_D4_MD5_XB:CA",
                 "Eurostat lc_lci_r2_q LCI B-S exc. bonuses, CA, 2020=100. TE attributes ECB which redistributes Eurostat LCI.",
                 extra_params={"dataset": "lc_lci_r2_q",
                               "params": {"unit": "I20", "s_adj": "CA",
                                          "nace_r2": "B-S", "lcstruct": "D1_D4_MD5_XB"}},
                 conversion=1.0, unit="Index", freq_hint="Q", adjustment="CA")
    delete_dp("BE", "labour-costs")

    # ===== 5) minimum-wages → eurostat earn_mw_cur =====
    flip_default("BE", "minimum-wages", "eurostat", "earn_mw_cur:EUR",
                 "Eurostat earn_mw_cur Minimum wage in EUR (semi-annual S1/S2)",
                 extra_params={"dataset": "earn_mw_cur",
                               "params": {"currency": "EUR"}},
                 conversion=1.0, unit="EUR/Month", freq_hint="S", adjustment="")
    delete_dp("BE", "minimum-wages")

    # ===== 6) retail-sales → eurostat sts_trtu_m =====
    flip_default("BE", "retail-sales", "eurostat",
                 "sts_trtu_m:G47:I21:VOL_SLS",
                 "Eurostat sts_trtu_m retail trade NACE G47 SCA volume of sales index 2021=100. TE attributes Eurostat.",
                 extra_params={"dataset": "sts_trtu_m",
                               "params": {"unit": "I21", "s_adj": "SCA",
                                          "nace_r2": "G47", "indic_bt": "VOL_SLS"}},
                 conversion=1.0, unit="Index", freq_hint="M", adjustment="SCA")
    delete_dp("BE", "retail-sales")


if __name__ == "__main__":
    main()
    print("DONE — re-run providers to backfill new sources.")
