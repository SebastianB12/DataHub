"""Fix current-account-to-gdp empty data and any remaining issues."""
import requests
from datetime import date

from pipeline.db import supabase as sb, upsert_data_points, datapoints_to_rows
from pipeline.base_provider import DataPoint
from pipeline.transforms import normalize_date


def fix_ca_to_gdp():
    url = ("https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
           "bop_gdp6_q?format=JSON&geo=FR&freq=A&unit=PC_GDP&bop_item=CA"
           "&partner=WRL_REST&s_adj=NSA&stk_flow=BAL&lang=EN")
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    d = r.json()
    ts = d["dimension"]["time"]["category"]["index"]
    rev = {v: k for k, v in ts.items()}
    points = []
    for idx_s, val in d["value"].items():
        period = rev.get(int(idx_s))
        if not period:
            continue
        try:
            year = int(period)
        except ValueError:
            continue
        try:
            v = float(val)
        except (TypeError, ValueError):
            continue
        dt = date(year, 1, 1)
        points.append(DataPoint(
            indicator="current-account-to-gdp",
            country="FR",
            date=normalize_date(dt, "A"),
            value=round(v, 6),
            source="eurostat",
            unit="%",
            series_id="bop_gdp6_q:CA:PC_GDP:WRL_REST",
            adjustment="NSA",
        ))

    # update series_id
    sb.table("indicator_sources").update({
        "series_id": "bop_gdp6_q:CA:PC_GDP:WRL_REST",
        "freq_hint": "A",
        "note": "Eurostat bop_gdp6_q Current Account % of GDP, WRL_REST partner, NSA, annual (TE primary).",
    }).eq("country", "FR").eq("indicator", "current-account-to-gdp").eq("source", "eurostat").eq("is_default", True).execute()

    sb.table("data_points").delete().eq("country", "FR").eq(
        "indicator", "current-account-to-gdp").execute()
    n = upsert_data_points(datapoints_to_rows(points))
    print(f"current-account-to-gdp: upserted {n} points")


def fix_employment_rate_quarterly():
    """TE shows 69.5 Q1 2026 quarterly INSEE.
    INSEE has CHOMAGE-TRIM-NATIONAL with TX_EMPLOI? Let's check.
    Existing default uses Melodi DD_EEC_ANNUEL which is annual.
    """
    from pynsee.macrodata import get_series_list, get_series
    sl = get_series_list("CHOMAGE-TRIM-NATIONAL")
    cols = sl.columns.tolist()
    print("CHOMAGE-TRIM-NATIONAL cols:", cols)
    inds = sl["INDICATEUR"].unique() if "INDICATEUR" in cols else []
    print("INDICATEUR uniq:", inds[:30])
    # CTTEC or CTEC = taux d'emploi?
    m = sl[(sl["FREQ"]=="T") & (sl["REF_AREA"]=="FM") & (sl["SEXE"]=="0") & (sl["AGE"]=="15-64") & (sl["UNIT_MEASURE"]=="POURCENT") & (sl["INDICATEUR"].str.startswith("CTTEC"))]
    print("CTTEC matches:")
    print(m[["IDBANK","INDICATEUR","NATURE","CORRECTION","INDICATEUR_label_en"]].to_string() if len(m) else "none")


if __name__ == "__main__":
    import sys
    which = sys.argv[1] if len(sys.argv) > 1 else "ca_gdp"
    if which == "ca_gdp":
        fix_ca_to_gdp()
    elif which == "emp_rate_discover":
        fix_employment_rate_quarterly()
