"""One-shot script: replace HR_SERIES + fetch_hr_pxweb with expanded version."""
import io

fp = 'pipeline/providers/national_eu.py'
with open(fp, 'r', encoding='utf-8') as f:
    src = f.read()

OLD = '''# === Croatia — DZS PxWeb (web.dzs.hr) ===

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
    return _parse_jsonstat(r.json(), freq)'''

NEW = '''# === Croatia — DZS PxWeb (web.dzs.hr) ===
#
# DZS PxWeb has aggressive rate limiting (~1 query / 8-10 s) and a cell-count
# cap of ~120 per response. Each HR_SERIES query pre-filters Year/Month/Quarter
# tightly; the fetcher sleeps between calls (handled in NationalEUProvider.fetch).
#
# Time-axis quirk: DZS does NOT use a single 'Tid' dim. Tables like BS_IN13,
# BS_PP11, BS_TR21 split time into separate GODINA (year) + MJESEC (month,
# Roman numerals I..XII). T1 (wages) uses GODINA + PERIOD (numeric 1..12).
# Quarterly GDP table BDP-T01_EUR uses Godina + Tromjesečje (1..4, '5'=annual aggr).

HR_ROMAN_MONTHS = {
    "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6,
    "VII": 7, "VIII": 8, "IX": 9, "X": 10, "XI": 11, "XII": 12,
}

# Recent windows kept under the 120-cell DZS cap.
HR_RECENT_YEARS_15 = [str(y) for y in range(2018, 2027)]   # 9 * 12 = 108
HR_QUARTER_YEARS = [str(y) for y in range(2010, 2027)]     # 17 * 4  = 68
HR_ALL_MONTHS_ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"]
HR_ALL_MONTHS_NUMERIC = [str(i) for i in range(1, 13)]
HR_ALL_QUARTERS = ["1", "2", "3", "4"]

HR_SERIES = [
    # 1. CPI — ME_PS09 (already validated). Base 2025=100, ECOICOP v2 Total.
    {"slug": "inflation-cpi", "kind": "tid",
     "path": "Cijene/Indeksi potrošačkih cijena/Indeksi potrošačkih cijena – ECOICOP, ver. 2/ME_PS09.px",
     "query": {"ECOICOP, ver. 2": "00", "Indikatori": "4"},
     "freq": "M", "unit": "Index (2025=100)", "adjustment": "NSA", "conversion": 1.0,
     "series_id": "DZS/ME_PS09",
     "note": "DZS ME_PS09 CPI 2025=100 total ECOICOP v2"},

    # 2. Industrial production — BS_IN13 SA+WDA, Total industry, base 2021=100.
    {"slug": "industrial-production", "kind": "year_roman_month",
     "path": "Industrija/Indeks industrijske proizvodnje/BS_IN13.px",
     "query": {"DJELATNOSTI": "Total", "GODINA": HR_RECENT_YEARS_15, "MJESEC": HR_ALL_MONTHS_ROMAN},
     "freq": "M", "unit": "Index (2021=100)", "adjustment": "SA",  "conversion": 1.0,
     "series_id": "DZS/BS_IN13",
     "note": "DZS BS_IN13 industrial production volume index, total industry, SA+WDA, 2021=100"},

    # 3. PPI — BS_PP11 domestic-market PPI level, Total industry, base 2021=100.
    {"slug": "ppi", "kind": "year_roman_month",
     "path": "Industrija/Indeks proizvođačkih cijena/BS_PP11.px",
     "query": {"DJELATNOSTI": "Ukupno", "GODINA": HR_RECENT_YEARS_15, "MJESEC": HR_ALL_MONTHS_ROMAN},
     "freq": "M", "unit": "Index (2021=100)", "adjustment": "NSA", "conversion": 1.0,
     "series_id": "DZS/BS_PP11",
     "note": "DZS BS_PP11 industrial producer price index, total industry, 2021=100"},

    # 4. Retail trade — BS_TR21 gross unadjusted value index, total retail trade G47, 2021=100.
    {"slug": "retail-sales", "kind": "year_roman_month",
     "path": "Trgovina na malo/BS_TR21.px",
     "query": {"DJELATNOSTI": "G47", "GODINA": HR_RECENT_YEARS_15, "MJESEC": HR_ALL_MONTHS_ROMAN},
     "freq": "M", "unit": "Index (2021=100)", "adjustment": "NSA", "conversion": 1.0,
     "series_id": "DZS/BS_TR21",
     "note": "DZS BS_TR21 retail trade turnover, total G47, gross value index 2021=100"},

    # 5. Wages — T1 (NKD 2025) average monthly NET earnings, total economy, EUR. Series starts 2025-01.
    {"slug": "wages", "kind": "year_numeric_month",
     "path": "Zaposlenost i plaće/Od 2025/T1.px",
     "query": {"DJELATNOST": "000", "GODINA": ["2025", "2026"],
               "PERIOD": HR_ALL_MONTHS_NUMERIC, "PLAĆA": "2"},
     "freq": "M", "unit": "EUR/month", "adjustment": "NSA", "conversion": 1.0,
     "series_id": "DZS/Wages_T1",
     "note": "DZS T1 average monthly net earnings, total economy NKD 2025, EUR (since Jan 2025)"},

    # 6. Quarterly GDP (level) — BDP-T01_EUR B1GQ current prices, Mln EUR -> Bln EUR.
    {"slug": "gdp-real", "kind": "year_quarter",
     "path": "Nacionalni racuni/BDP/Kvartalni nacionalni računi/BDP-T01_EUR.px",
     "query": {"Godina": HR_QUARTER_YEARS, "Tromjesečje": HR_ALL_QUARTERS,
               "Način prikaza": "1", "Pokazatelj": "B1GQ"},
     "freq": "Q", "unit": "Billion EUR (current prices)", "adjustment": "NSA", "conversion": 0.001,
     "series_id": "DZS/BDP-T01_EUR",
     "note": "DZS BDP-T01_EUR quarterly GDP B1GQ current prices, converted Mln->Bln EUR"},
]


def _hr_extract_dim(dim: dict, name: str) -> list[tuple[str, int]]:
    ix = dim[name].get("category", {}).get("index", {})
    if isinstance(ix, list):
        return [(c, p) for p, c in enumerate(ix)]
    return list(ix.items())


def _parse_dzs_year_month(js: dict, roman: bool) -> list[tuple[date, float]]:
    """DZS PxWeb tables with separate GODINA + MJESEC/PERIOD dimensions."""
    values = js.get("value", [])
    dim = js.get("dimension", {})
    dim_ids = js.get("id", [])
    sizes = js.get("size", [])
    if not values:
        return []
    year_dim = next((k for k in dim_ids if k.upper() in ("GODINA", "GODINE", "YEAR")), None)
    month_dim = next((k for k in dim_ids if k.upper() in ("MJESEC", "MJESECI", "MONTH", "PERIOD")), None)
    if not year_dim or not month_dim:
        return []
    yp = _hr_extract_dim(dim, year_dim)
    mp = _hr_extract_dim(dim, month_dim)
    out = []
    for ycode, ypos in yp:
        try:
            yy = int(ycode)
        except ValueError:
            continue
        for mcode, mpos in mp:
            if roman:
                mm = HR_ROMAN_MONTHS.get(mcode)
            else:
                try:
                    mm = int(mcode)
                except ValueError:
                    mm = None
            if mm is None or mm < 1 or mm > 12:
                continue
            indices = []
            for k in dim_ids:
                if k == year_dim:
                    indices.append(ypos)
                elif k == month_dim:
                    indices.append(mpos)
                else:
                    indices.append(0)
            flat = 0
            stride = 1
            for i in range(len(dim_ids) - 1, -1, -1):
                flat += indices[i] * stride
                stride *= sizes[i]
            if 0 <= flat < len(values):
                v = values[flat]
                if v is not None:
                    out.append((date(yy, mm, 1), float(v)))
    return sorted(out)


def _parse_dzs_year_quarter(js: dict) -> list[tuple[date, float]]:
    """BDP-T01: Godina + Tromjesečje (1..4); ignore code '5' (annual aggregate)."""
    values = js.get("value", [])
    dim = js.get("dimension", {})
    dim_ids = js.get("id", [])
    sizes = js.get("size", [])
    if not values:
        return []
    year_dim = next((k for k in dim_ids if k.lower() in ("godina", "year")), None)
    q_dim = next((k for k in dim_ids if k.lower() in ("tromjesečje", "tromjesecje", "quarter")), None)
    if not year_dim or not q_dim:
        return []
    yp = _hr_extract_dim(dim, year_dim)
    qp = _hr_extract_dim(dim, q_dim)
    out = []
    for ycode, ypos in yp:
        try:
            yy = int(ycode)
        except ValueError:
            continue
        for qcode, qpos in qp:
            try:
                q = int(qcode)
            except ValueError:
                continue
            if q < 1 or q > 4:
                continue
            indices = []
            for k in dim_ids:
                if k == year_dim:
                    indices.append(ypos)
                elif k == q_dim:
                    indices.append(qpos)
                else:
                    indices.append(0)
            flat = 0
            stride = 1
            for i in range(len(dim_ids) - 1, -1, -1):
                flat += indices[i] * stride
                stride *= sizes[i]
            if 0 <= flat < len(values):
                v = values[flat]
                if v is not None:
                    mm = {1: 1, 2: 4, 3: 7, 4: 10}[q]
                    out.append((date(yy, mm, 1), float(v)))
    return sorted(out)


def fetch_hr_pxweb(path: str, query_filters: dict, kind: str = "tid") -> list[tuple[date, float]]:
    """Generic DZS PxWeb POST. `kind` selects the time-axis parser."""
    import urllib.parse
    encoded_path = "/".join(urllib.parse.quote(p) for p in path.split("/"))
    url = f"https://web.dzs.hr/PXWeb/api/v1/en/{encoded_path}"
    body = {
        "query": [
            {"code": k, "selection": {"filter": "item",
                                      "values": v if isinstance(v, list) else [v]}}
            for k, v in query_filters.items()
        ],
        "response": {"format": "json-stat2"},
    }
    r = requests.post(url, json=body, timeout=30)
    r.raise_for_status()
    js = r.json()
    if kind == "tid":
        return _parse_jsonstat(js, "M")
    if kind == "year_roman_month":
        return _parse_dzs_year_month(js, roman=True)
    if kind == "year_numeric_month":
        return _parse_dzs_year_month(js, roman=False)
    if kind == "year_quarter":
        return _parse_dzs_year_quarter(js)
    return _parse_jsonstat(js, "M")'''

if OLD not in src:
    raise SystemExit('OLD pattern not found in file')

new_src = src.replace(OLD, NEW)
with open(fp, 'w', encoding='utf-8', newline='\n') as f:
    f.write(new_src)
print('OK — replaced', len(OLD), 'chars with', len(NEW), 'chars')
