"""
Dynamic scheduler for EconPulse data pipeline.
Reads data_sources table from Supabase, registers APScheduler jobs.
Each job runs the corresponding provider's run() function.

Usage: python -m pipeline.scheduler
"""

import signal
import sys

from apscheduler.schedulers.blocking import BlockingScheduler
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


def _parse_schedule(schedule_str: str) -> dict | None:
    """Parse schedule string like 'interval:15m' to APScheduler trigger kwargs."""
    if not schedule_str or ":" not in schedule_str:
        return None

    kind, value = schedule_str.split(":", 1)
    if kind != "interval":
        return None

    # Parse value: "15m", "1h", "30s"
    if value.endswith("m"):
        return {"minutes": int(value[:-1])}
    if value.endswith("h"):
        return {"hours": int(value[:-1])}
    if value.endswith("s"):
        return {"seconds": int(value[:-1])}

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

        trigger_kwargs = _parse_schedule(schedule)
        if not trigger_kwargs:
            print(f"  SKIP {slug}: invalid schedule '{schedule}'")
            continue

        scheduler.add_job(
            _run_provider,
            trigger=IntervalTrigger(**trigger_kwargs),
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
