"""
Dynamic scheduler for EconPulse data pipeline.
Reads data_sources table from Supabase, registers APScheduler jobs.
Each job runs the corresponding provider's run() function.

Usage: python -m pipeline.scheduler
"""

import signal
import sys

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from pipeline.db import supabase, log_pipeline_run

# Lazy imports to avoid loading all providers at startup
PROVIDER_MAP = {
    "fred": "pipeline.providers.fred",
    "eurostat": "pipeline.providers.eurostat",
    "insee": "pipeline.providers.insee",
    "bdf": "pipeline.providers.bdf",
    "ecb": "pipeline.providers.ecb",
    "ons": "pipeline.providers.ons",
    "worldbank": "pipeline.providers.worldbank",
    "destatis": "pipeline.providers.destatis",
    "bundesbank": "pipeline.providers.bundesbank",
    "curated": "pipeline.providers.curated",
    "eia": "pipeline.providers.eia",
    "gacc": "pipeline.providers.gacc",
    "akshare_cn": "pipeline.providers.akshare_cn",
    "ine_es": "pipeline.providers.ine_es",
    "dbnomics": "pipeline.providers.dbnomics",
    "national_eu": "pipeline.providers.national_eu",
    "nsi_bg": "pipeline.providers.nsi_bg",
    "gus_pl": "pipeline.providers.gus_pl",
}


def _run_provider(source_slug: str):
    """Run a provider by slug, importing it lazily."""
    import importlib
    module_path = PROVIDER_MAP.get(source_slug)
    if not module_path:
        print(f"Unknown provider: {source_slug}")
        return

    try:
        module = importlib.import_module(module_path)
        module.run()
    except Exception as e:
        print(f"Provider {source_slug} failed: {e}")


def _build_trigger(schedule_str: str):
    """Parse schedule string into an APScheduler trigger.

    Supported forms:
      interval:15m / 1h / 30s      → IntervalTrigger
      cron:<crontab>               → CronTrigger from a 5-field crontab
                                      (e.g. 'cron:0 7 * * 1-5' = Mon-Fri 07:00)
    Returns None for unsupported strings.
    """
    if not schedule_str or ":" not in schedule_str:
        return None

    kind, value = schedule_str.split(":", 1)

    if kind == "interval":
        if value.endswith("m"):
            return IntervalTrigger(minutes=int(value[:-1]))
        if value.endswith("h"):
            return IntervalTrigger(hours=int(value[:-1]))
        if value.endswith("s"):
            return IntervalTrigger(seconds=int(value[:-1]))
        return None

    if kind == "cron":
        try:
            return CronTrigger.from_crontab(value)
        except (ValueError, KeyError):
            return None

    return None


def main():
    """Load data sources and start the scheduler."""
    print("Loading data sources from Supabase...")

    result = supabase.table("data_sources").select("*").eq("enabled", True).execute()
    sources = result.data or []

    if not sources:
        print("No enabled data sources found.")
        return

    scheduler = BlockingScheduler()

    for source in sources:
        slug = source["slug"]
        schedule = source.get("schedule", "")

        if slug not in PROVIDER_MAP:
            print(f"  SKIP {slug}: no provider implementation")
            continue

        trigger = _build_trigger(schedule)
        if trigger is None:
            print(f"  SKIP {slug}: invalid schedule '{schedule}'")
            continue

        scheduler.add_job(
            _run_provider,
            trigger=trigger,
            args=[slug],
            id=slug,
            name=f"{source['name']} ({schedule})",
            max_instances=1,
        )
        print(f"  Registered {slug}: {schedule}")

    print(f"\n{len(scheduler.get_jobs())} jobs registered. Starting scheduler...")
    print("Press Ctrl+C to stop.\n")

    # Graceful shutdown
    def shutdown(signum, frame):
        print("\nShutting down scheduler...")
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    scheduler.start()


if __name__ == "__main__":
    main()
