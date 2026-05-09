"""Promote national-source rows for DK/FI/SE/IE inflation-cpi etc., demote Eurostat to fallback.

Sources:
  dst    -> Statistics Denmark (Statbank)
  stat_fi-> Statistics Finland (Tilastokeskus)
  scb_se -> Statistics Sweden (SCB PxWeb)
  cso_ie -> CSO Ireland (PxStat)
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb

# (country, slug, src, series_id, freq, unit, adjustment, conversion, note)
SEEDS = [
    # Denmark
    ("DK", "inflation-cpi",         "dst", "DST/PRIS01",   "M", "Index", "NSA", 1.0, "DK Statbank PRIS01 CPI all-items index"),
    ("DK", "industrial-production", "dst", "DST/IPOP21",   "M", "Index", "SA",  1.0, "DK Statbank IPOP21 IP manufacturing SA"),
    ("DK", "unemployment",          "dst", "DST/AUP01",    "M", "%",     "SA",  1.0, "DK Statbank AUP01 unemployment rate (registered)"),
    ("DK", "retail-sales",          "dst", "DST/DETA211A", "M", "Index", "NSA", 1.0, "DK Statbank DETA211A Retail Trade Index G47"),
    # Finland
    ("FI", "inflation-cpi",         "stat_fi", "STATFI/khi/15b5", "M", "Index", "NSA", 1.0, "FI Tilastokeskus 15b5 CPI 2025=100 monthly"),
    # Sweden
    ("SE", "inflation-cpi",            "scb_se", "SCB/PR0101A/KPI2020M",   "M", "Index",            "NSA", 1.0, "SE SCB shadow CPI continuous index 1980=100"),
    ("SE", "ppi",                      "scb_se", "SCB/PR0301G/PPI2020M",   "M", "Index (2020=100)", "NSA", 1.0, "SE SCB PR0301G Producer Price Index, total B-E, 2020=100"),
    ("SE", "industrial-production-yoy","scb_se", "SCB/NV0402A/IPI2010KedjM","M", "%",               "WDA", 1.0, "SE SCB NV0402A Industrial Production YoY% WDA (B-D)"),
    ("SE", "unemployment",             "scb_se", "SCB/AM0401A/AKURLBefM",  "M", "%",                "SA",  1.0, "SE SCB AM0401A LFS unemployment rate 15-74 SA trend"),
    ("SE", "gdp-growth-rate",          "scb_se", "SCB/NR0103B/T10SKv",     "Q", "%",                "SA",  1.0, "SE SCB NR0103B GDP QoQ% volume change SA"),
    ("SE", "trade-balance",            "scb_se", "SCB/HA0201A/ImportExportSnabbM", "M", "SEK million", "NSA", 1.0, "SE SCB HA0201A Net Trade of goods SEK million"),
    ("SE", "retail-sales-yoy",         "scb_se", "SCB/HA0101B/DetOms07N",  "M", "%",                "WDA", 1.0, "SE SCB HA0101B Retail Sales YoY% (excl fuel) WDA constant prices"),
    # Ireland
    ("IE", "inflation-cpi",         "cso_ie", "CSO/CPM01",   "M", "Index",            "NSA", 1.0, "CSO Ireland CPM01 CPI Base Dec 2023=100 all items"),
    ("IE", "unemployment",          "cso_ie", "CSO/MUM01",   "M", "%",                "SA",  1.0, "CSO Ireland MUM01 SA Monthly Unemployment Rate 15-74 both sexes"),
    ("IE", "ppi",                   "cso_ie", "CSO/WPM35",   "M", "Index (2020=100)", "NSA", 1.0, "CSO Ireland WPM35 Industrial Price Index (excl VAT) Manufacturing 10-33"),
    ("IE", "industrial-production", "cso_ie", "CSO/MIM05",   "M", "Index (2021=100)", "SA",  1.0, "CSO Ireland MIM05 SA Industrial Production Index Industries 05-35"),
    ("IE", "retail-sales",          "cso_ie", "CSO/RSM08",   "M", "Index (2021=100)", "SA",  1.0, "CSO Ireland RSM08 Retail Sales Volume Index SA all retail businesses"),
    ("IE", "trade-balance",         "cso_ie", "CSO/TSM01",   "M", "EUR thousand",     "NSA", 1.0, "CSO Ireland TSM01 Merchandise Trade Surplus (Exports-Imports)"),
    ("IE", "housing-index",         "cso_ie", "CSO/HPM09",   "M", "Index",            "NSA", 1.0, "CSO Ireland HPM09 Residential Property Price Index national all properties"),
    ("IE", "gdp-real",              "cso_ie", "CSO/NAQ03",   "Q", "EUR million",      "SA",  1.0, "CSO Ireland NAQ03 GDP at Constant Market Prices SA chain-linked"),
    # Austria — direct from Statistik Austria OGD CSV (catalog at data.statistik.gv.at)
    ("AT", "inflation-cpi",         "stat_at", "STATAT/OGD_vpi20_VPI_2020_1", "M", "Index", "NSA", 1.0, "Statistik Austria VPI base 2020=100 (2021-01..2025-12)"),
    ("AT", "ppi",                   "stat_at", "STATAT/OGD_epi2021nac08_EPI_2021_OENACE_1", "M", "Index (2021=100)", "NSA", 1.0, "Statistik Austria EPI 2021=100 Gesamtmarkt (TE-matching)"),
    ("AT", "industrial-production", "stat_at", "STATAT/OGD_kjiprodindex2021_KJID2021_PI_1", "M", "Index (2021=100, WDA)", "WDA", 1.0, "Statistik Austria Produktionsindex 2021=100 AT total WDA (TE-matching)"),
    ("AT", "unemployment",          "stat_at", "STATAT/OGD_ake100_hvd_ogdonly_HVD_ALQUO_1", "Q", "%", "NSA", 1.0, "Statistik Austria ALQ ILO concept, AT total quarterly"),
    ("AT", "gdp",                   "stat_at", "STATAT/OGD_vgr108_VGR_HA_vj_1", "Q", "Bn EUR (real, SA)", "SA", 0.001, "Statistik Austria VGR108 BIP real SA, Mio->Bn EUR"),
    ("AT", "wages",                 "stat_at", "STATAT/OGD_bruttoverdiensteindex2021a_KJID2021_BVIa_1", "M", "Index (2021=100, SA)", "SA", 1.0, "Statistik Austria Bruttoverdiensteindex 2021=100 SA"),
    ("AT", "import-prices",         "stat_at", "STATAT/OGD_impi21_Impi21_1", "Q", "Index (2021=100)", "NSA", 1.0, "Statistik Austria IMPI 2021=100 Gesamtmarkt"),
    # Slovenia — direct from SURS PxWeb
    ("SI", "inflation-cpi",         "surs_si", "SURS/0400608S.px", "M", "Index (same month py=100)", "NSA", 1.0, "SURS 0400608S CPI Index vs same month previous year, TOTAL"),
    ("SI", "ppi",                   "surs_si", "SURS/0457101S.px", "M", "Index (2021=100)", "NSA", 1.0, "SURS 0457101 PPI Industry (B-E), Month / avg 2021"),
    ("SI", "industrial-production", "surs_si", "SURS/1701111S.px", "M", "Index (2021=100, SA)", "SA", 1.0, "SURS 1701111 IP Total industry (B+C+D), seasonally+calendar adjusted"),
    ("SI", "unemployment",          "surs_si", "SURS/0762013S.px", "M", "%", "SA", 1.0, "SURS 0762013 monthly unemployment rate (experimental, SA, total sex+age)"),
    ("SI", "gdp-growth-rate",       "surs_si", "SURS/0300220S.px", "Q", "% YoY", "SA", 1.0, "SURS 0300220 GDP volume YoY growth rate, SA"),
    ("SI", "gdp",                   "surs_si", "SURS/0300220S.px", "Q", "Million EUR", "SA", 1.0, "SURS 0300220 GDP current prices, mio EUR, SA"),
    ("SI", "retail-sales",          "surs_si", "SURS/2001303S.px", "M", "Index (2021=100, WDA)", "WDA", 1.0, "SURS 2001303 Retail trade ex fuel value index, calendar adjusted"),
    ("SI", "trade-balance",         "surs_si", "SURS/2490001S.px", "M", "Million EUR", "NSA", 1e-6, "SURS 2490001 Trade balance (exports - imports), EUR -> mio EUR"),
    ("SI", "exports",               "surs_si", "SURS/2490001S.px", "M", "Million EUR", "NSA", 1e-6, "SURS 2490001 Exports of goods, EUR -> mio EUR"),
    ("SI", "imports",               "surs_si", "SURS/2490001S.px", "M", "Million EUR", "NSA", 1e-6, "SURS 2490001 Imports of goods, EUR -> mio EUR"),
    # Latvia — direct from CSP PxWeb
    ("LV", "inflation-cpi",         "csp_lv", "CSP/PCI030m", "M", "Index (Dec 1990=100)", "NSA", 1.0, "CSP Latvia PCI030m CPI continuous index Dec 1990=100"),
    # Estonia — direct from Statistics Estonia PxWeb
    ("EE", "inflation-cpi",         "stat_ee", "STATEE/IA002.px", "M", "Index (1997=100)", "NSA", 1.0, "Statistics Estonia IA002 CPI 1997=100, total"),
    # Croatia — direct from DZS PxWeb (web.dzs.hr)
    ("HR", "inflation-cpi",         "dzs_hr", "DZS/ME_PS09.px", "M", "Index (2025=100)", "NSA", 1.0, "DZS Croatia ME_PS09 CPI 2025=100, total ECOICOP v2"),
    # Belgium — direct from Statbel REST API
    ("BE", "inflation-cpi",         "statbel", "STATBEL/208b69bd", "M", "Index (2013=100)", "NSA", 1.0, "Statbel CPI base 2013=100 (last 13 months)"),
    # Slovakia — direct from ŠÚ SR DataCube REST
    ("SK", "inflation-cpi",         "susr_sk", "SUSR/sp2038ms/odb01/mj38", "M", "Index (Dec 2000=100)", "NSA", 1.0, "ŠÚ SR sp2038ms CPI Total, Dec 2000=100"),
    # Hungary — direct from KSH STADAT (HTML scrape)
    ("HU", "inflation-cpi",         "ksh_hu",  "KSH/ara0040", "M", "Index (same month previous year=100)", "NSA", 1.0, "KSH ara0040 CPI YoY, total"),
    # Romania — direct from INSSE Tempo via tempo-py library
    ("RO", "inflation-cpi",         "insse_ro", "INSSE/IPC102A", "M", "Index (previous month=100)", "NSA", 1.0, "INSSE Tempo IPC102A CPI MoM index, total"),
]


def main():
    inserted = 0
    for country, slug, src, series_id, freq, unit, adj, conv, note in SEEDS:
        # Delete same-source row if any
        sb.table("indicator_sources").delete().eq(
            "indicator", slug
        ).eq("country", country).eq("source", src).execute()
        # Demote eurostat for this slug
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
        print(f"  + {country}/{slug:<22} | {src:<8} | {series_id}")
    print(f"\n{inserted} national-source rows promoted; eurostat counterparts demoted.")


if __name__ == "__main__":
    main()
