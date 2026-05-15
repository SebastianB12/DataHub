"""ELSTAT (Hellenic Statistical Authority) direct provider for Greece.

ELSTAT does not publish a public SDMX REST or JSON API. Time-series data are
released as XLS/XLSX files through their Liferay-based publication portal
(www.statistics.gr) — the SAME files the press releases reference, with
filenames carrying the publication code, time range, and table number.

Indicators TE shows for GR that are sourced from ELSTAT directly:

  Stage 1 (already live):
    - inflation-cpi          DKT87  Table IV monthly CPI 1959-…  (XLSX, 2020=100)
    - industrial-production  DKT21  Table 04 SA monthly IPI 2000-…  (XLSX, 2021=100)
    - unemployment           SJO02  Table 1A monthly LFS 2004-…  (XLS legacy)

  Stage 2 (this commit):
    - ppi                    DKT15  Table 1 Total PPI 2021=100  (XLS legacy, current
                                    quarter only — ELSTAT publishes a "rolling" press
                                    release file, deep history requires archive scrape)
    - retail-sales           DKT39  Table 3 SA Turnover Index 2000-… (XLSX, 2021=100)
    - trade-balance          SFC02  Trade Balance SDDS monthly (XLSX, mEUR)
    - exports                SFC02  same workbook, EXPORTS-DISPATCHES col (mEUR)
    - imports                SFC02  same workbook, IMPORTS-ARRIVALS col (mEUR)
    - gdp-real               SEL84  Quarterly GDP SA chain-linked 2020 prices
                                    (XLS legacy, transposed wide)
    - employed-persons       SJO01  Table 3 Persons employed quarterly (NACE Rev 2
                                    aggregate, thousands)

  Documented gaps (NOT seeded — different publishers):
    - consumer-confidence    -> IOBE (Foundation for Economic & Industrial Research)
                                publishes the survey, NOT ELSTAT. TE attributes to
                                European Commission DG ECFIN — kept on Eurostat.
    - business-confidence    -> same as above, IOBE/DG ECFIN, kept on Eurostat.
    - current-account        -> Bank of Greece (bankofgreece.gr), NOT ELSTAT.
                                Future provider — BoG SDMX endpoint pending.

The download URL is the Liferay portlet "downloadResources" resource URL with a
stable numeric `documentID`. ELSTAT does not version these IDs — when a new
month is added they overwrite the same file. Filename always carries the period
range (verified across multiple downloads), e.g.:

  A0515_DKT87_TS_MM_01_1959_04_2026_04_F_EN.xlsx
  A0503_DKT21_TS_MM_01_2000_02_2026_04_P_EN.xlsx
  A0101_SJO02_TS_MM_01_2004_03_2026_01A_F_EN.xls

Validated 2026-05-09 against TE:
  - CPI April 2026 = 126.83 → YoY +5.45% (TE shows 5.40%, rounded)
  - IPI February 2026 SA index visible
  - Unemployment March 2026 SA = 9.0% (matches TE 9.0%)
"""
import io
import os
from datetime import date

import openpyxl
import requests
import xlrd
from dotenv import load_dotenv

from pipeline.base_provider import BaseProvider, DataPoint
from pipeline.transforms import normalize_date
from pipeline.db import upsert_data_points, log_pipeline_run, datapoints_to_rows

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))


HDR = {
    "User-Agent": "EconPulse/0.1 (Sebastian/SVM-AG)",
    "Accept": "*/*",
}


def _resource_url(document_id: int) -> str:
    """Build the stable Liferay 'downloadResources' URL for an ELSTAT document."""
    portlet = "documents_WAR_publicationsportlet_INSTANCE_Mr0GiQJSgPHd"
    return (
        "https://www.statistics.gr/en/statistics?"
        f"p_p_id={portlet}"
        "&p_p_lifecycle=2&p_p_state=normal&p_p_mode=view&p_p_cacheability=cacheLevelPage"
        f"&_{portlet}_javax.faces.resource=document"
        f"&_{portlet}_ln=downloadResources"
        f"&_{portlet}_documentID={document_id}"
        f"&_{portlet}_locale=en"
    )


# === CPI: DKT87, Table IV — Monthly evolution, base 2020=100 ============

CPI_DOC_ID = 114838  # "Monthly evolution of the Overall Consumer Price Index, 1959-…"

MONTHS_EN = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def fetch_elstat_cpi() -> list[tuple[date, float]]:
    """Download DKT87 Table IV (XLSX) and parse the year-major matrix."""
    r = requests.get(_resource_url(CPI_DOC_ID), headers=HDR, timeout=60)
    r.raise_for_status()
    wb = openpyxl.load_workbook(io.BytesIO(r.content), data_only=True, read_only=True)
    ws = wb.active

    out: list[tuple[date, float]] = []
    current_years: list[tuple[int, int]] = []  # [(col_index, year), ...]

    for row in ws.iter_rows(values_only=True):
        cells = list(row)
        # Header row containing "Month" then year ints across columns
        if "Month" in cells:
            idx = cells.index("Month")
            current_years = [
                (j, c) for j, c in enumerate(cells[idx + 1:], start=idx + 1)
                if isinstance(c, int) and 1900 <= c <= 2100
            ]
            continue
        if not current_years:
            continue
        # Find a month label in the row; that's a data row
        month_idx = next((i for i, c in enumerate(cells) if c in MONTHS_EN), None)
        if month_idx is None:
            continue
        month_num = MONTHS_EN.index(cells[month_idx]) + 1
        for col_j, year in current_years:
            v = cells[col_j] if col_j < len(cells) else None
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                try:
                    out.append((date(year, month_num, 1), float(v)))
                except ValueError:
                    pass
    out.sort()
    return out


# === IPI: DKT21, Sheet "INDUSTRIAL PRODUCTION INDEX" (SA, 2021=100) ======

IPI_DOC_ID = 114474  # "Seasonally Adjusted Industrial Production Index"


def fetch_elstat_ipi_sa() -> list[tuple[date, float]]:
    """Download DKT21 SA IPI XLSX. First sheet has columns: Year, Month,
    Index, Monthly rates (%). Year is only printed once per year.
    """
    r = requests.get(_resource_url(IPI_DOC_ID), headers=HDR, timeout=60)
    r.raise_for_status()
    wb = openpyxl.load_workbook(io.BytesIO(r.content), data_only=True, read_only=True)
    ws = wb["INDUSTRIAL PRODUCTION INDEX"] if "INDUSTRIAL PRODUCTION INDEX" in wb.sheetnames else wb.active

    out: list[tuple[date, float]] = []
    current_year: int | None = None
    for row in ws.iter_rows(values_only=True):
        cells = list(row)
        if not cells:
            continue
        # Year cell: first column is an int 1900..2100; month is second column int 1..12
        c0 = cells[0]
        if isinstance(c0, int) and 1900 <= c0 <= 2100:
            current_year = c0
        if current_year is None or len(cells) < 3:
            continue
        c1 = cells[1] if len(cells) > 1 else None
        if not isinstance(c1, int) or not (1 <= c1 <= 12):
            continue
        c2 = cells[2]
        if not isinstance(c2, (int, float)) or isinstance(c2, bool):
            continue
        out.append((date(current_year, c1, 1), float(c2)))
    out.sort()
    return out


# === LFS: SJO02, Table 1A — Monthly LFS unemployment rate SA ============

UNEMP_DOC_ID = 116021  # "Employment status and unemployment rate (Jan 2004 - …)"


def fetch_elstat_unemployment_sa() -> list[tuple[date, float]]:
    """Download SJO02 Table 1A (legacy .xls). Layout:
      row 0: title
      row 1: 'Unadjusted estimates' / 'Seasonally adjusted estimates' merged cells
      row 2: year header (col 0 = year int, then column labels)
      rows 3..14: months 'January'..'December' for that year
    Columns: 0=label, 1-4 unadj (Empl, Unempl, OutsideLF, UnemplRate),
             5-8 SA (Empl, Unempl, OutsideLF, UnemplRate)
    Year repeats every 13 rows. We only keep SA Unemployment rate (col 8).
    """
    r = requests.get(_resource_url(UNEMP_DOC_ID), headers=HDR, timeout=60)
    r.raise_for_status()
    wb = xlrd.open_workbook(file_contents=r.content)
    ws = wb.sheet_by_index(0)

    out: list[tuple[date, float]] = []
    current_year: int | None = None
    for r_i in range(ws.nrows):
        row = [ws.cell_value(r_i, c) for c in range(ws.ncols)]
        c0 = row[0]
        # Year header row: col 0 is a float year, others are header labels
        if isinstance(c0, float) and 1900 <= c0 <= 2100 and c0.is_integer():
            current_year = int(c0)
            continue
        if isinstance(c0, str) and c0 in MONTHS_EN and current_year is not None:
            month_num = MONTHS_EN.index(c0) + 1
            # SA unemployment rate is column index 8 (when present)
            if len(row) > 8 and isinstance(row[8], (int, float)) and row[8] != "":
                out.append((date(current_year, month_num, 1), float(row[8])))
    out.sort()
    return out


# === PPI: DKT15, "Total PPI" sheet — Monthly (current rolling quarter only) =

PPI_DOC_ID = 587776  # "Producer Price Index in Industry, base 2021=100, current quarter"


def fetch_elstat_ppi() -> list[tuple[date, float]]:
    """Download DKT15 'Total PPI' sheet (XLS legacy). Layout:
      row 11: header — col 0='Code', col 1='Description',
              col 2='Weight…', cols 3..N = 'YYYY_MM' period labels
      row 14: code '0020' Overall Market — values in cols 3..N
    We extract the Overall Market row only.
    """
    r = requests.get(_resource_url(PPI_DOC_ID), headers=HDR, timeout=60)
    r.raise_for_status()
    wb = xlrd.open_workbook(file_contents=r.content)
    ws = wb.sheet_by_name("Total PPI") if "Total PPI" in wb.sheet_names() else wb.sheet_by_index(0)

    # Locate header row (contains 'YYYY_MM' patterns)
    header_row: int | None = None
    period_cols: list[tuple[int, date]] = []
    for r_i in range(min(ws.nrows, 30)):
        row = [ws.cell_value(r_i, c) for c in range(ws.ncols)]
        labels = [(j, c) for j, c in enumerate(row) if isinstance(c, str) and len(c) == 7 and c[4] == "_"]
        if len(labels) >= 2:
            header_row = r_i
            for j, lbl in labels:
                try:
                    yr, mo = int(lbl[:4]), int(lbl[5:7])
                    if 1900 <= yr <= 2100 and 1 <= mo <= 12:
                        period_cols.append((j, date(yr, mo, 1)))
                except ValueError:
                    continue
            break
    if header_row is None or not period_cols:
        return []

    # Locate the "Overall Market" / code '0020' row
    out: list[tuple[date, float]] = []
    for r_i in range(header_row + 1, ws.nrows):
        c0 = ws.cell_value(r_i, 0)
        if str(c0).strip() in ("0020",) or (isinstance(c0, float) and int(c0) == 20):
            for col_j, dt in period_cols:
                v = ws.cell_value(r_i, col_j)
                if isinstance(v, (int, float)) and v != "" and not isinstance(v, bool):
                    out.append((dt, float(v)))
            break
    out.sort()
    return out


# === RETAIL: DKT39, SA Turnover Index — Monthly 2000-… (XLSX, 2021=100) ===

RETAIL_DOC_ID = 500036  # "Seasonally Adjusted Turnover Index in Retail Trade"

MONTHS_ROMAN = {
    "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6,
    "VII": 7, "VIII": 8, "IX": 9, "X": 10, "XI": 11, "XII": 12,
}


def fetch_elstat_retail_turnover_sa() -> list[tuple[date, float]]:
    """Download DKT39 SA Turnover (XLSX). Layout sheet 'TABLE 3':
      row 8+: col 0 = 'YYYY    I'..'YYYY    XII' (year only on month I row,
                                                   roman numerals thereafter),
              col 1 = Overall Index.
    """
    r = requests.get(_resource_url(RETAIL_DOC_ID), headers=HDR, timeout=60)
    r.raise_for_status()
    wb = openpyxl.load_workbook(io.BytesIO(r.content), data_only=True, read_only=True)
    ws = wb.active

    out: list[tuple[date, float]] = []
    current_year: int | None = None
    for row in ws.iter_rows(values_only=True):
        cells = list(row)
        if not cells:
            continue
        c0 = cells[0]
        if not isinstance(c0, str):
            continue
        label = c0.strip()
        # "YYYY    I" pattern — year + roman I
        parts = label.split()
        month_token: str | None = None
        if len(parts) >= 2 and parts[0].isdigit() and 1900 <= int(parts[0]) <= 2100:
            current_year = int(parts[0])
            month_token = parts[1]
        elif label in MONTHS_ROMAN:
            month_token = label
        if month_token is None or month_token not in MONTHS_ROMAN or current_year is None:
            continue
        v = cells[1] if len(cells) > 1 else None
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out.append((date(current_year, MONTHS_ROMAN[month_token], 1), float(v)))
    out.sort()
    return out


# === TRADE: SFC02, "TRADE BALANCE SDDS MONTHLY DATA" — 2004-… (XLSX, mEUR) ==

TRADE_DOC_ID = 115720  # "Imports/Exports/Trade Balance Intra+Extra EU, monthly"


def _fetch_elstat_trade_columns() -> list[tuple[date, float, float, float]]:
    """Returns rows of (date, imports_mEUR, exports_mEUR, balance_mEUR).
    Layout (SDDS MONTHLY sheet):
      header row idx 5 — cols 0,1 = imports YEAR/MONTH, col 2 = imports value,
                          cols 5,6 = exports YEAR/MONTH, col 7 = exports value,
                          col 10 = trade balance value.
    """
    r = requests.get(_resource_url(TRADE_DOC_ID), headers=HDR, timeout=60)
    r.raise_for_status()
    wb = openpyxl.load_workbook(io.BytesIO(r.content), data_only=True, read_only=True)
    ws = wb["TRADE BALANCE SDDS MONTHLY DATA"]

    out: list[tuple[date, float, float, float]] = []
    for row in ws.iter_rows(values_only=True):
        cells = list(row)
        if len(cells) < 11:
            continue
        yr, mo = cells[0], cells[1]
        if not (isinstance(yr, int) and isinstance(mo, int)
                and 2000 <= yr <= 2100 and 1 <= mo <= 12):
            continue
        imp, exp, bal = cells[2], cells[7], cells[10]
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                   for v in (imp, exp, bal)):
            continue
        out.append((date(yr, mo, 1), float(imp), float(exp), float(bal)))
    out.sort()
    return out


def fetch_elstat_imports() -> list[tuple[date, float]]:
    return [(d, imp) for d, imp, _, _ in _fetch_elstat_trade_columns()]


def fetch_elstat_exports() -> list[tuple[date, float]]:
    return [(d, exp) for d, _, exp, _ in _fetch_elstat_trade_columns()]


def fetch_elstat_trade_balance() -> list[tuple[date, float]]:
    return [(d, bal) for d, _, _, bal in _fetch_elstat_trade_columns()]


# === GDP REAL: SEL84, "GDP_SA_CLV20" — Quarterly chain-linked, 1995-… ======

GDP_DOC_ID = 115384  # "Quarterly GDP SA, chain-linked volumes constant 2020 prices"


def fetch_elstat_gdp_real() -> list[tuple[date, float]]:
    """Download SEL84 GDP file (XLS legacy). Wide-transposed layout:
      row 5: cols 1..N = '1995 Q1', '1995 Q2', … period labels (strings)
      row 6: col 0 = 'Gross Domestic Product', cols 1..N = values in mEUR.
    """
    r = requests.get(_resource_url(GDP_DOC_ID), headers=HDR, timeout=60)
    r.raise_for_status()
    wb = xlrd.open_workbook(file_contents=r.content)
    ws = wb.sheet_by_index(0)

    # Locate header row containing 'YYYY Q1' patterns
    header_row: int | None = None
    period_cols: list[tuple[int, date]] = []
    for r_i in range(min(ws.nrows, 15)):
        row = [ws.cell_value(r_i, c) for c in range(ws.ncols)]
        labels = []
        for j, c in enumerate(row):
            if isinstance(c, str) and " Q" in c:
                parts = c.replace("\xa0", " ").split()
                if len(parts) == 2 and parts[0].isdigit() and parts[1] in ("Q1", "Q2", "Q3", "Q4"):
                    yr = int(parts[0])
                    q = int(parts[1][1])
                    quarter_end_month = q * 3
                    labels.append((j, date(yr, quarter_end_month, 1)))
        if len(labels) >= 4:
            header_row = r_i
            period_cols = labels
            break
    if header_row is None:
        return []

    # The first row after header carrying 'Gross Domestic Product' string in col 0
    out: list[tuple[date, float]] = []
    for r_i in range(header_row + 1, ws.nrows):
        c0 = ws.cell_value(r_i, 0)
        if isinstance(c0, str) and "Gross Domestic Product" in c0:
            for col_j, dt in period_cols:
                v = ws.cell_value(r_i, col_j)
                if isinstance(v, (int, float)) and v != "" and not isinstance(v, bool):
                    out.append((dt, float(v)))
            break
    out.sort()
    return out


# === CPI SUB-INDICES: DKT87 Table VI doc 114839 — COICOP groups monthly ====

CPI_SUBGROUPS_DOC_ID = 114839  # "06. Monthly sub-indices of groups of items of CPI"

# Maps slug -> COICOP group label prefix (matches row[0] in DKT87 Table VI XLSX).
# Note: row labels start with the group number (1..13). We match by lowercased
# substring of the descriptive part after the number.
CPI_SUBGROUP_LABELS = {
    "cpi-food":                      "food and non-alcoholic",
    "cpi-clothing":                  "clothing and footwear",
    "cpi-housing-utilities":         "housing, water, electricity",
    "cpi-transportation":            "transport",
    "cpi-recreation-and-culture":    "recreation, sport and culture",
    "cpi-education":                 "education services",
}


def _fetch_elstat_cpi_subgroups() -> dict[str, list[tuple[date, float]]]:
    """Download DKT87 Table VI XLSX and parse monthly sub-indices for all
    COICOP groups in one pass. Layout: blocks of (Year YYYY header → header
    row with Jan..Dec → 13 data rows + Overall). Year header text is
    e.g. 'Year  2010' (single col 0). Header row has months in cols 1..12,
    'Average' in col 13.
    """
    r = requests.get(_resource_url(CPI_SUBGROUPS_DOC_ID), headers=HDR, timeout=60)
    r.raise_for_status()
    wb = openpyxl.load_workbook(io.BytesIO(r.content), data_only=True, read_only=True)
    ws = wb.active

    out: dict[str, list[tuple[date, float]]] = {slug: [] for slug in CPI_SUBGROUP_LABELS}
    current_year: int | None = None
    in_block = False
    rows = list(ws.iter_rows(values_only=True))
    for row in rows:
        cells = list(row)
        if not cells:
            continue
        c0 = cells[0]
        if isinstance(c0, str):
            s = c0.strip()
            # Year header
            if s.lower().startswith("year"):
                parts = s.split()
                for p in parts:
                    if p.isdigit() and 1900 <= int(p) <= 2100:
                        current_year = int(p)
                        in_block = False
                        break
                continue
            if s.lower().startswith("groups of") and current_year is not None:
                in_block = True
                continue
            if in_block and current_year is not None:
                # Strip leading group number "1 ", "10 ", etc.
                label = s
                if label and label[0].isdigit():
                    label = label.split(maxsplit=1)[-1] if " " in label else label
                low = label.lower()
                for slug, prefix in CPI_SUBGROUP_LABELS.items():
                    if low.startswith(prefix):
                        for m_idx in range(1, 13):
                            v = cells[m_idx] if m_idx < len(cells) else None
                            if isinstance(v, (int, float)) and not isinstance(v, bool):
                                out[slug].append((date(current_year, m_idx, 1), float(v)))
                        break
    for slug in out:
        out[slug].sort()
    return out


def fetch_elstat_cpi_food() -> list[tuple[date, float]]:
    return _fetch_elstat_cpi_subgroups()["cpi-food"]
def fetch_elstat_cpi_clothing() -> list[tuple[date, float]]:
    return _fetch_elstat_cpi_subgroups()["cpi-clothing"]
def fetch_elstat_cpi_housing_utilities() -> list[tuple[date, float]]:
    return _fetch_elstat_cpi_subgroups()["cpi-housing-utilities"]
def fetch_elstat_cpi_transportation() -> list[tuple[date, float]]:
    return _fetch_elstat_cpi_subgroups()["cpi-transportation"]
def fetch_elstat_cpi_recreation() -> list[tuple[date, float]]:
    return _fetch_elstat_cpi_subgroups()["cpi-recreation-and-culture"]
def fetch_elstat_cpi_education() -> list[tuple[date, float]]:
    return _fetch_elstat_cpi_subgroups()["cpi-education"]


# === LFS EMPLOYED: SJO01, Table 3 — Persons employed (quarterly, thousands) =

LFS_EMPLOYED_DOC_ID = 115983  # "Persons employed 15+ by economic activities"


def fetch_elstat_employed() -> list[tuple[date, float]]:
    """SJO01 Table 3 (XLS legacy). Two stacked tables:
      A) NACE Rev 1 — header row 2, 'Total employed' row 3 (2001..pre-2008)
      B) NACE Rev 2 — header row ~215, 'Total employed' row ~216 (2001..current)
    Strategy: scan all rows; if col 0 has a Greek/English 'Total employed' string,
    look upward for the most recent quarter-header row and align by column.
    """
    r = requests.get(_resource_url(LFS_EMPLOYED_DOC_ID), headers=HDR, timeout=60)
    r.raise_for_status()
    wb = xlrd.open_workbook(file_contents=r.content)
    ws = wb.sheet_by_index(0)

    rows = [[ws.cell_value(r_i, c) for c in range(ws.ncols)] for r_i in range(ws.nrows)]

    def parse_q_label(s) -> date | None:
        if not isinstance(s, str):
            return None
        s2 = " ".join(s.split())
        # Patterns: '1st quarter 2001', '2d quarter 2001', '3d quarter 2001', '4th quarter 2001'
        for prefix, q in (("1st", 1), ("2d", 2), ("3d", 3), ("4th", 4)):
            if s2.lower().startswith(prefix):
                tok = s2.split()
                for t in tok:
                    if t.isdigit() and 1900 <= int(t) <= 2100:
                        return date(int(t), q * 3, 1)
        return None

    # Collect (date, value) — prefer NACE Rev 2 table (later in the file)
    # so we walk from the BOTTOM. Find a 'Total employed' row, then look upward
    # for the matching header.
    out: dict[date, float] = {}
    last_header_cols: list[tuple[int, date]] = []
    for r_i, row in enumerate(rows):
        # detect header row
        labels = [(j, parse_q_label(c)) for j, c in enumerate(row)]
        labels = [(j, d) for j, d in labels if d is not None]
        if len(labels) >= 4:
            last_header_cols = labels
            continue
        # Total employed row
        col1 = row[1] if len(row) > 1 else None
        if isinstance(col1, str) and "Total employed" in col1 and last_header_cols:
            for col_j, dt in last_header_cols:
                v = row[col_j] if col_j < len(row) else None
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    # NACE Rev 2 (later in file) overwrites NACE Rev 1 -> good
                    out[dt] = float(v)

    return sorted(out.items())


SERIES = [
    {
        "slug": "inflation-cpi",
        "fetcher": fetch_elstat_cpi,
        "freq": "M",
        "unit": "Index (2020=100)",
        "adjustment": "NSA",
        "doc_id": CPI_DOC_ID,
        "publication": "DKT87",
        "note": "ELSTAT DKT87 Table IV monthly Overall CPI base 2020=100, 1959-onwards",
    },
    {
        "slug": "industrial-production",
        "fetcher": fetch_elstat_ipi_sa,
        "freq": "M",
        "unit": "Index (2021=100)",
        "adjustment": "SA",
        "doc_id": IPI_DOC_ID,
        "publication": "DKT21",
        "note": "ELSTAT DKT21 Seasonally Adjusted Industrial Production Index 2021=100, 2000-onwards",
    },
    {
        "slug": "unemployment",
        "fetcher": fetch_elstat_unemployment_sa,
        "freq": "M",
        "unit": "%",
        "adjustment": "SA",
        "doc_id": UNEMP_DOC_ID,
        "publication": "SJO02",
        "note": "ELSTAT SJO02 Table 1A LFS monthly unemployment rate (seasonally adjusted), 2004-onwards",
    },
    {
        "slug": "ppi",
        "fetcher": fetch_elstat_ppi,
        "freq": "M",
        "unit": "Index (2021=100)",
        "adjustment": "NSA",
        "doc_id": PPI_DOC_ID,
        "publication": "DKT15",
        "note": "ELSTAT DKT15 Total PPI Overall Market base 2021=100 (current rolling quarter press-release; deeper history via Eurostat sts_inpp_m fallback)",
    },
    {
        "slug": "retail-sales",
        "fetcher": fetch_elstat_retail_turnover_sa,
        "freq": "M",
        "unit": "Index (2021=100)",
        "adjustment": "SA",
        "doc_id": RETAIL_DOC_ID,
        "publication": "DKT39",
        "note": "ELSTAT DKT39 Table 3 SA Turnover Index in Retail Trade 2021=100, 2000-onwards",
    },
    {
        "slug": "imports",
        "fetcher": fetch_elstat_imports,
        "freq": "M",
        "unit": "Million EUR",
        "adjustment": "NSA",
        "doc_id": TRADE_DOC_ID,
        "publication": "SFC02",
        "note": "ELSTAT SFC02 Trade Balance SDDS monthly — imports/arrivals (intra+extra EU), 2004-onwards",
    },
    {
        "slug": "exports",
        "fetcher": fetch_elstat_exports,
        "freq": "M",
        "unit": "Million EUR",
        "adjustment": "NSA",
        "doc_id": TRADE_DOC_ID,
        "publication": "SFC02",
        "note": "ELSTAT SFC02 Trade Balance SDDS monthly — exports/dispatches (intra+extra EU), 2004-onwards",
    },
    {
        "slug": "trade-balance",
        "fetcher": fetch_elstat_trade_balance,
        "freq": "M",
        "unit": "Million EUR",
        "adjustment": "NSA",
        "doc_id": TRADE_DOC_ID,
        "publication": "SFC02",
        "note": "ELSTAT SFC02 Trade Balance SDDS monthly — exports - imports (intra+extra EU), 2004-onwards",
    },
    {
        "slug": "gdp-real",
        "fetcher": fetch_elstat_gdp_real,
        "freq": "Q",
        "unit": "Million EUR (chain-linked, 2020 prices)",
        "adjustment": "SA",
        "doc_id": GDP_DOC_ID,
        "publication": "SEL84",
        "note": "ELSTAT SEL84 Quarterly GDP SA chain-linked volumes constant 2020 prices, 1995-Q1 onwards",
    },
    # CPI sub-indices (COICOP groups, monthly, base 2020=100) — DKT87 Table VI
    {
        "slug": "cpi-food",
        "fetcher": fetch_elstat_cpi_food,
        "freq": "M",
        "unit": "Index (2020=100)",
        "adjustment": "NSA",
        "doc_id": CPI_SUBGROUPS_DOC_ID,
        "publication": "DKT87",
        "note": "ELSTAT DKT87 Table VI Group 1 Food & non-alcoholic beverages, base 2020=100",
    },
    {
        "slug": "cpi-clothing",
        "fetcher": fetch_elstat_cpi_clothing,
        "freq": "M",
        "unit": "Index (2020=100)",
        "adjustment": "NSA",
        "doc_id": CPI_SUBGROUPS_DOC_ID,
        "publication": "DKT87",
        "note": "ELSTAT DKT87 Table VI Group 3 Clothing & footwear, base 2020=100",
    },
    {
        "slug": "cpi-housing-utilities",
        "fetcher": fetch_elstat_cpi_housing_utilities,
        "freq": "M",
        "unit": "Index (2020=100)",
        "adjustment": "NSA",
        "doc_id": CPI_SUBGROUPS_DOC_ID,
        "publication": "DKT87",
        "note": "ELSTAT DKT87 Table VI Group 4 Housing/water/electricity/gas, base 2020=100",
    },
    {
        "slug": "cpi-transportation",
        "fetcher": fetch_elstat_cpi_transportation,
        "freq": "M",
        "unit": "Index (2020=100)",
        "adjustment": "NSA",
        "doc_id": CPI_SUBGROUPS_DOC_ID,
        "publication": "DKT87",
        "note": "ELSTAT DKT87 Table VI Group 7 Transport, base 2020=100",
    },
    {
        "slug": "cpi-recreation-and-culture",
        "fetcher": fetch_elstat_cpi_recreation,
        "freq": "M",
        "unit": "Index (2020=100)",
        "adjustment": "NSA",
        "doc_id": CPI_SUBGROUPS_DOC_ID,
        "publication": "DKT87",
        "note": "ELSTAT DKT87 Table VI Group 9 Recreation, sport & culture, base 2020=100",
    },
    {
        "slug": "cpi-education",
        "fetcher": fetch_elstat_cpi_education,
        "freq": "M",
        "unit": "Index (2020=100)",
        "adjustment": "NSA",
        "doc_id": CPI_SUBGROUPS_DOC_ID,
        "publication": "DKT87",
        "note": "ELSTAT DKT87 Table VI Group 10 Education services, base 2020=100",
    },
    {
        "slug": "employed-persons",
        "fetcher": fetch_elstat_employed,
        "freq": "Q",
        "unit": "Thousand persons",
        "adjustment": "NSA",
        "doc_id": LFS_EMPLOYED_DOC_ID,
        "publication": "SJO01",
        "note": "ELSTAT SJO01 Table 3 LFS Persons employed 15+ quarterly (NACE Rev 2 aggregate, thousands), 2001-onwards",
    },
]


class ElstatProvider(BaseProvider):
    name = "elstat"
    display_name = "ELSTAT (Hellenic Statistical Authority)"

    def fetch(self) -> list[DataPoint]:
        out: list[DataPoint] = []
        for cfg in SERIES:
            try:
                pairs = cfg["fetcher"]()
                for dt, v in pairs:
                    out.append(DataPoint(
                        indicator=cfg["slug"],
                        country="GR",
                        date=normalize_date(dt, cfg["freq"]),
                        value=round(float(v), 4),
                        source="elstat",
                        unit=cfg["unit"],
                        series_id=f"ELSTAT/{cfg['publication']}/{cfg['doc_id']}",
                        adjustment=cfg["adjustment"],
                    ))
                print(f"  OK {cfg['slug']}/GR ({cfg['publication']}): {len(pairs)} pts")
            except Exception as e:
                print(f"  FAIL {cfg['slug']}/GR ({cfg['publication']}): {e}")
        return out


def run():
    p = ElstatProvider()
    print(f"Fetching from {p.display_name}...")
    try:
        pts = p.fetch()
        print(f"\nTotal: {len(pts)} data points")
        rows = datapoints_to_rows(pts)
        total = 0
        for i in range(0, len(rows), 500):
            count = upsert_data_points(rows[i:i + 500])
            total += count
        log_pipeline_run("elstat", "success", total)
        print(f"\nDone. {total} rows upserted.")
    except Exception as e:
        log_pipeline_run("elstat", "failed", error_message=str(e))
        print(f"\nFailed: {e}")
        raise


if __name__ == "__main__":
    run()
