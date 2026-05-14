"""DE Stage-2 TE-Source-Conformity: promote Destatis + Bundesbank to default for
indicators where TE attributes the series nationally (Destatis or Bundesbank),
demoting the existing Eurostat fallback rows.

Source: docs/_te_inventory/DE.yaml (verified=true). Indicator coverage:

Destatis (Statistisches Bundesamt, GENESIS-Online):
  retail-sales                  45212-0005 (Umsatz Einzelhandel, real, original)
  manufacturing-production      42153-0001 (Produktionsindex, WZ08-C)
  mining-production             42153-0001 (Produktionsindex, WZ08-B)
  industrial-production         42153-0001 (Produktionsindex, WZ08-BCDE)
  employed-persons              13321-0001 (Erwerbstaetige Inlaender, monatl.)
  youth-unemployment-rate       13231-0003 (Erwerbslosenquote 15-24, SA)
  population                    12411-0001 (Bevoelkerung Stichtag, annual)
  government-debt               71311-0001 (Schulden nicht-oeffentl. Bereich, Q)
  government-debt-total         71311-0001 (same)
  consumer-spending             81000-0020 (Private Konsumausgaben VGR035, SA real chain)
  government-spending           81000-0020 (Konsumausgaben Staat VGR015, SA real chain)
  gross-fixed-capital-formation 81000-0020 (Bruttoanlageinv. VGR041, SA real chain)
  disposable-personal-income    81000-0010 (Bezugsgr. Sparquote VGR092, SA)
  budget-deficit                81000-0031 (Finanzierungssaldo VGR114, annual Mrd EUR)

Bundesbank (api.statistiken.bundesbank.de):
  current-account               BBFBOPV M.N.DE.W1.S1.S1.T.B.CA._Z._Z._Z.EUR._T._X.N.ALL
  labour-costs                  BBDE1   Q.DE.Y.LCA1.A2N100000.A.L.I20.A

Inflation sub-aggregates (core-cpi, food-inflation, services-inflation,
energy-inflation) require Destatis CPI Sonderaggregate which aren't exposed
in the standard 6111x flat-file tables — DEFERRED for a follow-up migration
once we wire the Sonderaggregate-API or scrape the monthly press release.
"""

import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb


DESTATIS_SEEDS = [
    # (slug, series_id, freq, unit, adjustment, conversion, note)
    ("retail-sales", "45212-0005", "M", "Index (2015=100)", "NSA", 1.0,
     "Umsatz im Einzelhandel ohne Kfz/Tankstellen WZ47-02 real Originalwerte 2015=100"),
    ("manufacturing-production", "42153-0001", "M", "Index (2021=100)", "NSA", 1.0,
     "Produktionsindex Verarbeitendes Gewerbe WZ08-C Originalwerte 2021=100"),
    ("mining-production", "42153-0001", "M", "Index (2021=100)", "NSA", 1.0,
     "Produktionsindex Bergbau WZ08-B Originalwerte 2021=100"),
    ("industrial-production", "42153-0001", "M", "Index (2021=100)", "NSA", 1.0,
     "Produktionsindex Industrie gesamt WZ08-BCDE Originalwerte 2021=100"),
    ("employed-persons", "13321-0001", "M", "Thousand persons", "NSA", 1.0,
     "Erwerbstaetige Inlaenderkonzept Originalwerte (TE-conform 45,519 Tsd. Mar 2026)"),
    ("youth-unemployment-rate", "13231-0003", "M", "%", "SA", 1.0,
     "Erwerbslosenquote 15-24 Jahre, beide Geschlechter, X13 saisonbereinigt"),
    ("population", "12411-0001", "A", "Million", "NSA", 1.0,
     "Bevoelkerung Stichtag 31.12., annual (conversion 1e-6 in provider, stored in Mio)"),
    ("government-debt", "71311-0001", "Q", "Million EUR", "NSA", 1.0,
     "Schulden beim nicht-oeffentl. Bereich, oeffentl. Gesamthaushalt Insgesamt, Quartalsende"),
    ("government-debt-total", "71311-0001", "Q", "Million EUR", "NSA", 1.0,
     "Same series as government-debt (TE has both slugs)"),
    ("consumer-spending", "81000-0020", "Q", "Billion EUR", "SA", 1.0,
     "Private Konsumausgaben VGR035, sa, preisbereinigt verkettete Volumenang. Mrd EUR"),
    ("government-spending", "81000-0020", "Q", "Billion EUR", "SA", 1.0,
     "Konsumausgaben des Staates VGR015, sa, preisbereinigt verkettete Volumenang. Mrd EUR"),
    ("gross-fixed-capital-formation", "81000-0020", "Q", "Billion EUR", "SA", 1.0,
     "Bruttoanlageinvestitionen VGR041, sa, preisbereinigt verkettete Volumenang. Mrd EUR"),
    ("disposable-personal-income", "81000-0010", "Q", "Billion EUR", "SA", 1.0,
     "Bezugsgroesse fuer Sparquote VGR092, X13 saisonbereinigt (TE-conform 670.87 Q4 2025)"),
    ("budget-deficit", "81000-0031", "A", "Billion EUR", "NSA", 1.0,
     "Finanzierungssaldo des Staates VGR114, annual Mrd EUR (frontend computes %-of-GDP)"),
]


BUNDESBANK_SEEDS = [
    ("current-account", "BBFBOPV.M.N.DE.W1.S1.S1.T.B.CA._Z._Z._Z.EUR._T._X.N.ALL",
     "M", "Million EUR", "NSA", 1.0,
     "Leistungsbilanzsaldo gg. Welt (BoP), Originalwerte (TE-conform 23,635 Mio Mar 2026)"),
    ("labour-costs", "BBDE1.Q.DE.Y.LCA1.A2N100000.A.L.I20.A",
     "Q", "Index (2020=100)", "SA", 1.0,
     "Arbeitskostenindex B-S Gesamtwirtschaft, kalender- und saisonbereinigt, 2020=100"),
]


def seed(country: str, slug: str, src: str, series_id: str,
         freq: str, unit: str, adj: str, conv: float, note: str) -> None:
    # Remove prior entry from same (slug, country, source) — idempotent re-runs
    sb.table("indicator_sources").delete().eq(
        "indicator", slug
    ).eq("country", country).eq("source", src).execute()
    # Demote any other defaults for (slug, country)
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


def main():
    inserted = 0
    for slug, sid, freq, unit, adj, conv, note in DESTATIS_SEEDS:
        seed("DE", slug, "destatis", sid, freq, unit, adj, conv, note)
        print(f"  + DE/{slug:<32} | destatis   | {sid}")
        inserted += 1
    for slug, sid, freq, unit, adj, conv, note in BUNDESBANK_SEEDS:
        seed("DE", slug, "bundesbank", sid, freq, unit, adj, conv, note)
        print(f"  + DE/{slug:<32} | bundesbank | {sid}")
        inserted += 1

    print(f"\n{inserted} DE Stage-2 rows promoted; eurostat counterparts demoted.")
    print("Deferred (require CPI Sonderaggregate):")
    print("  core-cpi, food-inflation, services-inflation, energy-inflation")


if __name__ == "__main__":
    main()
