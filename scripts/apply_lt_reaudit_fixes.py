"""Apply LT reaudit fixes:
1. Update indicator_sources to honest fetch-source (matching what truth.yaml says)
2. data.gov.lt is currently down for many namespaces — existing lsd_lt data in DB is current as of recent fetches
3. Honest source labels only (where DB row has lsd_lt data points, point indicator_sources to lsd_lt)
"""
from pipeline.db import supabase as sb

# Slug -> (new_source, new_series_id, new_unit, new_adjustment, reason)
FIXES = {
    # CPI subgroups: lsd_lt provider has them via SVKI, DB already has lsd_lt data
    "inflation-cpi": ("lsd_lt", "LSD/svki/S7R246M2020217", "Index (2015=100)", "NSA",
                      "TE source=Statistics Lithuania; provider has SVKI; existing lsd_lt data in DB"),
    "cpi-food": ("lsd_lt", "LSD/svki/S7R246M2020217/CP01", "Index (2015=100)", "NSA",
                 "TE=Statistics Lithuania; lsd_lt CP01"),
    "cpi-clothing": ("lsd_lt", "LSD/svki/S7R246M2020217/CP03", "Index (2015=100)", "NSA",
                     "TE=Statistics Lithuania; lsd_lt CP03"),
    "cpi-housing-utilities": ("lsd_lt", "LSD/svki/S7R246M2020217/CP04", "Index (2015=100)", "NSA",
                              "TE=Statistics Lithuania; lsd_lt CP04"),
    "cpi-transportation": ("lsd_lt", "LSD/svki/S7R246M2020217/CP07", "Index (2015=100)", "NSA",
                           "TE=Statistics Lithuania; lsd_lt CP07"),
    "cpi-recreation-and-culture": ("lsd_lt", "LSD/svki/S7R246M2020217/CP09", "Index (2015=100)", "NSA",
                                   "TE=Statistics Lithuania; lsd_lt CP09"),
    "cpi-education": ("lsd_lt", "LSD/svki/S7R246M2020217/CP10", "Index (2015=100)", "NSA",
                      "TE=Statistics Lithuania; lsd_lt CP10"),
    "ppi": ("lsd_lt", "LSD/pramones_produk_kainu_indeksai/S7R259M2020327", "Index (2015=100)", "NSA",
            "TE=Statistics Lithuania"),
    "retail-sales": ("lsd_lt", "LSD/mazmen_prekyb_imoniu_apyvartos_indeksai/S8R838M40701035", "Index (2021=100)", "SA",
                     "TE=Statistics Lithuania"),
    "manufacturing-production": ("lsd_lt", "LSD/SDMX/S8R918_M4050113_5/EVRKM4050107=C/LYGINIMAS=palyg_2021/Islyginimas_indeksai=sezon",
                                 "Index (2021=100)", "SA",
                                 "TE=EUROSTAT but our provider fetches lsd_lt SDMX directly"),
    "government-debt": ("lsd_lt", "LSD/valdzios_sektoriaus_mastrichto_skola/S7R267M2040215", "Million EUR", "NSA",
                       "TE=Statistics Lithuania; provider fetches LSD Maastricht debt directly"),
}

print("Applying indicator_sources updates...")
for slug, (src, sid, unit, adj, reason) in FIXES.items():
    upd = {
        "source": src,
        "series_id": sid,
        "unit": unit,
        "adjustment": adj,
    }
    res = sb.table("indicator_sources").update(upd).eq("country", "LT").eq("indicator", slug).eq("is_default", True).execute()
    print(f"  [{slug:35s}] -> source={src:10s} | {sid[:60]} | {reason[:60]}")

print(f"\nApplied {len(FIXES)} fixes.")
