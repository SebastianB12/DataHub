"""Apply FR batch1 fixes: current-account → BdF, cpi-food → INSEE."""
import subprocess
from datetime import date
import requests

from pipeline.db import supabase as sb, upsert_data_points, datapoints_to_rows
from pipeline.base_provider import DataPoint
from pipeline.transforms import normalize_date


def parse_month(s):
    y, m = s.split("-")
    return date(int(y), int(m), 1)


def fix_current_account():
    """Switch FR current-account from eurostat → bdf via DBnomics BDF/BPM6
    monthly seasonally adjusted balance.
    """
    series_code = "M.S.FR.W1.S1.S1.T.B.CA._Z._Z._Z.EUR._T._X.N.ALL"
    url = f"https://api.db.nomics.world/v22/series/BDF/BPM6/{series_code}?observations=1"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    docs = r.json()["series"]["docs"]
    if not docs:
        raise RuntimeError("BDF current-account series empty")
    s = docs[0]
    points = []
    for p, v in zip(s["period"], s["value"]):
        if v is None:
            continue
        try:
            val = float(v) / 1000.0  # EUR Mil -> EUR Bil
        except (TypeError, ValueError):
            continue
        dt = parse_month(p)
        points.append(DataPoint(
            indicator="current-account",
            country="FR",
            date=normalize_date(dt, "M"),
            value=round(val, 6),
            source="bdf",
            unit="EUR Billion",
            series_id=f"BPM6:{series_code}",
            adjustment="SA",
        ))

    # Update indicator_sources: bdf → default, eurostat → not default
    sb.table("indicator_sources").update({"is_default": False}).eq(
        "country", "FR").eq("indicator", "current-account").eq("source", "eurostat").execute()

    # Upsert bdf row (or insert)
    existing = sb.table("indicator_sources").select("*").eq("country", "FR").eq(
        "indicator", "current-account").eq("source", "bdf").execute().data
    payload = {
        "country": "FR",
        "indicator": "current-account",
        "source": "bdf",
        "series_id": f"BPM6:{series_code}",
        "is_default": True,
        "active": True,
        "freq_hint": "M",
        "unit": "EUR Billion",
        "conversion": 0.001,
        "adjustment": "SA",
        "note": "Banque de France BPM6 Current Account Total Economy Balance, monthly seasonally-adjusted (TE primary).",
    }
    if existing:
        sb.table("indicator_sources").update(payload).eq("country", "FR").eq(
            "indicator", "current-account").eq("source", "bdf").execute()
    else:
        sb.table("indicator_sources").insert(payload).execute()

    # Delete old eurostat datapoints; we keep eurostat row as fallback but switch the public data
    sb.table("data_points").delete().eq("country", "FR").eq(
        "indicator", "current-account").eq("source", "eurostat").execute()

    n = upsert_data_points(datapoints_to_rows(points))
    print(f"current-account: upserted {n} BDF points")


def fix_cpi_food():
    """Switch FR cpi-food from eurostat HICP → INSEE IPC-2025 COICOP 01.
    Same as food-inflation series but mapped to cpi-food slug.
    """
    # We re-use INSEE COICOP01 — series IDBANK 011814667 (FORME_VENTE=SO, FREQ=M)
    from pynsee.macrodata import get_series
    df = get_series(["011814667"]).dropna(subset=["OBS_VALUE"])
    points = []
    for _, row in df.iterrows():
        p = row["TIME_PERIOD"]
        try:
            y, m = p.split("-")
            dt = date(int(y), int(m), 1)
        except Exception:
            continue
        try:
            v = float(row["OBS_VALUE"])
        except (TypeError, ValueError):
            continue
        points.append(DataPoint(
            indicator="cpi-food",
            country="FR",
            date=normalize_date(dt, "M"),
            value=round(v, 6),
            source="insee",
            unit="Index",
            series_id="IPC-2025:011814667",
            adjustment="NSA",
        ))

    sb.table("indicator_sources").update({"is_default": False}).eq(
        "country", "FR").eq("indicator", "cpi-food").eq("source", "eurostat").execute()
    existing = sb.table("indicator_sources").select("*").eq("country", "FR").eq(
        "indicator", "cpi-food").eq("source", "insee").execute().data
    payload = {
        "country": "FR",
        "indicator": "cpi-food",
        "source": "insee",
        "series_id": "IPC-2025:011814667",
        "is_default": True,
        "active": True,
        "freq_hint": "M",
        "unit": "Index",
        "conversion": 1.0,
        "adjustment": "NSA",
        "note": "INSEE IPC-2025 COICOP 01 Food & non-alcoholic beverages (TE primary).",
    }
    if existing:
        sb.table("indicator_sources").update(payload).eq("country", "FR").eq(
            "indicator", "cpi-food").eq("source", "insee").execute()
    else:
        sb.table("indicator_sources").insert(payload).execute()

    sb.table("data_points").delete().eq("country", "FR").eq(
        "indicator", "cpi-food").eq("source", "eurostat").execute()
    n = upsert_data_points(datapoints_to_rows(points))
    print(f"cpi-food: upserted {n} INSEE points")


def fix_employed_persons_to_eurostat_y15_64():
    """TE shows 28177 Q4 2025 = LFS Y15-64 not Y20-64.
    Switch eurostat default from Y20-64 → Y15-64.
    """
    # Re-fetch from Eurostat directly
    url = "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/lfsi_emp_q/Q.PC.Y15-64.EMP_LFS.T.FR?format=JSON"
    # Try quarterly LFS dataset
    r = requests.get(url, timeout=60)
    if r.status_code != 200:
        print(f"FAIL eurostat lfsi_emp_q: {r.status_code}")
        return
    data = r.json()
    # Eurostat JSON structure: dimension/values
    dims = data.get("dimension", {})
    obs = data.get("value", {})
    if not obs:
        print("FAIL eurostat lfsi_emp_q: no obs")
        return
    print(f"eurostat fetched {len(obs)} obs")
    # Get time dim
    time_idx = dims["time"]["category"]["index"]
    # Index map: position → date
    rev = {v: k for k, v in time_idx.items()}
    # Each value is at a flat index = product of dim sizes / map by id sequence
    # Simpler: assume only varying dim is time (filtered on others)
    points = []
    for idx_str, val in obs.items():
        idx = int(idx_str)
        period = rev.get(idx)
        if period is None:
            continue
        # period like "2024-Q1" or "2024Q1"
        s = period.replace("-Q", "Q")
        try:
            y, q = s.split("Q")
            month = {"1": 1, "2": 4, "3": 7, "4": 10}[q]
            dt = date(int(y), month, 1)
        except Exception:
            continue
        try:
            v = float(val)
        except (TypeError, ValueError):
            continue
        points.append(DataPoint(
            indicator="employed-persons",
            country="FR",
            date=normalize_date(dt, "Q"),
            value=round(v / 100.0 * 0 + v, 6),  # passthrough
            source="eurostat",
            unit="Thousand",
            series_id="lfsi_emp_q:EMP_LFS:Y15-64",
            adjustment="NSA",
        ))

    # Filter unit "PC" -> we want "THS" thousand persons
    points = []  # discard above
    url2 = "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/lfsq_egan/Q.THS.T.Y15-64.FR?format=JSON"
    r = requests.get(url2, timeout=60)
    if r.status_code != 200:
        print(f"FAIL eurostat lfsq_egan: {r.status_code}")
        # Try alternative dataset
        url3 = "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/lfsi_emp_q/Q.THS_PER.Y15-64.EMP_LFS.T.FR?format=JSON"
        r = requests.get(url3, timeout=60)
        if r.status_code != 200:
            print(f"FAIL eurostat lfsi_emp_q v2: {r.status_code}")
            return
    data = r.json()
    dims = data.get("dimension", {})
    obs = data.get("value", {})
    time_idx = dims["time"]["category"]["index"]
    rev = {v: k for k, v in time_idx.items()}
    for idx_str, val in obs.items():
        idx = int(idx_str)
        period = rev.get(idx)
        if period is None:
            continue
        s = period.replace("-Q", "Q")
        try:
            y, q = s.split("Q")
            month = {"1": 1, "2": 4, "3": 7, "4": 10}[q]
            dt = date(int(y), month, 1)
        except Exception:
            continue
        try:
            v = float(val)
        except (TypeError, ValueError):
            continue
        points.append(DataPoint(
            indicator="employed-persons",
            country="FR",
            date=normalize_date(dt, "Q"),
            value=round(v, 6),
            source="eurostat",
            unit="Thousand",
            series_id="lfsi_emp_q:THS_PER:Y15-64",
            adjustment="NSA",
        ))

    if not points:
        print("FAIL employed-persons: no points")
        return

    # update default sid
    sb.table("indicator_sources").update({
        "series_id": "lfsi_emp_q:THS_PER:Y15-64",
        "freq_hint": "Q",
        "note": "Eurostat lfsi_emp_q THS_PER total Y15-64 quarterly (TE primary).",
    }).eq("country", "FR").eq("indicator", "employed-persons").eq("source", "eurostat").execute()

    # Delete old eurostat points
    sb.table("data_points").delete().eq("country", "FR").eq(
        "indicator", "employed-persons").eq("source", "eurostat").execute()

    n = upsert_data_points(datapoints_to_rows(points))
    print(f"employed-persons: upserted {n} eurostat Y15-64 points")


if __name__ == "__main__":
    import sys
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which in ("all", "ca"):
        fix_current_account()
    if which in ("all", "cpi-food"):
        fix_cpi_food()
    if which in ("all", "emp"):
        fix_employed_persons_to_eurostat_y15_64()
