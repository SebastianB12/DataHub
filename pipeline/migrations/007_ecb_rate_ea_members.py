"""Add ECB Main Refinancing Rate as is_default=true for all Euro Area members."""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb

# All 20 Euro Area members (excluding DE/FR/EA which already exist)
EA_MEMBERS = ["AT", "BE", "CY", "EE", "FI", "GR", "IE", "IT", "LV", "LT",
              "LU", "MT", "NL", "PT", "SK", "SI", "ES", "HR"]
# HR (Croatia) joined EA on 2023-01-01

template_country = "FR"
r = sb.table("indicator_sources").select("*").eq("source", "ecb").eq("indicator", "interest-rate").eq("country", template_country).execute()
template = r.data[0]

rows = []
for c in EA_MEMBERS:
    rows.append({
        "indicator": "interest-rate",
        "country": c,
        "source": "ecb",
        "series_id": template["series_id"],
        "is_default": True,
        "transform": template["transform"],
        "conversion": template["conversion"],
        "unit": template["unit"],
        "adjustment": template["adjustment"],
        "freq_hint": template["freq_hint"],
        "extra_params": template["extra_params"],
        "active": True,
        "note": f"ECB Main Refinancing Rate (Fixed). {c} is in EA, shares ECB rate.",
    })

# Delete existing first
for c in EA_MEMBERS:
    sb.table("indicator_sources").delete().eq("indicator", "interest-rate").eq("country", c).eq("source", "ecb").execute()

res = sb.table("indicator_sources").insert(rows).execute()
print(f"Inserted {len(res.data)} ECB interest-rate rows for EA members")
