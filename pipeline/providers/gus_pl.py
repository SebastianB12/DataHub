"""GUS DBW Provider — Statistics Poland direct via dbw.stat.gov.pl/api_app.

TE-Source-First: für PL-Reihen wo TE „Source: Statistics Poland (GUS)" zeigt.
Reverse-engineered API; siehe memory/reference_gus_dbw_api.md.

Pattern:
  1. POST /api_app/wsk/GetTableNewManyIndicatorsNew with dimensional payload
  2. Extract latest periods + values from data[0][col_offset:]

Rate limit: 5 req/s, 100/15min. We sleep 0.3s between requests.

CPI subcomponents use two sections per slug:
  sec=909 (COICOP 1999) for 2014-2025 + sec=1698 (COICOP 2018) for 2026+
"""
import time
from datetime import date

import requests

from pipeline.base_provider import BaseProvider, DataPoint
from pipeline.transforms import normalize_date
from pipeline.db import upsert_data_points, log_pipeline_run, datapoints_to_rows

API = "https://dbw.stat.gov.pl/api_app"
HDR = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json", "Accept": "application/json"}

# Monthly: M01=247, M02=248, ..., M12=258. Quarterly Q1=270, Q2=271, Q3=272, Q4=273.
MONTH_OKRESY = {1: 247, 2: 248, 3: 249, 4: 250, 5: 251, 6: 252,
                7: 253, 8: 254, 9: 255, 10: 256, 11: 257, 12: 258}
QUARTER_OKRESY = {1: 270, 2: 271, 3: 272, 4: 273}

# Territorial unit id for Poland (national total)
JT_POLAND = 33617


def _spec(variable_id, section_id, type_id, positions, freq="M", years=None):
    """One (variable, section, presentation, positions) fetch spec."""
    return {
        "variable_id": variable_id,
        "section_id": section_id,
        "type_id": type_id,
        "positions": positions,
        "freq": freq,
        "years": years,  # optional restriction (list); None = all from start_year
    }


# Per-slug config. "specs" = list of fetch specs (some slugs need multi-section join).
SERIES = [
    {
        "indicator": "inflation-cpi",
        "specs": [
            _spec(305, 909, 5,
                  ["305;909;5;784.7215815", "305;909;5;562.6902025"], "M",
                  years=list(range(2014, 2026))),
            _spec(305, 1698, 5,
                  ["305;1698;5;1337.14916914", "305;1698;5;562.6902025"], "M",
                  years=list(range(2026, date.today().year + 1))),
        ],
        "unit": "Index (previous year=100)",
        "adjustment": "NSA",
        "series_id": "GUS:var=305/COICOP=Total",
        "note": "GUS DBW var=305 (CPI YoY index, COICOP Total: sec 909 2014-2025 + sec 1698 2026+)",
    },
    {
        "indicator": "ppi",
        "specs": [_spec(1667, 1413, 372,
                        ["1667;1413;372;1115.12275488", "1667;1413;372;1116.11065748"],
                        "M")],
        "unit": "Index (2021=100)",
        "adjustment": "NSA",
        "series_id": "GUS:var=1667/sec=1413/type=372",
        "note": "GUS DBW var=1667 sec=1413 pres=372 (PPI 2021=100, market-total, NACE-total, POLAND)",
    },
    {
        "indicator": "industrial-production",
        "specs": [_spec(814, 2, 7, ["814;2;7;"], "M")],
        "unit": "Index (previous year=100, constant prices)",
        "adjustment": "NSA",
        "series_id": "GUS:var=814/sec=2/type=7",
        "note": "GUS DBW var=814 sec=2 pres=7 (Sold production of industry YoY constant prices, POLAND)",
    },
    {
        "indicator": "unemployment-rate-registered",
        "specs": [_spec(875, 143, 95, ["875;143;95;"], "M")],
        "unit": "%",
        "adjustment": "NSA",
        "series_id": "GUS:var=875/sec=143/type=95",
        "note": "GUS DBW var=875 sec=143 pres=95 (Registered unemployment rate %, POLAND)",
    },
    {
        "indicator": "unemployment",
        # TE labels this 'unemployment-rate' attributing GUS — same series as
        # unemployment-rate-registered. Honest fetch = GUS DBW.
        "specs": [_spec(875, 143, 95, ["875;143;95;"], "M")],
        "unit": "%",
        "adjustment": "NSA",
        "series_id": "GUS:var=875/sec=143/type=95",
        "note": "GUS DBW var=875 sec=143 pres=95 (Registered unemployment rate %, POLAND) — TE primary 'unemployment-rate'",
    },
    {
        "indicator": "unemployed-persons",
        # GUS var=507 = Registered unemployed persons (count); sec=871, type=93,
        # dim1 (Sex)=6648242 Total, dim687 (Categories)=7226259 Unemployed.
        # Split into chunks of ~5 years to avoid 30s timeout on full series.
        "specs": [
            _spec(507, 871, 93, ["507;871;93;1.6648242", "507;871;93;687.7226259"], "M",
                  years=list(range(2010, 2016))),
            _spec(507, 871, 93, ["507;871;93;1.6648242", "507;871;93;687.7226259"], "M",
                  years=list(range(2016, 2021))),
            _spec(507, 871, 93, ["507;871;93;1.6648242", "507;871;93;687.7226259"], "M",
                  years=list(range(2021, date.today().year + 1))),
        ],
        "unit": "Thousand",
        "adjustment": "NSA",
        "series_id": "GUS:var=507/sec=871/type=93",
        "conversion_after_fetch": 0.001,  # raw is persons; convert to thousand
        "note": "GUS DBW var=507 sec=871 pres=93 (Registered unemployed persons, count converted to thousand)",
    },
    {
        "indicator": "retail-sales",
        "specs": [_spec(109, 849, 7, ["109;849;7;505.6661586"], "M")],
        "unit": "Index (previous year=100, constant prices)",
        "adjustment": "NSA",
        "series_id": "GUS:var=109/sec=849/type=7",
        "note": "GUS DBW var=109 sec=849 pres=7 (Retail sales of goods YoY constant prices, POLAND)",
    },
    # === NEW (037_pl_gapfill) ===
    {
        "indicator": "business-confidence",
        "specs": [_spec(184, 751, 117, ["184;751;117;618.6670316"], "M")],
        "unit": "Index (balance)",
        "adjustment": "NSA",
        "series_id": "GUS:var=184/sec=751/type=117",
        "note": "GUS DBW var=184 sec=751 pres=117 (General business climate indicator, Main industrial groupings Total, POLAND)",
    },
    {
        "indicator": "consumer-confidence",
        "specs": [_spec(469, 16, 117, ["469;16;117;"], "M")],
        "unit": "Index (balance)",
        "adjustment": "NSA",
        "series_id": "GUS:var=469/sec=16/type=117",
        "note": "GUS DBW var=469 sec=16 pres=117 (Current Consumer Confidence Indicator BWUK, POLAND)",
    },
    {
        "indicator": "capacity-utilization",
        "specs": [_spec(189, 751, 95, ["189;751;95;618.6670316"], "M")],
        "unit": "%",
        "adjustment": "NSA",
        "series_id": "GUS:var=189/sec=751/type=95",
        "note": "GUS DBW var=189 sec=751 pres=95 (Capacity utilization %, Main industrial groupings Total, POLAND)",
    },
    {
        "indicator": "mining-production",
        "specs": [_spec(814, 807, 7, ["814;807;7;711.6971717"], "M")],
        "unit": "Index (previous year=100, constant prices)",
        "adjustment": "NSA",
        "series_id": "GUS:var=814/sec=807/type=7/B",
        "note": "GUS DBW var=814 sec=807 pres=7 dim 711 pos B (Sold production - Mining and quarrying YoY)",
    },
    {
        "indicator": "manufacturing-production",
        "specs": [_spec(814, 807, 7, ["814;807;7;711.6971743"], "M")],
        "unit": "Index (previous year=100, constant prices)",
        "adjustment": "NSA",
        "series_id": "GUS:var=814/sec=807/type=7/C",
        "note": "GUS DBW var=814 sec=807 pres=7 dim 711 pos C (Sold production - Manufacturing YoY)",
    },
    {
        "indicator": "changes-in-inventories",
        "specs": [_spec(1199, 16, 105, ["1199;16;105;"], "Q")],
        "unit": "mln zl",
        "adjustment": "NSA",
        "series_id": "GUS:var=1199/sec=16/type=105",
        "note": "GUS DBW var=1199 sec=16 pres=105 (Changes in inventories, current prices, mln zl, quarterly)",
    },
    {
        "indicator": "gross-fixed-capital-formation",
        "specs": [_spec(1198, 1099, 105, ["1198;1099;105;933.7310848"], "Q")],
        "unit": "mln zl",
        "adjustment": "NSA",
        "series_id": "GUS:var=1198/sec=1099/type=105",
        "note": "GUS DBW var=1198 sec=1099 pres=105 (Gross fixed capital formation, Total economy S.1, current prices, quarterly)",
    },
    {
        "indicator": "consumer-spending",
        "specs": [_spec(1391, 950, 105, ["1391;950;105;809.7310945"], "Q")],
        "unit": "mln zl",
        "adjustment": "NSA",
        "series_id": "GUS:var=1391/sec=950/type=105",
        "note": "GUS DBW var=1391 sec=950 pres=105 (Final consumption expenditure of households S.14, current prices, quarterly)",
    },
    {
        "indicator": "government-spending",
        "specs": [_spec(1196, 1040, 105, ["1196;1040;105;880.7310934"], "Q")],
        "unit": "mln zl",
        "adjustment": "NSA",
        "series_id": "GUS:var=1196/sec=1040/type=105",
        "note": "GUS DBW var=1196 sec=1040 pres=105 (General government final consumption expenditure S.13, current prices, quarterly)",
    },
    {
        "indicator": "employed-persons",
        # var 1036 = Employment ESA 2010, sec 1418 quarterly, dim 1118 (status)=Total + dim 1119 (NACE)=TOTAL.
        "specs": [_spec(1036, 1418, 98,
                        ["1036;1418;98;1118.11943578", "1036;1418;98;1119.11065748"], "Q")],
        "unit": "thousand persons",
        "adjustment": "NSA",
        "series_id": "GUS:var=1036/sec=1418/type=98",
        "note": "GUS DBW var=1036 sec=1418 pres=98 (Employed persons ESA 2010, Total status, Total NACE, quarterly, thousand persons)",
    },
    # === CPI subcomponents — use sec 909 (COICOP 1999) for 2014-2025 + sec 1698 (COICOP 2018) for 2026+ ===
    {
        "indicator": "cpi-food",
        "specs": [
            _spec(305, 909, 5, ["305;909;5;784.7215829", "305;909;5;562.6902025"], "M",
                  years=list(range(2014, 2026))),
            _spec(305, 1698, 5, ["305;1698;5;1337.14150568", "305;1698;5;562.6902025"], "M",
                  years=list(range(2026, date.today().year + 1))),
        ],
        "unit": "Index (previous year=100)",
        "adjustment": "NSA",
        "series_id": "GUS:var=305/COICOP=01",
        "note": "GUS DBW var=305 (CPI COICOP 01 Food and non-alcoholic beverages, YoY index)",
    },
    {
        "indicator": "cpi-clothing",
        "specs": [
            _spec(305, 909, 5, ["305;909;5;784.7215827", "305;909;5;562.6902025"], "M",
                  years=list(range(2014, 2026))),
            _spec(305, 1698, 5, ["305;1698;5;1337.14150566", "305;1698;5;562.6902025"], "M",
                  years=list(range(2026, date.today().year + 1))),
        ],
        "unit": "Index (previous year=100)",
        "adjustment": "NSA",
        "series_id": "GUS:var=305/COICOP=03",
        "note": "GUS DBW var=305 (CPI COICOP 03 Clothing and footwear, YoY index)",
    },
    {
        "indicator": "cpi-housing-utilities",
        "specs": [
            _spec(305, 909, 5, ["305;909;5;784.7215826", "305;909;5;562.6902025"], "M",
                  years=list(range(2014, 2026))),
            _spec(305, 1698, 5, ["305;1698;5;1337.14150565", "305;1698;5;562.6902025"], "M",
                  years=list(range(2026, date.today().year + 1))),
        ],
        "unit": "Index (previous year=100)",
        "adjustment": "NSA",
        "series_id": "GUS:var=305/COICOP=04",
        "note": "GUS DBW var=305 (CPI COICOP 04 Housing, water, electricity, gas and other fuels, YoY index)",
    },
    {
        "indicator": "cpi-transportation",
        "specs": [
            _spec(305, 909, 5, ["305;909;5;784.7215822", "305;909;5;562.6902025"], "M",
                  years=list(range(2014, 2026))),
            _spec(305, 1698, 5, ["305;1698;5;1337.14150562", "305;1698;5;562.6902025"], "M",
                  years=list(range(2026, date.today().year + 1))),
        ],
        "unit": "Index (previous year=100)",
        "adjustment": "NSA",
        "series_id": "GUS:var=305/COICOP=07",
        "note": "GUS DBW var=305 (CPI COICOP 07 Transport, YoY index)",
    },
    {
        "indicator": "cpi-recreation-and-culture",
        "specs": [
            _spec(305, 909, 5, ["305;909;5;784.7215820", "305;909;5;562.6902025"], "M",
                  years=list(range(2014, 2026))),
            _spec(305, 1698, 5, ["305;1698;5;1337.14150560", "305;1698;5;562.6902025"], "M",
                  years=list(range(2026, date.today().year + 1))),
        ],
        "unit": "Index (previous year=100)",
        "adjustment": "NSA",
        "series_id": "GUS:var=305/COICOP=09",
        "note": "GUS DBW var=305 (CPI COICOP 09 Recreation and culture, YoY index)",
    },
    {
        "indicator": "cpi-education",
        "specs": [
            _spec(305, 909, 5, ["305;909;5;784.7215819", "305;909;5;562.6902025"], "M",
                  years=list(range(2014, 2026))),
            _spec(305, 1698, 5, ["305;1698;5;1337.14150559", "305;1698;5;562.6902025"], "M",
                  years=list(range(2026, date.today().year + 1))),
        ],
        "unit": "Index (previous year=100)",
        "adjustment": "NSA",
        "series_id": "GUS:var=305/COICOP=10",
        "note": "GUS DBW var=305 (CPI COICOP 10 Education, YoY index)",
    },
    # === Special-aggregate CPI (food/services/energy inflation) — sec 1722 (COICOP-2018 special aggregates from 2026) ===
    {
        "indicator": "food-inflation",
        "specs": [_spec(305, 1722, 5,
                        ["305;1722;5;1338.14916613", "305;1722;5;562.6902025"], "M",
                        years=list(range(2026, date.today().year + 1)))],
        "unit": "Index (previous year=100)",
        "adjustment": "NSA",
        "series_id": "GUS:var=305/sec=1722/GR477507",
        "note": "GUS DBW var=305 sec=1722 (Food and non-alcoholic beverages special aggregate, YoY)",
    },
    {
        "indicator": "services-inflation",
        "specs": [_spec(305, 1722, 5,
                        ["305;1722;5;1338.14916840", "305;1722;5;562.6902025"], "M",
                        years=list(range(2026, date.today().year + 1)))],
        "unit": "Index (previous year=100)",
        "adjustment": "NSA",
        "series_id": "GUS:var=305/sec=1722/GR477510",
        "note": "GUS DBW var=305 sec=1722 (Services special aggregate, YoY)",
    },
    {
        "indicator": "energy-inflation",
        # GR477512 = Fuels (liquid + solid + motor). Closest proxy in sec 1722.
        "specs": [_spec(305, 1722, 5,
                        ["305;1722;5;1338.14916865", "305;1722;5;562.6902025"], "M",
                        years=list(range(2026, date.today().year + 1)))],
        "unit": "Index (previous year=100)",
        "adjustment": "NSA",
        "series_id": "GUS:var=305/sec=1722/GR477512",
        "note": "GUS DBW var=305 sec=1722 (Fuels special aggregate, YoY) — used as energy-inflation proxy",
    },
]


def _build_payload(spec: dict) -> dict:
    """Build GetTableNewManyIndicatorsNew payload."""
    var = spec["variable_id"]
    sec = spec["section_id"]
    typ = spec["type_id"]
    freq = spec["freq"]
    years = spec["years"] or list(range(2010, date.today().year + 1))

    col_values, col_years, col_titles = [], [], []
    if freq == "M":
        for yr in years:
            for k, oid in MONTH_OKRESY.items():
                col_values.append(oid)
                col_years.append(yr)
                col_titles.append(f"{yr} M{k:02d}")
    else:
        for yr in years:
            for k, oid in QUARTER_OKRESY.items():
                col_values.append(oid)
                col_years.append(yr)
                col_titles.append(f"{yr} Q{k}")

    rows = [
        {"type": "Zm", "title": "Variable", "values": [var], "idx": 0, "loaded": True,
         "titles": [""], "titles_orig": [""]},
        {"type": "TYPE", "title": "Information type", "values": [typ], "new_values": [typ], "idx": 1,
         "titles": [""]},
    ]
    for i, posval in enumerate(spec["positions"]):
        rows.append({"type": "POS", "section_id": sec, "title": f"dim{i}",
                     "loaded": True, "values": [posval], "titles": [], "idx": 2 + i})
    rows.append({"type": "JT", "title": "Territorial unit", "values": [JT_POLAND],
                 "titles": ["POLAND"], "titles_orig": ["POLSKA"], "idx": 2 + len(spec["positions"])})

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


def _parse_response(resp_json: dict, spec: dict) -> list[tuple[date, float]]:
    """Returns list of (date, value) for non-null cells."""
    data = resp_json.get("data") or []
    if not data:
        return []
    row = data[0]
    out: list[tuple[date, float]] = []
    freq = spec["freq"]
    years = spec["years"] or list(range(2010, date.today().year + 1))
    period_keys = list(MONTH_OKRESY.keys()) if freq == "M" else list(QUARTER_OKRESY.keys())
    n_per_year = len(period_keys)
    data_cells: list[float | None] = []
    for cell in row:
        if not isinstance(cell, dict):
            continue
        d = cell.get("d")
        if isinstance(d, (int, float)):
            data_cells.append(float(d))
        elif isinstance(d, str) and d.startswith("("):
            data_cells.append(None)
        # else: a string label = metadata
    expected = len(years) * n_per_year
    if len(data_cells) < expected:
        return []
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
            out.append((dt, v))
    return out


def _fetch_spec(spec: dict) -> list[tuple[date, float]]:
    payload = _build_payload(spec)
    r = requests.post(f"{API}/wsk/GetTableNewManyIndicatorsNew", json=payload, headers=HDR, timeout=30)
    r.raise_for_status()
    return _parse_response(r.json(), spec)


def _fetch_series(cfg: dict) -> list[DataPoint]:
    """Fetch all specs for one slug, concat their pairs."""
    pairs: dict[date, float] = {}
    for spec in cfg["specs"]:
        try:
            for dt, val in _fetch_spec(spec):
                pairs[dt] = val
        except Exception as e:
            print(f"    spec var={spec['variable_id']}/sec={spec['section_id']} failed: {e}")
        time.sleep(0.3)
    freq = cfg["specs"][0]["freq"]
    conv = cfg.get("conversion_after_fetch", 1.0)
    out: list[DataPoint] = []
    for dt, val in sorted(pairs.items()):
        norm = normalize_date(dt, freq)
        out.append(DataPoint(
            indicator=cfg["indicator"], country="PL", date=norm,
            value=val * conv, source="gus_pl",
            unit=cfg["unit"],
            series_id=cfg["series_id"],
            adjustment=cfg["adjustment"],
        ))
    return out


class GusPlProvider(BaseProvider):
    name = "gus_pl"
    display_name = "Statistics Poland (GUS DBW)"

    def fetch(self) -> list[DataPoint]:
        out: list[DataPoint] = []
        for cfg in SERIES:
            try:
                pts = _fetch_series(cfg)
                out.extend(pts)
                print(f"  OK {cfg['indicator']}/PL: {len(pts)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['indicator']}/PL: {e}")
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
