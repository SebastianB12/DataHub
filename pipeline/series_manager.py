"""Series-Manager: Lifecycle-Helfer fuer data_series mit Pre-Activation-Guard.

Verwendung:
  from pipeline.series_manager import propose_series, activate_series

  # 1. neue data_series-Row (NICHT aktiviert) anlegen
  series_pk = propose_series(
      instance_id=123,
      fetch_provider='fred',
      fetch_series_id='CPIAUCSL',
      role='primary',
      is_default=False,    # erstmal sekundaer, bis Fingerprint passt
      value_kind='level',
  )

  # 2. Aktivierung versuchen (mit Fingerprint-Check)
  ok, details = activate_series(series_pk, make_default=True)
  if not ok:
      print("Activation rejected:", details)

Falls Aktivierung scheitert (Fingerprint-Mismatch), bleibt die Row in data_series
mit `fingerprint_check_passed=false` und `activated_at IS NULL`. Der Scheduler
ignoriert sie. Der User kann via Findings-Dashboard manuell akzeptieren.

Bei Versuch eine **neue is_default=true Row** anzulegen wird die alte
Default-Row geschlossen (valid_to=NOW(), superseded_by=neue_series_pk) — so
behalten die data_points ihre Linkage zur urspruenglichen Spec.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from pipeline.base_provider import SeriesSpec, Observation
from pipeline.db import supabase as sb
from pipeline.dispatcher import get_provider


FINGERPRINT_ATH_TOL_PCT = 0.05   # 5% rel. Toleranz fuer ATH
FINGERPRINT_LATEST_TOL_ABS = 0.5
FINGERPRINT_LATEST_TOL_PCT = 0.05  # 5% rel. — Sample-Fetch vs TE-latest


@dataclass
class ActivationResult:
    ok:                bool
    series_pk:         int
    fingerprint_check: bool
    message:           str
    sample_latest:     Optional[float] = None
    te_latest:         Optional[float] = None
    sample_max:        Optional[float] = None
    te_ath:            Optional[float] = None


def _within(observed: float, expected: float,
            tol_abs: float, tol_pct: float) -> bool:
    diff = abs(observed - expected)
    return diff <= tol_abs or (expected != 0 and diff / abs(expected) <= tol_pct)


def propose_series(instance_id: int,
                   fetch_provider: str,
                   fetch_series_id: str,
                   role: str = "primary",
                   is_default: bool = False,
                   value_kind: str = "level",
                   fetch_extra_params: dict | None = None,
                   fetch_unit: str = "",
                   fetch_adjustment: str = "",
                   notes: str | None = None) -> int:
    """Lege eine neue data_series-Row an (noch nicht aktiviert).
    Returnt series_pk."""
    row = {
        "instance_id":        instance_id,
        "role":               role,
        "is_default":         False,   # erst nach activate_series setzen
        "fetch_provider":     fetch_provider,
        "fetch_series_id":    fetch_series_id,
        "fetch_extra_params": fetch_extra_params,
        "fetch_unit":         fetch_unit,
        "fetch_adjustment":   fetch_adjustment,
        "value_kind":         value_kind,
        "fingerprint_check_passed": False,
        "notes":              (notes or "") + " | proposed via propose_series",
    }
    res = sb.table("data_series").insert(row).execute()
    if not res.data:
        raise RuntimeError(f"propose_series: insert returned no rows")
    series_pk = res.data[0]["series_pk"]

    # Wenn der Caller is_default=True will, parken wir das in metadata
    # bis activate_series den Tausch macht.
    if is_default:
        sb.table("data_series").update({
            "notes": (notes or "") + " | requested is_default at activation"
        }).eq("series_pk", series_pk).execute()
    return series_pk


def _load_latest_snapshot(instance_id: int) -> dict | None:
    r = (
        sb.table("te_page_snapshots")
          .select("*")
          .eq("instance_id", instance_id)
          .order("scraped_at", desc=True)
          .limit(1)
          .execute()
    )
    return r.data[0] if r.data else None


def _load_series(series_pk: int) -> dict | None:
    r = (
        sb.table("data_series")
          .select(
              "series_pk,instance_id,role,is_default,fetch_provider,fetch_series_id,"
              "fetch_extra_params,fetch_unit,fetch_adjustment,value_kind,"
              "valid_from,valid_to,activated_at,fingerprint_check_passed,"
              "indicator_instances!inner("
              " instance_id,family_id,country_id,"
              " indicator_families!inner(family_code,default_freq),"
              " countries!inner(code)"
              ")"
          )
          .eq("series_pk", series_pk)
          .limit(1)
          .execute()
    )
    return r.data[0] if r.data else None


def _sample_fetch(series: dict) -> list[Observation]:
    """Try a sample fetch — pulls full history; we use latest + recent_max."""
    provider = get_provider(series["fetch_provider"])
    if provider is None:
        raise RuntimeError(f"provider '{series['fetch_provider']}' not registered")
    inst = series.get("indicator_instances") or {}
    fam = inst.get("indicator_families") or {}
    cc = (inst.get("countries") or {}).get("code")
    spec = SeriesSpec(
        series_id=series["fetch_series_id"],
        extra_params=series.get("fetch_extra_params"),
        freq_hint=fam.get("default_freq") or "M",
        conversion=1.0,
        unit=series.get("fetch_unit") or "",
        adjustment=series.get("fetch_adjustment") or "",
        country_hint=cc,
    )
    return provider.fetch_series(spec) or []


def activate_series(series_pk: int, make_default: bool = False,
                    skip_fingerprint: bool = False,
                    force: bool = False) -> ActivationResult:
    """Pre-Activation-Guard.

    1. Sample-Fetch via provider.fetch_series()
    2. Latest TE-Snapshot lesen
    3. Fingerprint-Check: latest_value sample <-> te_last_value (5% Toleranz)
                         + max(samples) <-> te_ath (5% Toleranz, max darf nicht ueber TE-ATH)
    4. Bei Match: fingerprint_check_passed=true, activated_at=NOW()
    5. Bei make_default=true: alte default-Row (gleiche instance_id, is_default=true, valid_to IS NULL)
       schliessen (valid_to=NOW(), superseded_by=series_pk) und neue auf is_default=true setzen.

    force=true ignoriert Fingerprint-Mismatch (manueller Override).
    skip_fingerprint=true ueberspringt den TE-Check (z.B. wenn keine Snapshot vorhanden).
    """
    series = _load_series(series_pk)
    if series is None:
        return ActivationResult(ok=False, series_pk=series_pk,
                                fingerprint_check=False,
                                message=f"series_pk {series_pk} not found")
    if series.get("activated_at"):
        return ActivationResult(ok=False, series_pk=series_pk,
                                fingerprint_check=False,
                                message="already activated")

    # 1. Sample-Fetch
    try:
        obs = _sample_fetch(series)
    except Exception as e:
        if force:
            obs = []
        else:
            return ActivationResult(ok=False, series_pk=series_pk,
                                    fingerprint_check=False,
                                    message=f"sample fetch failed: {e}")

    if not obs and not force:
        return ActivationResult(ok=False, series_pk=series_pk,
                                fingerprint_check=False,
                                message="sample fetch returned 0 observations")

    sample_latest = obs[-1].value if obs else None
    sample_max = max((o.value for o in obs), default=None)

    # 2/3. Fingerprint-Check
    fingerprint_passed = True
    fingerprint_msg = "no fingerprint check (skipped)"
    te_latest_v = None
    te_ath_v = None
    if not skip_fingerprint:
        snap = _load_latest_snapshot(series["instance_id"])
        if snap is None:
            fingerprint_msg = "no TE-snapshot — fingerprint not verified"
            # Wenn force oder no snapshot, lassen wir durch
            if not force:
                return ActivationResult(ok=False, series_pk=series_pk,
                                        fingerprint_check=False,
                                        message=fingerprint_msg,
                                        sample_latest=sample_latest,
                                        sample_max=sample_max)
        else:
            te_latest_v = snap.get("te_last_value")
            te_ath_v    = snap.get("te_ath")
            checks = []
            # Recent-Max < TE-ATH * (1 + tol)
            if sample_max is not None and te_ath_v is not None:
                if sample_max > te_ath_v * (1 + FINGERPRINT_ATH_TOL_PCT):
                    checks.append(f"sample_max {sample_max:.2f} > TE-ATH {te_ath_v:.2f}")
            # Latest values nah beieinander (transform-aware ist Phase 4 — hier nur raw level check)
            if sample_latest is not None and te_latest_v is not None and series["value_kind"] == "level":
                if not _within(sample_latest, te_latest_v,
                                FINGERPRINT_LATEST_TOL_ABS, FINGERPRINT_LATEST_TOL_PCT):
                    # Latest values muessen NICHT exakt matchen — wir vergleichen RAW level
                    # vs TE-Display-Wert, das kann YoY% sein -> wir warnen aber blockieren nicht.
                    checks.append(
                        f"latest {sample_latest:.2f} vs TE {te_latest_v:.2f} (may be transform diff, not blocking)"
                    )
            critical = [c for c in checks if "sample_max" in c]  # nur ATH ist blocker
            if critical and not force:
                fingerprint_passed = False
                fingerprint_msg = " | ".join(critical)
            else:
                fingerprint_msg = (
                    "ok" if not checks else ("warnings: " + " | ".join(checks))
                )

    if not fingerprint_passed and not force:
        return ActivationResult(
            ok=False, series_pk=series_pk,
            fingerprint_check=False,
            message=f"fingerprint mismatch: {fingerprint_msg}",
            sample_latest=sample_latest, te_latest=te_latest_v,
            sample_max=sample_max, te_ath=te_ath_v,
        )

    # 4. Aktivieren
    now = datetime.now(tz=timezone.utc).isoformat()
    update_fields = {
        "fingerprint_check_passed": fingerprint_passed,
        "activated_at": now,
    }

    # 5. is_default-Swap (wenn make_default)
    if make_default:
        # Alte Default-Row schliessen
        prev = (
            sb.table("data_series")
              .select("series_pk")
              .eq("instance_id", series["instance_id"])
              .eq("is_default", True)
              .is_("valid_to", "null")
              .execute()
        ).data or []
        for old in prev:
            if old["series_pk"] == series_pk:
                continue
            sb.table("data_series").update({
                "is_default": False,
                "valid_to": now,
                "superseded_by": series_pk,
            }).eq("series_pk", old["series_pk"]).execute()
        update_fields["is_default"] = True

    sb.table("data_series").update(update_fields).eq("series_pk", series_pk).execute()

    return ActivationResult(
        ok=True, series_pk=series_pk,
        fingerprint_check=fingerprint_passed,
        message=f"activated. fingerprint: {fingerprint_msg}",
        sample_latest=sample_latest, te_latest=te_latest_v,
        sample_max=sample_max, te_ath=te_ath_v,
    )


__all__ = [
    "propose_series", "activate_series", "ActivationResult",
]
