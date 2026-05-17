"""national_eu V2 — 16 stateless sub-providers (one BaseProvider class each).

Each sub-provider:
  * has a unique `name` (the DB fetch_provider code)
  * implements `fetch_series(spec) -> list[Observation]`
  * looks up its config by `spec.series_id` in a per-provider dict built from
    the V1 national_eu.SERIES lists
  * applies conversion + normalize_date on output

We REUSE the V1 fetcher functions and SERIES configs from `pipeline.providers.national_eu`
(no rewrite, just wrap them). The V1 NationalEUProvider.fetch() umbrella is replaced
by 16 dispatcher-callable classes that share a tiny mixin.

V1 NationalEUProvider is left in place for backwards-compat but should never be
registered as a dispatcher provider (it returns DataPoint, not Observation).

Architecture note:
  Each sub-provider keeps a `_INDEX: dict[series_id, cfg]` built at import time.
  The encoding mirrors V1's series_id-construction logic so the existing
  data_series.fetch_series_id rows resolve cleanly.

Smoke-test (PowerShell):
  pipeline/.venv/Scripts/python -c "from pipeline.providers import national_eu_v2 as nv2; \
    from pipeline.base_provider import SeriesSpec; \
    print(nv2.DstProvider().fetch_series(SeriesSpec(series_id='DST/PRIS01', freq_hint='M'))[:3])"
"""
from __future__ import annotations

import time
from datetime import date
from typing import Callable, Iterable

from pipeline.base_provider import (
    BaseProvider, SeriesSpec, Observation,
    ProviderError, TransientProviderError,
)
from pipeline.transforms import normalize_date

# Import the V1 module — pulls in SERIES lists + fetcher functions.
# Side-effects on import: only module-level constants + function defs (no
# fetch loop runs, no provider registration).
from pipeline.providers import national_eu as _v1


# ----------------------------------------------------------------------------
# Generic helpers
# ----------------------------------------------------------------------------

def _to_observations(pairs: Iterable[tuple[date, float]],
                     conversion: float, freq: str) -> list[Observation]:
    out: list[Observation] = []
    for dt, v in pairs:
        if v is None:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        out.append(Observation(
            date=normalize_date(dt, freq),
            value=round(fv * conversion, 6),
        ))
    return out


def _wrap_v1_call(call: Callable[[], list[tuple[date, float]]],
                  context: str) -> list[tuple[date, float]]:
    """Call a V1 fetcher and translate exceptions into V2 ProviderError types.

    Network/HTTP 5xx / timeouts -> TransientProviderError so the dispatcher retries.
    Everything else -> ProviderError (terminal for this dispatch run).
    """
    try:
        import requests  # local import — only used for isinstance
    except Exception:  # pragma: no cover
        requests = None  # type: ignore

    try:
        return call()
    except Exception as e:
        msg = str(e)
        if requests is not None and isinstance(e, (requests.ConnectionError, requests.Timeout)):
            raise TransientProviderError(f"{context}: network {e}") from e
        if requests is not None and isinstance(e, requests.HTTPError):
            sc = getattr(getattr(e, "response", None), "status_code", 0) or 0
            if sc in (429, 502, 503, 504) or 500 <= sc < 600:
                raise TransientProviderError(f"{context}: HTTP {sc}") from e
            raise ProviderError(f"{context}: HTTP {sc} {msg[:160]}") from e
        # heuristic: msg-based transient detection
        low = msg.lower()
        if any(t in low for t in ("timeout", "timed out", "temporarily", "connection reset")):
            raise TransientProviderError(f"{context}: {msg[:160]}") from e
        raise ProviderError(f"{context}: {msg[:200]}") from e


# ----------------------------------------------------------------------------
# DB-driven series_id resolution
#
# Some V1 SERIES cfgs share the same `path`/`table` (e.g. SCB NR0103B is reused
# for gdp-real and gdp-growth-rate with different ContentsCode queries) and the
# DB encodes series_id with disambiguator tails that aren't deterministically
# reconstructable from the cfg alone. We therefore query data_series at
# module-import time to learn (provider, series_id) -> (slug, country), then
# match cfg by slug. Static builders below are kept as a fallback for new rows
# inserted after this module loads (cache stale).
# ----------------------------------------------------------------------------

def _query_db_series_index() -> dict[str, dict[str, tuple[str, str]]]:
    """{provider_name: {series_id: (slug, country)}}, populated from data_series."""
    try:
        from pipeline.db import supabase as sb
    except Exception:
        return {}
    providers = ("dst", "stat_fi", "scb_se", "ine_pt", "cso_ie", "stat_at",
                 "surs_si", "csp_lv", "stat_ee", "dzs_hr", "statbel", "nbb",
                 "susr_sk", "ksh_hu", "insse_ro", "nso_mt", "cystat_cy")
    try:
        res = (sb.table("data_series")
                 .select("fetch_provider,fetch_series_id,"
                         "indicator_instances!inner(indicator_families!inner(family_code),"
                         "countries!inner(code))")
                 .in_("fetch_provider", list(providers))
                 .is_("valid_to", "null")
                 .execute())
        out: dict[str, dict[str, tuple[str, str]]] = {}
        for r in res.data or []:
            inst = r["indicator_instances"]
            slug = inst["indicator_families"]["family_code"]
            country = inst["countries"]["code"]
            out.setdefault(r["fetch_provider"], {})[r["fetch_series_id"]] = (slug, country)
        return out
    except Exception as e:  # pragma: no cover
        print(f"[warn] national_eu_v2: DB index query failed: {e}")
        return {}


_DB_INDEX = _query_db_series_index()


def _merge_db_index(provider: str, static_idx: dict[str, dict],
                    cfgs_by_slug: dict[str, list[dict]]) -> dict[str, dict]:
    """Resolve (series_id -> cfg) using DB rows when available, static fallback otherwise.

    Priority:
      1. DB row's slug -> cfgs_by_slug[slug][0]. This is authoritative because
         the DB row tells us exactly which slug a (provider, series_id) serves.
      2. Static-builder entries (for series_ids not present in DB, e.g. new
         data_series inserted after import — rare).

    The DB resolution wins because the static builder's series_id <-> slug
    mapping is ambiguous when multiple cfgs share a path/table.
    """
    db = _DB_INDEX.get(provider, {})
    merged: dict[str, dict] = {}
    # Step 1: DB-driven mappings.
    for sid, (slug, _country) in db.items():
        cfgs = cfgs_by_slug.get(slug) or []
        if cfgs:
            merged[sid] = cfgs[0]
    # Step 2: fill in static entries the DB didn't cover.
    for sid, cfg in static_idx.items():
        merged.setdefault(sid, cfg)
    return merged


def _cfgs_by_slug(series_list: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for cfg in series_list:
        s = cfg.get("slug") or ""
        out.setdefault(s, []).append(cfg)
    return out


# ----------------------------------------------------------------------------
# Per-provider series_id → cfg index builders
#
# These replicate the V1 NationalEUProvider.fetch() series_id construction so
# the (provider, series_id) rows already in data_series resolve to the right cfg.
# ----------------------------------------------------------------------------

def _build_dst_index() -> dict[str, dict]:
    idx: dict[str, dict] = {}
    for cfg in _v1.DK_SERIES:
        sid = cfg.get("series_id") or f"DST/{cfg['table']}"
        idx[sid] = cfg
    return idx


def _build_statfi_index() -> dict[str, dict]:
    idx: dict[str, dict] = {}
    for cfg in _v1.FI_SERIES:
        sid = cfg.get("series_id") or f"STATFI/{cfg['path']}"
        idx[sid] = cfg
    return idx


def _build_scb_index() -> dict[str, dict]:
    """SCB DB rows encode series_id in three flavours:

      SCB/PR/PR0101/PR0101A/KPI2020M     full path (V1 fallback)
      SCB/PR0101A/KPI2020M               short = last 2 path segments
      SCB/AM0401A/empl-rate              short + slug suffix (variant series)
    """
    idx: dict[str, dict] = {}
    for cfg in _v1.SE_SERIES:
        path = cfg["path"]
        full_sid = f"SCB/{path}"
        if cfg.get("series_id"):
            idx[cfg["series_id"]] = cfg
        idx.setdefault(full_sid, cfg)
        # last-two-segments short form (used by some migration scripts).
        parts = path.split("/")
        if len(parts) >= 2:
            idx.setdefault(f"SCB/{parts[-2]}/{parts[-1]}", cfg)
    # Disambiguation between sibling cfgs that share a path is delegated to
    # _merge_db_index (DB-driven). Static collisions get resolved later by slug.
    return idx


def _build_ine_pt_index() -> dict[str, dict]:
    idx: dict[str, dict] = {}
    for cfg in _v1.PT_SERIES:
        sid = cfg.get("series_id") or f"INE-PT/{cfg['varcd']}"
        idx[sid] = cfg
        # Some DB rows use the shorter `INE/{varcd}` prefix; index both.
        short = f"INE/{cfg['varcd']}"
        idx.setdefault(short, cfg)
    return idx


def _build_cso_index() -> dict[str, dict]:
    idx: dict[str, dict] = {}
    for cfg in _v1.IE_SERIES:
        sid = cfg.get("series_id") or f"CSO/{cfg['table']}"
        idx[sid] = cfg
    return idx


def _build_stat_at_index() -> dict[str, dict]:
    idx: dict[str, dict] = {}
    # V1 constructed: f"STATAT/{cfg['ogd']}".  However the DB stores
    # disambiguating tails like #VPI-01 / #F-FAKT-46 / #VGRHAG-23 / #NAC_B etc.
    # to make (slug, ogd) unique.  We deterministically reconstruct that suffix.
    for cfg in _v1.AT_SERIES:
        ogd = cfg["ogd"]
        slug = cfg.get("slug", "")
        # Default: bare OGD.
        sid_candidates = [f"STATAT/{ogd}"]

        # Disambiguator suffixes used by migration scripts to keep series_id unique.
        # We add ALL plausible variants as keys so any DB-encoded form resolves.
        filt = cfg.get("filters") or {}
        # OGD_vpi20 COICOP suffix: #VPI-01..VPI-12 (from C-VPI5NEU-0 filter)
        if ogd == "OGD_vpi20_VPI_2020_1":
            tag = filt.get("C-VPI5NEU-0")
            vcol = cfg.get("value_col") or ""
            if tag and tag != "VPI-0":
                if vcol == "F-VPIPZVJM":
                    sid_candidates.append(f"STATAT/{ogd}#{tag}-PZVJM")
                else:
                    sid_candidates.append(f"STATAT/{ogd}#{tag}")
        # OGD_vgr108: VGRHAG-14 is the bare gdp-real series; subcomponents append #VGRHAG-XX.
        if ogd == "OGD_vgr108_VGR_HA_vj_1":
            tag = filt.get("C-VGRHAG79-0")
            if tag and tag != "VGRHAG-14":
                sid_candidates.append(f"STATAT/{ogd}#{tag}")
        # konjunkturmonitor: exports/imports/trade-balance suffix the value cols.
        if ogd == "OGD_konjunkturmonitor_KonMon_1":
            vcol = cfg.get("value_col") or ""
            vcolb = cfg.get("value_col_b")
            if cfg.get("derive") == "sub_b" and vcolb:
                sid_candidates.append(f"STATAT/{ogd}#{vcol}-{vcolb}")
            else:
                sid_candidates.append(f"STATAT/{ogd}#{vcol}")
        # kjiprodindex2021 sub-breakdowns: NACE B / NACE C
        if ogd == "OGD_kjiprodindex2021_KJID2021_PI_1":
            vcol = cfg.get("value_col") or ""
            if vcol == "F-KJIP_NAC_B":
                sid_candidates.append(f"STATAT/{ogd}#NAC_B")
            elif vcol == "F-KJIP_NAC_C":
                sid_candidates.append(f"STATAT/{ogd}#NAC_C")
        # konjidxhan21 retail-sales NACE-47
        if ogd == "OGD_konjidxhan21_KJIX_H_21_1":
            naceidx = filt.get("C-NACEIDX-0") or ""
            vcol = cfg.get("value_col") or ""
            if naceidx.startswith("NACEIDX-"):
                tail = naceidx.replace("NACEIDX-", "NACE-")
                sid_candidates.append(f"STATAT/{ogd}#{tail}-{vcol}")
        # vgr111 employed-persons BEREIN suffix
        if ogd == "OGD_vgr111_VGR_Flashes_Erwerb_1":
            tag = filt.get("C-BEREIN-0") or ""
            vcol = cfg.get("value_col") or ""
            sid_candidates.append(f"STATAT/{ogd}#{tag}#{vcol}")
        # kons_brv government-debt-total
        if ogd == "OGD_kons_brv_HVD_KONS_BRV_1":
            vcol = cfg.get("value_col") or ""
            sid_candidates.append(f"STATAT/{ogd}#{vcol}")
        # Explicit override on cfg
        if cfg.get("series_id"):
            sid_candidates.insert(0, cfg["series_id"])
        for sid in sid_candidates:
            idx.setdefault(sid, cfg)
    return idx


def _build_surs_index() -> dict[str, dict]:
    idx: dict[str, dict] = {}
    for cfg in _v1.SI_SERIES:
        sid = cfg.get("series_id") or f"SURS/{cfg['table']}"
        idx[sid] = cfg
    return idx


def _build_csp_index() -> dict[str, dict]:
    idx: dict[str, dict] = {}
    for cfg in _v1.LV_SERIES:
        sid = cfg.get("series_id") or f"CSP/{cfg['path'].rsplit('/', 1)[-1]}"
        idx[sid] = cfg
    return idx


def _build_stat_ee_index() -> dict[str, dict]:
    idx: dict[str, dict] = {}
    for cfg in _v1.EE_SERIES:
        table_id = cfg["path"].rsplit("/", 1)[-1].split(".")[0]
        sid = cfg.get("series_id") or f"STATEE/{table_id}"
        idx[sid] = cfg
        # Also index the .px form (DB rows like 'STATEE/IA002.px' coexist with 'STATEE/IA002').
        full_id = cfg["path"].rsplit("/", 1)[-1]
        if full_id != table_id:
            idx.setdefault(f"STATEE/{full_id}", cfg)
    return idx


def _build_dzs_index() -> dict[str, dict]:
    idx: dict[str, dict] = {}
    for cfg in _v1.HR_SERIES:
        table_id = cfg["path"].rsplit("/", 1)[-1].replace(".px", "")
        sid = cfg.get("series_id") or f"DZS/{table_id}"
        idx[sid] = cfg
        # Also accept '.px' suffixed form
        full = cfg["path"].rsplit("/", 1)[-1]
        idx.setdefault(f"DZS/{full}", cfg)
    return idx


def _build_statbel_index() -> dict[str, dict]:
    idx: dict[str, dict] = {}
    for cfg in _v1.BE_SERIES:
        if cfg.get("kind") != "statbel":
            continue
        sid = cfg.get("series_id") or f"STATBEL/{cfg['view_id'][:8]}"
        idx[sid] = cfg
    return idx


def _build_nbb_index() -> dict[str, dict]:
    idx: dict[str, dict] = {}
    for cfg in _v1.BE_SERIES:
        if cfg.get("kind") != "nbb":
            continue
        sid = cfg.get("series_id") or f"NBB/{cfg['dataflow']}/{cfg['key']}"
        idx[sid] = cfg
    return idx


def _build_susr_index() -> dict[str, dict]:
    idx: dict[str, dict] = {}
    for cfg in _v1.SK_SERIES:
        ds = cfg["dataset_id"]
        seg_tail = "/".join(cfg["segments"][2:]) if len(cfg.get("segments", [])) > 2 else ""
        sid = cfg.get("series_id") or (f"SUSR/{ds}/{seg_tail}" if seg_tail else f"SUSR/{ds}")
        idx[sid] = cfg
        # also accept bare-dataset key for synthetic configs
        idx.setdefault(f"SUSR/{ds}", cfg)
    return idx


def _build_ksh_index() -> dict[str, dict]:
    idx: dict[str, dict] = {}
    for cfg in _v1.HU_SERIES:
        sid = cfg.get("series_id") or f"KSH/{cfg['table']}"
        idx[sid] = cfg
    return idx


def _build_insse_index() -> dict[str, dict]:
    idx: dict[str, dict] = {}
    for cfg in _v1.RO_SERIES + _v1.RO_TRADE_SERIES:
        sid = cfg.get("series_id") or f"INSSE/{cfg['matrix']}"
        idx[sid] = cfg
    return idx


def _build_nso_index() -> dict[str, dict]:
    idx: dict[str, dict] = {}
    for cfg in _v1.MT_SERIES:
        sid = cfg.get("series_id") or f"NSO/{cfg['dataflow']}/{cfg['key']}"
        idx[sid] = cfg
    return idx


def _build_cystat_index() -> dict[str, dict]:
    idx: dict[str, dict] = {}
    for cfg in _v1.CY_SERIES:
        if cfg.get("series_id"):
            sid = cfg["series_id"]
        elif "pxweb_query" in cfg:
            sid_tail = "/".join(sorted(cfg["pxweb_query"].keys()))
            sid = f"CYSTAT/{cfg['px_path'].rsplit('/', 1)[-1]}/{sid_tail}"
        else:
            sid = f"CYSTAT/{cfg['px_path'].rsplit('/', 1)[-1]}/B{cfg['base_year']}"
        idx[sid] = cfg
    return idx


# ----------------------------------------------------------------------------
# Sub-provider classes (16)
# ----------------------------------------------------------------------------

class _SubBase(BaseProvider):
    """Shared resolution mixin. Subclasses set `name`, `display_name`, `_INDEX`."""
    _INDEX: dict[str, dict] = {}

    def _resolve(self, spec: SeriesSpec) -> dict:
        sid = (spec.series_id or "").strip()
        cfg = self._INDEX.get(sid)
        if cfg is None:
            raise ProviderError(
                f"{self.name}: unknown series_id '{sid}' "
                f"(known {len(self._INDEX)} entries; first 3 keys: "
                f"{list(self._INDEX)[:3]})"
            )
        return cfg


# ---------------- Denmark — DST ----------------

class DstProvider(_SubBase):
    name = "dst"
    display_name = "Statistics Denmark"
    _INDEX = _merge_db_index("dst", _build_dst_index(), _cfgs_by_slug(_v1.DK_SERIES))

    def fetch_series(self, spec: SeriesSpec) -> list[Observation]:
        cfg = self._resolve(spec)
        freq = cfg["freq"]
        conv = cfg["conversion"]
        pairs = _wrap_v1_call(
            lambda: _v1.fetch_dk_table(cfg["table"], cfg["filters"], freq),
            f"dst/{cfg['table']}",
        )
        return _to_observations(pairs, conv, freq)


# ---------------- Finland — STAT_FI ----------------

class StatFiProvider(_SubBase):
    name = "stat_fi"
    display_name = "Statistics Finland"
    _INDEX = _merge_db_index("stat_fi", _build_statfi_index(), _cfgs_by_slug(_v1.FI_SERIES))

    def fetch_series(self, spec: SeriesSpec) -> list[Observation]:
        cfg = self._resolve(spec)
        freq = cfg["freq"]
        conv = cfg["conversion"]
        slug = cfg.get("slug")

        # Special-case: trade-balance derived in V1 from exports/imports of tpulk 12gq.
        if slug == "trade-balance" and "tpulk" in cfg.get("path", ""):
            # Find the paired exports/imports cfgs
            exp_cfg = next((c for c in _v1.FI_SERIES
                            if c.get("slug") == "exports" and "tpulk" in c["path"]), None)
            imp_cfg = next((c for c in _v1.FI_SERIES
                            if c.get("slug") == "imports" and "tpulk" in c["path"]), None)
            if not (exp_cfg and imp_cfg):
                raise ProviderError("stat_fi: cannot derive trade-balance — missing exp/imp cfg")
            exp_pairs = _wrap_v1_call(
                lambda: _v1.fetch_fi_table(exp_cfg["path"], exp_cfg["query"], exp_cfg["freq"]),
                "stat_fi/exports",
            )
            imp_pairs = _wrap_v1_call(
                lambda: _v1.fetch_fi_table(imp_cfg["path"], imp_cfg["query"], imp_cfg["freq"]),
                "stat_fi/imports",
            )
            exp_map = {normalize_date(dt, exp_cfg["freq"]): v * exp_cfg["conversion"]
                       for dt, v in exp_pairs}
            imp_map = {normalize_date(dt, imp_cfg["freq"]): v * imp_cfg["conversion"]
                       for dt, v in imp_pairs}
            out: list[Observation] = []
            for d in sorted(set(exp_map) & set(imp_map)):
                out.append(Observation(date=d, value=round(exp_map[d] - imp_map[d], 6)))
            return out

        pairs = _wrap_v1_call(
            lambda: _v1.fetch_fi_table(cfg["path"], cfg["query"], freq),
            f"stat_fi/{cfg['path']}",
        )
        return _to_observations(pairs, conv, freq)


# ---------------- Sweden — SCB ----------------

class ScbSeProvider(_SubBase):
    name = "scb_se"
    display_name = "Statistics Sweden (SCB)"
    _INDEX = _merge_db_index("scb_se", _build_scb_index(), _cfgs_by_slug(_v1.SE_SERIES))

    def fetch_series(self, spec: SeriesSpec) -> list[Observation]:
        cfg = self._resolve(spec)
        freq = cfg["freq"]
        conv = cfg["conversion"]
        pairs = _wrap_v1_call(
            lambda: _v1.fetch_se_table(cfg["path"], cfg["query"], freq),
            f"scb_se/{cfg['path']}",
        )
        return _to_observations(pairs, conv, freq)


# ---------------- Portugal — INE PT ----------------

class InePtProvider(_SubBase):
    name = "ine_pt"
    display_name = "INE Portugal"
    _INDEX = _merge_db_index("ine_pt", _build_ine_pt_index(), _cfgs_by_slug(_v1.PT_SERIES))

    def fetch_series(self, spec: SeriesSpec) -> list[Observation]:
        cfg = self._resolve(spec)
        freq = cfg["freq"]
        conv = cfg["conversion"]
        pairs = _wrap_v1_call(
            lambda: _v1.fetch_pt_indicator(
                cfg["varcd"], freq, row_filter=cfg.get("row_filter"),
                op2_only=cfg.get("op2_only", False),
            ),
            f"ine_pt/{cfg['varcd']}",
        )
        return _to_observations(pairs, conv, freq)


# ---------------- Ireland — CSO ----------------

class CsoIeProvider(_SubBase):
    name = "cso_ie"
    display_name = "Central Statistics Office Ireland"
    _INDEX = _merge_db_index("cso_ie", _build_cso_index(), _cfgs_by_slug(_v1.IE_SERIES))

    def fetch_series(self, spec: SeriesSpec) -> list[Observation]:
        cfg = self._resolve(spec)
        freq = cfg["freq"]
        conv = cfg["conversion"]
        pairs = _wrap_v1_call(
            lambda: _v1.fetch_ie_table(cfg["table"], cfg["filters"], freq),
            f"cso_ie/{cfg['table']}",
        )
        return _to_observations(pairs, conv, freq)


# ---------------- Austria — STAT_AT ----------------

class StatAtProvider(_SubBase):
    name = "stat_at"
    display_name = "Statistics Austria"
    _INDEX = _merge_db_index("stat_at", _build_stat_at_index(), _cfgs_by_slug(_v1.AT_SERIES))

    def fetch_series(self, spec: SeriesSpec) -> list[Observation]:
        cfg = self._resolve(spec)
        freq = cfg["freq"]
        conv = cfg["conversion"]
        pairs = _wrap_v1_call(
            lambda: _v1.fetch_at_csv(
                cfg["ogd"], cfg["filters"], cfg["time_col"], cfg["value_col"], freq,
                value_col_b=cfg.get("value_col_b"), derive=cfg.get("derive"),
            ),
            f"stat_at/{cfg['ogd']}",
        )
        return _to_observations(pairs, conv, freq)


# ---------------- Slovenia — SURS ----------------

class SursSiProvider(_SubBase):
    name = "surs_si"
    display_name = "SURS — Statistical Office of the Republic of Slovenia"
    _INDEX = _merge_db_index("surs_si", _build_surs_index(), _cfgs_by_slug(_v1.SI_SERIES))

    def fetch_series(self, spec: SeriesSpec) -> list[Observation]:
        cfg = self._resolve(spec)
        freq = cfg["freq"]
        conv = cfg["conversion"]
        pairs = _wrap_v1_call(
            lambda: _v1.fetch_si_pxweb(cfg["table"], cfg["query"], freq),
            f"surs_si/{cfg['table']}",
        )
        return _to_observations(pairs, conv, freq)


# ---------------- Latvia — CSP ----------------

class CspLvProvider(_SubBase):
    name = "csp_lv"
    display_name = "Central Statistical Bureau of Latvia"
    _INDEX = _merge_db_index("csp_lv", _build_csp_index(), _cfgs_by_slug(_v1.LV_SERIES))

    def fetch_series(self, spec: SeriesSpec) -> list[Observation]:
        cfg = self._resolve(spec)
        freq = cfg["freq"]
        conv = cfg["conversion"]
        pairs = _wrap_v1_call(
            lambda: _v1.fetch_lv_pxweb(cfg["path"], cfg["query"], freq),
            f"csp_lv/{cfg['path']}",
        )
        return _to_observations(pairs, conv, freq)


# ---------------- Estonia — STAT_EE ----------------

class StatEeProvider(_SubBase):
    name = "stat_ee"
    display_name = "Statistics Estonia"
    _INDEX = _merge_db_index("stat_ee", _build_stat_ee_index(), _cfgs_by_slug(_v1.EE_SERIES))

    def fetch_series(self, spec: SeriesSpec) -> list[Observation]:
        cfg = self._resolve(spec)
        freq = cfg["freq"]
        conv = cfg["conversion"]
        # EE uses pseudo-freq codes for special parsers — pass through to fetcher.
        pairs = _wrap_v1_call(
            lambda: _v1.fetch_ee_pxweb(cfg["path"], cfg["query"], freq),
            f"stat_ee/{cfg['path']}",
        )
        # Normalize freq for the Observation timestamp (M_year_month_combo -> M etc.)
        eff_freq = {"M_year_month_combo": "M", "Q_year_quarter_combo": "Q"}.get(freq, freq)
        return _to_observations(pairs, conv, eff_freq)


# ---------------- Croatia — DZS ----------------

class DzsHrProvider(_SubBase):
    name = "dzs_hr"
    display_name = "Croatian Bureau of Statistics (DZS)"
    _INDEX = _merge_db_index("dzs_hr", _build_dzs_index(), _cfgs_by_slug(_v1.HR_SERIES))

    def fetch_series(self, spec: SeriesSpec) -> list[Observation]:
        cfg = self._resolve(spec)
        freq = cfg["freq"]
        conv = cfg["conversion"]
        pairs = _wrap_v1_call(
            lambda: _v1.fetch_hr_pxweb(cfg["path"], cfg["query"], freq, cfg.get("parse", "tid")),
            f"dzs_hr/{cfg['path']}",
        )
        return _to_observations(pairs, conv, freq)


# ---------------- Belgium — Statbel ----------------

class StatbelProvider(_SubBase):
    name = "statbel"
    display_name = "Statbel"
    _INDEX = _merge_db_index(
        "statbel",
        _build_statbel_index(),
        _cfgs_by_slug([c for c in _v1.BE_SERIES if c.get("kind") == "statbel"]),
    )

    def fetch_series(self, spec: SeriesSpec) -> list[Observation]:
        cfg = self._resolve(spec)
        freq = cfg["freq"]
        conv = cfg["conversion"]
        pairs = _wrap_v1_call(
            lambda: _v1.fetch_be_statbel_csv(
                cfg["view_id"], cfg["value_col"], freq, row_filter=cfg.get("row_filter"),
            ),
            f"statbel/{cfg['view_id'][:8]}",
        )
        return _to_observations(pairs, conv, freq)


# ---------------- Belgium — NBB ----------------

class NbbProvider(_SubBase):
    name = "nbb"
    display_name = "National Bank of Belgium"
    _INDEX = _merge_db_index(
        "nbb",
        _build_nbb_index(),
        _cfgs_by_slug([c for c in _v1.BE_SERIES if c.get("kind") == "nbb"]),
    )

    def fetch_series(self, spec: SeriesSpec) -> list[Observation]:
        cfg = self._resolve(spec)
        freq = cfg["freq"]
        conv = cfg["conversion"]
        pairs = _wrap_v1_call(
            lambda: _v1.fetch_nbb_sdmx(cfg["dataflow"], cfg["key"], freq),
            f"nbb/{cfg['dataflow']}",
        )
        return _to_observations(pairs, conv, freq)


# ---------------- Slovakia — SUSR ----------------

class SusrSkProvider(_SubBase):
    name = "susr_sk"
    display_name = "Statistical Office of the Slovak Republic"
    _INDEX = _merge_db_index("susr_sk", _build_susr_index(), _cfgs_by_slug(_v1.SK_SERIES))

    def fetch_series(self, spec: SeriesSpec) -> list[Observation]:
        cfg = self._resolve(spec)
        freq = cfg["freq"]
        conv = cfg["conversion"]
        dsid = cfg["dataset_id"]
        # V1 special: nu1807qs_synthetic = P5 - P51G
        if dsid == "nu1807qs_synthetic":
            p5 = _wrap_v1_call(
                lambda: _v1.fetch_sk_datacube(
                    "nu1807qs", ["all", "all", "U_NU_P5", "MJ_CLV20_MEUR"], "Q"),
                "susr_sk/nu1807qs P5",
            )
            p51g = _wrap_v1_call(
                lambda: _v1.fetch_sk_datacube(
                    "nu1807qs", ["all", "all", "U_NU_P51G", "MJ_CLV20_MEUR"], "Q"),
                "susr_sk/nu1807qs P51G",
            )
            p5_map = dict(p5)
            p51g_map = dict(p51g)
            pairs = [(dt, p5_map[dt] - p51g_map[dt])
                     for dt in sorted(set(p5_map) & set(p51g_map))]
            return _to_observations(pairs, conv, freq)

        pairs = _wrap_v1_call(
            lambda: _v1.fetch_sk_datacube(dsid, cfg["segments"], freq),
            f"susr_sk/{dsid}",
        )
        return _to_observations(pairs, conv, freq)


# ---------------- Hungary — KSH ----------------

class KshHuProvider(_SubBase):
    name = "ksh_hu"
    display_name = "Hungarian Central Statistical Office"
    _INDEX = _merge_db_index("ksh_hu", _build_ksh_index(), _cfgs_by_slug(_v1.HU_SERIES))

    def fetch_series(self, spec: SeriesSpec) -> list[Observation]:
        cfg = self._resolve(spec)
        freq = cfg["freq"]
        conv = cfg["conversion"]
        parser = cfg.get("parser")
        table = cfg["table"]
        if table == "kkr_synthetic":
            pairs = _wrap_v1_call(_v1.fetch_hu_trade_balance, "ksh_hu/kkr_synthetic")
        elif parser == "mun0159_count":
            pairs = _wrap_v1_call(
                lambda: _v1.fetch_hu_mun0159_count(cfg["value_col_index"]),
                "ksh_hu/mun0159",
            )
        elif parser == "mun0099_rolling":
            pairs = _wrap_v1_call(
                lambda: _v1.fetch_hu_mun0099_rolling(cfg["value_col_index"]),
                "ksh_hu/mun0099",
            )
        elif parser == "nep0001_annual":
            pairs = _wrap_v1_call(
                lambda: _v1.fetch_hu_nep0001_annual(cfg["row_index"]),
                "ksh_hu/nep0001",
            )
        elif cfg.get("row_oriented"):
            pairs = _wrap_v1_call(
                lambda: _v1.fetch_hu_stadat_row(
                    table, cfg["row_index"],
                    cfg.get("n_years", 5), cfg.get("start_year", 2022),
                    section=cfg.get("section", "ara"),
                ),
                f"ksh_hu/{table}",
            )
        else:
            pairs = _wrap_v1_call(
                lambda: _v1.fetch_hu_stadat(
                    table, cfg["value_col_index"], freq,
                    section=cfg.get("section", "ara"),
                ),
                f"ksh_hu/{table}",
            )
        return _to_observations(pairs, conv, freq)


# ---------------- Romania — INSSE ----------------

class InsseRoProvider(_SubBase):
    name = "insse_ro"
    display_name = "INSSE — Romania"
    _INDEX = _merge_db_index(
        "insse_ro",
        _build_insse_index(),
        _cfgs_by_slug(_v1.RO_SERIES + _v1.RO_TRADE_SERIES),
    )

    def fetch_series(self, spec: SeriesSpec) -> list[Observation]:
        cfg = self._resolve(spec)
        freq = cfg["freq"]
        conv = cfg["conversion"]
        # Trade-balance is a derived series in V1.  In V2 we expose it under
        # series_id 'INSSE/EXP101I-EXP102I' if it ever lands in data_series.
        if cfg.get("series_id") == "INSSE/EXP101I-EXP102I" or cfg.get("slug") == "trade-balance":
            # Find exports & imports cfgs in RO_TRADE_SERIES
            exp = next((c for c in _v1.RO_TRADE_SERIES if c.get("slug") == "exports"), None)
            imp = next((c for c in _v1.RO_TRADE_SERIES if c.get("slug") == "imports"), None)
            if exp and imp:
                exp_pairs = _wrap_v1_call(
                    lambda: _v1.fetch_ro_tempo(
                        exp["parent"], exp["matrix"],
                        exp.get("filter_dims", {}), exp.get("unit_value"),
                        exp["freq"], exp.get("row_filter"),
                    ),
                    "insse_ro/exports",
                )
                imp_pairs = _wrap_v1_call(
                    lambda: _v1.fetch_ro_tempo(
                        imp["parent"], imp["matrix"],
                        imp.get("filter_dims", {}), imp.get("unit_value"),
                        imp["freq"], imp.get("row_filter"),
                    ),
                    "insse_ro/imports",
                )
                exp_map = dict(exp_pairs)
                imp_map = dict(imp_pairs)
                pairs = [(dt, (exp_map[dt] - imp_map[dt]) * 1e-3)
                         for dt in sorted(set(exp_map) & set(imp_map))]
                return _to_observations(pairs, conv, freq)

        pairs = _wrap_v1_call(
            lambda: _v1.fetch_ro_tempo(
                cfg["parent"], cfg["matrix"],
                cfg.get("filter_dims", {}), cfg.get("unit_value", "Procente"),
                freq, cfg.get("row_filter"),
            ),
            f"insse_ro/{cfg['matrix']}",
        )
        return _to_observations(pairs, conv, freq)


# ---------------- Malta — NSO ----------------

class NsoMtProvider(_SubBase):
    name = "nso_mt"
    display_name = "National Statistics Office Malta"
    _INDEX = _merge_db_index("nso_mt", _build_nso_index(), _cfgs_by_slug(_v1.MT_SERIES))

    def fetch_series(self, spec: SeriesSpec) -> list[Observation]:
        cfg = self._resolve(spec)
        freq = cfg["freq"]
        conv = cfg["conversion"]
        derive = cfg.get("derive")
        if derive == "lfs_unemp_rate":
            pairs = _wrap_v1_call(_v1.fetch_mt_lfs_unemp_rate, "nso_mt/lfs_unemp_rate")
            return _to_observations(pairs, conv, freq)
        if derive == "mt_trade_balance":
            exp = _wrap_v1_call(
                lambda: _v1.fetch_mt_sdmx("DF_ITGS_D_HS", "M..X.", "M", aggregate="sum_product"),
                "nso_mt/exports",
            )
            imp = _wrap_v1_call(
                lambda: _v1.fetch_mt_sdmx("DF_ITGS_A_HS", "M..M.", "M", aggregate="sum_product"),
                "nso_mt/imports",
            )
            exp_map = dict(exp)
            imp_map = dict(imp)
            pairs = [(dt, (exp_map[dt] - imp_map[dt]) * 0.001)
                     for dt in sorted(set(exp_map) & set(imp_map))]
            return _to_observations(pairs, conv, freq)
        pairs = _wrap_v1_call(
            lambda: _v1.fetch_mt_sdmx(cfg["dataflow"], cfg["key"], freq,
                                       aggregate=cfg.get("aggregate")),
            f"nso_mt/{cfg['dataflow']}",
        )
        return _to_observations(pairs, conv, freq)


# ---------------- Cyprus — CYSTAT ----------------

class CystatCyProvider(_SubBase):
    name = "cystat_cy"
    display_name = "Statistical Service of Cyprus"
    _INDEX = _merge_db_index("cystat_cy", _build_cystat_index(), _cfgs_by_slug(_v1.CY_SERIES))

    def fetch_series(self, spec: SeriesSpec) -> list[Observation]:
        cfg = self._resolve(spec)
        freq = cfg["freq"]
        conv = cfg["conversion"]
        if "pxweb_query" in cfg:
            pairs = _wrap_v1_call(
                lambda: _v1.fetch_cy_pxweb_generic(
                    cfg["px_path"], cfg["pxweb_query"], cfg["time_dim"], freq,
                ),
                f"cystat_cy/{cfg['px_path']}",
            )
        else:
            pairs = _wrap_v1_call(
                lambda: _v1.fetch_cy_pxweb(cfg["px_path"], cfg["base_year"], freq),
                f"cystat_cy/{cfg['px_path']}",
            )
        return _to_observations(pairs, conv, freq)


# ----------------------------------------------------------------------------
# Self-registration (16 classes)
# ----------------------------------------------------------------------------

from pipeline.dispatcher import register_provider  # noqa: E402

_ALL_SUB_PROVIDERS: tuple[type[_SubBase], ...] = (
    DstProvider, StatFiProvider, ScbSeProvider, InePtProvider,
    CsoIeProvider, StatAtProvider, SursSiProvider, CspLvProvider,
    StatEeProvider, DzsHrProvider, StatbelProvider, NbbProvider,
    SusrSkProvider, KshHuProvider, InsseRoProvider, NsoMtProvider,
    CystatCyProvider,
)

for _cls in _ALL_SUB_PROVIDERS:
    try:
        register_provider(_cls())
    except Exception as e:  # noqa: BLE001
        print(f"[warn] {_cls.__name__} not registered: {e}")
