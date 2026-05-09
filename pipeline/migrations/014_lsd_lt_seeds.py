"""Promote LSD Lithuania (Lietuvos statistikos departamentas) as primary source
for LT inflation-cpi (HICP/SVKI) and ppi.

Source code:    lsd_lt
Endpoint:       https://get.data.gov.lt/datasets/gov/lsd/statistika/<ns>/<table_id>
Provider:       pipeline/providers/lsd_lt.py

The LSD's user-facing portal (osp.stat.gov.lt) is behind Cloudflare Turnstile
and Bank of Lithuania (www.lb.lt) is similarly gated. Lithuania's official
open-data gateway data.gov.lt re-publishes the same LSD datasets via a stable
public REST API — that is the working primary-source path.

Demotes the eurostat counterparts (ei_cphi_m for HICP, sts_inppd_m for PPI)
to is_default=False so the frontend pulls from lsd_lt by default.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb


# Register data source row (mirrors the pattern of insee/bdf — interval=6h
# because LSD publishes monthly, so 15m polling is wasteful).
DATA_SOURCE = {
    "slug": "lsd_lt",
    "name": "LSD Lithuania (via data.gov.lt)",
    "schedule": "interval:6h",
    "enabled": True,
    "config": {"base_url": "https://get.data.gov.lt/datasets/gov/lsd/statistika"},
}


# (country, slug, src, series_id, freq, unit, adjustment, conversion, note)
SEEDS = [
    ("LT", "inflation-cpi", "lsd_lt",
     "LSD/svki/S7R246M2020217",
     "M", "Index (2015=100)", "NSA", 1.0,
     "LSD SVKI HICP all-items total, 2015=100, via data.gov.lt"),
    ("LT", "ppi", "lsd_lt",
     "LSD/pramones_produk_kainu_indeksai/S7R259M2020327",
     "M", "Index (2015=100)", "NSA", 1.0,
     "LSD Pramones produkcijos kainu indeksai B_TO_E total industry, visa rinka, 2015=100"),
]


def main():
    # 1) data_sources upsert
    sb.table("data_sources").upsert(DATA_SOURCE, on_conflict="slug").execute()
    print(f"  data_sources: upserted {DATA_SOURCE['slug']}")

    # 2) indicator_sources promote/demote
    inserted = 0
    for country, slug, src, series_id, freq, unit, adj, conv, note in SEEDS:
        # Drop existing same-source row (idempotent re-run)
        sb.table("indicator_sources").delete().eq(
            "indicator", slug
        ).eq("country", country).eq("source", src).execute()
        # Demote eurostat counterpart (keep row as fallback, but not default)
        sb.table("indicator_sources").update({"is_default": False}).eq(
            "indicator", slug
        ).eq("country", country).eq("source", "eurostat").execute()
        row = {
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
        }
        sb.table("indicator_sources").insert(row).execute()
        inserted += 1
        print(f"  + {country}/{slug:<14} | {src:<7} | {series_id}")

    print(f"\n{inserted} LSD-direct rows promoted; eurostat counterparts demoted.")


if __name__ == "__main__":
    main()
