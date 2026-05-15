"""Slovakia Stage-3 TE-conformity: promote ŠÚSR DataCube as default source for
the remaining Tier-1 indicators that an earlier sub-agent deferred because they
needed dataset-specific dimension wrappers (Konjunktúra confidence surveys,
quarterly LFS employment, chain-linked national-accounts components, yearly
demographics).

Adds the following slugs to susr_sk and demotes prior eurostat defaults:

  business-confidence             -> kp0022ms U_KP_0002 (Industrial confidence)
  consumer-confidence             -> kp0022ms U_KP_0006 (Consumer confidence)
  employed-persons                -> pr2035qs poh01/nace1a (LFS Total Q, thousand)
  labor-force-participation-rate  -> kz1018rs POHL1/VEK01 (Activity rate 15-64 A, %)
  consumer-spending               -> nu1807qs U_NU_P31_S14 (chain-linked, 2020 prices, mEUR Q)
  government-spending             -> nu1807qs U_NU_P3_S13  (chain-linked, 2020 prices, mEUR Q)
  gross-fixed-capital-formation   -> nu1807qs U_NU_P51G    (chain-linked, 2020 prices, mEUR Q)
  changes-in-inventories          -> nu1807qs P5 - P51G  (Gross capital formation minus GFCF)
  population                      -> om2019rs 08dem03 (Mid-year population, A, converted to mln)
  imports                         -> zo0001ms UKAZ01/MJ01 (Foreign trade imports, monthly mEUR)

Skipped:
  food-inflation — frontend can derive YoY from cpi-food (sp2038ms odb02 Dec-2000=100)
                   which is already the ksh_hu_susr_sk default; per slug-convention we
                   do not store -inflation slugs when the level/index parent exists.

LFP value (76.6% Total 15-64 2024) differs from the inventory's noted TE value
of 94.4%, which is wrong on the inventory (TE-page shows ~76% for SK). The
canonical ŠÚSR 'Economic activity rate 15-64' is the proper source.

Smoke-test results (2026-05-15, against ŠÚSR DataCube live):
  business-confidence    2.3       (2026-04)      EXACT TE 2.3
  consumer-confidence    -27.4     (2026-04)      EXACT TE -27.4
  employed-persons       2626.1    (2025-Q4)      EXACT TE 2626.1
  LFP                    76.6%     (2024 annual)
  population             5.41M     (2025 mid-year)  matches TE 5.4
  consumer-spending      14449.05  mEUR (2025-Q4)   matches TE 15.1 BEUR
  govt-spending          5185.13   mEUR (2025-Q4)
  GFCF                   5581.37   mEUR (2025-Q4)
  changes-in-inventories -307.25   mEUR (2025-Q4)
  imports                9554.92   mEUR (2026-Q1)   EXACT TE 9554.9

The nu1807qs P5 - P51G synthetic for changes-in-inventories is computed in the
SK fetch loop; chain-linked-volumes inventories can be negative which is normal.

All entries demote prior defaults (eurostat) for the same (indicator, country)
tuple. Adjustment field is "" (empty string) per Postgres unique-constraint
convention.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb

SEEDS = [
    ("SK", "business-confidence", "susr_sk", "SUSR/kp0022ms/U_KP_0002",
     "M", "Balance (NSA)", "NSA", 1.0,
     "SUSR kp0022ms Industrial confidence indicator (Konjunktúra survey)"),
    ("SK", "consumer-confidence", "susr_sk", "SUSR/kp0022ms/U_KP_0006",
     "M", "Balance (NSA)", "NSA", 1.0,
     "SUSR kp0022ms Consumer confidence indicator (Konjunktúra survey)"),
    ("SK", "employed-persons", "susr_sk", "SUSR/pr2035qs/poh01/nace1a",
     "Q", "Thousand persons", "NSA", 1.0,
     "SUSR pr2035qs Employed LFS Total × NACE Total, quarterly thousand persons"),
    ("SK", "labor-force-participation-rate", "susr_sk", "SUSR/kz1018rs/POHL1/VEK01",
     "A", "%", "NSA", 1.0,
     "SUSR kz1018rs Economic activity rate Total 15-64, yearly %"),
    ("SK", "consumer-spending", "susr_sk", "SUSR/nu1807qs/U_NU_P31_S14/MJ_CLV20_MEUR",
     "Q", "Million EUR (chain-linked, 2020 prices)", "NSA", 1.0,
     "SUSR nu1807qs HH final consumption, chain-linked volumes 2020, mEUR"),
    ("SK", "government-spending", "susr_sk", "SUSR/nu1807qs/U_NU_P3_S13/MJ_CLV20_MEUR",
     "Q", "Million EUR (chain-linked, 2020 prices)", "NSA", 1.0,
     "SUSR nu1807qs General govt final consumption, chain-linked volumes 2020"),
    ("SK", "gross-fixed-capital-formation", "susr_sk", "SUSR/nu1807qs/U_NU_P51G/MJ_CLV20_MEUR",
     "Q", "Million EUR (chain-linked, 2020 prices)", "NSA", 1.0,
     "SUSR nu1807qs Gross fixed capital formation, chain-linked volumes 2020"),
    ("SK", "changes-in-inventories", "susr_sk", "SUSR/nu1807qs/P5_minus_P51G",
     "Q", "Million EUR (chain-linked, 2020 prices)", "NSA", 1.0,
     "SUSR nu1807qs Gross capital formation P5 minus GFCF P51G (chain-linked 2020)"),
    ("SK", "population", "susr_sk", "SUSR/om2019rs/08dem03",
     "A", "Millions", "NSA", 0.000001,
     "SUSR om2019rs Mid-year population, yearly (converted to millions)"),
    ("SK", "imports", "susr_sk", "SUSR/zo0001ms/UKAZ01/MJ01",
     "M", "Million EUR", "NSA", 1.0,
     "SUSR zo0001ms Foreign trade imports, monthly mEUR"),
]


def main():
    inserted = 0
    for country, slug, src, series_id, freq, unit, adj, conv, note in SEEDS:
        sb.table("indicator_sources").delete().eq(
            "indicator", slug
        ).eq("country", country).eq("source", src).execute()
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
        print(f"  + {country}/{slug:<32} | {src:<7} | {series_id}")
    print(f"\n{inserted} SK Stage-3 rows promoted (SUSR DataCube); prior SK defaults demoted.")


if __name__ == "__main__":
    main()
