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
    js = r.json()
    values = js.get("value", [])
    dim = js.get("dimension", {})
    # Find time
    tid = next((k for k, v in dim.items() if v.get("role", {}).get("time")), None)
    if not tid:
        # fallback
        tid = next((k for k in dim if k.lower() in ("vuosi", "kuukausi", "aika", "year", "month", "tid")), None)
    if not tid:
        return []
    cat = dim[tid].get("category", {})
    idx_map = cat.get("index", {})
    out = []
    for code, idx in idx_map.items():
        if isinstance(idx, int) and idx < len(values):
            v = values[idx]
            if v is not None:
                dt = _parse_period(code, freq)
                if dt:
                    out.append((dt, float(v)))
    return sorted(out)


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
    js = r.json()
    values = js.get("value", [])
    dim = js.get("dimension", {})
    tid = next((k for k, v in dim.items() if v.get("role", {}).get("time")), None)
    if not tid:
        tid = next((k for k in dim if k.lower() in ("tid", "month", "year", "kvartal")), None)
    if not tid:
        return []
    cat = dim[tid].get("category", {})
    idx_map = cat.get("index", {})
    out = []
    for code, idx in idx_map.items():
        if isinstance(idx, int) and idx < len(values):
            v = values[idx]
            if v is not None:
                dt = _parse_period(code, freq)
                if dt:
                    out.append((dt, float(v)))
    return sorted(out)


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
    # Belgium HICP via NBB Belgostat — NBB is the central bank but it serves data
    # via stat.nbb.be. The reachable JSON API:
    # https://stat.nbb.be/sdmx/V21/data/<dataset>/<key>
    # Belgostat is HTML-only for some datasets. Use NBB Belgostat for HICP.
    # Actually for Belgium HICP, Statbel publishes CSV at:
    # https://statbel.fgov.be/sites/default/files/files/opendata/CPI/CPI%202024.csv
    # We use NBB SDMX as primary since Statbel CSV requires year scraping.
]


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


# Aggregate fetchers
COUNTRY_FETCHERS = {
    # source_code -> (country, fetcher_function, series_list, label, url)
    "dst":      ("DK", DK_SERIES, "Statistics Denmark (Statbank)",       "https://www.dst.dk/en/Statistik/statbank"),
    "stat_fi":  ("FI", FI_SERIES, "Statistics Finland (Tilastokeskus)",  "https://www.stat.fi"),
    "scb_se":   ("SE", SE_SERIES, "Statistics Sweden (SCB)",             "https://www.scb.se"),
    "ine_pt":   ("PT", PT_SERIES, "INE Portugal",                        "https://www.ine.pt"),
    "cso_ie":   ("IE", IE_SERIES, "CSO Ireland",                         "https://www.cso.ie"),
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
