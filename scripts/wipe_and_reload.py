"""Phase 3.1e — TRUNCATE data_points + Full-Reload via V2-Dispatcher.

DESTRUKTIV. Sebastian hat das autorisiert weil bestehende data_points "vintage drift"
gegenueber TE haben und ein Full-Refresh die einzige saubere Basis fuer das
Phase-4-Audit liefert.

Sicherheits-Mechanismus:
  python -m scripts.wipe_and_reload --dump        # zeigt Pre-Counts, kein Eingriff
  python -m scripts.wipe_and_reload --confirm     # echte TRUNCATE + Reload
  python -m scripts.wipe_and_reload --reload-only # ohne TRUNCATE (upsert-Pfad)

Phasen:
  A. Pre-State-Dump (counts per country/provider)
  B. Verify alle Provider registriert
  C. TRUNCATE data_points (wenn --confirm)
  D. dispatch() pro Provider (alle aktiven data_series)
  E. Post-State-Dump + Audit-Re-Run gegen latest snapshots
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone


def status_dump(sb, label: str):
    """Status via SELECT MAX(id) als Proxy — count(*) bei 570k+ rows hat Timeouts."""
    print(f"\n--- {label} ---")
    try:
        r = sb.table("data_points").select("id").order("id", desc=True).limit(1).execute()
        max_id = r.data[0]["id"] if r.data else 0
        print(f"  data_points MAX(id): {max_id}")
    except Exception as e:
        print(f"  data_points MAX(id): err {e}")
    try:
        # Per-country count via group ist via PostgREST schwierig — wir nutzen ein SELECT pro Land
        # NUR fuer 'US' als Sanity-Check
        r = sb.table("data_points").select("count", count="exact").eq("country", "US").limit(0).execute()
        print(f"  data_points (US only, exact): {r.count}")
    except Exception as e:
        print(f"  data_points US: err {e}")
    try:
        r3 = sb.table("te_page_snapshots").select("count", count="exact").execute()
        print(f"  te_page_snapshots: {r3.count}")
    except Exception as e:
        print(f"  snapshots: err {e}")
    try:
        r4 = sb.table("te_audit_findings").select("count", count="exact").is_("resolved_at", "null").execute()
        print(f"  open findings: {r4.count}")
    except Exception as e:
        print(f"  findings: err {e}")


def truncate_data_points(sb):
    """Workaround: PostgREST hat kein TRUNCATE. Nutze grosses DELETE."""
    print("\n=== TRUNCATE data_points ===")
    # Wir koennen nur via Supabase MCP eine TRUNCATE machen — hier ein Hinweis:
    print("MANUAL STEP: Run via Supabase MCP:")
    print("  apply_migration name=phase_3_1e_wipe_data_points")
    print("  query: TRUNCATE TABLE data_points;")
    print("Then run --reload-only to fetch fresh data.")


def reload_via_dispatcher(only_default: bool = False,
                          providers_filter: list[str] | None = None) -> dict:
    """Full-Reload aller aktiven data_series via V2-Dispatcher."""
    from pipeline import providers           # noqa: F401  Provider registrieren
    from pipeline.dispatcher import dispatch, list_providers
    registered = list_providers()
    targets = providers_filter or registered
    targets = [t for t in targets if t in registered]
    print(f"\n=== Reloading via Dispatcher ===")
    print(f"Registered providers: {len(registered)}")
    print(f"Target providers: {len(targets)} — {targets}")

    grand = defaultdict(int)
    t0 = time.time()
    for prov in targets:
        bar = "=" * 60
        print(f"\n{bar}\n{prov.upper()}\n{bar}")
        try:
            stats = dispatch(provider_filter=prov, only_default=only_default)
            for k, v in stats.items():
                grand[k] += v
        except Exception as exc:
            print(f">>> {prov} FAILED: {exc}")
            grand["crashed"] += 1
    elapsed = time.time() - t0
    print(f"\n=== Reload done in {elapsed/60:.1f} min ===")
    print(f"GRAND TOTAL: {dict(grand)}")
    return dict(grand)


def audit_rerun_against_existing_snapshots() -> int:
    """Re-run audit_instance fuer alle Instances mit Snapshot — keine neuen scrapes."""
    print("\n=== Audit Re-Run (gegen existing te_page_snapshots) ===")
    from pipeline.db import supabase as sb
    from pipeline.te_audit import audit_instance, insert_findings

    # Alle Instances mit mindestens einem Snapshot
    snap_instances = sb.table("te_page_snapshots").select("instance_id").execute().data or []
    instance_ids = sorted({r["instance_id"] for r in snap_instances})
    print(f"  Instances with snapshot: {len(instance_ids)}")

    # Resolve all open findings first (sie sind veraltet nach Reload)
    now_iso = datetime.now(tz=timezone.utc).isoformat()
    res = (
        sb.table("te_audit_findings")
          .update({"resolved_at": now_iso, "resolved_by": "auto:wipe_and_reload",
                   "resolution_note": "stale; data_points freshly reloaded, re-audit pending"})
          .is_("resolved_at", "null")
          .execute()
    )
    print(f"  Resolved {len(res.data or [])} stale findings.")

    total_findings = 0
    for i, instance_id in enumerate(instance_ids, 1):
        try:
            findings = audit_instance(sb, instance_id)
            if findings:
                inserted = insert_findings(sb, findings)
                total_findings += inserted
        except Exception as e:
            print(f"  instance {instance_id} audit error: {e}")
        if i % 50 == 0:
            print(f"  {i}/{len(instance_ids)} re-audited, {total_findings} findings")
    print(f"  TOTAL new findings: {total_findings}")
    return total_findings


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("--dump", action="store_true", help="Pre-State-Dump only")
    p.add_argument("--confirm", action="store_true",
                   help="TRUNCATE + Full Reload + Re-Audit (DESTRUCTIVE)")
    p.add_argument("--reload-only", action="store_true",
                   help="Skip TRUNCATE, just upsert via dispatcher")
    p.add_argument("--only-default", action="store_true",
                   help="Only is_default=true series (faster)")
    p.add_argument("--providers", help="Comma-list, default: alle registrierten")
    p.add_argument("--audit-rerun", action="store_true",
                   help="Re-run audit_instance against existing snapshots after reload")
    args = p.parse_args()

    from pipeline.db import supabase as sb

    status_dump(sb, "PRE")

    if args.dump:
        print("\n--dump only. Exiting.")
        return

    if args.confirm:
        truncate_data_points(sb)
        print("\nAfter manual TRUNCATE, re-run with --reload-only --confirm")
        return

    if args.reload_only:
        providers = args.providers.split(",") if args.providers else None
        reload_via_dispatcher(only_default=args.only_default,
                              providers_filter=providers)
        status_dump(sb, "POST-RELOAD")
        if args.audit_rerun:
            audit_rerun_against_existing_snapshots()
            status_dump(sb, "POST-AUDIT-RERUN")
        return

    print("Usage:")
    print("  --dump            zeige Pre-Counts")
    print("  --confirm         TRUNCATE (manual via MCP) + Anweisung folgen")
    print("  --reload-only     dispatch() pro Provider")
    print("  --audit-rerun     re-audit gegen existing snapshots")


if __name__ == "__main__":
    main()
