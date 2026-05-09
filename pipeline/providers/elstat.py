"""ELSTAT (Hellenic Statistical Authority) direct provider for Greece.

ELSTAT does not publish a public SDMX REST or JSON API. Time-series data are
released as XLS/XLSX files through their Liferay-based publication portal
(www.statistics.gr) — the SAME files the press releases reference, with
filenames carrying the publication code, time range, and table number.

Three primary indicators TE shows for GR are sourced from ELSTAT directly:
  - inflation-cpi          DKT87  Table IV monthly CPI 1959-…  (XLSX, 2020=100)
  - industrial-production  DKT21  Table 04 SA monthly IPI 2000-…  (XLSX, 2021=100)
  - unemployment           SJO02  Table 1A monthly LFS 2004-…  (XLS legacy)

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
