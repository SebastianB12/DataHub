import os
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

supabase = create_client(
    os.environ["SUPABASE_URL"],
    os.environ["SUPABASE_SERVICE_ROLE_KEY"],
)


def upsert_data_points(points: list[dict]) -> int:
    """Upsert data points into Supabase. Returns number of rows affected."""
    if not points:
        return 0
    result = supabase.table("data_points").upsert(
        points,
        on_conflict="indicator,country,date",
    ).execute()
    return len(result.data)


def log_pipeline_run(source: str, status: str, rows_upserted: int = 0, error_message: str | None = None):
    """Log a pipeline run to the pipeline_runs table."""
    supabase.table("pipeline_runs").insert({
        "source": source,
        "status": status,
        "rows_upserted": rows_upserted,
        "error_message": error_message,
        "finished_at": datetime.utcnow().isoformat() if status != "running" else None,
    }).execute()
