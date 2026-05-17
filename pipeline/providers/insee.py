"""InseeProvider — Institut National de la Statistique (V2 stateless).

V2 stateless: provider.fetch_series(SeriesSpec) -> list[Observation].
Keine indicator/country/source-Knowledge mehr. Wird vom Dispatcher pro
data_series-Row gerufen.

Dispatch-Modi (entscheidet sich aus spec.series_id / spec.extra_params):

1) IDBANK direkt:
     spec.series_id = "011814143"   (numerische IDBANK)
     -> pynsee.get_series([idbank])

2) IDBANK via Dataset + Filter resolven:
     spec.series_id = "IPC-2025"   (oder beliebige Markierung)
     spec.extra_params = {"dataset": "IPC-2025", "filters": {...}}
     -> get_series_list(dataset) + Filter -> 1 IDBANK -> get_series([idbank])

3) Melodi REST (Datasets nicht in BDM, z.B. DD_EEC_ANNUEL):
     spec.extra_params = {"melodi_dataset": "DD_EEC_ANNUEL", "filters": {...}}
     -> GET https://api.insee.fr/melodi/data/<dataset>?page=N

4) Derived/Ratio (deficit-to-GDP):
     spec.extra_params = {"derived_method": "deficit_ratio_annual",
                          "numerator_idbank": "...", "denominator_idbank": "..."}
"""
from __future__ import annotations

from datetime import date

import requests

from pipeline.base_provider import (
    BaseProvider, SeriesSpec, Observation,
    ProviderError, TransientProviderError,
)
from pipeline.transforms import normalize_date
from pipeline.dispatcher import register_provider


MELODI_BASE = "https://api.insee.fr/melodi/data"


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


def _is_transient(exc: BaseException) -> bool:
    """INSEE 5xx / Timeout / Connection -> Retry."""
    msg = str(exc)
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return True
    transient = ("500", "502", "503", "504",
                 "Internal Server Error", "Bad Gateway",
                 "Service Unavailable", "Gateway Timeout",
                 "timed out", "Connection")
    return any(s in msg for s in transient)


def _resolve_idbank(dataset: str, filters: dict) -> str:
    """Apply filters → expect exactly 1 IDBANK. Else raise ProviderError."""
    from pynsee.macrodata import get_series_list
    try:
        sl = get_series_list(dataset)
    except Exception as e:
        if _is_transient(e):
            raise TransientProviderError(f"get_series_list({dataset}): {e}") from e
        raise ProviderError(f"get_series_list({dataset}): {e}") from e

    mask = None
    for col, val in (filters or {}).items():
        if col not in sl.columns:
            raise ProviderError(
                f"{dataset}: filter column {col!r} not in dimensions"
            )
        m = (sl[col] == val)
        mask = m if mask is None else (mask & m)
    matched = sl if mask is None else sl[mask]
    if len(matched) != 1:
        raise ProviderError(
            f"{dataset} {filters}: expected 1 IDBANK, got {len(matched)}"
        )
    return matched.iloc[0]["IDBANK"]


def _fetch_idbank(idbank: str, freq: str, conv: float) -> list[Observation]:
    from pynsee.macrodata import get_series
    try:
        df = get_series([idbank])
    except Exception as e:
        if _is_transient(e):
            raise TransientProviderError(f"get_series({idbank}): {e}") from e
        raise ProviderError(f"get_series({idbank}): {e}") from e

    if "OBS_VALUE" in df.columns:
        df = df.dropna(subset=["OBS_VALUE"])

    out: list[Observation] = []
    for _, row in df.iterrows():
        period_str = row.get("TIME_PERIOD") or row.get("DATE")
        if period_str is None:
            continue
        dt = _parse_period(period_str, freq)
        if dt is None:
            continue
        raw = row.get("OBS_VALUE", row.get("VALEUR"))
        if raw is None:
            continue
        try:
            val = float(raw) * conv
        except (ValueError, TypeError):
            continue
        out.append(Observation(
            date=normalize_date(dt, freq),
            value=round(val, 6),
        ))
    return out


def _fetch_melodi_dataset(dataset: str) -> list[dict]:
    """Page through DD_EEC_ANNUEL et al. via Melodi REST API."""
    url = f"{MELODI_BASE}/{dataset}"
    all_obs: list[dict] = []
    page = 1
    while True:
        try:
            r = requests.get(url, params={"page": page}, timeout=120)
        except (requests.ConnectionError, requests.Timeout) as e:
            raise TransientProviderError(f"melodi {dataset}: {e}") from e
        if r.status_code >= 500:
            raise TransientProviderError(f"melodi {dataset} HTTP {r.status_code}")
        if r.status_code != 200:
            raise ProviderError(f"melodi {dataset} HTTP {r.status_code}: {r.text[:200]}")
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


def _fetch_melodi(dataset: str, filters: dict, freq: str, conv: float) -> list[Observation]:
    obs = _fetch_melodi_dataset(dataset)
    out: list[Observation] = []
    for o in obs:
        dims = o.get("dimensions", {})
        if not all(dims.get(k) == v for k, v in (filters or {}).items()):
            continue
        period = dims.get("TIME_PERIOD")
        if period is None:
            continue
        dt = _parse_period(period, freq)
        if dt is None:
            continue
        m = o.get("measures") or {}
        if not m:
            continue
        raw = list(m.values())[0].get("value")
        if raw is None:
            continue
        try:
            val = float(raw) * conv
        except (ValueError, TypeError):
            continue
        out.append(Observation(
            date=normalize_date(dt, freq),
            value=round(val, 6),
        ))
    return out


def _compute_deficit_ratio_annual(num_idbank: str, den_idbank: str) -> list[Observation]:
    """Sum quarterly num/den to annual, return ratio*100 per year."""
    from pynsee.macrodata import get_series
    try:
        num_df = get_series([num_idbank])
        den_df = get_series([den_idbank])
    except Exception as e:
        if _is_transient(e):
            raise TransientProviderError(f"deficit_ratio: {e}") from e
        raise ProviderError(f"deficit_ratio: {e}") from e

    num_df = num_df[["TIME_PERIOD", "OBS_VALUE"]].dropna()
    den_df = den_df[["TIME_PERIOD", "OBS_VALUE"]].dropna()
    num_df["year"] = num_df["TIME_PERIOD"].astype(str).str[:4]
    den_df["year"] = den_df["TIME_PERIOD"].astype(str).str[:4]
    num_df["OBS_VALUE"] = num_df["OBS_VALUE"].astype(float)
    den_df["OBS_VALUE"] = den_df["OBS_VALUE"].astype(float)

    num_counts = num_df.groupby("year").size()
    den_counts = den_df.groupby("year").size()
    complete_years = sorted(
        set(num_counts[num_counts >= 4].index)
        & set(den_counts[den_counts >= 4].index)
    )
    num_ann = num_df.groupby("year")["OBS_VALUE"].sum()
    den_ann = den_df.groupby("year")["OBS_VALUE"].sum()

    out: list[Observation] = []
    for year in complete_years:
        ratio = num_ann[year] / den_ann[year] * 100.0
        out.append(Observation(
            date=normalize_date(date(int(year), 1, 1), "A"),
            value=round(ratio, 2),
        ))
    return out


class InseeProvider(BaseProvider):
    name = "insee"
    display_name = "INSEE"

    def fetch_series(self, spec: SeriesSpec) -> list[Observation]:
        ep = spec.extra_params or {}
        freq = spec.freq_hint or "M"
        # INSEE 'T' (trimestre) maps to our 'Q' for normalize_date.
        if freq == "T":
            freq = "Q"
        conv = spec.conversion or 1.0

        # 4) Derived series.
        derived = ep.get("derived_method")
        if derived:
            if derived == "deficit_ratio_annual":
                num = ep.get("numerator_idbank")
                den = ep.get("denominator_idbank")
                if not num or not den:
                    raise ProviderError(
                        "deficit_ratio_annual needs numerator_idbank + denominator_idbank"
                    )
                return _compute_deficit_ratio_annual(num, den)
            raise ProviderError(f"unknown derived_method: {derived}")

        # 3) Melodi REST.
        melodi_ds = ep.get("melodi_dataset")
        if melodi_ds:
            filters = ep.get("filters") or {}
            return _fetch_melodi(melodi_ds, filters, freq, conv)

        # 2) BDM via dataset + filters -> resolve IDBANK.
        dataset = ep.get("dataset")
        filters = ep.get("filters")
        if dataset and filters:
            idbank = _resolve_idbank(dataset, filters)
            return _fetch_idbank(idbank, freq, conv)

        # 1) IDBANK direkt aus spec.series_id.
        sid = (spec.series_id or "").strip()
        if not sid:
            raise ProviderError("insee: series_id empty and no dataset/filters provided")
        # Falls jemand "IPC-2025:011814143" reicht: nimm rechtes Stück als IDBANK.
        if ":" in sid:
            sid = sid.rsplit(":", 1)[-1].strip()
        if not sid.isdigit():
            raise ProviderError(
                f"insee: series_id {spec.series_id!r} is not a numeric IDBANK and "
                "no dataset/filters extra_params provided"
            )
        return _fetch_idbank(sid, freq, conv)


try:
    register_provider(InseeProvider())
except ProviderError as e:
    print(f"[warn] InseeProvider not registered: {e}")
