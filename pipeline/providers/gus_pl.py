"""GUS DBW Provider — Statistics Poland direct via dbw.stat.gov.pl/api_app.

TE-Source-First: für PL-Reihen wo TE „Source: Statistics Poland (GUS)" zeigt.
Reverse-engineered API; siehe memory/reference_gus_dbw_api.md.

Pattern:
  1. POST /api_app/wsk/GetTableNewManyIndicatorsNew with dimensional payload
  2. Extract latest periods + values from data[0][col_offset:]

Rate limit: 5 req/s, 100/15min. We sleep 0.3s between requests.
"""
import time
from datetime import date

import requests

from pipeline.base_provider import BaseProvider, DataPoint
from pipeline.transforms import normalize_date
from pipeline.db import upsert_data_points, log_pipeline_run, datapoints_to_rows

API = "https://dbw.stat.gov.pl/api_app"
HDR = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json", "Accept": "application/json"}

# Period id (okresy) → (period kind, sub-index) for monthly. Verified from live request 2026-05-10.
# Monthly: M01=247, M02=248, ..., M12=258. Quarterly Q1=270, Q2=271, Q3=272, Q4=273. Annual=282.
MONTH_OKRESY = {1: 247, 2: 248, 3: 249, 4: 250, 5: 251, 6: 252,
                7: 253, 8: 254, 9: 255, 10: 256, 11: 257, 12: 258}
QUARTER_OKRESY = {1: 270, 2: 271, 3: 272, 4: 273}

# Territorial unit id for Poland (national total)
JT_POLAND = 33617

# Per-slug config: variable_id, section_id, type_of_information, position values, freq, unit, adjustment.
# Position values = "<var>;<sec>;<type>;<dim>.<position>" — verified live for inflation-cpi.
SERIES = [
    {
        "indicator": "inflation-cpi",
        "variable_id": 305,
        "section_id": 1698,
        "type_id": 5,  # "previous year=100" → YoY index
        "positions": ["305;1698;5;1337.14916914", "305;1698;5;562.6902025"],
        "freq": "M",
        "unit": "Index (previous year=100)",
        "adjustment": "NSA",
        "conversion": 1.0,
        "note": "GUS DBW var=305 sec=1698 type=5 (CPI YoY index, 0-TOTAL COICOP-2018, all households, POLAND)",
    },
    {
        # PPI = "Producer prices in industry by KAU" (Ceny producenta w przemyśle wg JRD)
        # Stored as 2021=100 index level; frontend computes YoY on demand.
        "indicator": "ppi",
        "variable_id": 1667,
        "section_id": 1413,
        "type_id": 372,  # id_presentation=372 "monthly average of 2021=100"
        "positions": [
            "1667;1413;372;1115.12275488",  # dim 1115 (Type of market) pos 0 = Producer price - Total
            "1667;1413;372;1116.11065748",  # dim 1116 (Industry NACE) pos OG119340 = TOTAL
        ],
        "freq": "M",
        "unit": "Index (2021=100)",
        "adjustment": "NSA",
        "conversion": 1.0,
        "note": "GUS DBW var=1667 sec=1413 pres=372 (PPI 2021=100, market-total, NACE-total, POLAND)",
    },
    {
        # Industrial Production = "Sold production of industry" (Produkcja sprzedana przemysłu)
        # Native GUS publication is YoY index (corresponding period of previous year=100, constant prices).
        # Section 2 has no dimensions for the national total — payload uses empty position value.
        "indicator": "industrial-production",
        "variable_id": 814,
        "section_id": 2,
        "type_id": 7,  # id_presentation=7 "corresponding period of previous year=100, constant prices"
        "positions": ["814;2;7;"],
        "freq": "M",
        "unit": "Index (previous year=100, constant prices)",
        "adjustment": "NSA",
        "conversion": 1.0,
        "note": "GUS DBW var=814 sec=2 pres=7 (Sold production of industry YoY constant prices, POLAND)",
    },
    {
        # Registered unemployment rate (Stopa bezrobocia rejestrowanego). Different methodology from
        # LFS unemployment — typically higher; this is the headline series MoLFS uses for "stopa bezrobocia".
        "indicator": "unemployment-rate-registered",
        "variable_id": 875,
        "section_id": 143,
        "type_id": 95,  # id_presentation=95 "[%]"
        "positions": ["875;143;95;"],
        "freq": "M",
        "unit": "%",
        "adjustment": "NSA",
        "conversion": 1.0,
        "note": "GUS DBW var=875 sec=143 pres=95 (Registered unemployment rate %, POLAND)",
    },
    {
        # Retail Sales = "Retail sales of goods" (Sprzedaż detaliczna towarów)
        # YoY constant prices (corresponding period of previous year=100).
        "indicator": "retail-sales",
        "variable_id": 109,
        "section_id": 849,
        "type_id": 7,  # id_presentation=7 "corresponding period of previous year=100, constant prices"
        "positions": ["109;849;7;505.6661586"],  # dim 505 pos GR255640 = Total retail sales (by PKD)
        "freq": "M",
        "unit": "Index (previous year=100, constant prices)",
        "adjustment": "NSA",
        "conversion": 1.0,
        "note": "GUS DBW var=109 sec=849 pres=7 (Retail sales of goods YoY constant prices, POLAND)",
    },
]


def _build_payload(cfg: dict, years: list[int]) -> dict:
    """Build a GetTableNewManyIndicatorsNew payload requesting all 12 monthly periods of each year."""
    var = cfg["variable_id"]
    sec = cfg["section_id"]
    typ = cfg["type_id"]
    okresy = list(MONTH_OKRESY.values()) if cfg["freq"] == "M" else list(QUARTER_OKRESY.values())

    col_values, col_years, col_titles = [], [], []
    for yr in years:
        for k, oid in (MONTH_OKRESY.items() if cfg["freq"] == "M" else QUARTER_OKRESY.items()):
            col_values.append(oid)
            col_years.append(yr)
            tag = f"M{k:02d}" if cfg["freq"] == "M" else f"Q{k}"
            col_titles.append(f"{yr} {tag}")

    rows = [
        {"type": "Zm", "title": "Variable", "values": [var], "idx": 0, "loaded": True,
         "titles": [""], "titles_orig": [""]},
        {"type": "TYPE", "title": "Information type", "values": [typ], "new_values": [typ], "idx": 1,
         "titles": [""]},
    ]
    for i, posval in enumerate(cfg["positions"]):
        rows.append({"type": "POS", "section_id": sec, "title": f"dim{i}",
                     "loaded": True, "values": [posval], "titles": [], "idx": 2 + i})
    rows.append({"type": "JT", "title": "Territorial unit", "values": [JT_POLAND],
                 "titles": ["POLAND"], "titles_orig": ["POLSKA"], "idx": 2 + len(cfg["positions"])})

    return {
        "opts": {"showSymbols": False, "showEmptyRows": True, "showEmptyCols": True, "lang": "en"},
        "list": [],
        "rows": rows,
        "cols": [{
            "type": "SC",
            "title": "Time series",
            "values": col_values,
            "years": col_years,
            "titles": col_titles,
            "titles_orig": col_titles,
            "idx": 999999990,
            "values_sort": [],
        }],
        "params": {"page": 0, "offset": 0, "rowsPerPage": 100, "sort": []},
    }


def _parse_response(resp_json: dict, years: list[int], freq: str) -> list[tuple[date, float]]:
    """Returns list of (date, value) for non-null cells."""
    data = resp_json.get("data") or []
    if not data:
        return []
    row = data[0]
    # First N cells are dimension/JT names; data starts after them. Determine offset by counting metadata cells.
    # In our payload we have rows: Zm, TYPE, POS, POS, JT — so 5 metadata cells before data.
    meta_count = sum(1 for _ in row if isinstance(_, dict) and "_p" not in _ and isinstance(_.get("d"), str))
    # Safer: detect by skipping cells where d is not numeric-or-(.).
    out = []
    period_keys = list(MONTH_OKRESY.keys()) if freq == "M" else list(QUARTER_OKRESY.keys())
    n_per_year = len(period_keys)
    data_cells = []
    for cell in row:
        if not isinstance(cell, dict):
            continue
        d = cell.get("d")
        if isinstance(d, (int, float)):
            data_cells.append(d)
        elif isinstance(d, str) and d.startswith("("):
            data_cells.append(None)  # missing flag like "(.)" or "(nd)"
        # else string label — metadata cell
    expected = len(years) * n_per_year
    if len(data_cells) < expected:
        return []
    # Take last `expected` cells (they correspond to our col list in order)
    data_cells = data_cells[-expected:]
    idx = 0
    for yr in years:
        for k in period_keys:
            v = data_cells[idx]
            idx += 1
            if v is None:
                continue
            if freq == "M":
                dt = date(yr, k, 1)
            else:
                dt = date(yr, (k - 1) * 3 + 1, 1)
            out.append((dt, float(v)))
    return out


def _fetch(cfg: dict, years: list[int]) -> list[DataPoint]:
    payload = _build_payload(cfg, years)
    r = requests.post(f"{API}/wsk/GetTableNewManyIndicatorsNew", json=payload, headers=HDR, timeout=30)
    r.raise_for_status()
    pairs = _parse_response(r.json(), years, cfg["freq"])
    out = []
    for dt, val in pairs:
        norm = normalize_date(dt, cfg["freq"])
        out.append(DataPoint(
            indicator=cfg["indicator"], country="PL", date=norm,
            value=val * cfg["conversion"], source="gus_pl",
            unit=cfg["unit"],
            series_id=f"GUS:var={cfg['variable_id']}/sec={cfg['section_id']}/type={cfg['type_id']}",
            adjustment=cfg["adjustment"],
        ))
    return out


class GusPlProvider(BaseProvider):
    name = "gus_pl"
    display_name = "Statistics Poland (GUS DBW)"

    def fetch(self) -> list[DataPoint]:
        out: list[DataPoint] = []
        years = list(range(2010, date.today().year + 1))
        for cfg in SERIES:
            try:
                pts = _fetch(cfg, years)
                out.extend(pts)
                print(f"  OK {cfg['indicator']}/PL (var {cfg['variable_id']}): {len(pts)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['indicator']}/PL (var {cfg['variable_id']}): {e}")
            time.sleep(0.3)  # rate-limit guard
        return out


def run():
    p = GusPlProvider()
    print(f"Fetching from {p.display_name}...")
    try:
        pts = p.fetch()
        print(f"\nTotal: {len(pts)} data points")
        rows = datapoints_to_rows(pts)
        total = 0
        for i in range(0, len(rows), 500):
            count = upsert_data_points(rows[i:i+500])
            total += count
        log_pipeline_run("gus_pl", "success", total)
        print(f"\nDone. {total} rows upserted.")
    except Exception as e:
        log_pipeline_run("gus_pl", "failed", error_message=str(e))
        print(f"\nFailed: {e}")
        raise


if __name__ == "__main__":
    run()
