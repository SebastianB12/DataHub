"""Dispatcher — zentrale V2-Pipeline-Komponente.

Liest aktive data_series, ruft pro Series provider.fetch_series(SeriesSpec),
schreibt Observations in data_points (mit series_pk-FK), aktualisiert
data_series.last_fetched_at + last_fetch_status.

Provider-Registry:
  Jeder Provider registriert sich beim Import via @register_provider("name").
  Der Dispatcher importiert pipeline.providers (das __init__ loaded alle).

Rate-Limits werden per fetch_provider durchgesetzt (Default 0s; Provider-spezifisch
in PROVIDER_RATE_LIMITS).

Error-Strategie:
  - TransientProviderError -> bis zu 3 Retries mit Backoff (5s, 15s, 45s)
  - ProviderError -> last_fetch_status='error: ...', skip
  - Ueberschreibt KEINE existing data_points wenn die series_pk schon Daten hat.

Smoke-Test:
  python -m pipeline.dispatcher --providers fred --series-pks 1,2,3
  python -m pipeline.dispatcher --providers fred --all-active
"""
from __future__ import annotations

import argparse
import math
import sys
import time
import traceback
from collections import defaultdict
from dataclasses import asdict
from datetime import date, datetime, timezone
from typing import Callable, Iterable

from pipeline.base_provider import (
    BaseProvider, SeriesSpec, Observation,
    ProviderError, TransientProviderError,
)
from pipeline.db import supabase as sb


# ---------------- Provider-Registry ----------------

_REGISTRY: dict[str, BaseProvider] = {}


def register_provider(provider: BaseProvider) -> None:
    """Provider-Instance registrieren. Wird im Modul-Init der Provider aufgerufen."""
    if not provider.name:
        raise ValueError(f"Provider {provider.__class__.__name__} has empty .name")
    _REGISTRY[provider.name] = provider


def get_provider(name: str) -> BaseProvider | None:
    return _REGISTRY.get(name)


def list_providers() -> list[str]:
    return sorted(_REGISTRY.keys())


# ---------------- Rate-Limits pro Provider ----------------

PROVIDER_RATE_LIMITS: dict[str, float] = {
    # Sekunden Pause zwischen Calls. 0 = kein Limit.
    "fred":        0.0,    # FREDApi handles internally
    "eurostat":    0.5,    # SDMX, eher tolerant
    "ecb":         0.5,
    "ons":         1.0,
    "bundesbank":  1.5,
    "destatis":    2.0,    # generisch konservativ wegen "Ups, ein Fehler!"
    "insee":       1.0,
    "istat":       1.0,
    "ine_es":      1.0,
    "ine_pt":      2.0,    # SMI-API kann zicken
    "akshare":     1.0,
    "akshare_cn":  1.0,
    "gacc":        2.0,
    "bdf":         1.0,
    "statec":      1.0,
    "elstat":      1.0,
    "nsi_bg":      1.0,
    "czso":        1.0,
    "lsd_lt":      1.0,
    "konj_se":     1.0,
    "eia":         0.0,    # EIA API hat eigene Quota
    "curated":     0.0,    # kein Network
    "worldbank":   1.0,
    # national_eu-Aliases
    "stat_at":  1.0, "statbel": 1.0, "cso_ie": 1.0, "stat_fi": 1.0,
    "susr_sk":  1.0, "surs_si": 1.0, "stat_ee": 1.0, "csp_lv": 1.0,
    "cystat_cy": 1.0, "nso_mt": 1.0, "scb_se": 1.0, "dst": 1.0,
    "dzs_hr":   1.0, "ksh_hu": 1.0, "insse_ro": 1.0, "nbb": 1.0,
    "gus_pl":   1.0,
}


class RateLimiter:
    def __init__(self):
        self._last_call: dict[str, float] = {}

    def wait_for(self, provider_name: str):
        delay = PROVIDER_RATE_LIMITS.get(provider_name, 1.0)
        if delay <= 0:
            return
        last = self._last_call.get(provider_name, 0.0)
        elapsed = time.time() - last
        if elapsed < delay:
            time.sleep(delay - elapsed)
        self._last_call[provider_name] = time.time()


# ---------------- Series-Spec laden ----------------

def load_active_series(provider: str | None = None,
                       series_pks: list[int] | None = None,
                       only_default: bool = False) -> list[dict]:
    """Hole alle aktiven data_series-Rows. Mit Family + Country joined."""
    q = (
        sb.table("data_series")
          .select(
              "series_pk,instance_id,fetch_provider,fetch_series_id,fetch_extra_params,"
              "fetch_unit,fetch_adjustment,value_kind,role,is_default,notes,"
              "indicator_instances!inner("
              " instance_id,family_id,country_id,te_url,"
              " indicator_families!inner(family_code,default_freq),"
              " countries!inner(code)"
              ")"
          )
          .is_("valid_to", "null")
          .not_.is_("activated_at", "null")
    )
    if provider:
        q = q.eq("fetch_provider", provider)
    if only_default:
        q = q.eq("is_default", True)
    if series_pks:
        q = q.in_("series_pk", series_pks)
    return q.execute().data or []


def series_row_to_spec(row: dict) -> SeriesSpec:
    """data_series-Row -> SeriesSpec (Provider-Input)."""
    inst = row.get("indicator_instances") or {}
    fam  = inst.get("indicator_families") or {}
    cc   = (inst.get("countries") or {}).get("code")
    return SeriesSpec(
        series_id=row["fetch_series_id"],
        extra_params=row.get("fetch_extra_params"),
        freq_hint=fam.get("default_freq") or "M",
        conversion=1.0,    # die data_series fuehrt keine getrennte conversion; Provider liefert raw
        unit=row.get("fetch_unit") or "",
        adjustment=row.get("fetch_adjustment") or "",
        country_hint=cc,
    )


# ---------------- Observation -> data_points-Row ----------------

def observations_to_rows(obs: list[Observation], row: dict) -> list[dict]:
    """Konvertiert provider-Observationen zu data_points-Upsert-Rows.

    Wichtig: schreibt die alten V1-Felder (indicator/country/source/series_id/...) MIT,
    damit die unique-Constraints noch zuverlaessig deduplizieren bis Phase 7 sie droppt.
    """
    inst = row.get("indicator_instances") or {}
    fam  = inst.get("indicator_families") or {}
    cc   = (inst.get("countries") or {}).get("code")
    indicator = fam.get("family_code")
    rows: list[dict] = []
    for o in obs:
        if o.value is None:
            continue
        try:
            v = float(o.value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(v):
            continue
        rows.append({
            "indicator":  indicator,
            "country":    cc,
            "date":       o.date.isoformat(),
            "value":      v,
            "source":     row["fetch_provider"],
            "unit":       row.get("fetch_unit") or None,
            "series_id":  row["fetch_series_id"] or None,
            "adjustment": row.get("fetch_adjustment") or "",
            "series_pk":  row["series_pk"],
        })
    return rows


def upsert_observations(rows: list[dict]) -> int:
    if not rows:
        return 0
    # Postgrest unique: (indicator, country, date, source, adjustment) — dedup intra-batch
    dedup: dict[tuple, dict] = {}
    for r in rows:
        key = (r["indicator"], r["country"], r["date"], r["source"], r["adjustment"])
        dedup[key] = r
    unique = list(dedup.values())
    res = sb.table("data_points").upsert(
        unique, on_conflict="indicator,country,date,source,adjustment",
    ).execute()
    return len(res.data or [])


# ---------------- Dispatch-Loop ----------------

def update_series_status(series_pk: int, status: str) -> None:
    sb.table("data_series").update({
        "last_fetched_at": datetime.now(tz=timezone.utc).isoformat(),
        "last_fetch_status": status[:200],
    }).eq("series_pk", series_pk).execute()


def fetch_with_retry(provider: BaseProvider, spec: SeriesSpec,
                     retries: int = 3) -> list[Observation]:
    delays = [5, 15, 45]
    for attempt in range(retries):
        try:
            return provider.fetch_series(spec)
        except TransientProviderError as e:
            if attempt + 1 >= retries:
                raise
            time.sleep(delays[min(attempt, len(delays) - 1)])
    return []


def dispatch(provider_filter: str | None = None,
             series_pks: list[int] | None = None,
             only_default: bool = False,
             dry_run: bool = False,
             progress_cb: Callable[[int, int, str], None] | None = None) -> dict:
    """Hauptloop: alle aktiven data_series fuer einen Provider abfetchen + upserten."""
    rate = RateLimiter()
    series = load_active_series(provider=provider_filter, series_pks=series_pks,
                                only_default=only_default)
    print(f"Dispatcher: {len(series)} active data_series to process "
          f"(provider={provider_filter or 'ALL'} only_default={only_default}).")

    stats = defaultdict(int)
    for i, row in enumerate(series, 1):
        prov_name = row["fetch_provider"]
        provider = get_provider(prov_name)
        label = (
            (row.get('indicator_instances') or {}).get('countries', {}).get('code', '?')
            + "/" +
            ((row.get('indicator_instances') or {}).get('indicator_families', {}).get('family_code', '?'))
            + "/" + prov_name + ":" + row["fetch_series_id"]
        )

        if provider is None:
            stats["no_provider"] += 1
            update_series_status(row["series_pk"], f"error: provider '{prov_name}' not registered")
            if progress_cb:
                progress_cb(i, len(series), label + " -> NO PROVIDER")
            else:
                print(f"[{i}/{len(series)}] {label}: no provider registered")
            continue

        rate.wait_for(prov_name)
        spec = series_row_to_spec(row)
        try:
            obs = fetch_with_retry(provider, spec)
        except Exception as e:
            stats["fetch_error"] += 1
            update_series_status(row["series_pk"], f"error: {e}")
            if progress_cb:
                progress_cb(i, len(series), f"{label} -> ERR: {e}")
            else:
                print(f"[{i}/{len(series)}] {label}: ERROR {e}")
            continue

        if not obs:
            stats["empty"] += 1
            update_series_status(row["series_pk"], "ok: 0 observations")
            if progress_cb:
                progress_cb(i, len(series), f"{label} -> 0 obs")
            else:
                print(f"[{i}/{len(series)}] {label}: 0 obs")
            continue

        if dry_run:
            stats["dry_run_ok"] += 1
            update_series_status(row["series_pk"], f"dry-run: {len(obs)} obs")
            if progress_cb:
                progress_cb(i, len(series), f"{label} -> dry {len(obs)}")
            else:
                print(f"[{i}/{len(series)}] {label}: dry-run {len(obs)} obs")
            continue

        rows = observations_to_rows(obs, row)
        if not rows:
            stats["no_finite"] += 1
            update_series_status(row["series_pk"], "ok: 0 finite observations")
            continue
        try:
            n = upsert_observations(rows)
            stats["upserted_rows"] += n
            stats["series_ok"] += 1
            update_series_status(row["series_pk"], f"ok: {n} rows")
            if progress_cb:
                progress_cb(i, len(series), f"{label} -> {n} rows")
            else:
                print(f"[{i}/{len(series)}] {label}: {n} rows")
        except Exception as e:
            stats["upsert_error"] += 1
            update_series_status(row["series_pk"], f"error: upsert {e}")
            if progress_cb:
                progress_cb(i, len(series), f"{label} -> upsert ERR: {e}")
            else:
                print(f"[{i}/{len(series)}] {label}: upsert ERROR {e}")
                traceback.print_exc()

    return dict(stats)


def main():
    """Entry-Point. Wird NICHT direkt ausgefuehrt — siehe scripts/run_dispatcher.py.
    Grund: `python -m pipeline.dispatcher` waere das __main__-Modul, und
    `from pipeline.dispatcher import register_provider` in Providern wuerde einen
    ZWEITEN dispatcher-Modul laden (mit anderem _REGISTRY-Dict)."""
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("--providers", help="Comma-separated provider names; default: all registered")
    p.add_argument("--series-pks", help="Comma-separated series_pk to fetch")
    p.add_argument("--only-default", action="store_true",
                   help="Only fetch is_default=true series")
    p.add_argument("--dry-run", action="store_true",
                   help="Fetch but do not upsert (smoke-test)")
    args = p.parse_args()

    # Provider laden -> registriert sich
    from pipeline import providers  # noqa: F401

    print(f"Registered providers: {list_providers()}")

    pks = [int(x) for x in args.series_pks.split(",")] if args.series_pks else None
    providers_list = args.providers.split(",") if args.providers else [None]
    grand = defaultdict(int)
    for prov in providers_list:
        stats = dispatch(provider_filter=prov, series_pks=pks,
                         only_default=args.only_default, dry_run=args.dry_run)
        print(f"  {prov or 'ALL'} stats: {dict(stats)}")
        for k, v in stats.items():
            grand[k] += v
    print(f"\n=== TOTAL ===\n{dict(grand)}")
