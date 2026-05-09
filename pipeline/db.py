import os
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

supabase = create_client(
    os.environ["SUPABASE_URL"],
    os.environ["SUPABASE_SERVICE_ROLE_KEY"],
)


def datapoints_to_rows(points: list) -> list[dict]:
    """Convert DataPoint objects to dicts for Supabase upsert.

    adjustment is always stored as a non-null string ("" for unspecified).
    Postgres unique constraints treat NULL as distinct, so NULL here would
    break upsert and produce duplicate rows per (indicator, country, date, source).
    """
    return [
        {
            "indicator": p.indicator,
            "country": p.country,
            "date": p.date.isoformat(),
            "value": p.value,
            "source": p.source,
            "unit": p.unit or None,
            "series_id": p.series_id or None,
            "adjustment": p.adjustment or "",
        }
        for p in points
    ]


def upsert_data_points(points: list[dict]) -> int:
    """Upsert data points into Supabase. Returns number of rows affected.

    Deduplicates within the batch by (indicator, country, date, source, adjustment) —
    Postgres ON CONFLICT forbids a single command from hitting the same constrained
    row twice, so two providers that resolve to the same key in one fetch would error.
    Later occurrences win (arbitrary but deterministic given stable iteration order).
    """
    if not points:
        return 0
    dedup: dict[tuple, dict] = {}
    for p in points:
        key = (p["indicator"], p["country"], p["date"], p["source"], p["adjustment"])
        dedup[key] = p
    unique = list(dedup.values())
    result = supabase.table("data_points").upsert(
        unique,
        on_conflict="indicator,country,date,source,adjustment",
    ).execute()
    return len(result.data)


def load_series_config(source: str) -> list[dict]:
    """Load active series configuration for a provider from indicator_sources.

    Replaces hardcoded Python dicts in pipeline/providers/*.py.
    Each row has: indicator, country, series_id, conversion, unit, adjustment,
    freq_hint, extra_params (jsonb), is_default, transform, note.
    """
    result = (
        supabase.table("indicator_sources")
        .select("*")
        .eq("source", source)
        .eq("active", True)
        .execute()
    )
    return result.data or []


def log_pipeline_run(source: str, status: str, rows_upserted: int = 0, error_message: str | None = None):
    """Log a pipeline run to the pipeline_runs table."""
    supabase.table("pipeline_runs").insert({
        "source": source,
        "status": status,
        "rows_upserted": rows_upserted,
        "error_message": error_message,
        "finished_at": datetime.utcnow().isoformat() if status != "running" else None,
    }).execute()
