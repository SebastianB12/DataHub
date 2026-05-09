"""Bulk-clone Eurostat indicator_sources rows to all 25 new EU countries.

Strategy:
- Take FR Eurostat rows as template (FR has most coverage: 35+ slugs).
- For slugs only in EA (consumer-confidence, business-confidence, services-sentiment),
  take EA row as template.
- Skip slugs only in GB (e.g. UK-specific Eurostat aggregates).
- For each (indicator, dataset+params) clone for all 25 new countries with is_default=true.
- series_id is country-agnostic ('dataset:filter'), so direct copy is safe.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb

NEW_COUNTRIES = ["AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "GR",
                 "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT",
                 "RO", "SK", "SI", "ES", "SE"]

# Slugs whose templates only exist in EA (need EA-row clone)
EA_ONLY_TEMPLATES = ["consumer-confidence", "business-confidence", "services-sentiment"]

def get_template_row(indicator: str, template_country: str):
    r = (sb.table("indicator_sources")
         .select("*")
         .eq("source", "eurostat")
         .eq("indicator", indicator)
         .eq("country", template_country)
         .eq("active", True)
         .limit(1).execute())
    return r.data[0] if r.data else None

def main():
    # Get all distinct active eurostat indicators
    r = (sb.table("indicator_sources")
         .select("indicator,country")
         .eq("source", "eurostat")
         .eq("active", True).execute())

    by_ind = {}
    for row in r.data:
        by_ind.setdefault(row["indicator"], set()).add(row["country"])

    total_inserts = 0
    skipped = []
    for indicator, existing_countries in sorted(by_ind.items()):
        # Pick template country
        if "FR" in existing_countries:
            template_country = "FR"
        elif "EA" in existing_countries:
            template_country = "EA"
        elif "DE" in existing_countries:
            template_country = "DE"
        else:
            skipped.append((indicator, "no template (no FR/EA/DE row)"))
            continue

        template = get_template_row(indicator, template_country)
        if not template:
            skipped.append((indicator, f"template country {template_country} returned no row"))
            continue

        rows_to_insert = []
        for country in NEW_COUNTRIES:
            if country in existing_countries:
                continue
            new_row = {
                "indicator": indicator,
                "country": country,
                "source": "eurostat",
                "series_id": template["series_id"],
                "is_default": True,
                "transform": template.get("transform") or "raw",
                "conversion": template.get("conversion") or 1.0,
                "unit": template.get("unit"),
                "adjustment": template.get("adjustment"),
                "freq_hint": template.get("freq_hint"),
                "extra_params": template.get("extra_params"),
                "active": True,
            }
            rows_to_insert.append(new_row)

        if rows_to_insert:
            # Plain insert; skip rows that already exist (handled per-row)
            inserted_count = 0
            for row in rows_to_insert:
                # Delete any existing row first to avoid PK conflict
                sb.table("indicator_sources").delete().eq(
                    "indicator", row["indicator"]
                ).eq("country", row["country"]).eq("source", "eurostat").execute()
            res = sb.table("indicator_sources").insert(rows_to_insert).execute()
            inserted_count = len(res.data)
            total_inserts += inserted_count
            print(f"  {indicator:36s} (template={template_country}): +{inserted_count} rows")

    print(f"\nTotal new rows: {total_inserts}")
    if skipped:
        print("\nSkipped:")
        for ind, why in skipped:
            print(f"  {ind}: {why}")

if __name__ == "__main__":
    main()
