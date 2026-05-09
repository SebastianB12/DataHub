"""
GaccProvider — General Administration of Customs of China (english.customs.gov.cn).

Source for TE's "China Balance of Trade", "China Exports", "China Imports".

Strategy: parse the "Monthly Bulletin" index page for current year (and recent
years), extract bulletin URLs for "Summary of Imports and Exports (In USD)
Monthly" (item B), fetch the table and extract Year-Month / Total / Export /
Import / Balance rows. Each bulletin contains 12+ months of data; fetching the
latest available month-bulletin per year covers everything we need.

API: HTML scraping. No key. Stable URL pattern with hex-GUID per bulletin.
"""

import re
import time
from datetime import date

import requests

from pipeline.base_provider import BaseProvider, DataPoint
from pipeline.transforms import normalize_date
from pipeline.db import upsert_data_points, log_pipeline_run, datapoints_to_rows

INDEX_URL = "http://english.customs.gov.cn/statics/report/monthly.html"
BULLETIN_BASE = "http://english.customs.gov.cn"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; EconPulse/1.0)"}


def _get_with_retry(url: str, retries: int = 3, base_delay: float = 5.0) -> requests.Response:
    last_exc: BaseException | None = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            if resp.status_code in (502, 503, 504):
                last_exc = RuntimeError(f"HTTP {resp.status_code}")
                time.sleep(base_delay * (attempt + 1))
                continue
            resp.raise_for_status()
            return resp
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_exc = exc
            if attempt == retries - 1:
                raise
            time.sleep(base_delay * (attempt + 1))
    raise last_exc  # unreachable


def _fetch_bulletin_index() -> dict[str, list[tuple[str, str]]]:
    """Return dict {year: [(month_label, bulletin_url), ...]} for the
    'Summary of Imports and Exports (In USD) B：Monthly' row of the index page.

    The index page table has 18 rows. Row 1 is "(1) Summary (In USD) A:
    Annually", row 2 is "(1) Summary (In USD) B:Monthly" — the one we want.
    The HTML uses fullwidth Chinese parens/colons that complicate text matching,
    so we just take the row by position.
    """
    resp = _get_with_retry(INDEX_URL)
    html = resp.text

    # Year selector options: <option value="2026">2026</option> — first one is
    # current year.
    years = re.findall(r'<option[^>]+value="(\d{4})"', html)
    current_year = years[0] if years else str(date.today().year)

    rows = re.findall(r'<tr><td>(.*?)</td><td>(.*?)</td></tr>', html, re.DOTALL)
    if len(rows) < 2:
        return {}

    # Row index 1 = "Summary B Monthly"
    _title, cell = rows[1]
    links = re.findall(r'<a[^>]+href=([^>\s]+)>\s*(\w+)\.\s*</a>', cell)
    if not links:
        return {}
    return {current_year: [(month, url) for url, month in links]}


def _parse_bulletin_table(html: str) -> list[tuple[str, int, int, int, int]]:
    """Parse the bulletin's data table → list of (year_month, total, export, import, balance).
    All values in USD million.
    """
    table_match = re.search(r'<table[^>]*>(.*?)</table>', html, re.DOTALL)
    if not table_match:
        return []
    table_html = table_match.group(1)
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', table_html, re.DOTALL)

    out: list[tuple[str, int, int, int, int]] = []
    for row in rows:
        cells = re.findall(r'<t[hd][^>]*>(.*?)</t[hd]>', row, re.DOTALL)
        cells_clean = [
            re.sub(r'<[^>]+>|&nbsp;|&amp;', ' ', c).strip().replace(",", "")
            for c in cells
        ]
        if not cells_clean:
            continue
        ym = cells_clean[0]
        if not re.match(r'^\d{4}\.\d{2}$', ym):
            continue
        # Columns: YYYY.MM | Total | Export | Import | Balance | (cumulative same 4)
        try:
            total, export, imp, balance = (int(cells_clean[i]) for i in (1, 2, 3, 4))
        except (ValueError, IndexError):
            continue
        out.append((ym, total, export, imp, balance))
    return out


_MONTH_NUM = {f"{i:02d}": i for i in range(1, 13)}


def _to_dataset(rows: list[tuple[str, int, int, int, int]]) -> list[DataPoint]:
    """Build DataPoints for exports / imports / trade-balance CN."""
    points: list[DataPoint] = []
    for ym, _total, exp_m, imp_m, bal_m in rows:
        y, m = ym.split(".")
        try:
            dt = date(int(y), int(m), 1)
        except ValueError:
            continue
        norm = normalize_date(dt, "M")
        # USD million → USD billion (TE labels match)
        for indicator, value_m in (
            ("exports", exp_m),
            ("imports", imp_m),
            ("trade-balance", bal_m),
        ):
            points.append(DataPoint(
                indicator=indicator,
                country="CN",
                date=norm,
                value=round(value_m / 1000, 2),
                source="gacc",
                unit="Billion USD",
                series_id=f"GACC:{indicator}",
                adjustment="NSA",
            ))
    return points


class GaccProvider(BaseProvider):
    name = "gacc"
    display_name = "General Administration of Customs of China"

    def fetch(self) -> list[DataPoint]:
        index = _fetch_bulletin_index()
        if not index:
            print("  GACC: index parse returned no bulletin URLs")
            return []

        all_rows: dict[str, tuple[str, int, int, int, int]] = {}
        # Fetch the latest bulletin per year (each contains the full YTD table
        # with prior-year comparison rows). Iterate descending.
        for year in sorted(index, reverse=True):
            month_links = index[year]
            if not month_links:
                continue
            # Take the bulletin from the latest published month
            month_label, url = month_links[-1]
            full_url = url if url.startswith("http") else f"{BULLETIN_BASE}{url}"
            try:
                resp = _get_with_retry(full_url)
                rows = _parse_bulletin_table(resp.text)
                for r in rows:
                    all_rows[r[0]] = r
                print(f"  GACC bulletin {year} {month_label}: {len(rows)} rows")
                time.sleep(2)
            except Exception as exc:
                print(f"  GACC FAIL bulletin {year} {month_label}: {exc}")

        rows_sorted = sorted(all_rows.values())
        points = _to_dataset(rows_sorted)
        print(f"  GACC: {len(points)} data points "
              f"({len(rows_sorted)} months × 3 indicators)")
        return points


def run():
    provider = GaccProvider()
    print(f"Fetching data from {provider.display_name}...")
    try:
        points = provider.fetch()
        print(f"\nTotal: {len(points)} data points")
        if not points:
            log_pipeline_run("gacc", "success", 0)
            return
        rows = datapoints_to_rows(points)
        total = 0
        for i in range(0, len(rows), 500):
            count = upsert_data_points(rows[i:i + 500])
            total += count
            print(f"  Upserted batch {i // 500 + 1}: {count} rows")
        log_pipeline_run("gacc", "success", total)
        print(f"Done. {total} rows upserted.")
    except Exception as exc:
        log_pipeline_run("gacc", "failed", error_message=str(exc))
        print(f"Failed: {exc}")
        raise


if __name__ == "__main__":
    run()
