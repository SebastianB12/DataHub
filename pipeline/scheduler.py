"""V2 dynamic scheduler — Cron-based pro indicator_family.

Liest active data_series (valid_to IS NULL AND activated_at IS NOT NULL),
gruppiert nach (family_id, instance_id.refresh_cron_override OR family.default_refresh_cron).
Schedules pro Cron-Expression einen Job der `dispatch()` mit dem Series-pk-Set ausfuehrt.

Vorteile gegenueber V1 (data_sources-Tabelle):
  - Cron-Expression kommt aus indicator_families.default_refresh_cron (monatlich/quartal/jaehrlich).
  - Per-Instance-Override via indicator_instances.refresh_cron_override (z.B. EIA weekly).
  - Provider-Rate-Limits werden im dispatch() durchgesetzt.
  - Pre-Activation-Guard verhindert dass falsche Series gefetched werden.

Usage: python -m pipeline.scheduler
"""
from __future__ import annotations

import signal
import sys
from collections import defaultdict

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from pipeline.db import supabase
from pipeline.dispatcher import dispatch


def _run_series_batch(series_pks: list[int]):
    """Fetch + upsert eine Gruppe von Series via Dispatcher."""
    print(f"\n>>> Scheduler-Job: dispatch {len(series_pks)} series ...")
    try:
        stats = dispatch(series_pks=series_pks)
        print(f"<<< done. stats: {dict(stats)}")
    except Exception as e:
        print(f"<<< failed: {e}")


def _build_cron_trigger(cron_str: str) -> CronTrigger | None:
    """Cron-Expression (5-field) -> CronTrigger. Returns None bei Parse-Fehler."""
    if not cron_str:
        return None
    try:
        return CronTrigger.from_crontab(cron_str)
    except (ValueError, KeyError):
        return None


def _load_active_series_with_cron() -> list[dict]:
    """Aktive data_series + zugehoeriger Cron (Instance-Override > Family-Default)."""
    rows = (
        supabase.table("data_series")
          .select(
              "series_pk,instance_id,fetch_provider,"
              "indicator_instances!inner("
              " instance_id,refresh_cron_override,family_id,"
              " indicator_families!inner(family_code,default_refresh_cron)"
              ")"
          )
          .is_("valid_to", "null")
          .not_.is_("activated_at", "null")
          .execute()
          .data or []
    )
    out: list[dict] = []
    for r in rows:
        inst = r.get("indicator_instances") or {}
        fam = inst.get("indicator_families") or {}
        cron = inst.get("refresh_cron_override") or fam.get("default_refresh_cron")
        if not cron:
            continue
        out.append({
            "series_pk": r["series_pk"],
            "cron": cron,
            "family_code": fam.get("family_code"),
            "fetch_provider": r["fetch_provider"],
        })
    return out


def main():
    """Loop: laden + scheduling pro Cron-Gruppe."""
    sys.stdout.reconfigure(encoding="utf-8")
    print("Loading active data_series + cron schedules from V2 schema ...")

    # Provider-Module importieren -> Registry fuellt sich
    from pipeline import providers  # noqa: F401

    series = _load_active_series_with_cron()
    if not series:
        print("No active data_series with cron-Expression found.")
        return

    # Gruppiere series_pks pro Cron-Expression (1 APScheduler-Job pro Cron-Gruppe)
    by_cron: dict[str, list[int]] = defaultdict(list)
    for s in series:
        by_cron[s["cron"]].append(s["series_pk"])

    scheduler = BlockingScheduler()
    registered = 0
    for cron_str, pks in sorted(by_cron.items()):
        trigger = _build_cron_trigger(cron_str)
        if trigger is None:
            print(f"  SKIP cron='{cron_str}': invalid expression ({len(pks)} series)")
            continue
        job_id = f"cron_{cron_str.replace(' ', '_')}"
        scheduler.add_job(
            _run_series_batch,
            trigger=trigger,
            args=[pks],
            id=job_id,
            name=f"{cron_str} ({len(pks)} series)",
            max_instances=1,
            coalesce=True,
        )
        registered += 1
        print(f"  Registered {job_id}: {cron_str} -> {len(pks)} series")

    print(f"\n{registered} cron-Gruppen registriert. Starting scheduler ...")
    print("Press Ctrl+C to stop.\n")

    def shutdown(signum, frame):
        print("\nShutting down scheduler...")
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    scheduler.start()


if __name__ == "__main__":
    main()
