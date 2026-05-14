"""
DestatisProvider — Statistisches Bundesamt (GENESIS-Online) via pystatis.

Uses the canonical pystatis package (CorrelAid) which handles the GENESIS API quirks:
- 3-parallel-requests-per-user limit (auto-recovers via logincheck)
- Local caching to avoid redundant calls
- Pandas DataFrame output

For tables that exceed Destatis' synchronous-fetch size limit, pystatis would start
a background job — but our token is not authorised for jobs ("Code 12: Sie sind nicht
berechtigt diesen Service aufzurufen"). To keep big tables synchronous-only, we add a
direct-call helper `_fetch_table_direct` that lets the caller pass GENESIS server-side
filters (classifyingvariable1/2/3 + classifyingkey1/2/3, regionalvariable/key) so the
server returns only the slice we want. That keeps the response below the size cap.

We feed credentials in-memory (no ~/.pystatis/config.ini file with secrets).

API docs: https://www-genesis.destatis.de/datenbank/online/docs/
"""

import csv
import io
import os
import time
import zipfile
from datetime import date

import requests
from dotenv import load_dotenv

from pipeline.base_provider import BaseProvider, DataPoint
from pipeline.transforms import normalize_date
from pipeline.db import upsert_data_points, log_pipeline_run, datapoints_to_rows


load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

DIRECT_BASE_URL = "https://www-genesis.destatis.de/genesisWS/rest/2020/data/tablefile"
DIRECT_HEADERS_TEMPLATE = {
    "User-Agent": "Mozilla/5.0 (compatible; EconPulse/1.0)",
    "Content-Type": "application/x-www-form-urlencoded",
}


def _setup_pystatis() -> None:
    """Inject credentials into pystatis' in-memory config (no file write)."""
    token = os.environ.get("DESTATIS_TOKEN", "").strip()
    if not token:
        raise ValueError("DESTATIS_TOKEN not set in .env")

    import pystatis  # imported lazily so import-time failure doesn't break other providers
    from pystatis import config as cfg

    cfg.config.set("genesis", "username", token)
    cfg.config.set("genesis", "password", token)


# GENESIS tables to fetch.
#
# Each row picks rows from the ffcsv output via filters and turns them into DataPoints.
#   - filter_unit:       substring match against `value_unit` (e.g. "2020=100", "Prozent", "%")
#   - filter_value_code: exact match against `value_variable_code` (e.g. "WERTA" exports, "WERTE" imports)
#   - filter_series:     substring match against any cell (e.g. "ERW112")
#   - filter_region:     substring match against any cell, AND row must NOT contain
#                        regional-breakdown markers ("Früheres Bundesgebiet", "Neue Länder")
#   - conversion:        multiplier on raw values (e.g. 1e-6 to convert Tsd. EUR -> Billion EUR)
TABLES: list[dict] = [
    {
        "name": "61111-0002",  # VPI monatlich
        "indicator": "inflation-cpi",
        "filter_unit": "2020=100",
        "freq": "M",
        "unit": "Index",
        "adjustment": "NSA",
    },
    {
        "name": "13211-0002",  # Arbeitsmarktstatistik BA, monatlich
        "indicator": "unemployment",
        "filter_unit": "Prozent",
        "filter_series": "ERW112",  # Arbeitslosenquote aller zivilen Erwerbspersonen
        "filter_region": "Insgesamt",
        "freq": "M",
        "unit": "%",
        "adjustment": "NSA",
    },
    {
        "name": "61241-0002",  # Erzeugerpreise gewerblicher Produkte, monatlich (Index 2021=100)
        "indicator": "ppi",
        "filter_unit": "2021=100",
        "freq": "M",
        "unit": "Index",
        "adjustment": "NSA",
    },
    {
        "name": "51000-0002",  # Außenhandel Gesamt monatlich, Werte in Tsd. EUR
        "indicator": "exports",
        "filter_unit": "Tsd. EUR",
        "filter_value_code": "WERTA",  # Ausfuhr: Wert
        "conversion": 1e-6,  # Tsd. EUR -> Billion EUR
        "freq": "M",
        "unit": "Billion EUR",
        "adjustment": "NSA",
    },
    {
        "name": "51000-0002",
        "indicator": "imports",
        "filter_unit": "Tsd. EUR",
        "filter_value_code": "WERTE",  # Einfuhr: Wert
        "conversion": 1e-6,
        "freq": "M",
        "unit": "Billion EUR",
        "adjustment": "NSA",
    },
    {
        "name": "42151-0001",  # Auftragseingang im Verarbeitenden Gewerbe (Wertindex 2021=100)
        "indicator": "factory-orders",
        # Server-side filters (table is 5-dim, exceeds sync size cap without slicing)
        "classifyingvariable1": "WERT03",   "classifyingkey1": "WERTORG",      # Originalwerte
        "classifyingvariable2": "ABSATZ",   "classifyingkey2": "INSGESAMT",    # Inland+Ausland
        "classifyingvariable3": "WZ08Y1",   "classifyingkey3": "WZ08-C",       # Verarb. Gewerbe gesamt
        "filter_unit": "2021=100",
        "filter_value_code": "AUF101",
        "freq": "M",
        "unit": "Index",
        "adjustment": "NSA",
    },
    {
        "name": "61411-0002",  # Index der Einfuhrpreise — Deutschland insgesamt monatlich
        "indicator": "import-prices",
        "filter_unit": "2021=100",
        "freq": "M",
        "unit": "Index",
        "adjustment": "NSA",
    },
    {
        "name": "61421-0002",  # Index der Ausfuhrpreise — Deutschland insgesamt monatlich
        "indicator": "export-prices",
        "filter_unit": "2021=100",
        "freq": "M",
        "unit": "Index",
        "adjustment": "NSA",
    },
    {
        "name": "62361-0007",  # Index der durchschnittl. Bruttomonatsverdienste, monatlich, 2025=100
        "indicator": "wages",
        "filter_unit": "2025=100",
        "filter_value_code": "VST070",  # Bruttomonatsverdienste (nicht VST080 Stundenverdienste)
        "filter_attrs": {"3_variable_attribute_code": "WZ08-B-S"},  # Produzierendes Gewerbe + Dienstleistung (≈ Gesamtwirtschaft)
        "freq": "M",
        "unit": "Index",
        "adjustment": "NSA",
    },
    # ============== DE Stage-2 (TE-source-conformity) — 2026-05-14 ==============
    # Retail-sales: Umsatz im Einzelhandel ohne KFZ/Tankstellen (WZ47-02), real, original, 2015=100
    # Big table — needs server-side classifying filters to stay under sync size cap.
    {
        "name": "45212-0005",
        "indicator": "retail-sales",
        "classifyingvariable1": "WZ08E7",   "classifyingkey1": "WZ08-47-02",  # Einzelhandel ohne Kfz/Tankstellen
        "classifyingvariable2": "WERTE4",   "classifyingkey2": "REAL",        # Preisbereinigt (Realumsatz)
        "classifyingvariable3": "WERT03",   "classifyingkey3": "WERTORG",     # Originalwerte
        "filter_unit": "2015=100",
        "filter_value_code": "UMS002",
        "freq": "M",
        "unit": "Index",
        "adjustment": "NSA",
    },
    # Manufacturing-production: Produktionsindex, WZ08-C (Verarbeitendes Gewerbe), Original
    {
        "name": "42153-0001",
        "indicator": "manufacturing-production",
        "classifyingvariable1": "WERT03",   "classifyingkey1": "WERTORG",  # Originalwerte
        "classifyingvariable2": "WZ08V1",   "classifyingkey2": "WZ08-C",   # Verarb. Gewerbe
        "filter_unit": "2021=100",
        "filter_value_code": "PRO101",
        "freq": "M",
        "unit": "Index",
        "adjustment": "NSA",
    },
    # Mining-production: same table, WZ08-B (Bergbau)
    {
        "name": "42153-0001",
        "indicator": "mining-production",
        "classifyingvariable1": "WERT03",   "classifyingkey1": "WERTORG",
        "classifyingvariable2": "WZ08V1",   "classifyingkey2": "WZ08-B",
        "filter_unit": "2021=100",
        "filter_value_code": "PRO101",
        "freq": "M",
        "unit": "Index",
        "adjustment": "NSA",
    },
    # Industrial-production: Produktionsindex, "Produzierendes Gewerbe ohne Baugewerbe" (Industrie inkl. Energie)
    {
        "name": "42153-0001",
        "indicator": "industrial-production",
        "classifyingvariable1": "WERT03",   "classifyingkey1": "WERTORG",
        "classifyingvariable2": "WZ08V1",   "classifyingkey2": "WZ08-BCDE",
        "filter_unit": "2021=100",
        "filter_value_code": "PRO101",
        "filter_attrs": {
            "4_variable_attribute_code": "WZ08-B-18",  # Produzierendes Gewerbe ohne Baugewerbe (Industrie-Headline)
        },
        "freq": "M",
        "unit": "Index",
        "adjustment": "NSA",
    },
    # Employed-persons: Erwerbstaetige Inlaenderkonzept, monatlich (in Tsd.)
    # March 2026 KONZEPTW Original = 45,519 (TE-conform)
    {
        "name": "13321-0001",
        "indicator": "employed-persons",
        "filter_unit": "1000",
        "filter_value_code": "ERW002",
        "filter_attrs": {
            "3_variable_attribute_code": "KONZEPTW",  # Inlaenderkonzept (residents)
            "4_variable_attribute_code": "WERTORG",   # Originalwerte
        },
        "freq": "M",
        "unit": "Thousand persons",
        "adjustment": "NSA",
    },
    # Youth-unemployment-rate: Erwerbslosenquote 15-24, monatlich, beide Geschlechter, saisonbereinigt (X13)
    # March 2026 = 7.5% (TE-conform)
    {
        "name": "13231-0003",
        "indicator": "youth-unemployment-rate",
        "filter_unit": "Prozent",
        "filter_value_code": "ERW089",
        "filter_attrs": {
            "3_variable_attribute_code": "X13JDTB",   # X13 JDemetra+ saisonbereinigt (matches TE 7.5)
            "4_variable_attribute_code": "",           # Insgesamt (beide Geschlechter)
            "5_variable_attribute_code": "ALT015B25",  # 15-24 Jahre
        },
        "freq": "M",
        "unit": "%",
        "adjustment": "SA",
    },
    # Population: Bevoelkerung Stichtag, annual
    {
        "name": "12411-0001",
        "indicator": "population",
        "filter_unit": "Anzahl",
        "filter_value_code": "BEVSTD",
        "conversion": 1e-6,  # absolute Personen -> Mio
        "freq": "A",
        "unit": "Million",
        "adjustment": "NSA",
    },
    # Government-debt level: Schulden beim nicht-oeffentl. Bereich, Quartalsende
    # Insgesamt: alle 2_/3_/4_ Attribute = leerer Code (= "Insgesamt"); Q4 2025 TE = 2,661,549 Mill. EUR
    {
        "name": "71311-0001",
        "indicator": "government-debt",
        "filter_unit": "Mill. EUR",
        "filter_value_code": "SLD016",
        "filter_attrs": {
            "2_variable_attribute_code": "",  # Insgesamt (alle Ebenen)
            "3_variable_attribute_code": "",  # Insgesamt (Kern + Extrahaushalte)
            "4_variable_attribute_code": "",  # Insgesamt (alle Schuldenarten)
        },
        "freq": "Q",
        "unit": "Million EUR",
        "adjustment": "NSA",
    },
    # Government-debt-total: same series (TE has dupe slug)
    {
        "name": "71311-0001",
        "indicator": "government-debt-total",
        "filter_unit": "Mill. EUR",
        "filter_value_code": "SLD016",
        "filter_attrs": {
            "2_variable_attribute_code": "",
            "3_variable_attribute_code": "",
            "4_variable_attribute_code": "",
        },
        "freq": "Q",
        "unit": "Million EUR",
        "adjustment": "NSA",
    },
    # Consumer-spending: Private Konsumausgaben, sa real chain, Mrd EUR (Q4 2025 TE = 484.81)
    {
        "name": "81000-0020",
        "indicator": "consumer-spending",
        "filter_value_code": "VGR035",
        "filter_attrs": {
            "3_variable_attribute_code": "X13JDKSB",  # X13 kalender- und saisonbereinigt
            "4_variable_attribute_code": "VGRPVK",     # preisbereinigt, verkettete Volumenang. Mrd EUR
        },
        "freq": "Q",
        "unit": "Billion EUR",
        "adjustment": "SA",
    },
    # Government-spending: Konsumausgaben des Staates, sa real chain (Q4 2025 TE = 209.33)
    {
        "name": "81000-0020",
        "indicator": "government-spending",
        "filter_value_code": "VGR015",
        "filter_attrs": {
            "3_variable_attribute_code": "X13JDKSB",
            "4_variable_attribute_code": "VGRPVK",
        },
        "freq": "Q",
        "unit": "Billion EUR",
        "adjustment": "SA",
    },
    # Gross-fixed-capital-formation: Bruttoanlageinvestitionen, sa real chain (Q4 2025 TE = 177.05)
    {
        "name": "81000-0020",
        "indicator": "gross-fixed-capital-formation",
        "filter_value_code": "VGR041",
        "filter_attrs": {
            "3_variable_attribute_code": "X13JDKSB",
            "4_variable_attribute_code": "VGRPVK",
        },
        "freq": "Q",
        "unit": "Billion EUR",
        "adjustment": "SA",
    },
    # Disposable-personal-income: Bezugsgroesse fuer Sparquote = SA Verfuegb.Einkommen (Q4 2025 TE = 670.87)
    {
        "name": "81000-0010",
        "indicator": "disposable-personal-income",
        "filter_unit": "Mrd. EUR",
        "filter_value_code": "VGR092",
        "filter_attrs": {
            "3_variable_attribute_code": "X13JDSB",  # X13 JDemetra+ saisonbereinigt
        },
        "freq": "Q",
        "unit": "Billion EUR",
        "adjustment": "SA",
    },
    # Budget-deficit: Finanzierungssaldo des Staates, annual Mrd EUR
    # TE shows -2.7% of GDP for 2025 = -119.147 / ~4400 GDP. Frontend computes ratio.
    {
        "name": "81000-0031",
        "indicator": "budget-deficit",
        "filter_unit": "Mrd. EUR",
        "filter_value_code": "VGR114",
        "freq": "A",
        "unit": "Billion EUR",
        "adjustment": "NSA",
    },
]


MONTH_MAP = {
    "Januar": 1, "Februar": 2, "März": 3, "April": 4,
    "Mai": 5, "Juni": 6, "Juli": 7, "August": 8,
    "September": 9, "Oktober": 10, "November": 11, "Dezember": 12,
}

QUARTER_MAP = {
    "1. Quartal": 1, "2. Quartal": 4, "3. Quartal": 7, "4. Quartal": 10,
    "Quartal 1": 1, "Quartal 2": 4, "Quartal 3": 7, "Quartal 4": 10,
}


def _fetch_table(name: str, startyear: str = "1991", retries: int = 5):
    """Fetch a GENESIS table via pystatis with retry on transient 5xx.

    Returns the pandas DataFrame (raw ffcsv layout, prettify=False).
    """
    import pystatis
    from pystatis import Table

    last_exc = None
    for attempt in range(retries):
        if attempt:
            time.sleep(15 * attempt)  # 0, 15, 30, 45, 60 ...
        try:
            t = Table(name)
            t.get_data(
                prettify=False,
                compress=False,
                language="de",
                startyear=startyear,
            )
            return t.data
        except Exception as e:
            last_exc = e
            msg = str(e)
            # 502/503 are transient — retry. Other errors are real, fail fast.
            if "502" in msg or "503" in msg or "504" in msg:
                continue
            raise


def _fetch_table_direct(table: dict, startyear: str = "1991"):
    """Direct POST to /data/tablefile with server-side classifying filters.

    Used for tables that would trigger Destatis' background-job mode (which our
    token is not authorised for). The classifying* params reduce the table slice
    below the synchronous size cap.

    Expected `table` keys:
      name, classifyingvariable1/2/3, classifyingkey1/2/3,
      regionalvariable, regionalkey

    Returns a pandas DataFrame in the same ffcsv shape as pystatis prettify=False.
    """
    import pandas as pd
    token = os.environ.get("DESTATIS_TOKEN", "").strip()
    if not token:
        raise ValueError("DESTATIS_TOKEN not set in .env")

    headers = {**DIRECT_HEADERS_TEMPLATE, "username": token, "password": token}
    data = {
        "name": table["name"],
        "area": "all",
        "format": "ffcsv",
        "language": "de",
        "compress": "true",
        "startyear": startyear,
    }
    for key in (
        "classifyingvariable1", "classifyingkey1",
        "classifyingvariable2", "classifyingkey2",
        "classifyingvariable3", "classifyingkey3",
        "regionalvariable", "regionalkey",
    ):
        if table.get(key):
            data[key] = table[key]

    last_exc = None
    for attempt in range(5):
        if attempt:
            time.sleep(15 * attempt)
        try:
            resp = requests.post(DIRECT_BASE_URL, headers=headers, data=data, timeout=(30, 240))
            ct = resp.headers.get("content-type", "")
            if "json" in ct:
                # Real API error JSON — Code 6 (parallel) → retry; others fail
                payload = resp.json() if resp.text else {}
                code = payload.get("Status", {}).get("Code") or payload.get("Code")
                content = payload.get("Status", {}).get("Content") or payload.get("Content", "")
                if code == 6:
                    last_exc = RuntimeError(f"Code 6 parallel limit ({content[:120]})")
                    continue
                raise RuntimeError(f"Destatis Code {code}: {content[:200]}")
            if resp.status_code in (502, 503, 504):
                last_exc = RuntimeError(f"HTTP {resp.status_code}")
                continue
            resp.raise_for_status()
            # ZIP with one CSV inside
            z = zipfile.ZipFile(io.BytesIO(resp.content))
            csv_text = z.read(z.namelist()[0]).decode("utf-8-sig")
            return pd.read_csv(io.StringIO(csv_text), sep=";", dtype=str, na_filter=False)
        except (requests.RequestException, zipfile.BadZipFile) as e:
            last_exc = e
            continue
    raise RuntimeError(f"{table['name']}: direct-fetch retries exhausted: {last_exc}") from last_exc
    raise RuntimeError(f"{name}: {retries} retries exhausted: {last_exc}") from last_exc


def _parse_period(year_str: str, sub_label: str, freq: str) -> date | None:
    """Parse GENESIS period fields to a normalised date.

    `year_str` may be "1991" or a full date "2024-12-31" (when the table's
    primary time-dim is Stichtag).
    """
    # Try full date first (Stichtag tables)
    try:
        if len(year_str) >= 10 and "-" in year_str:
            return date.fromisoformat(year_str[:10])
    except ValueError:
        pass

    try:
        year = int(year_str[:4])
    except (ValueError, TypeError):
        return None

    if freq == "M":
        month = MONTH_MAP.get(sub_label)
        return date(year, month, 1) if month else None
    if freq == "Q":
        month = QUARTER_MAP.get(sub_label)
        return date(year, month, 1) if month else None
    return date(year, 1, 1)


def _row_matches(row: dict, filter_series: str, filter_region: str) -> bool:
    """Apply series/region filters."""
    if filter_series:
        haystack = ";".join(str(v) for v in row.values())
        if filter_series not in haystack:
            return False

    if filter_region:
        haystack = ";".join(str(v) for v in row.values())
        if "Früheres Bundesgebiet;" in haystack or "Neue Länder;" in haystack:
            # Skip regional breakdowns — only accept rows that match `filter_region` in any attribute
            attr_hits = [v for k, v in row.items() if "attribute_label" in k and filter_region in str(v)]
            if not attr_hits:
                return False
        elif filter_region not in haystack:
            return False
    return True


def _parse_dataframe(df, table: dict) -> list[DataPoint]:
    """Convert a GENESIS ffcsv DataFrame into DataPoints for one indicator."""
    indicator = table["indicator"]
    freq = table.get("freq", "M")
    filter_unit = table.get("filter_unit", "")
    filter_value_code = table.get("filter_value_code", "")
    filter_series = table.get("filter_series", "")
    filter_region = table.get("filter_region", "")
    filter_attrs = table.get("filter_attrs") or {}  # generic dict {col_name: substring_or_exact}
    conversion = float(table.get("conversion", 1))
    dp_unit = table.get("unit", "")
    adjustment = table.get("adjustment", "")

    points: list[DataPoint] = []
    for _, row in df.iterrows():
        d = row.to_dict()

        unit = str(d.get("value_unit", "")).strip()
        if filter_unit and filter_unit not in unit:
            continue
        if filter_value_code and str(d.get("value_variable_code", "")).strip() != filter_value_code:
            continue
        if filter_attrs:
            mismatch = False
            for col, expected in filter_attrs.items():
                raw = d.get(col, "")
                # pystatis returns NaN (float) for empty cells; normalise to ""
                if raw is None:
                    val = ""
                else:
                    s = str(raw).strip()
                    val = "" if s.lower() == "nan" else s
                if val != expected:
                    mismatch = True
                    break
            if mismatch:
                continue
        if not _row_matches(d, filter_series, filter_region):
            continue

        value_str = str(d.get("value", "")).strip()
        if not value_str or value_str in ("-", "...", "nan"):
            continue
        try:
            value = float(value_str.replace(",", "."))
        except ValueError:
            continue

        year_str = str(d.get("time", "")).strip()
        sub_label = str(d.get("1_variable_attribute_label", "")).strip()
        if not sub_label:
            sub_label = str(d.get("2_variable_attribute_label", "")).strip()

        dt = _parse_period(year_str, sub_label, freq)
        if not dt:
            continue

        points.append(DataPoint(
            indicator=indicator,
            country="DE",
            date=normalize_date(dt, freq),
            value=round(value * conversion, 2),
            source="destatis",
            unit=dp_unit,
            series_id=table["name"],
            adjustment=adjustment,
        ))
    return points


def _compute_trade_balance(points: list[DataPoint]) -> list[DataPoint]:
    """Build trade-balance DataPoints by subtracting imports from exports per date."""
    exports = {p.date: p for p in points if p.indicator == "exports" and p.country == "DE"}
    imports = {p.date: p for p in points if p.indicator == "imports" and p.country == "DE"}
    out: list[DataPoint] = []
    for dt, ex in exports.items():
        im = imports.get(dt)
        if not im:
            continue
        out.append(DataPoint(
            indicator="trade-balance",
            country="DE",
            date=dt,
            value=round(ex.value - im.value, 2),
            source="destatis",
            unit=ex.unit,
            series_id="51000-0002",
            adjustment=ex.adjustment,
        ))
    return out


class DestatisProvider(BaseProvider):
    name = "destatis"
    display_name = "Statistisches Bundesamt"

    def __init__(self):
        _setup_pystatis()

    def fetch(self) -> list[DataPoint]:
        # Once at the start, clear any stale 15-min sessions on our token.
        try:
            import pystatis
            status = pystatis.logincheck("genesis")
            print(f"  logincheck: {status[:120]}")
        except Exception as e:
            print(f"  logincheck failed (non-fatal): {e}")

        all_points: list[DataPoint] = []

        for table in TABLES:
            try:
                # Use direct-call when classifyingkey filters are needed (big tables)
                fetcher = _fetch_table_direct if table.get("classifyingkey1") else _fetch_table
                df = fetcher(table, startyear=table.get("startyear", "1991")) if fetcher is _fetch_table_direct else _fetch_table(table["name"], startyear=table.get("startyear", "1991"))
                points = _parse_dataframe(df, table)
                all_points.extend(points)

                dates = [p.date for p in points]
                if dates:
                    print(f"  OK {table['indicator']} ({table['name']}): {len(points)} points "
                          f"({min(dates)} - {max(dates)})")
                else:
                    print(f"  EMPTY {table['indicator']} ({table['name']}): df={len(df)} rows but 0 matched filters")

                time.sleep(2)  # gentle pacing between tables
            except Exception as e:
                print(f"  FAIL {table['indicator']} ({table['name']}): {e}")

        # Compute trade-balance from exports/imports if both are present
        balance = _compute_trade_balance(all_points)
        if balance:
            print(f"  OK trade-balance (computed): {len(balance)} points "
                  f"({min(p.date for p in balance)} - {max(p.date for p in balance)})")
            all_points.extend(balance)

        return all_points


def run():
    """Run the Destatis provider and write to Supabase."""
    provider = DestatisProvider()
    print(f"Fetching data from {provider.display_name}...")

    try:
        points = provider.fetch()
        print(f"\nTotal: {len(points)} data points")

        rows = datapoints_to_rows(points)

        total_upserted = 0
        batch_size = 500
        for i in range(0, len(rows), batch_size):
            batch = rows[i : i + batch_size]
            count = upsert_data_points(batch)
            total_upserted += count
            print(f"  Upserted batch {i // batch_size + 1}: {count} rows")

        log_pipeline_run("destatis", "success", total_upserted)
        print(f"\nDone. {total_upserted} rows upserted to Supabase.")

    except Exception as e:
        log_pipeline_run("destatis", "failed", error_message=str(e))
        print(f"\nFailed: {e}")
        raise


if __name__ == "__main__":
    run()
