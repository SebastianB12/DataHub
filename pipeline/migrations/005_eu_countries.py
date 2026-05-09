"""Insert 25 EU countries (all EU-27 except DE/FR which already exist)."""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from pipeline.db import supabase as sb

EU_COUNTRIES = [
    ("AT", "Austria",       "Österreich",        "🇦🇹"),
    ("BE", "Belgium",       "Belgien",           "🇧🇪"),
    ("BG", "Bulgaria",      "Bulgarien",         "🇧🇬"),
    ("HR", "Croatia",       "Kroatien",          "🇭🇷"),
    ("CY", "Cyprus",        "Zypern",            "🇨🇾"),
    ("CZ", "Czech Republic","Tschechien",        "🇨🇿"),
    ("DK", "Denmark",       "Dänemark",          "🇩🇰"),
    ("EE", "Estonia",       "Estland",           "🇪🇪"),
    ("FI", "Finland",       "Finnland",          "🇫🇮"),
    ("GR", "Greece",        "Griechenland",      "🇬🇷"),
    ("HU", "Hungary",       "Ungarn",            "🇭🇺"),
    ("IE", "Ireland",       "Irland",            "🇮🇪"),
    ("IT", "Italy",         "Italien",           "🇮🇹"),
    ("LV", "Latvia",        "Lettland",          "🇱🇻"),
    ("LT", "Lithuania",     "Litauen",           "🇱🇹"),
    ("LU", "Luxembourg",    "Luxemburg",         "🇱🇺"),
    ("MT", "Malta",         "Malta",             "🇲🇹"),
    ("NL", "Netherlands",   "Niederlande",       "🇳🇱"),
    ("PL", "Poland",        "Polen",             "🇵🇱"),
    ("PT", "Portugal",      "Portugal",          "🇵🇹"),
    ("RO", "Romania",       "Rumänien",          "🇷🇴"),
    ("SK", "Slovakia",      "Slowakei",          "🇸🇰"),
    ("SI", "Slovenia",      "Slowenien",         "🇸🇮"),
    ("ES", "Spain",         "Spanien",           "🇪🇸"),
    ("SE", "Sweden",        "Schweden",          "🇸🇪"),
]

rows = [
    {"code": code, "name": name, "name_de": name_de, "region": "Europe", "flag_emoji": flag}
    for code, name, name_de, flag in EU_COUNTRIES
]

result = sb.table("countries").upsert(rows, on_conflict="code").execute()
print(f"Upserted {len(result.data)} country rows")
existing = sb.table("countries").select("code,name").order("code").execute()
print(f"\nAll countries now in DB ({len(existing.data)}):")
for r in existing.data:
    print(f"  {r['code']}: {r['name']}")
