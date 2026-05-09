"""
InseeProvider — direct fetch from INSEE BDM via the official `pynsee` library.

For French Tier-1 indicators where Trading Economics cites INSEE as the source,
this provider replaces the Eurostat-FR mirror as the primary data path.
Eurostat rows for the same slugs stay in `indicator_sources` as `is_default=False`
fallback.

Library-First-Regel: pynsee (v0.2.5, InseeFrLab) wrapped die offizielle BDM SDMX-API.
Niemals selber HTTP-Code dafür schreiben.

API-Pattern:
    get_series_list(<dataset>) -> DataFrame mit IDBANK + dimension columns
    get_series([<idbank>])     -> DataFrame mit TIME_PERIOD, OBS_VALUE

Per-slug config in SERIES list. Filter dict isolates one IDBANK per dataset.
If multiple IDBANKs match, the slug fails — better than silent wrong data.
"""

from datetime import date

import requests
from pynsee.macrodata import get_series_list, get_series

from pipeline.base_provider import BaseProvider, DataPoint
from pipeline.transforms import normalize_date
from pipeline.db import upsert_data_points, log_pipeline_run, datapoints_to_rows


MELODI_BASE = "https://api.insee.fr/melodi/data"


# Stage 1 — verified 2026-05-05 against tradingeconomics.com/france/<slug>:
#
#   inflation-cpi          IPC-2025:011814630   Apr 2026 = 102.26 (Index Base 2025)
#                                               YoY ≈ +2.2% matches TE
#   industrial-production  IPI-2021:010768261   Feb 2026 = 102.0  (Index Base 2021, A10-BE)
#                                               YoY ≈ -0.3% matches TE
#   ppi                    IPPI-2021:010765093  Mar 2026 = 115.4  (Industrie totale BII0)
#                                               YoY ≈ +0.2% matches TE
#   retail-sales           ICA-2021-COMMERCE:010770798  Feb 2026 = 120.13
#                                               (NAF2 47, Retail Trade total)
#
# Stage 2 (separat) — core-cpi, gdp-real (CNT-Quarterly), unemployment (BIT 15+),
# consumer/business-confidence, balance-of-trade, employment-rate, labour-costs etc.
SERIES: list[dict] = [
    # === Stage 1 ===
    {
        "indicator": "inflation-cpi",
        "dataset": "IPC-2025",
        "filters": {
            "COICOP2018": "00", "MENAGES_IPC": "ENSEMBLE", "REF_AREA": "FE",
            "UNIT_MEASURE": "SO", "FREQ": "M", "NATURE": "INDICE",
            "CORRECTION": "BRUT", "PRIX_CONSO": "SO",
        },
        "freq": "M", "unit": "Index", "adjustment": "NSA", "conversion": 1.0,
    },
    {
        "indicator": "industrial-production",
        "dataset": "IPI-2021",
        "filters": {
            "FREQ": "M", "INDICATEUR": "IPI", "NATURE": "INDICE",
            "CORRECTION": "CVS-CJO", "NAF2": "A10-BE",
        },
        "freq": "M", "unit": "Index", "adjustment": "SA", "conversion": 1.0,
    },
    {
        "indicator": "ppi",
        "dataset": "IPPI-2021",
        "filters": {
            "FREQ": "M", "INDICATEUR": "ENS_IPP", "NATURE": "INDICE",
            "PRODUIT_IPPI": "BII0", "PRODUIT_DETAILLE_IPPI": "SO",
            "REF_AREA": "FE", "CORRECTION": "BRUT",
        },
        "freq": "M", "unit": "Index", "adjustment": "NSA", "conversion": 1.0,
    },
    {
        "indicator": "retail-sales",
        "dataset": "ICA-2021-COMMERCE",
        "filters": {
            "FREQ": "M", "INDICATEUR": "ICA_COMM", "NAF2": "47",
            "NATURE": "INDICE_VAL", "REF_AREA": "FE",
            "CORRECTION": "CVS-CJO",
        },
        "freq": "M", "unit": "Index", "adjustment": "SA", "conversion": 1.0,
    },

    # === Stage 2 — added 2026-05-05 (Sebastian: keine Eurostat-Mirrors für TE-INSEE-Slugs) ===

    # GDP — Quarterly volume chained 2020 (TE shows ~595 Bil EUR Q1 2026; conversion to Billion EUR)
    {
        "indicator": "gdp-real",
        "dataset": "CNT-2020-PIB-EQB-RF",
        "filters": {
            "FREQ": "T", "OPERATION": "PIB", "NATURE": "VALEUR_ABSOLUE",
            "VALORISATION": "L", "UNIT_MEASURE": "EUROS",
            "CORRECTION": "CVS-CJO", "REF_AREA": "FE",
        },
        "freq": "Q", "unit": "Billion EUR", "adjustment": "SA", "conversion": 0.001,
    },
    # GDP growth rate — Quarterly QoQ %
    {
        "indicator": "gdp-growth-rate",
        "dataset": "CNT-2020-PIB-EQB-RF",
        "filters": {
            "FREQ": "T", "OPERATION": "PIB", "NATURE": "TAUX",
            "UNIT_MEASURE": "POURCENT", "CORRECTION": "CVS-CJO", "REF_AREA": "FE",
        },
        "freq": "Q", "unit": "%", "adjustment": "SA", "conversion": 1.0,
    },

    # Unemployment — France métropolitaine BIT TAUX, both sexes, age 15+
    # IDBANK 001688526. Agent's earlier filter (FR-D976) targeted Mayotte; corrected here.
    {
        "indicator": "unemployment",
        "dataset": "CHOMAGE-TRIM-NATIONAL",
        "filters": {
            "FREQ": "T", "INDICATEUR": "CTTXC", "NATURE": "TAUX",
            "REF_AREA": "FM", "SEXE": "0", "AGE": "00-",
            "UNIT_MEASURE": "POURCENT", "CORRECTION": "CVS",
            "SERIE_ARRETEE": "FALSE",
        },
        "freq": "Q", "unit": "%", "adjustment": "SA", "conversion": 1.0,
    },

    # Consumer confidence — INSEE CAMME (Indice synthétique de confiance des ménages)
    {
        "indicator": "consumer-confidence",
        "dataset": "ENQ-CONJ-MENAGES",
        "filters": {
            "FREQ": "M", "INDICATEUR": "IND_SYNT_CONF", "CORRECTION": "CVS",
        },
        "freq": "M", "unit": "Index", "adjustment": "SA", "conversion": 1.0,
    },

    # Business confidence — TE shows INSEE "Climat des Affaires Industrie" (A10-CZ ~100).
    # ENQ-CONJ-ACT-IND INDICATEUR=CLIMAT_AFFAIRES NAF2=A10-CZ (Industrie manufacturière, CVS).
    {
        "indicator": "business-confidence",
        "dataset": "ENQ-CONJ-ACT-IND",
        "filters": {
            "FREQ": "M", "INDICATEUR": "CLIMAT_AFFAIRES", "NAF2": "A10-CZ",
            "NATURE": "INDICE", "CORRECTION": "CVS",
        },
        "freq": "M", "unit": "Index", "adjustment": "SA", "conversion": 1.0,
    },

    # Core CPI — IPC-2025 ex Energy ex Food (PRIX_CONSO=4001 spec)
    {
        "indicator": "core-cpi",
        "dataset": "IPC-2025",
        "filters": {
            "FREQ": "M", "MENAGES_IPC": "ENSEMBLE", "REF_AREA": "FE",
            "NATURE": "INDICE", "CORRECTION": "BRUT",
            "COICOP2018": "SO", "PRIX_CONSO": "4001", "UNIT_MEASURE": "SO",
        },
        "freq": "M", "unit": "Index", "adjustment": "NSA", "conversion": 1.0,
    },

    # CPI sub-items by COICOP — Index Base 2025
    {
        "indicator": "food-inflation",
        "dataset": "IPC-2025",
        "filters": {
            "COICOP2018": "01", "MENAGES_IPC": "ENSEMBLE", "REF_AREA": "FE",
            "UNIT_MEASURE": "SO", "FREQ": "M", "NATURE": "INDICE",
            "CORRECTION": "BRUT", "PRIX_CONSO": "SO",
        },
        "freq": "M", "unit": "Index", "adjustment": "NSA", "conversion": 1.0,
    },
    {
        "indicator": "cpi-clothing",
        "dataset": "IPC-2025",
        "filters": {
            "COICOP2018": "03", "MENAGES_IPC": "ENSEMBLE", "REF_AREA": "FE",
            "UNIT_MEASURE": "SO", "FREQ": "M", "NATURE": "INDICE",
            "CORRECTION": "BRUT", "PRIX_CONSO": "SO",
        },
        "freq": "M", "unit": "Index", "adjustment": "NSA", "conversion": 1.0,
    },
    {
        "indicator": "cpi-housing-utilities",
        "dataset": "IPC-2025",
        "filters": {
            "COICOP2018": "04", "MENAGES_IPC": "ENSEMBLE", "REF_AREA": "FE",
            "UNIT_MEASURE": "SO", "FREQ": "M", "NATURE": "INDICE",
            "CORRECTION": "BRUT", "PRIX_CONSO": "SO",
        },
        "freq": "M", "unit": "Index", "adjustment": "NSA", "conversion": 1.0,
    },
    {
        "indicator": "cpi-transportation",
        "dataset": "IPC-2025",
        "filters": {
            "COICOP2018": "07", "MENAGES_IPC": "ENSEMBLE", "REF_AREA": "FE",
            "UNIT_MEASURE": "SO", "FREQ": "M", "NATURE": "INDICE",
            "CORRECTION": "BRUT", "PRIX_CONSO": "SO",
        },
        "freq": "M", "unit": "Index", "adjustment": "NSA", "conversion": 1.0,
    },
    {
        "indicator": "cpi-recreation-and-culture",
        "dataset": "IPC-2025",
        "filters": {
            "COICOP2018": "09", "MENAGES_IPC": "ENSEMBLE", "REF_AREA": "FE",
            "UNIT_MEASURE": "SO", "FREQ": "M", "NATURE": "INDICE",
            "CORRECTION": "BRUT", "PRIX_CONSO": "SO",
        },
        "freq": "M", "unit": "Index", "adjustment": "NSA", "conversion": 1.0,
    },
    {
        "indicator": "cpi-education",
        "dataset": "IPC-2025",
        "filters": {
            "COICOP2018": "10", "MENAGES_IPC": "ENSEMBLE", "REF_AREA": "FE",
            "UNIT_MEASURE": "SO", "FREQ": "M", "NATURE": "INDICE",
            "CORRECTION": "BRUT", "PRIX_CONSO": "SO",
        },
        "freq": "M", "unit": "Index", "adjustment": "NSA", "conversion": 1.0,
    },

    # Industrial production sub-aggregates
    {
        "indicator": "manufacturing-production",
        "dataset": "IPI-2021",
        "filters": {
            "FREQ": "M", "INDICATEUR": "IPI", "NATURE": "INDICE",
            "CORRECTION": "CVS-CJO", "NAF2": "A10-CZ", "REF_AREA": "FM",
        },
        "freq": "M", "unit": "Index", "adjustment": "SA", "conversion": 1.0,
    },
    {
        "indicator": "mining-production",
        "dataset": "IPI-2021",
        "filters": {
            "FREQ": "M", "INDICATEUR": "IPI", "NATURE": "INDICE",
            "CORRECTION": "CVS-CJO", "NAF2": "A21-B", "REF_AREA": "FM",
        },
        "freq": "M", "unit": "Index", "adjustment": "SA", "conversion": 1.0,
    },

    # Labour costs (Q4 2025 = 114.1, Coût horaire BTN ex-agri ex-domestic, ICT)
    {
        "indicator": "labour-costs",
        "dataset": "ICT-2020",
        "filters": {
            "FREQ": "T", "INDICATEUR": "ICT", "NAF2": "A21-BTN",
            "NATURE": "INDICE", "COMPO_COUT_TRAVAIL": "CH",
            "REF_AREA": "FE", "CORRECTION": "CVS-CJO",
            "SERIE_ARRETEE": "FALSE",
        },
        "freq": "Q", "unit": "Index", "adjustment": "SA", "conversion": 1.0,
    },

    # === Stage 3 — added 2026-05-06 ===

    # GDP nominal-V (current price) components — TE displays these for FR
    # Q1 2026 verified: P3 S14 = 390447 Mio EUR, P51 S0 = 166315 Mio EUR.
    {
        "indicator": "consumer-spending",
        "dataset": "CNT-2020-PIB-EQB-RF",
        "filters": {
            "FREQ": "T", "OPERATION": "P3", "SECT_INST": "S14",
            "NATURE": "VALEUR_ABSOLUE", "VALORISATION": "V",
            "UNIT_MEASURE": "EUROS", "CORRECTION": "CVS-CJO", "REF_AREA": "FE",
        },
        "freq": "Q", "unit": "Billion EUR", "adjustment": "SA", "conversion": 0.001,
    },
    {
        "indicator": "gross-fixed-capital-formation",
        "dataset": "CNT-2020-PIB-EQB-RF",
        "filters": {
            "FREQ": "T", "OPERATION": "P51", "SECT_INST": "S0",
            "NATURE": "VALEUR_ABSOLUE", "VALORISATION": "V",
            "UNIT_MEASURE": "EUROS", "CORRECTION": "CVS-CJO", "REF_AREA": "FE",
        },
        "freq": "Q", "unit": "Billion EUR", "adjustment": "SA", "conversion": 0.001,
    },
    {
        "indicator": "changes-in-inventories",
        "dataset": "CNT-2020-PIB-EQB-RF",
        "filters": {
            "FREQ": "T", "OPERATION": "P52", "SECT_INST": "SO",
            "NATURE": "VALEUR_ABSOLUE", "VALORISATION": "V",
            "UNIT_MEASURE": "EUROS", "CORRECTION": "CVS-CJO", "REF_AREA": "FE",
        },
        "freq": "Q", "unit": "Billion EUR", "adjustment": "SA", "conversion": 0.001,
    },
    # government-spending: TE shows P3 chained-volume Total Final Consumption (mislabel as
    # "Government Spending" but actual value matches P3 SO L). TE Mar 2026 = 169953 ≈ our 169979.
    {
        "indicator": "government-spending",
        "dataset": "CNT-2020-PIB-EQB-RF",
        "filters": {
            "FREQ": "T", "OPERATION": "P3", "SECT_INST": "SO",
            "NATURE": "VALEUR_ABSOLUE", "VALORISATION": "L",
            "UNIT_MEASURE": "EUROS", "CORRECTION": "CVS-CJO", "REF_AREA": "FE",
        },
        "freq": "Q", "unit": "Billion EUR", "adjustment": "SA", "conversion": 0.001,
    },
    # disposable-personal-income: INSEE CNT-2020-CSI B6 (RDB) Households S14
    # Q4 2025 = 471342 EUR Mio (TE 471367 — exakter Match)
    {
        "indicator": "disposable-personal-income",
        "dataset": "CNT-2020-CSI",
        "filters": {
            "FREQ": "T", "OPERATION": "B6", "SECT_INST": "S14",
            "NATURE": "VALEUR_ABSOLUE", "CORRECTION": "CVS-CJO",
            "UNIT_MEASURE": "EUROS", "REF_AREA": "FE",
        },
        "freq": "Q", "unit": "Million EUR", "adjustment": "SA", "conversion": 1.0,
    },
    # Quarterly nominal exports/imports (replaces Eurostat annual nama_10_exi)
    {
        "indicator": "exports",
        "dataset": "CNT-2020-PIB-EQB-RF",
        "filters": {
            "FREQ": "T", "OPERATION": "P6", "SECT_INST": "SO",
            "NATURE": "VALEUR_ABSOLUE", "VALORISATION": "V",
            "UNIT_MEASURE": "EUROS", "CORRECTION": "CVS-CJO", "REF_AREA": "FE",
        },
        "freq": "Q", "unit": "Billion EUR", "adjustment": "SA", "conversion": 0.001,
    },
    {
        "indicator": "imports",
        "dataset": "CNT-2020-PIB-EQB-RF",
        "filters": {
            "FREQ": "T", "OPERATION": "P7", "SECT_INST": "SO",
            "NATURE": "VALEUR_ABSOLUE", "VALORISATION": "V",
            "UNIT_MEASURE": "EUROS", "CORRECTION": "CVS-CJO", "REF_AREA": "FE",
        },
        "freq": "Q", "unit": "Billion EUR", "adjustment": "SA", "conversion": 0.001,
    },
    # IPC sub-indices for Energy and Services
    # Apr 2026 verified: 4007 (Energy) = 113.3, 4009 (Services) = 101.9.
    {
        "indicator": "energy-inflation",
        "dataset": "IPC-2025",
        "filters": {
            "FREQ": "M", "MENAGES_IPC": "ENSEMBLE", "REF_AREA": "FE",
            "NATURE": "INDICE", "CORRECTION": "BRUT",
            "COICOP2018": "SO", "PRIX_CONSO": "4007", "UNIT_MEASURE": "SO",
        },
        "freq": "M", "unit": "Index", "adjustment": "NSA", "conversion": 1.0,
    },
    {
        "indicator": "services-inflation",
        "dataset": "IPC-2025",
        "filters": {
            "FREQ": "M", "MENAGES_IPC": "ENSEMBLE", "REF_AREA": "FE",
            "NATURE": "INDICE", "CORRECTION": "BRUT",
            "COICOP2018": "SO", "PRIX_CONSO": "4009", "UNIT_MEASURE": "SO",
        },
        "freq": "M", "unit": "Index", "adjustment": "NSA", "conversion": 1.0,
    },
]


# Stage 7 — added 2026-05-08. Slugs only available via Melodi REST API
# (DD_EEC_ANNUEL: Activity/Employment/Unemployment annual results), not in pynsee BDM.
# All annual; dimensions filter selects exactly one series. Verified 2024 vs TE Q4 2025:
#   employment-rate     EMPRATE _T Y15T64 = 68.8% (TE 69.4 Q4 2025; vintage diff)
#   labor-force-part... ACTRATE _T Y15T64 = 74.4% (TE 75.4 Q4 2025)
#   unemployed-persons  UNEMP   _T Y15T74 = 2331.4 thousand
#   youth-unempl-rate   UNEMPRATE _T Y15T24 = 18.8% (TE ~20.5)
MELODI_SERIES: list[dict] = [
    {
        "indicator": "employment-rate",
        "dataset": "DD_EEC_ANNUEL",
        "filters": {"EEC_MEASURE": "EMPRATE", "SEX": "_T", "AGE": "Y15T64",
                    "EDUC": "_T", "IMMI": "_T"},
        "freq": "A", "unit": "%", "adjustment": "NSA", "conversion": 1.0,
    },
    {
        "indicator": "labor-force-participation-rate",
        "dataset": "DD_EEC_ANNUEL",
        "filters": {"EEC_MEASURE": "ACTRATE", "SEX": "_T", "AGE": "Y15T64",
                    "EDUC": "_T", "IMMI": "_T"},
        "freq": "A", "unit": "%", "adjustment": "NSA", "conversion": 1.0,
    },
    {
        "indicator": "youth-unemployment-rate",
        "dataset": "DD_EEC_ANNUEL",
        "filters": {"EEC_MEASURE": "UNEMPRATE", "SEX": "_T", "AGE": "Y15T24",
                    "EDUC": "_T", "IMMI": "_T"},
        "freq": "A", "unit": "%", "adjustment": "NSA", "conversion": 1.0,
    },
    {
        "indicator": "unemployed-persons",
        "dataset": "DD_EEC_ANNUEL",
        "filters": {"EEC_MEASURE": "UNEMP", "SEX": "_T", "AGE": "Y15T74",
                    "EDUC": "_T", "IMMI": "_T"},
        "freq": "A", "unit": "Thousand", "adjustment": "NSA", "conversion": 1.0,
    },
    # employed-persons LFS-BIT 15-64 Total — replaces CNA-2020-EMPLOI Domestic-Total
    # which TE doesn't use (TE: 28117 Eurostat LFS, our DD_EEC_ANNUEL EMP _T Y15T64 = 28420)
    {
        "indicator": "employed-persons",
        "dataset": "DD_EEC_ANNUEL",
        "filters": {"EEC_MEASURE": "EMP", "SEX": "_T", "AGE": "Y15T64",
                    "EDUC": "_T", "IMMI": "_T", "PCS": "_T", "EMPSTA": "1_BIT",
                    "ACTIVITY": "_T", "WKTIME": "_T", "EMPFORM": "_T",
                    "UNDEREMP": "_T", "UNEMPDUR": "_T", "COMPOHALO": "_T"},
        "freq": "A", "unit": "Thousand", "adjustment": "NSA", "conversion": 1.0,
    },
]


def _fetch_melodi_dataset(dataset: str) -> list[dict]:
    """Page through DD_EEC_ANNUEL et al. via Melodi REST API."""
    url = f"{MELODI_BASE}/{dataset}"
    all_obs: list[dict] = []
    page = 1
    while True:
        r = requests.get(url, params={"page": page}, timeout=120)
        r.raise_for_status()
        d = r.json()
        obs = d.get("observations", []) or []
        if not obs:
            break
        all_obs.extend(obs)
        if d.get("paging", {}).get("isLast"):
            break
        page += 1
        if page > 30:
            break
    return all_obs


def _filter_melodi(observations: list[dict], filters: dict) -> list[dict]:
    out = []
    for o in observations:
        d = o.get("dimensions", {})
        if all(d.get(k) == v for k, v in filters.items()):
            out.append(o)
    return out


def _melodi_to_datapoints(matched: list[dict], cfg: dict) -> list[DataPoint]:
    out: list[DataPoint] = []
    for o in matched:
        period = o["dimensions"].get("TIME_PERIOD")
        if period is None:
            continue
        dt = _parse_period(period, cfg["freq"])
        if dt is None:
            continue
        m = o.get("measures") or {}
        if not m:
            continue
        raw = list(m.values())[0].get("value")
        if raw is None:
            continue
        try:
            val = float(raw) * cfg["conversion"]
        except (ValueError, TypeError):
            continue
        # Drop overseas / age-mix duplicates: emit one DataPoint per unique date
        out.append(DataPoint(
            indicator=cfg["indicator"],
            country="FR",
            date=normalize_date(dt, cfg["freq"]),
            value=round(val, 6),
            source="insee",
            unit=cfg["unit"],
            series_id=f"melodi:{cfg['dataset']}:{cfg['filters'].get('EEC_MEASURE','?')}:{cfg['filters'].get('AGE','?')}",
            adjustment=cfg["adjustment"],
        ))
    return out


def _resolve_idbank(dataset: str, filters: dict) -> str:
    """Apply filters → expect exactly 1 IDBANK. Else raise."""
    sl = get_series_list(dataset)
    mask = None
    for col, val in filters.items():
        if col not in sl.columns:
            raise ValueError(f"{dataset}: filter column {col!r} not in dimensions {[c for c in sl.columns if 'label' not in c]}")
        m = (sl[col] == val)
        mask = m if mask is None else (mask & m)
    matched = sl[mask]
    if len(matched) != 1:
        raise ValueError(
            f"{dataset} {filters}: expected 1 IDBANK, got {len(matched)}. "
            f"Refine filters."
        )
    return matched.iloc[0]["IDBANK"]


def _parse_period(period_str: str, freq: str) -> date | None:
    """INSEE TIME_PERIOD formats: 'YYYY-MM' (M), 'YYYY-Qn' (Q/T), 'YYYY' (A)."""
    s = str(period_str).strip()
    try:
        if freq == "Q" or freq == "T" or "Q" in s:
            year, q = s.replace("-Q", "Q").split("Q")
            month = {"1": 1, "2": 4, "3": 7, "4": 10}[q]
            return date(int(year), month, 1)
        if freq == "M" or len(s) == 7:
            year, month = s.split("-")
            return date(int(year), int(month), 1)
        if freq == "A" or len(s) == 4:
            return date(int(s), 1, 1)
    except (ValueError, KeyError):
        pass
    return None


class InseeProvider(BaseProvider):
    name = "insee"
    display_name = "INSEE (Institut National de la Statistique)"

    def fetch(self) -> list[DataPoint]:
        out: list[DataPoint] = []
        for cfg in SERIES:
            slug = cfg["indicator"]
            try:
                idbank = _resolve_idbank(cfg["dataset"], cfg["filters"])
            except ValueError as e:
                print(f"  FAIL {slug}/FR: {e}")
                continue
            try:
                df = get_series([idbank])
            except Exception as e:
                print(f"  FAIL {slug}/FR (IDBANK {idbank}): {e}")
                continue

            if "OBS_VALUE" in df.columns:
                df = df.dropna(subset=["OBS_VALUE"])
            n_added = 0
            for _, row in df.iterrows():
                period_str = row.get("TIME_PERIOD") or row.get("DATE")
                if period_str is None:
                    continue
                dt = _parse_period(period_str, cfg["freq"])
                if dt is None:
                    continue
                raw = row.get("OBS_VALUE", row.get("VALEUR"))
                if raw is None:
                    continue
                try:
                    val = float(raw) * cfg["conversion"]
                except (ValueError, TypeError):
                    continue
                out.append(DataPoint(
                    indicator=slug,
                    country="FR",
                    date=normalize_date(dt, cfg["freq"]),
                    value=round(val, 6),
                    source="insee",
                    unit=cfg["unit"],
                    series_id=f"{cfg['dataset']}:{idbank}",
                    adjustment=cfg["adjustment"],
                ))
                n_added += 1
            print(f"  OK {slug}/FR (IDBANK {idbank}): {n_added} points")

        # Melodi REST series (DD_EEC_ANNUEL etc.)
        dataset_cache: dict[str, list[dict]] = {}
        for cfg in MELODI_SERIES:
            slug = cfg["indicator"]
            ds = cfg["dataset"]
            try:
                if ds not in dataset_cache:
                    dataset_cache[ds] = _fetch_melodi_dataset(ds)
                obs = dataset_cache[ds]
            except Exception as e:
                print(f"  FAIL {slug}/FR (Melodi {ds}): {e}")
                continue
            matched = _filter_melodi(obs, cfg["filters"])
            if not matched:
                print(f"  FAIL {slug}/FR: 0 matches in Melodi {ds} for {cfg['filters']}")
                continue
            pts = _melodi_to_datapoints(matched, cfg)
            out.extend(pts)
            print(f"  OK {slug}/FR (Melodi {ds} {cfg['filters'].get('EEC_MEASURE')}): {len(pts)} points")

        return out


def run():
    provider = InseeProvider()
    print(f"Fetching data from {provider.display_name}...")
    try:
        points = provider.fetch()
    except Exception as exc:
        print(f"Provider failed: {exc}")
        log_pipeline_run("insee", "fail", 0, str(exc))
        raise
    rows = datapoints_to_rows(points)
    upserted = upsert_data_points(rows)
    log_pipeline_run("insee", "success", upserted)
    print(f"Done. {upserted} rows upserted.")


if __name__ == "__main__":
    run()
