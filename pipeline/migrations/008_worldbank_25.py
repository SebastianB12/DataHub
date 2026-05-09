"""Add World Bank annual indicators for all 25 new EU countries."""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb

NEW_COUNTRIES = ["AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "GR",
                 "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT",
                 "RO", "SK", "SI", "ES", "SE"]

# WB indicators using FR as template
TEMPLATE_COUNTRY = "FR"

r = sb.table("indicator_sources").select("*").eq("source", "worldbank").eq("country", TEMPLATE_COUNTRY).execute()
templates = r.data
print(f"Templates from FR: {len(templates)}")

# population is in Eurostat already (AVIA_PA_FA_TOT or demo_pjan). For WB we replicate too — TE for many EU countries shows World Bank for population.
# Let's add all 4 WB indicators per country.

rows_to_insert = []
for c in NEW_COUNTRIES:
    for t in templates:
        # population: WB has it but Eurostat is also default. We'll add as second source
        # so user can pick. For other 3 (gdp, gdp-per-capita, gdp-per-capita-ppp), WB is primary.
        is_default = True
        if t["indicator"] == "population":
            # Keep Eurostat as default for EU countries (TE typically shows World Bank
            # for non-EU, Eurostat for EU). We'll add WB as alternative source.
            is_default = False
        rows_to_insert.append({
            "indicator": t["indicator"],
            "country": c,
            "source": "worldbank",
            "series_id": t["series_id"],
            "is_default": is_default,
            "transform": t["transform"],
            "conversion": t["conversion"],
            "unit": t["unit"],
            "adjustment": t["adjustment"],
            "freq_hint": t["freq_hint"],
            "extra_params": t["extra_params"],
            "active": True,
        })

# Delete existing WB rows for these countries first
for c in NEW_COUNTRIES:
    for t in templates:
        sb.table("indicator_sources").delete().eq("indicator", t["indicator"]).eq("country", c).eq("source", "worldbank").execute()

res = sb.table("indicator_sources").insert(rows_to_insert).execute()
print(f"Inserted {len(res.data)} WorldBank rows")
