"""Confidence-survey TE-conformity for SE / FI / LV.

TE attributes the confidence surveys to national bodies, not Eurostat. This
migration wires the primary-source providers and demotes the eurostat fallbacks.

Per country / slug:

  SE consumer-confidence  -> konj_se  (NIER hushall/indikatorhus bhuscon, All)
       Verified 2026-05-15: 2026-04 = 91.5  (TE: 91.5 EXACT)

  SE business-confidence  -> konj_se  (NIER indikatorer/Indikatorm BTOT)
       Verified 2026-05-15: 2026-04 = 103.3 (TE: 103.3 EXACT)

  FI consumer-confidence  -> stat_fi  (Tilastokeskus kbar 11cc CCI_A1)
       Verified 2026-05-15: 2026-04 = -12.5 (TE: -12.5 EXACT)

  FI business-confidence  -> gap, kept on eurostat fallback.
       TE source is "Confederation of Finnish Industries (EK)". EK publishes only
       PDF / Excel reports (no JSON/SDMX/PxWeb), and Tilastokeskus does not
       republish the EK business-tendency series. Documented in
       docs/te_coverage_gaps.yaml.

  LV consumer-confidence  -> csp_lv  (CSP KRE020m CI_CONSUM, NSA — fixed series_id)
       Migration 042 picked VAL=SA which doesn't match TE; TE shows the NSA
       balance. LV_SERIES updated to VAL=NSA, series_id suffix /NSA.
       Verified 2026-05-15: 2026-03 = -16.1 NSA (TE: -16.1 EXACT)

  LV business-confidence  -> csp_lv  (CSP KRE020m CI_IND, NSA — fixed series_id)
       Same VAL fix as consumer-confidence.
       Verified 2026-05-15: 2026-03 = -0.3 NSA (TE: -0.3 EXACT)

Run order:
    python -m pipeline.migrations.061_confidence_providers
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb


SEEDS = [
    # (country, slug, src, series_id, freq, unit, adjustment, conversion, note)
    ("SE", "consumer-confidence", "konj_se",
     "KONJ/hushall/indikatorhus/bhuscon", "M",
     "Index (2000-2024=100)", "NSA", 1.0,
     "NIER Konjunkturbarometer Consumer Confidence Indicator (bhuscon)"),
    ("SE", "business-confidence", "konj_se",
     "KONJ/indikatorer/Indikatorm/BTOT", "M",
     "Index (2000-2024=100)", "NSA", 1.0,
     "NIER Konjunkturbarometer Business Sector composite (BTOT)"),
    ("FI", "consumer-confidence", "stat_fi",
     "STATFI/kbar/11cc/CCI_A1", "M",
     "Balance (%)", "NSA", 1.0,
     "FI Tilastokeskus 11cc Consumer Confidence Indicator A1 composite balance"),
    ("LV", "consumer-confidence", "csp_lv",
     "CSP/KRE020m/CI_CONSUM/NSA", "M",
     "Net balance, %", "NSA", 1.0,
     "CSP Latvia KRE020m Consumer Confidence Indicator (DG ECFIN), NSA"),
    ("LV", "business-confidence", "csp_lv",
     "CSP/KRE020m/CI_IND/NSA", "M",
     "Net balance, %", "NSA", 1.0,
     "CSP Latvia KRE020m Industrial Confidence Indicator (DG ECFIN), NSA"),
]


def main():
    inserted = 0
    for country, slug, src, series_id, freq, unit, adj, conv, note in SEEDS:
        # Drop any pre-existing row for this exact (indicator, country, source).
        sb.table("indicator_sources").delete().eq(
            "indicator", slug
        ).eq("country", country).eq("source", src).execute()
        # Demote any other defaults for the same indicator/country pair.
        sb.table("indicator_sources").update({"is_default": False}).eq(
            "indicator", slug
        ).eq("country", country).execute()
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
        print(f"  + {country}/{slug:<24} | {src:<8} | {series_id}")
    print(
        f"\n{inserted} confidence-survey rows promoted "
        "(SE konj_se x2, FI stat_fi x1, LV csp_lv x2)."
    )
    print(
        "Note: FI business-confidence stays on eurostat fallback — EK has no "
        "machine-readable endpoint (see docs/te_coverage_gaps.yaml)."
    )


if __name__ == "__main__":
    main()
