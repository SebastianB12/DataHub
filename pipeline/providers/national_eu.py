"""Direct national stat-office provider for EU countries.

For each country, we hit the OFFICIAL primary source's API directly (not via
DBnomics/Eurostat). Source labels match what TE shows.

Currently supported (verified reachable from this network as of 2026-05-09):
  DK — Statistics Denmark / Statbank API (api.statbank.dk)
  FI — Statistics Finland / Tilastokeskus PxWeb (pxdata.stat.fi)
  PL — GUS / BDL API (bdl.stat.gov.pl)
  SE — Statistics Sweden / SCB PxWeb (api.scb.se)
  PT — INE Portugal JSON-Indicador API (www.ine.pt)
  IE — CSO Ireland PxStat REST (ws.cso.ie)
  BE — Statbel REST API (bestat.statbel.fgov.be)

Network-blocked from this environment (deferred):
  NL — datasets.cbs.nl Connection Timeout
  CZ — apl.czso.cz HTML only (no JSON API)
  HU — statinfo.ksh.hu HTML only
  AT — Statistik Austria endpoint discovery pending
  GR — ELSTAT static-files only
  RO — INSSE Tempo SSL handshake fails
"""
import os
import time
from datetime import date

import requests
from dotenv import load_dotenv

from pipeline.base_provider import BaseProvider, DataPoint
from pipeline.transforms import normalize_date
from pipeline.db import upsert_data_points, log_pipeline_run, datapoints_to_rows

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))


def _parse_period(p: str, freq: str) -> date | None:
    try:
        if freq == "M":
            if "M" in p:
                yy, mm = p.split("M")
                return date(int(yy), int(mm), 1)
            if "-" in p and len(p) == 7:
                yy, mm = p.split("-")
                return date(int(yy), int(mm), 1)
        if freq == "Q":
            if "K" in p:  # Danish Kvartal
                yy, q = p.split("K")
                return date(int(yy), {"1":1,"2":4,"3":7,"4":10}[q], 1)
            if "Q" in p:
                yy, q = p.split("Q")
                return date(int(yy), {"1":1,"2":4,"3":7,"4":10}[q], 1)
        if freq == "A" and len(p) == 4:
            return date(int(p), 1, 1)
    except Exception:
        return None
    return None


# === Denmark — Statbank API ===

DK_SERIES = [
    # PRIS01: Consumer price index by commodity group, unit, time
    # VAREGR=000000 (total), ENHED=100 (Index), monthly
    {"slug": "inflation-cpi", "table": "PRIS01",
     "filters": {"VAREGR": "000000", "ENHED": "100"},
     "freq": "M", "unit": "Index", "adjustment": "NSA", "conversion": 1.0,
     "note": "DK Statbank PRIS01 CPI total all-items index"},
    # IPOP21: Industrial production index — total industry C, non-seasonal
    {"slug": "industrial-production", "table": "IPOP21",
     "filters": {"SÆSON": "SÆSON", "BRANCHEDB25UDVALG": "C"},
     "freq": "M", "unit": "Index", "adjustment": "SA", "conversion": 1.0,
     "note": "DK Statbank IPOP21 IP index total manufacturing SA"},
    # AUP01: Unemployment % of labour force — All Denmark, total age, total sex
    {"slug": "unemployment", "table": "AUP01",
     "filters": {"OMRÅDE": "000", "KØN": "TOT", "ALDER": "TOT"},
     "freq": "M", "unit": "%", "adjustment": "SA", "conversion": 1.0,
     "note": "DK Statbank AUP01 unemployment rate (all DK, both genders, all ages)"},
    # DETA211A: Retail Trade Index — total retail trade
    {"slug": "retail-sales", "table": "DETA211A",
     "filters": {"BRANCHEDB25UDVALG": "G47"},
     "freq": "M", "unit": "Index", "adjustment": "NSA", "conversion": 1.0,
     "note": "DK Statbank DETA211A Retail Trade total G47"},
]


def fetch_dk_table(table: str, filters: dict, freq: str = "M") -> list[tuple[date, float]]:
    """Statbank.dk JSON-stat data API. Tid=* fetches the full time series."""
    variables = [{"code": k, "values": [v]} for k, v in filters.items()]
    variables.append({"code": "Tid", "values": ["*"]})
    payload = {
        "table": table,
        "format": "JSONSTAT",
        "valuePresentation": "Default",
        "lang": "en",
        "variables": variables,
    }
    r = requests.post("https://api.statbank.dk/v1/data", json=payload, timeout=30)
    r.raise_for_status()
    js = r.json()
    # JSON-stat structure: dataset.value (array), dataset.dimension.<id>.category.label/index
    ds = js.get("dataset", js)
    values = ds.get("value", [])
    dim = ds.get("dimension", {})
    # Find time dimension (last in 'id' usually)
    tid_dim = "Tid" if "Tid" in dim else next((k for k in dim if "time" in k.lower() or "Tid" in k), None)
    if not tid_dim:
        return []
    tid_cat = dim[tid_dim].get("category", {})
    idx_map = tid_cat.get("index", {})
    label_map = tid_cat.get("label", {})
    if not idx_map:
        return []
    # values are 1-D when only one combo
    out = []
    for code, idx in idx_map.items():
        if idx >= len(values):
            continue
        v = values[idx]
        if v is None:
            continue
        dt = _parse_period(code, freq)
        if dt is None:
            continue
        out.append((dt, float(v)))
    return sorted(out)


# === Finland — Tilastokeskus PxWeb ===

FI_SERIES = [
    # statfin_khi_pxt_15b5.px: CPI (2025=100) monthly — Hyödyke=SSS (Total), Tiedot=ip_khi (Index)
    {"slug": "inflation-cpi", "path": "StatFin/khi/statfin_khi_pxt_15b5.px",
     "query": {"Hyödyke": "SSS", "Tiedot": "ip_khi"},
     "freq": "M", "unit": "Index", "adjustment": "NSA", "conversion": 1.0,
     "note": "FI Tilastokeskus 15b5 CPI 2025=100 total monthly"},
]


def fetch_fi_table(path: str, query_filters: dict, freq: str = "M") -> list[tuple[date, float]]:
    url = f"https://pxdata.stat.fi/PxWeb/api/v1/en/{path}"
    body = {
        "query": [{"code": k, "selection": {"filter": "item", "values": [v]}}
                  for k, v in query_filters.items()],
        "response": {"format": "json-stat2"},
    }
    r = requests.post(url, json=body, timeout=30)
    r.raise_for_status()
    return _parse_jsonstat(r.json(), freq)


# === Sweden — SCB PxWeb ===

SE_SERIES = [
    # PR/PR0101/PR0101A/KPI2020M: CPI by ContentsCode, monthly
    # Using shadow/fixed numbers — specific COD via probing
    # 00000807 = CPI shadow index (continuous index)
    {"slug": "inflation-cpi", "path": "PR/PR0101/PR0101A/KPI2020M",
     "query": {"ContentsCode": "00000807"},
     "freq": "M", "unit": "Index", "adjustment": "NSA", "conversion": 1.0,
     "note": "SE SCB CPI shadow index (continuous 1980=100)"},
]


def fetch_se_table(path: str, query_filters: dict, freq: str = "M") -> list[tuple[date, float]]:
    url = f"https://api.scb.se/OV0104/v1/doris/en/ssd/{path}"
    body = {
        "query": [{"code": k, "selection": {"filter": "item", "values": [v]}}
                  for k, v in query_filters.items()],
        "response": {"format": "json-stat2"},
    }
    r = requests.post(url, json=body, timeout=30)
    r.raise_for_status()
    return _parse_jsonstat(r.json(), freq)


# === Portugal — INE PT JSON-Indicador ===

PT_SERIES = [
    # IPC base 2025 (varcd 0008273 = total) — TE shows Apr 2026 = 0.4%
    # Use op=2 to get latest period as JSON
    {"slug": "inflation-cpi", "varcd": "0008273", "freq": "M",
     "unit": "Index", "adjustment": "NSA", "conversion": 1.0,
     "note": "PT INE IPC total nacional"},
]


def fetch_pt_indicator(varcd: str, freq: str = "M") -> list[tuple[date, float]]:
    """INE Portugal JSON-Indicador, last 60 obs."""
    url = f"https://www.ine.pt/ine/json_indicador/pindica.jsp?op=2&varcd={varcd}&lang=EN"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    js = r.json()
    # Structure: list of {"Sucesso": [...]} with Dados under nested keys
    out = []
    for entry in js:
        sucesso = entry.get("Sucesso", {})
        if isinstance(sucesso, dict):
            verd = sucesso.get("Verdadeiro", [])
        else:
            verd = sucesso
        for item in verd if isinstance(verd, list) else []:
            dados = item.get("Dados", {})
            if isinstance(dados, dict):
                for period_key, obs_list in dados.items():
                    if not isinstance(obs_list, list):
                        continue
                    for obs in obs_list:
                        val_str = obs.get("valor")
                        try:
                            val = float(val_str)
                        except (ValueError, TypeError):
                            continue
                        # period_key like "2026M04" or "S7A2024"
                        per = period_key.replace("S7A", "")
                        dt = _parse_period(per, freq)
                        if dt:
                            out.append((dt, val))
    return sorted(out)


# === Ireland — CSO PxStat ===

IE_SERIES = [
    # CPM01: STATISTIC=CPM01C08 (Base Dec 2023=100, latest base), C01779V03424=- (All items)
    {"slug": "inflation-cpi", "table": "CPM01",
     "filters": {"STATISTIC": "CPM01C08", "C01779V03424": "-"},
     "freq": "M", "unit": "Index", "adjustment": "NSA", "conversion": 1.0,
     "note": "CSO Ireland CPM01 CPI Base Dec 2023=100, all items"},
]


def fetch_ie_table(table: str, filters: dict, freq: str = "M") -> list[tuple[date, float]]:
    """CSO PxStat ReadDataset (JSON-stat 2.0). category.index can be list or dict."""
    url = f"https://ws.cso.ie/public/api.restful/PxStat.Data.Cube_API.ReadDataset/{table}/JSON-stat/2.0/en"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    js = r.json()
    values = js.get("value", [])
    dim = js.get("dimension", {})
    dim_ids = js.get("id", [])
    dim_sizes = js.get("size", [])
    if not dim_ids:
        return []

    # Find time dimension by name
    tid = next((k for k in dim_ids if k.startswith("TLIST") or "TIME" in k.upper()), None)
    if not tid:
        return []

    def get_index_dict(name):
        cat = dim.get(name, {}).get("category", {})
        idx = cat.get("index", {})
        if isinstance(idx, list):
            return {code: pos for pos, code in enumerate(idx)}
        return idx  # dict

    time_idx_dict = get_index_dict(tid)
    if not time_idx_dict:
        return []

    # Resolve filter target indices
    target_idx = {}
    for k in dim_ids:
        if k == tid:
            continue
        wanted = filters.get(k)
        if wanted is None:
            target_idx[k] = 0
            continue
        if isinstance(wanted, list):
            wanted = wanted[0] if wanted else None
        idx_dict = get_index_dict(k)
        if wanted in idx_dict:
            target_idx[k] = idx_dict[wanted]
        else:
            target_idx[k] = 0

    out = []
    for time_code, time_pos in time_idx_dict.items():
        indices = []
        for k in dim_ids:
            indices.append(time_pos if k == tid else target_idx.get(k, 0))
        flat = 0
        stride = 1
        for i in range(len(dim_ids) - 1, -1, -1):
            flat += indices[i] * stride
            stride *= dim_sizes[i]
        if 0 <= flat < len(values):
            v = values[flat]
            if v is not None:
                dt = _parse_ie_time(time_code, freq)
                if dt:
                    out.append((dt, float(v)))
    return sorted(out)


def _parse_ie_time(p: str, freq: str) -> date | None:
    """CSO time codes: '202604' (YYYYMM), '2026Q1' (YYYYQ#)."""
    try:
        if freq == "M" and len(p) == 6 and p.isdigit():
            return date(int(p[:4]), int(p[4:]), 1)
    except Exception:
        pass
    return _parse_period(p, freq)


# === Belgium — Statbel REST API (CSV) ===
# Statbel uses unique view IDs per dataset. We pre-resolve them.
# bestat.statbel.fgov.be/bestat/api/views?lang=en&format=json gives the list.
# For inflation: search "consumer price index" — view ID encoded.

BE_SERIES = [
    # Statbel API via bestat.statbel.fgov.be — view ID for "Consumer price index,
    # inflation, health index..." monthly. Gives ~13 months history.
    {"slug": "inflation-cpi", "view_id": "208b69bd-05c5-4947-b7f9-2d2300f517b8",
     "value_col": "Consumer price index",
     "freq": "M", "unit": "Index (2013=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "Statbel CPI base 2013=100, last 13 months"},
]


def fetch_be_statbel_csv(view_id: str, value_col: str, freq: str = "M") -> list[tuple[date, float]]:
    """Statbel publishes views as CSV. Year/Month columns + named value cols."""
    import csv as csvm, io as iom
    url = f"https://bestat.statbel.fgov.be/bestat/api/views/{view_id}/result/CSV"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    reader = csvm.DictReader(iom.StringIO(r.text))
    out = []
    months_map = {"January":1,"February":2,"March":3,"April":4,"May":5,"June":6,
                  "July":7,"August":8,"September":9,"October":10,"November":11,"December":12}
    for row in reader:
        month_text = row.get("Month", "")
        # "January 2025" -> 2025-01
        try:
            mname, ystr = month_text.rsplit(" ", 1)
            yy = int(ystr)
            mm = months_map[mname]
            dt = date(yy, mm, 1)
        except Exception:
            continue
        val_str = row.get(value_col, "").replace(",", "")
        try:
            val = float(val_str)
        except ValueError:
            continue
        out.append((dt, val))
    return sorted(out)


def fetch_nbb_sdmx(dataset: str, key: str, freq: str = "M") -> list[tuple[date, float]]:
    """NBB SDMX V21 endpoint."""
    url = f"https://stat.nbb.be/sdmx/V21/data/{dataset}/{key}"
    r = requests.get(url, headers={"Accept": "application/json"}, timeout=30)
    r.raise_for_status()
    js = r.json()
    # SDMX-JSON structure
    series = js.get("data", {}).get("dataSets", [{}])[0].get("series", {})
    out = []
    for ser_key, ser_data in series.items():
        observations = ser_data.get("observations", {})
        time_dim = js["data"]["structure"]["dimensions"]["observation"][0]["values"]
        for obs_idx_str, obs_value in observations.items():
            obs_idx = int(obs_idx_str)
            if obs_idx >= len(time_dim):
                continue
            period = time_dim[obs_idx]["id"]
            dt = _parse_period(period, freq)
            if dt and obs_value and obs_value[0] is not None:
                out.append((dt, float(obs_value[0])))
    return sorted(out)


# === Poland — GUS BDL API ===

PL_SERIES = [
    # GUS BDL: variable IDs need to be discovered.
    # Variable 217230 = CPI (poprzedni miesiąc=100) ; 217 ID family
    # We use direct BDL API: /api/v1/data/by-variable/<var_id>?unit-level=0&format=json
]


def fetch_gus_variable(var_id: int, freq: str = "M") -> list[tuple[date, float]]:
    """GUS BDL API — fetch all observations for a variable at national level (unit=000000000000)."""
    url = f"https://bdl.stat.gov.pl/api/v1/data/by-variable/{var_id}?unit-level=0&format=json&page-size=1000&lang=en"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    js = r.json()
    out = []
    for unit_obs in js.get("results", []):
        for v in unit_obs.get("values", []):
            year = v.get("year")
            attr = (v.get("year") or "")
            val = v.get("val")
            # GUS returns year as YYYY for annual, "YYYYMnn" for monthly
            # No standardised period — usually .year is for annual; need to inspect
            try:
                val = float(val)
            except Exception:
                continue
            if isinstance(year, int):
                dt = date(year, 1, 1) if freq == "A" else None
                if dt:
                    out.append((dt, val))
    return sorted(out)


# === Austria — Statistik Austria OGD (CSV semicolon-separated, German decimals) ===

AT_SERIES = [
    # vpi20 (base 2020) covers 2021-01 to 2025-12 monthly. F-VPIMZVM is the index level;
    # filter VPI5NEU = VPI-0 for all-items.
    {"slug": "inflation-cpi", "ogd": "OGD_vpi20_VPI_2020_1",
     "filter_col": "C-VPI5NEU-0", "filter_val": "VPI-0",
     "value_col": "F-VPIMZVM",
     "freq": "M", "unit": "Index", "adjustment": "NSA", "conversion": 1.0,
     "note": "Statistik Austria VPI base 2020=100 (covers 2021-01..2025-12)"},
    # vpi25 (base 2025) for 2026 onwards. We'll add it as a supplementary row that data_points
    # gets merged on (date, indicator, country, source) — but use a different source code so
    # rows don't conflict. Actually keep it simple — use vpi20 for now.
]


def fetch_at_csv(ogd: str, filter_col: str, filter_val: str, value_col: str, freq: str = "M") -> list[tuple[date, float]]:
    """Fetch Statistik Austria OGD CSV, filter and parse."""
    import csv as csvm
    import io as iom
    url = f"https://data.statistik.gv.at/data/{ogd}.csv"
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    reader = csvm.DictReader(iom.StringIO(r.text), delimiter=";")
    out = []
    for row in reader:
        if row.get(filter_col) != filter_val:
            continue
        time_code = row.get("C-VPIZR-0") or row.get("C-MZR-0") or row.get("C-ZR-0") or ""
        # VPIZR-202601 -> 2026-01 (monthly), VPIZR-2025 -> 2025 (annual; skip)
        if not time_code or "-" not in time_code:
            continue
        period = time_code.split("-")[1]
        if len(period) == 6 and period.isdigit():
            try:
                yy, mm = int(period[:4]), int(period[4:6])
                dt = date(yy, mm, 1)
            except Exception:
                continue
        else:
            # annual or unsupported - skip monthly-only fetcher
            continue
        val_str = row.get(value_col, "").replace(",", ".")
        try:
            val = float(val_str)
        except ValueError:
            continue
        if val == 0.0:  # placeholder for missing data in some rows
            continue
        out.append((dt, val))
    return sorted(out)


# === Slovenia — SURS PxWeb (pxweb.stat.si) ===

SI_SERIES = [
    # 0400608S CPI ECOICOP v2 — TOT = all-items, MERITVE=2 = Index (same month previous year)
    # Better: MERITVE=3 (Index month/Dec of previous year). For our use we want the LEVEL.
    # Use MERITVE=2 which is the most-cited YoY index format. Or MERITVE=1 for month-on-month.
    # The cleanest "level" doesn't exist directly — SI publishes only relatives.
    # Use MERITVE=2 (Index vs same month previous year) — TE shows YoY rate, this is the source.
    {"slug": "inflation-cpi", "table": "0400608S.px",
     "query": {"ŽIVLJENJSKA POTREBŠČINA": "TOT", "MERITVE": "2"},
     "freq": "M", "unit": "Index (same month py=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "SURS 0400608S CPI YoY index (same-month-previous-year=100), TOTAL"},
]


def fetch_si_pxweb(table: str, query_filters: dict, freq: str = "M") -> list[tuple[date, float]]:
    url = f"https://pxweb.stat.si/SiStatData/api/v1/en/Data/{table}"
    body = {
        "query": [{"code": k, "selection": {"filter": "item", "values": [v]}}
                  for k, v in query_filters.items()],
        "response": {"format": "json-stat2"},
    }
    r = requests.post(url, json=body, timeout=30)
    r.raise_for_status()
    js = r.json()
    return _parse_jsonstat(js, freq)


def _parse_jsonstat(js: dict, freq: str) -> list[tuple[date, float]]:
    """Parse JSON-stat 2.0 response — handles role.time or detects time dim by name."""
    values = js.get("value", [])
    dim = js.get("dimension", {})
    dim_ids = js.get("id", [])
    dim_sizes = js.get("size", [])
    if not dim_ids or not values:
        return []
    # find time dim: prefer top-level role.time (JSON-stat 2.0)
    tid = None
    role = js.get("role") or {}
    role_time = role.get("time") if isinstance(role, dict) else None
    if role_time:
        tid = role_time[0] if isinstance(role_time, list) else role_time
    # fallback: per-dim role.time (older format)
    if tid is None:
        for k, v in dim.items():
            if isinstance(v, dict) and v.get("role", {}).get("time"):
                tid = k; break
    # heuristic: dim name contains time-like word
    if tid is None:
        for k in dim_ids:
            kl = k.lower()
            if any(w in kl for w in ("tid", "time", "month", "mjesec", "mesec", "kuukausi", "vuosi", "år", "ar", "luni", "ani", "tlist")):
                tid = k; break
    if tid is None:
        return []
    cat = dim[tid].get("category", {})
    idx_obj = cat.get("index", {})
    if isinstance(idx_obj, list):
        time_pairs = list(enumerate(idx_obj))
        time_pairs = [(code, pos) for pos, code in time_pairs]
    else:
        time_pairs = [(code, pos) for code, pos in idx_obj.items()]

    # build flat-index for non-time dims (single value each since user filtered)
    other_indices = []
    for k in dim_ids:
        if k == tid:
            other_indices.append(None)
        else:
            other_indices.append(0)

    out = []
    tid_pos_in_id = dim_ids.index(tid)
    for time_code, time_pos in time_pairs:
        indices = list(other_indices)
        indices[tid_pos_in_id] = time_pos
        flat = 0
        stride = 1
        for i in range(len(dim_ids) - 1, -1, -1):
            flat += indices[i] * stride
            stride *= dim_sizes[i]
        if 0 <= flat < len(values):
            v = values[flat]
            if v is not None:
                dt = _parse_period(time_code, freq)
                if dt:
                    out.append((dt, float(v)))
    return sorted(out)


# === Latvia — CSP PxWeb (data.stat.gov.lv) ===

LV_SERIES = [
    # PCI030m: Consumer price indices December 1990=100, monthly 1991M01-2026M03
    {"slug": "inflation-cpi", "table": "PCI030m",
     "query": {"ContentsCode": "PCI030m"},
     "freq": "M", "unit": "Index (Dec 1990=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "CSP Latvia PCI030m CPI Dec 1990=100"},
]


def fetch_lv_pxweb(table_path: str, query_filters: dict, freq: str = "M") -> list[tuple[date, float]]:
    url = f"https://data.stat.gov.lv/api/v1/en/OSP_PUB/VEK/PC/PCI/{table_path}"
    body = {
        "query": [{"code": k, "selection": {"filter": "item", "values": [v]}}
                  for k, v in query_filters.items()],
        "response": {"format": "json-stat2"},
    }
    r = requests.post(url, json=body, timeout=30)
    r.raise_for_status()
    return _parse_jsonstat(r.json(), freq)


# === Romania — INSSE Tempo (HTTP only on port 8077) ===

RO_SERIES = [
    # IPC102A: Indicii preturilor de consum - evolutia lunara fata de luna anterioara
    # We'll fetch all monthly data and filter for category Total
    {"slug": "inflation-cpi", "matrix": "IPC102A",
     "category_id": 11730,  # Total
     "freq": "M", "unit": "Index (prev month=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "INSSE Tempo IPC102A monthly CPI MoM index (prev month=100)"},
]


def fetch_ro_tempo(matrix: str, category_id: int, freq: str = "M") -> list[tuple[date, float]]:
    """RO INSSE Tempo POST query for a matrix."""
    # First fetch matrix metadata to get all option IDs
    meta_r = requests.get(f"http://statistici.insse.ro:8077/tempo-ins/matrix/{matrix}", timeout=30)
    meta = meta_r.json()
    # Build a selection: select category + all months/years + UM
    # Tempo API requires array of selected option IDs per dimension
    selections = []
    for dim in meta.get("dimensionsMap", []):
        opts = dim.get("options", [])
        label = dim.get("label", "").lower()
        if "marfuri" in label or "categori" in label:
            # category filter
            selections.append([category_id])
        else:
            # take all options
            selections.append([o["nomItemId"] for o in opts])
    # POST /tempo-ins/matrix/<matrix>/data
    payload = {
        "encoded": False,
        "name": meta.get("matrixName"),
        "details": meta.get("details"),
        "code": matrix,
        "language": "en",
        "matrixDetails": meta.get("matrixDetails"),
        "metaData": meta.get("metaData"),
        "dimensionsMap": meta.get("dimensionsMap"),
    }
    # Actually Tempo uses /matrix/{matrix}/data with arrayOfNomItemIds matrices
    # try POST data
    r2 = requests.post(
        f"http://statistici.insse.ro:8077/tempo-ins/matrix/{matrix}/data",
        json=selections,
        timeout=60,
    )
    if r2.status_code != 200:
        # fallback: try GET with query
        return []
    try:
        data = r2.json()
    except Exception:
        return []
    # Tempo returns flat list per coordinate
    out = []
    for entry in data.get("matrix", []):
        # entry has dimensions and 'val'
        # period dim is "Luni" -> e.g. "Ianuarie 2026"
        period_label = ""
        for d in entry.get("dimensions", []):
            if "uni" in d.get("dimensionLabel", "").lower() or "ani" in d.get("dimensionLabel", "").lower():
                period_label = d.get("optionLabel", "")
        # parse
        try:
            ro_months = {"Ianuarie":1,"Februarie":2,"Martie":3,"Aprilie":4,"Mai":5,"Iunie":6,
                         "Iulie":7,"August":8,"Septembrie":9,"Octombrie":10,"Noiembrie":11,"Decembrie":12}
            parts = period_label.split()
            if len(parts) == 2 and parts[0] in ro_months:
                dt = date(int(parts[1]), ro_months[parts[0]], 1)
                val = entry.get("val")
                if val is not None:
                    out.append((dt, float(val)))
        except Exception:
            continue
    return sorted(out)


# === Estonia — Statistics Estonia PxWeb (andmed.stat.ee) ===

EE_SERIES = [
    # IA002.px = CPI 1997=100 monthly. Filter Kaubagrupp=1 (Total)
    {"slug": "inflation-cpi", "path": "majandus/hinnad/IA002.px",
     "query": {"Kaubagrupp": "1"},  # Total commodity group
     "freq": "M_year_month_combo", "unit": "Index (1997=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "Statistics Estonia IA002 CPI 1997=100, total commodity"},
]


def fetch_ee_pxweb(path: str, query_filters: dict, freq: str = "M") -> list[tuple[date, float]]:
    """Estonia PxWeb. Note: their tables often have separate Year and Month dims (not single Tid)."""
    url = f"https://andmed.stat.ee/api/v1/en/stat/{path}"
    body = {
        "query": [{"code": k, "selection": {"filter": "item", "values": [v]}}
                  for k, v in query_filters.items()],
        "response": {"format": "json-stat2"},
    }
    r = requests.post(url, json=body, timeout=30)
    r.raise_for_status()
    js = r.json()
    # If freq is 'M_year_month_combo', the table has Year and Month dims separately
    if freq == "M_year_month_combo":
        return _parse_jsonstat_year_month(js)
    return _parse_jsonstat(js, freq)


def _parse_jsonstat_year_month(js: dict) -> list[tuple[date, float]]:
    """Parse JSON-stat where time is split across Year (Aasta/Vuosi) and Month (Kuu/Kuukausi) dimensions."""
    values = js.get("value", [])
    dim = js.get("dimension", {})
    dim_ids = js.get("id", [])
    dim_sizes = js.get("size", [])
    if not values:
        return []
    # find year and month dims
    year_dim = next((k for k in dim_ids if k.lower() in ("aasta", "vuosi", "year", "år", "ar")), None)
    month_dim = next((k for k in dim_ids if k.lower() in ("kuu", "kuukausi", "month", "månad", "manad", "mesec")), None)
    if not year_dim or not month_dim:
        return []

    def get_index(name):
        idx = dim[name].get("category", {}).get("index", {})
        if isinstance(idx, list):
            return [(code, pos) for pos, code in enumerate(idx)]
        return [(code, pos) for code, pos in idx.items()]

    year_pairs = get_index(year_dim)
    month_pairs = get_index(month_dim)

    other_indices = {}
    for k in dim_ids:
        if k in (year_dim, month_dim):
            continue
        other_indices[k] = 0

    out = []
    yi = dim_ids.index(year_dim)
    mi = dim_ids.index(month_dim)
    for ycode, ypos in year_pairs:
        for mcode, mpos in month_pairs:
            indices = []
            for k in dim_ids:
                if k == year_dim:
                    indices.append(ypos)
                elif k == month_dim:
                    indices.append(mpos)
                else:
                    indices.append(other_indices.get(k, 0))
            flat = 0
            stride = 1
            for i in range(len(dim_ids) - 1, -1, -1):
                flat += indices[i] * stride
                stride *= dim_sizes[i]
            if 0 <= flat < len(values):
                v = values[flat]
                if v is not None:
                    try:
                        yy = int(ycode)
                        mm = int(mcode)
                        if 1 <= mm <= 12:
                            out.append((date(yy, mm, 1), float(v)))
                    except Exception:
                        continue
    return sorted(out)


# === Croatia — DZS PxWeb (web.dzs.hr) ===

HR_SERIES = [
    # ME_PS09.px CPI ECOICOP v2 monthly. ECOICOP_ver_2='00' (Total), Indikatori='4' (index 2025=100)
    {"slug": "inflation-cpi",
     "path": "Cijene/Indeksi potrošačkih cijena/Indeksi potrošačkih cijena – ECOICOP, ver. 2/ME_PS09.px",
     "query": {"ECOICOP, ver. 2": "00", "Indikatori": "4"},
     "freq": "M", "unit": "Index (2025=100)", "adjustment": "NSA", "conversion": 1.0,
     "note": "DZS Croatia ME_PS09 CPI 2025=100 total ECOICOP v2"},
]


def fetch_hr_pxweb(path: str, query_filters: dict, freq: str = "M") -> list[tuple[date, float]]:
    import urllib.parse
    encoded_path = "/".join(urllib.parse.quote(p) for p in path.split("/"))
    url = f"https://web.dzs.hr/PXWeb/api/v1/en/{encoded_path}"
    body = {
        "query": [{"code": k, "selection": {"filter": "item", "values": [v]}}
                  for k, v in query_filters.items()],
        "response": {"format": "json-stat2"},
    }
    r = requests.post(url, json=body, timeout=30)
    r.raise_for_status()
    return _parse_jsonstat(r.json(), freq)


# Aggregate fetchers
COUNTRY_FETCHERS = {
    # source_code -> (country, fetcher_function, series_list, label, url)
    "dst":      ("DK", DK_SERIES, "Statistics Denmark (Statbank)",       "https://www.dst.dk/en/Statistik/statbank"),
    "stat_fi":  ("FI", FI_SERIES, "Statistics Finland (Tilastokeskus)",  "https://www.stat.fi"),
    "scb_se":   ("SE", SE_SERIES, "Statistics Sweden (SCB)",             "https://www.scb.se"),
    "ine_pt":   ("PT", PT_SERIES, "INE Portugal",                        "https://www.ine.pt"),
    "cso_ie":   ("IE", IE_SERIES, "CSO Ireland",                         "https://www.cso.ie"),
    "stat_at":  ("AT", AT_SERIES, "Statistik Austria",                   "https://www.statistik.at"),
    "surs_si":  ("SI", SI_SERIES, "SURS Statistical Office Slovenia",    "https://www.stat.si"),
    "csp_lv":   ("LV", LV_SERIES, "CSP Latvia",                          "https://stat.gov.lv"),
    "insse_ro": ("RO", RO_SERIES, "INSSE Romania",                       "https://insse.ro"),
    "stat_ee":  ("EE", EE_SERIES, "Statistics Estonia",                  "https://andmed.stat.ee"),
    "dzs_hr":   ("HR", HR_SERIES, "DZS Croatian Bureau of Statistics",   "https://web.dzs.hr"),
    "statbel":  ("BE", BE_SERIES, "Statbel (Belgium)",                   "https://statbel.fgov.be"),
}


class NationalEUProvider(BaseProvider):
    name = "national_eu"
    display_name = "EU national stat offices (direct)"

    def fetch(self) -> list[DataPoint]:
        out: list[DataPoint] = []
        # Denmark
        for cfg in DK_SERIES:
            try:
                pairs = fetch_dk_table(cfg["table"], cfg["filters"], cfg["freq"])
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"], country="DK",
                        date=normalize_date(dt, cfg["freq"]),
                        value=round(v * cfg["conversion"], 4),
                        source="dst", unit=cfg["unit"],
                        series_id=f"DST/{cfg['table']}",
                        adjustment=cfg["adjustment"],
                    ))
                print(f"  OK {cfg['slug']}/DK ({cfg['table']}): {len(pairs)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['slug']}/DK ({cfg['table']}): {e}")
            time.sleep(0.3)

        # Finland
        for cfg in FI_SERIES:
            try:
                pairs = fetch_fi_table(cfg["path"], cfg["query"], cfg["freq"])
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"], country="FI",
                        date=normalize_date(dt, cfg["freq"]),
                        value=round(v * cfg["conversion"], 4),
                        source="stat_fi", unit=cfg["unit"],
                        series_id=f"STATFI/{cfg['path']}",
                        adjustment=cfg["adjustment"],
                    ))
                print(f"  OK {cfg['slug']}/FI ({cfg['path'][-30:]}): {len(pairs)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['slug']}/FI: {e}")
            time.sleep(0.3)

        # Sweden
        for cfg in SE_SERIES:
            try:
                pairs = fetch_se_table(cfg["path"], cfg["query"], cfg["freq"])
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"], country="SE",
                        date=normalize_date(dt, cfg["freq"]),
                        value=round(v * cfg["conversion"], 4),
                        source="scb_se", unit=cfg["unit"],
                        series_id=f"SCB/{cfg['path']}",
                        adjustment=cfg["adjustment"],
                    ))
                print(f"  OK {cfg['slug']}/SE: {len(pairs)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['slug']}/SE: {e}")
            time.sleep(0.3)

        # Portugal
        for cfg in PT_SERIES:
            try:
                pairs = fetch_pt_indicator(cfg["varcd"], cfg["freq"])
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"], country="PT",
                        date=normalize_date(dt, cfg["freq"]),
                        value=round(v * cfg["conversion"], 4),
                        source="ine_pt", unit=cfg["unit"],
                        series_id=f"INE-PT/{cfg['varcd']}",
                        adjustment=cfg["adjustment"],
                    ))
                print(f"  OK {cfg['slug']}/PT (varcd {cfg['varcd']}): {len(pairs)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['slug']}/PT: {e}")
            time.sleep(0.3)

        # Ireland
        for cfg in IE_SERIES:
            try:
                pairs = fetch_ie_table(cfg["table"], cfg["filters"], cfg["freq"])
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"], country="IE",
                        date=normalize_date(dt, cfg["freq"]),
                        value=round(v * cfg["conversion"], 4),
                        source="cso_ie", unit=cfg["unit"],
                        series_id=f"CSO/{cfg['table']}",
                        adjustment=cfg["adjustment"],
                    ))
                print(f"  OK {cfg['slug']}/IE ({cfg['table']}): {len(pairs)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['slug']}/IE: {e}")
            time.sleep(0.3)

        # Austria
        for cfg in AT_SERIES:
            try:
                pairs = fetch_at_csv(cfg["ogd"], cfg["filter_col"], cfg["filter_val"], cfg["value_col"], cfg["freq"])
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"], country="AT",
                        date=normalize_date(dt, cfg["freq"]),
                        value=round(v * cfg["conversion"], 4),
                        source="stat_at", unit=cfg["unit"],
                        series_id=f"STATAT/{cfg['ogd']}",
                        adjustment=cfg["adjustment"],
                    ))
                print(f"  OK {cfg['slug']}/AT ({cfg['ogd'][:30]}): {len(pairs)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['slug']}/AT: {e}")
            time.sleep(0.3)

        # Slovenia
        for cfg in SI_SERIES:
            try:
                pairs = fetch_si_pxweb(cfg["table"], cfg["query"], cfg["freq"])
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"], country="SI",
                        date=normalize_date(dt, cfg["freq"]),
                        value=round(v * cfg["conversion"], 4),
                        source="surs_si", unit=cfg["unit"],
                        series_id=f"SURS/{cfg['table']}",
                        adjustment=cfg["adjustment"],
                    ))
                print(f"  OK {cfg['slug']}/SI ({cfg['table']}): {len(pairs)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['slug']}/SI: {e}")
            time.sleep(0.3)

        # Latvia
        for cfg in LV_SERIES:
            try:
                pairs = fetch_lv_pxweb(cfg["table"], cfg["query"], cfg["freq"])
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"], country="LV",
                        date=normalize_date(dt, cfg["freq"]),
                        value=round(v * cfg["conversion"], 4),
                        source="csp_lv", unit=cfg["unit"],
                        series_id=f"CSP/{cfg['table']}",
                        adjustment=cfg["adjustment"],
                    ))
                print(f"  OK {cfg['slug']}/LV ({cfg['table']}): {len(pairs)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['slug']}/LV: {e}")
            time.sleep(0.3)

        # Estonia
        for cfg in EE_SERIES:
            try:
                pairs = fetch_ee_pxweb(cfg["path"], cfg["query"], cfg["freq"])
                eff_freq = "M" if cfg["freq"] == "M_year_month_combo" else cfg["freq"]
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"], country="EE",
                        date=normalize_date(dt, eff_freq),
                        value=round(v * cfg["conversion"], 4),
                        source="stat_ee", unit=cfg["unit"],
                        series_id=f"STATEE/{cfg['path']}",
                        adjustment=cfg["adjustment"],
                    ))
                print(f"  OK {cfg['slug']}/EE ({cfg['path'][-25:]}): {len(pairs)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['slug']}/EE: {e}")
            time.sleep(0.3)

        # Belgium
        for cfg in BE_SERIES:
            try:
                pairs = fetch_be_statbel_csv(cfg["view_id"], cfg["value_col"], cfg["freq"])
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"], country="BE",
                        date=normalize_date(dt, cfg["freq"]),
                        value=round(v * cfg["conversion"], 4),
                        source="statbel", unit=cfg["unit"],
                        series_id=f"STATBEL/{cfg['view_id'][:8]}",
                        adjustment=cfg["adjustment"],
                    ))
                print(f"  OK {cfg['slug']}/BE (Statbel): {len(pairs)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['slug']}/BE: {e}")
            time.sleep(0.3)

        # Croatia
        for cfg in HR_SERIES:
            try:
                pairs = fetch_hr_pxweb(cfg["path"], cfg["query"], cfg["freq"])
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"], country="HR",
                        date=normalize_date(dt, cfg["freq"]),
                        value=round(v * cfg["conversion"], 4),
                        source="dzs_hr", unit=cfg["unit"],
                        series_id=f"DZS/{cfg['path'][-30:]}",
                        adjustment=cfg["adjustment"],
                    ))
                print(f"  OK {cfg['slug']}/HR (ME_PS09): {len(pairs)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['slug']}/HR: {e}")
            time.sleep(0.3)

        # Romania
        for cfg in RO_SERIES:
            try:
                pairs = fetch_ro_tempo(cfg["matrix"], cfg["category_id"], cfg["freq"])
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"], country="RO",
                        date=normalize_date(dt, cfg["freq"]),
                        value=round(v * cfg["conversion"], 4),
                        source="insse_ro", unit=cfg["unit"],
                        series_id=f"INSSE/{cfg['matrix']}",
                        adjustment=cfg["adjustment"],
                    ))
                print(f"  OK {cfg['slug']}/RO ({cfg['matrix']}): {len(pairs)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['slug']}/RO: {e}")
            time.sleep(0.3)

        return out


def run():
    p = NationalEUProvider()
    print(f"Fetching from {p.display_name}...")
    try:
        pts = p.fetch()
        print(f"\nTotal: {len(pts)} data points")
        rows = datapoints_to_rows(pts)
        total = 0
        for i in range(0, len(rows), 500):
            count = upsert_data_points(rows[i:i+500])
            total += count
        log_pipeline_run("national_eu", "success", total)
        print(f"\nDone. {total} rows upserted.")
    except Exception as e:
        log_pipeline_run("national_eu", "failed", error_message=str(e))
        print(f"\nFailed: {e}")
        raise


if __name__ == "__main__":
    run()
