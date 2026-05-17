"""Apply PL re-audit fixes.

Strategy per slug:
  * SOURCE-LABEL = TECHNICAL FETCH (no relabel)
  * Eurostat fetches stay 'eurostat' even when TE attributes upstream (NBP/GUS)
  * Compute YoY frontend-side for index series (no DB rewrite)
  * Update curated values where TE shows newer figures
  * Switch source where existing source returns wrong metric

Run: pipeline/.venv/Scripts/python.exe scripts/fix_pl_reaudit.py
"""
from __future__ import annotations

import json
import sys
import time
from datetime import date
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.db import supabase as sb  # noqa: E402

# ============================================================================
# CONFIG OF FIXES
# ============================================================================
# Each fix is one of:
#   (slug, 'curated_update', {value, date, unit, note})
#   (slug, 'switch_source', {source, series_id, extra_params, unit, freq_hint, adjustment, note})
#   (slug, 'note_only', {note})   -> update note only, don't touch data
#   (slug, 'truth_yaml_update', {...})

FIXES = [
    # ---- Curated value updates (TE shows newer/different values) ----
    ("terrorism-index", "curated_update", {
        "value": 1.68, "date": "2025-12-31", "unit": "Points",
        "note": "Global Terrorism Index 2025 (Institute for Economics and Peace via TE).",
    }),
    ("social-security-rate", "curated_update", {
        "value": 34.19, "date": "2026-12-31", "unit": "%",
        "note": "Total social-security contributions PL 2026 (per TE).",
    }),
    ("social-security-rate-companies", "curated_update", {
        "value": 20.48, "date": "2026-12-31", "unit": "%",
        "note": "Employer SS share 2026 (per TE).",
    }),
    ("corruption-rank", "curated_update", {
        "value": 52, "date": "2025-12-31", "unit": "Rank",
        "note": "CPI 2025 Transparency International (per TE).",
    }),
    # ---- Source switches ----
    ("minimum-wages", "switch_source", {
        "source": "eurostat",
        "series_id": "earn_mw_cur:PL:EUR",
        "extra_params": {"dataset": "earn_mw_cur", "params": {"currency": "EUR"}},
        "unit": "EUR/Month",
        "freq_hint": "S",
        "adjustment": "NSA",
        "conversion": 1,
        "transform": "raw",
        "note": "Eurostat earn_mw_cur (semi-annual EUR/Month). TE attributes Eurostat.",
    }),
    ("labor-force-participation-rate", "switch_source", {
        "source": "eurostat",
        "series_id": "lfsq_argan:Y_GE15:ACT",
        "extra_params": {"dataset": "lfsq_argan", "params": {"age": "Y_GE15", "sex": "T", "citizen": "TOTAL"}},
        "unit": "%",
        "freq_hint": "Q",
        "adjustment": "NSA",
        "conversion": 1,
        "transform": "raw",
        "note": "Eurostat lfsq_argan Y_GE15 (matches TE BAEL economic-activity-rate 15+).",
    }),
    ("current-account-to-gdp", "switch_source", {
        "source": "eurostat",
        "series_id": "bop_gdp6_q:CA:PC_GDP:WRL_REST",
        "extra_params": {"dataset": "bop_gdp6_q",
                         "params": {"unit": "PC_GDP", "partner": "WRL_REST",
                                    "bop_item": "CA", "s_adj": "NSA"}},
        "unit": "% of GDP",
        "freq_hint": "Q",
        "adjustment": "NSA",
        "conversion": 1,
        "transform": "raw",
        "note": "Eurostat bop_gdp6_q WRL_REST/NSA (was SCA/EXT_EU27_2020 — empty for PL).",
    }),
    ("gdp-real", "switch_source", {
        "source": "eurostat",
        "series_id": "namq_10_gdp:B1GQ:CLV_PCH_PRE",
        "extra_params": {"dataset": "namq_10_gdp",
                         "params": {"unit": "CLV_PCH_PRE", "na_item": "B1GQ", "s_adj": "NSA"}},
        "unit": "%",
        "freq_hint": "Q",
        "adjustment": "NSA",
        "conversion": 1,
        "transform": "raw",
        "note": "Eurostat namq_10_gdp B1GQ/CLV_PCH_PRE (real GDP YoY %, was MEUR level).",
    }),
    ("job-vacancies", "switch_source", {
        "source": "eurostat",
        "series_id": "jvs_q_nace2:JOBVAC",
        "extra_params": {"dataset": "jvs_q_nace2",
                         "params": {"s_adj": "NSA", "nace_r2": "B-S",
                                    "indic_em": "JOBVAC", "sizeclas": "TOTAL"}},
        "unit": "Vacancies",
        "freq_hint": "Q",
        "adjustment": "NSA",
        "conversion": 1,
        "transform": "raw",
        "note": "Eurostat jvs_q_nace2 JOBVAC count (was JVR %). TE attributes GUS (different methodology: registered vacancies); we fetch Eurostat — source label = eurostat per honest-label rule.",
    }),
]


def apply_curated_update(slug, cfg):
    """Update pipeline/curated/pl.yaml and the corresponding DB row."""
    yml_path = ROOT / "pipeline/curated/pl.yaml"
    with open(yml_path, "r", encoding="utf-8") as f:
        cur = yaml.safe_load(f)
    cur[slug] = {
        "value": cfg["value"],
        "date": cfg["date"],
        "unit": cfg["unit"],
    }
    if cfg.get("note"):
        cur[slug]["note"] = cfg["note"]
    with open(yml_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(cur, f, sort_keys=False, allow_unicode=True, default_flow_style=False)

    # Refresh DB datapoint
    sb.table("data_points").delete().eq("country", "PL").eq("indicator", slug).execute()
    sb.table("data_points").insert({
        "indicator": slug,
        "country": "PL",
        "date": cfg["date"],
        "value": cfg["value"],
        "source": "curated",
        "unit": cfg["unit"],
        "series_id": f"PL:{slug}",
        "adjustment": "",
    }).execute()
    if cfg.get("note"):
        sb.table("indicator_sources").update({"note": cfg["note"]}).eq(
            "country", "PL").eq("indicator", slug).eq("is_default", True).execute()
    print(f"  CURATED {slug} = {cfg['value']} {cfg['unit']} ({cfg['date']})")


def apply_switch_source(slug, cfg):
    """Switch source and refresh data."""
    upd = {
        "source": cfg["source"],
        "series_id": cfg["series_id"],
        "extra_params": cfg["extra_params"],
        "unit": cfg["unit"],
        "freq_hint": cfg["freq_hint"],
        "adjustment": cfg["adjustment"],
        "conversion": cfg.get("conversion", 1),
        "transform": cfg.get("transform", "raw"),
        "note": cfg["note"],
    }
    sb.table("indicator_sources").update(upd).eq("country", "PL").eq(
        "indicator", slug).eq("is_default", True).execute()
    # Wipe old data so the next pipeline run repopulates from new source
    sb.table("data_points").delete().eq("country", "PL").eq("indicator", slug).execute()
    print(f"  SWITCH {slug} -> {cfg['source']} ({cfg['series_id']})")


def main():
    for slug, kind, cfg in FIXES:
        print(f"[{kind}] {slug}")
        try:
            if kind == "curated_update":
                apply_curated_update(slug, cfg)
            elif kind == "switch_source":
                apply_switch_source(slug, cfg)
            else:
                print(f"  ?? unknown kind {kind}")
        except Exception as e:
            print(f"  FAIL: {e}")
    print("\nDone.")


if __name__ == "__main__":
    main()
