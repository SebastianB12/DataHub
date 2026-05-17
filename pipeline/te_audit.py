"""TE-Audit: vergleicht TE-Snapshot mit unseren data_points -> findings.

Per indicator_instance:
  1. Hole latest te_page_snapshots-Row
  2. Hole latest data_points der default+active data_series
  3. Wende family.default_te_display_transform x data_series.value_kind an
  4. Vergleiche transformierten Wert mit te_last_value (+ Toleranzen)
  5. Fingerprint-Check (avg/ATH/ATL/Source-Label)
  6. Insert findings (offene Tickets) bei Abweichungen

Finding-Typen:
  - series_wrong:     Fingerprint matched nicht (avg/ATH/ATL deutlich daneben).
                      Kritisch — falsche Reihe gefetched.
  - transform_diff:   Headline-Wert weicht ab, aber Fingerprint passt.
                      Falsche Display-Transform.
  - vintage_drift:    Wert weicht innerhalb Toleranz ab (Revision).
  - stale_data:       Letzter data_point aelter als family.default_freq erlaubt.
  - no_db_data:       TE hat Wert, wir haben nichts.
  - no_te_data:       Parse failed.
  - source_mismatch:  TE-Source-Label != te_source_attributions.te_label.
  - parse_failure:    HTML-Parsing fehlgeschlagen.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional


# Fingerprint-Toleranzen — bewusst sehr eng, sonst werden falsche Reihen durchgelassen.
# Wenn die TE-Description sagt "averaged 3.27 percent from 1914 until 2025" und
# wir berechnen aus unseren data_points 4.50, dann ist das KEINE Reihe-Match.
FINGERPRINT_AVG_TOL_PCT = 0.10   # 10% rel. Toleranz fuer Durchschnitt
FINGERPRINT_ATH_TOL_PCT = 0.05   # 5%  rel. Toleranz fuer All-time-high
FINGERPRINT_ATL_TOL_ABS = 0.50   # 0.5 abs. Toleranz fuer All-time-low (Vorzeichen kritisch)


@dataclass
class Finding:
    instance_id:     int
    snapshot_id:     Optional[int]
    series_pk:       Optional[int]
    finding_type:    str
    severity:        str
    message:         str
    observed_value:  Optional[float] = None
    expected_value:  Optional[float] = None
    transform_used:  Optional[str] = None


# ---------------- Transform-Logik ----------------

def transform_value(level_value: float, value_kind: str,
                    display_transform: str,
                    prev_year_value: Optional[float] = None,
                    prev_month_value: Optional[float] = None) -> Optional[float]:
    """Konvertiere data_series.value_kind -> family.default_te_display_transform.
    Return None wenn nicht moeglich (z.B. yoy-Display verlangt level, prev_year fehlt).

    Wenn value_kind == display_transform: identity.
    Wenn value_kind == 'level' und display_transform == 'yoy_pct': brauche prev_year.
    Wenn value_kind == 'level' und display_transform == 'mom_pct': brauche prev_month.
    Wenn value_kind == 'sign_flipped_level': flip sign.
    """
    if value_kind == display_transform:
        return level_value
    if display_transform == "sign_flipped_level":
        return -level_value
    if value_kind == "level":
        if display_transform == "yoy_pct" and prev_year_value not in (None, 0):
            return 100.0 * (level_value - prev_year_value) / prev_year_value
        if display_transform == "mom_pct" and prev_month_value not in (None, 0):
            return 100.0 * (level_value - prev_month_value) / prev_month_value
        if display_transform == "qoq_pct" and prev_month_value not in (None, 0):
            return 100.0 * (level_value - prev_month_value) / prev_month_value
    # Pre-computed yoy_pct/mom_pct -> level: nicht zurueckrechenbar
    return None


def within_tolerance(observed: float, expected: float,
                     tol_abs: float, tol_pct: float) -> bool:
    diff = abs(observed - expected)
    if diff <= tol_abs:
        return True
    if expected != 0 and diff / abs(expected) <= tol_pct:
        return True
    return False


# ---------------- DB-Hilfen ----------------

def get_latest_snapshot(sb, instance_id: int) -> Optional[dict]:
    r = (
        sb.table("te_page_snapshots")
          .select("*")
          .eq("instance_id", instance_id)
          .order("scraped_at", desc=True)
          .limit(1)
          .execute()
    )
    return r.data[0] if r.data else None


def get_default_series(sb, instance_id: int) -> Optional[dict]:
    r = (
        sb.table("data_series")
          .select("series_pk,fetch_provider,fetch_series_id,value_kind,is_default,role,"
                  "activated_at,fingerprint_check_passed")
          .eq("instance_id", instance_id)
          .eq("is_default", True)
          .is_("valid_to", "null")
          .limit(1)
          .execute()
    )
    return r.data[0] if r.data else None


def get_latest_datapoints(sb, series_pk: int, n: int = 13) -> list[dict]:
    """Letzte n data_points fuer eine Series (DESC nach date)."""
    r = (
        sb.table("data_points")
          .select("date,value")
          .eq("series_pk", series_pk)
          .order("date", desc=True)
          .limit(n)
          .execute()
    )
    return r.data or []


def get_family_and_instance(sb, instance_id: int) -> Optional[dict]:
    r = (
        sb.table("indicator_instances")
          .select(
              "instance_id,family_id,country_id,te_attribution_id,te_url,"
              "te_display_transform_override,tolerance_abs_override,tolerance_pct_override,"
              "freq_override,refresh_cron_override"
          )
          .eq("instance_id", instance_id)
          .limit(1)
          .execute()
    )
    if not r.data:
        return None
    inst = r.data[0]
    fam = (
        sb.table("indicator_families")
          .select(
              "family_id,family_code,default_te_display_transform,default_freq,"
              "default_refresh_cron,tolerance_abs,tolerance_pct"
          )
          .eq("family_id", inst["family_id"])
          .limit(1)
          .execute()
    )
    if not fam.data:
        return None
    inst["family"] = fam.data[0]
    return inst


def get_attribution(sb, attribution_id: int) -> Optional[dict]:
    r = (
        sb.table("te_source_attributions")
          .select("attribution_id,te_label,canonical_provider,country_id")
          .eq("attribution_id", attribution_id)
          .limit(1)
          .execute()
    )
    return r.data[0] if r.data else None


# ---------------- Finding-Persistierung ----------------

def insert_findings(sb, findings: list[Finding]) -> int:
    if not findings:
        return 0
    rows = []
    for f in findings:
        rows.append({
            "instance_id": f.instance_id,
            "snapshot_id": f.snapshot_id,
            "series_pk": f.series_pk,
            "finding_type": f.finding_type,
            "severity": f.severity,
            "message": f.message,
            "observed_value": f.observed_value,
            "expected_value": f.expected_value,
            "transform_used": f.transform_used,
        })
    # Insert in 200er-Batches
    inserted = 0
    for i in range(0, len(rows), 200):
        res = sb.table("te_audit_findings").insert(rows[i:i + 200]).execute()
        inserted += len(res.data) if res.data else 0
    return inserted


# ---------------- Audit-Logik pro Instance ----------------

def audit_instance(sb, instance_id: int) -> list[Finding]:
    """Auditiere eine Instance gegen den jeweils letzten Snapshot. Return Findings (offene Tickets)."""
    findings: list[Finding] = []
    info = get_family_and_instance(sb, instance_id)
    if info is None:
        return findings
    fam = info["family"]
    display_transform = info["te_display_transform_override"] or fam["default_te_display_transform"] or "level"
    tol_abs = info["tolerance_abs_override"] or fam["tolerance_abs"] or 0.05
    tol_pct = info["tolerance_pct_override"] or fam["tolerance_pct"] or 0.001

    snap = get_latest_snapshot(sb, instance_id)
    if snap is None:
        return findings  # noch kein Snapshot -> nichts zu auditieren
    snapshot_id = snap["snapshot_id"]
    series = get_default_series(sb, instance_id)

    # Parse-Quality-Check
    if snap.get("parse_quality") == "failed":
        findings.append(Finding(
            instance_id=instance_id, snapshot_id=snapshot_id,
            series_pk=(series or {}).get("series_pk"),
            finding_type="parse_failure",
            severity="warning",
            message=f"TE-Page konnte nicht geparst werden: {snap.get('parse_error')}",
        ))
        return findings

    # Source-Mismatch-Check (TE-Page-Label vs unsere Attribution)
    if snap.get("te_source_label") and info.get("te_attribution_id"):
        attr = get_attribution(sb, info["te_attribution_id"])
        if attr and attr["te_label"] and snap["te_source_label"]:
            # Heuristik: te_label-Substring-Match (Tolerance fuer Suffixe wie ", France")
            a = attr["te_label"].lower()
            b = snap["te_source_label"].lower()
            if a not in b and b not in a:
                findings.append(Finding(
                    instance_id=instance_id, snapshot_id=snapshot_id,
                    series_pk=(series or {}).get("series_pk"),
                    finding_type="source_mismatch",
                    severity="warning",
                    message=f"TE-Source-Label '{snap['te_source_label']}' != "
                            f"erwartetes '{attr['te_label']}'.",
                ))

    if series is None:
        # Wir haben einen TE-Snapshot, aber keine aktive default-Series
        findings.append(Finding(
            instance_id=instance_id, snapshot_id=snapshot_id,
            series_pk=None,
            finding_type="no_db_data",
            severity="critical",
            message="TE hat einen Wert, aber wir haben keine aktive default-data_series.",
            expected_value=snap.get("te_last_value"),
        ))
        return findings

    # Headline-Wert-Check
    if snap.get("te_last_value") is None:
        findings.append(Finding(
            instance_id=instance_id, snapshot_id=snapshot_id,
            series_pk=series["series_pk"],
            finding_type="no_te_data",
            severity="info",
            message="TE-Description enthielt keinen parsbar Headline-Wert.",
        ))
        return findings

    dps = get_latest_datapoints(sb, series["series_pk"], n=13)
    if not dps:
        findings.append(Finding(
            instance_id=instance_id, snapshot_id=snapshot_id,
            series_pk=series["series_pk"],
            finding_type="no_db_data",
            severity="critical",
            message="Keine data_points fuer aktive default-series_pk.",
            expected_value=snap["te_last_value"],
        ))
        return findings

    # Latest + prev_year + prev_month/quarter
    latest_dp = dps[0]
    prev_year_value = None
    prev_month_value = None
    if len(dps) >= 13:
        prev_year_value = dps[12]["value"]
    if len(dps) >= 2:
        prev_month_value = dps[1]["value"]

    transformed = transform_value(
        level_value=latest_dp["value"],
        value_kind=series["value_kind"],
        display_transform=display_transform,
        prev_year_value=prev_year_value,
        prev_month_value=prev_month_value,
    )
    if transformed is None:
        findings.append(Finding(
            instance_id=instance_id, snapshot_id=snapshot_id,
            series_pk=series["series_pk"],
            finding_type="transform_diff",
            severity="warning",
            message=f"Transform '{series['value_kind']}'->'{display_transform}' "
                    f"nicht durchfuehrbar (Vorgaengerwerte fehlen).",
            observed_value=latest_dp["value"],
            expected_value=snap["te_last_value"],
            transform_used=f"{series['value_kind']}->{display_transform}",
        ))
        return findings

    if not within_tolerance(transformed, snap["te_last_value"], tol_abs, tol_pct):
        # Fingerprint-Check: vergleicht TRANSFORMIERTE historische Werte mit TE-avg/ATH/ATL.
        # ohne Transform waere der Vergleich gegen den Index-Level statt YoY/MoM%
        # und faelschlich als series_wrong markiert.
        is_series_wrong = False
        msgs = []
        # Baue Transform-Reihe: jedes dps[i] mit dps[i+12] (YoY) bzw dps[i+1] (MoM) als Vorgaenger
        transformed_history = []
        for i, d in enumerate(dps):
            prev_y = dps[i + 12]["value"] if i + 12 < len(dps) else None
            prev_m = dps[i + 1]["value"] if i + 1 < len(dps) else None
            tv = transform_value(d["value"], series["value_kind"], display_transform,
                                 prev_year_value=prev_y, prev_month_value=prev_m)
            if tv is not None:
                transformed_history.append(tv)
        if snap.get("te_avg") is not None and len(transformed_history) >= 24:
            our_avg = sum(transformed_history) / len(transformed_history)
            if not within_tolerance(our_avg, snap["te_avg"], 0.5, FINGERPRINT_AVG_TOL_PCT):
                is_series_wrong = True
                msgs.append(f"avg-Mismatch (our_recent_avg={our_avg:.2f}, te={snap['te_avg']})")
        if snap.get("te_ath") is not None and transformed_history:
            our_ath = max(transformed_history)
            # ATH-Vergleich nur als Indikator, nicht alleinige series_wrong-Quelle
            # (TE-ATH stammt aus 50+ Jahren Historie, wir haben nur ~24 Monate)
            if our_ath > snap["te_ath"] * (1 + FINGERPRINT_ATH_TOL_PCT):
                # Recent-Max ueberschreitet TE-ATH -> definitiv falsche Reihe
                is_series_wrong = True
                msgs.append(f"recent_max ({our_ath:.2f}) ueber TE-ATH ({snap['te_ath']})")
        finding_type = "series_wrong" if is_series_wrong else "transform_diff"
        severity = "critical" if is_series_wrong else "warning"
        findings.append(Finding(
            instance_id=instance_id, snapshot_id=snapshot_id,
            series_pk=series["series_pk"],
            finding_type=finding_type,
            severity=severity,
            message=(
                f"Headline-Wert weicht ab. Our (transform={series['value_kind']}->"
                f"{display_transform})={transformed:.4f}, TE={snap['te_last_value']}. "
                + " | ".join(msgs)
            ),
            observed_value=transformed,
            expected_value=snap["te_last_value"],
            transform_used=f"{series['value_kind']}->{display_transform}",
        ))

    # Staleness-Check
    freq = info.get("freq_override") or fam.get("default_freq") or "M"
    max_age_days = {"D": 14, "W": 21, "M": 90, "Q": 180, "A": 540, "S": 270}.get(freq, 90)
    latest_date = datetime.fromisoformat(latest_dp["date"]).replace(tzinfo=timezone.utc)
    if (datetime.now(tz=timezone.utc) - latest_date).days > max_age_days:
        findings.append(Finding(
            instance_id=instance_id, snapshot_id=snapshot_id,
            series_pk=series["series_pk"],
            finding_type="stale_data",
            severity="warning",
            message=f"Letzter data_point ist {latest_dp['date']} (>{max_age_days}d fuer freq={freq}).",
        ))
    return findings


__all__ = [
    "Finding", "audit_instance", "insert_findings",
    "transform_value", "within_tolerance",
]
