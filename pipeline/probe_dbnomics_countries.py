"""Probe DBnomics for fresh data for each major EU country's primary indicators.

Goal: for each country, find DBnomics paths that return Apr/Mar 2026 data
matching what TE shows. Output a JSON mapping that becomes the seed for
indicator_sources.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
import requests
import json
import time

API = "https://api.db.nomics.world/v22"

def latest(provider: str, dataset: str, series: str) -> tuple[str, float]:
    try:
        r = requests.get(f"{API}/series/{provider}/{dataset}/{series}?observations=1", timeout=30)
        r.raise_for_status()
        s = r.json().get("series", {}).get("docs", [{}])[0]
        periods = s.get("period", [])
        values = s.get("value", [])
        if not periods or not values:
            return None, None
        return periods[-1], values[-1]
    except Exception as e:
        return None, str(e)

# Per country: (slug, dbnomics_provider, dataset_id, series_key, expected_freq)
PROBES = {
    "IT": [  # ISTAT
        ("industrial-production", "ISTAT", "115_333_DF_DCSC_INDXPRODIND_1_6", "M.IT.IND_PROD_21.N.0020", "M"),
        ("ppi",                   "ISTAT", "145_360_DF_DCSC_PREZZPIND_1_4",  None, "M"),
        ("retail-sales",          "ISTAT", "120_337_DF_DCSC_COMMDET_1_15",   None, "M"),
        ("inflation-cpi",         "ISTAT", "167_744_DF_DCSP_NIC1B2015_1",    None, "M"),
    ],
    "PT": [  # INEPT
        ("inflation-cpi",         "INEPT", "ipc-cap1-todos",                  None, "M"),
        ("unemployment",          "INEPT", "ie",                              None, "M"),
    ],
    "IE": [  # CSO
        ("inflation-cpi",         "CSO",   "CPM01",                           None, "M"),
        ("unemployment",          "CSO",   "MUM01",                           None, "M"),
    ],
    "BE": [  # NBB
        ("interest-rate",         "NBB",   None,                              None, "M"),
    ],
    "GR": [  # ELSTAT
        ("inflation-cpi",         "ELSTAT", None,                             None, "M"),
    ],
    "SE": [  # SCB
        ("inflation-cpi",         "SCB",   "PR0101A_KPI2020M",                None, "M"),
    ],
    "PL": [  # STATPOL
        ("inflation-cpi",         "STATPOL", None,                            None, "M"),
        ("unemployment",          "STATPOL", None,                            None, "M"),
    ],
}

def list_datasets(provider: str, kw: str) -> list[str]:
    r = requests.get(f"{API}/datasets/{provider}?limit=500", timeout=60)
    docs = r.json().get("datasets", {}).get("docs", [])
    return [(d["code"], d["name"]) for d in docs if kw.lower() in (d.get("name") or "").lower()]


for country, items in PROBES.items():
    print(f"\n========== {country} ==========")
    for slug, provider, dataset, series, freq in items:
        if not series:
            print(f"  {slug}: dataset={dataset} (need series probe)")
            if dataset:
                # Get first 2 series in dataset
                try:
                    r = requests.get(f"{API}/series/{provider}/{dataset}?limit=3", timeout=30)
                    docs = r.json().get("series", {}).get("docs", [])
                    for s in docs:
                        print(f"    candidate: {s['series_code']} | {s['series_name'][:80]}")
                except Exception as e:
                    print(f"    ERR: {e}")
        else:
            p, v = latest(provider, dataset, series)
            print(f"  {slug}: {dataset}/{series} → latest {p} = {v}")
        time.sleep(0.3)
