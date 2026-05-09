"""
Print a coverage matrix for every (indicator, country) combination:
 - latest data date (for recency / staleness check)
 - number of data points
 - which sources contribute

Run: python -m pipeline.coverage_matrix
"""

from collections import defaultdict
from datetime import date, datetime, timedelta
from pipeline.db import supabase


# Staleness thresholds per indicator frequency. Jährliche GDP-Reihen sollen nicht
# bei 4 Monaten already als stale markiert werden — die haben nur jährliche Releases.
FREQ_STALE_DAYS = {
    "daily": 30,
    "D": 30,
    "weekly": 45,
    "W": 45,
    "monthly": 75,   # typical 30-45 day lag + 30 day buffer
    "M": 75,
    "quarterly": 180,
    "Q": 180,
    "annual": 540,
    "A": 540,
    # Event-based series (only update when the underlying decision changes).
    # Example: ECB / Fed policy rates. Threshold is intentionally generous.
    "event": 540,
}
DEFAULT_STALE_DAYS = 120

# Indicators whose values only change on discrete events (central-bank decisions)
# rather than on a regular release schedule. coverage_matrix treats these as
# "event" frequency regardless of what the `indicators.frequency` column says.
EVENT_BASED_INDICATORS = {"interest-rate"}


def fetch_all_points():
    """Fetch every (indicator, country, date, source) row (paginated)."""
    out = []
    step = 1000
    offset = 0
    while True:
        batch = (
            supabase.table("data_points")
            .select("indicator, country, date, source")
            .range(offset, offset + step - 1)
            .execute()
        ).data
        out.extend(batch)
        if len(batch) < step:
            break
        offset += step
    return out


def fetch_taxonomy():
    indicators = (
        supabase.table("indicators")
        .select("slug, name_de, frequency")
        .order("slug")
        .execute()
    ).data
    countries = supabase.table("countries").select("code, name_de").order("code").execute().data
    return indicators, countries


def stale_threshold_for(frequency: str | None) -> int:
    if not frequency:
        return DEFAULT_STALE_DAYS
    return FREQ_STALE_DAYS.get(frequency.strip().lower(), FREQ_STALE_DAYS.get(frequency.strip(), DEFAULT_STALE_DAYS))


def main():
    print("Fetching all data points...")
    rows = fetch_all_points()
    print(f"  {len(rows)} rows loaded")

    indicators, countries = fetch_taxonomy()
    ind_slugs = [i["slug"] for i in indicators]
    freq_by_slug = {i["slug"]: i.get("frequency") for i in indicators}
    country_codes = [c["code"] for c in countries]

    # Build per (indicator, country) summary
    summary = defaultdict(lambda: {"count": 0, "sources": set(), "latest": None})
    for r in rows:
        key = (r["indicator"], r["country"])
        s = summary[key]
        s["count"] += 1
        s["sources"].add(r["source"])
        d = r["date"]
        if s["latest"] is None or d > s["latest"]:
            s["latest"] = d

    today = date.today()

    # Header
    print("\nCoverage Matrix  (latest date per indicator x country; ! = stale vs frequency)")
    print("=" * 80)

    col_w = 10
    header = f"{'indicator':<22}{'freq':<6}" + "".join(f"{c:>{col_w}}" for c in country_codes)
    print(header)
    print("-" * len(header))

    missing_pairs = []
    stale_pairs = []

    for slug in ind_slugs:
        freq = (freq_by_slug.get(slug) or "").strip()
        if slug in EVENT_BASED_INDICATORS:
            freq = "event"
        threshold = stale_threshold_for(freq)
        cells = [f"{slug:<22}{(freq or '?'):<6}"]
        for code in country_codes:
            s = summary.get((slug, code))
            if not s:
                cells.append(f"{'—':>{col_w}}")
                missing_pairs.append((slug, code))
            else:
                latest = datetime.strptime(s["latest"], "%Y-%m-%d").date()
                age_days = (today - latest).days
                stale = age_days > threshold
                label = s["latest"]
                if stale:
                    label = "!" + label
                    stale_pairs.append((slug, code, s["latest"], age_days, threshold))
                cells.append(f"{label:>{col_w}}")
        print("".join(cells))

    print("\nSummary")
    print("=" * 80)
    print(f"  Total (indicator x country) combinations: {len(ind_slugs) * len(country_codes)}")
    covered = sum(1 for k in summary)
    print(f"  Covered: {covered}")
    print(f"  Missing: {len(missing_pairs)}")
    print(f"  Stale (older than frequency-specific threshold): {len(stale_pairs)}")

    if missing_pairs:
        print("\nMissing pairs:")
        for slug, code in missing_pairs:
            print(f"  - {slug} / {code}")

    if stale_pairs:
        print("\nStale pairs (age days vs frequency threshold):")
        for slug, code, latest, age, threshold in sorted(stale_pairs, key=lambda x: x[2]):
            print(f"  - {slug} / {code}: {latest}  ({age}d, threshold {threshold}d)")

    # Sources summary
    print("\nSources per (indicator, country) — multi-source coverage:")
    multi_source_pairs = [(k, s) for k, s in summary.items() if len(s["sources"]) > 1]
    if multi_source_pairs:
        for (slug, code), s in sorted(multi_source_pairs):
            sources = ", ".join(sorted(s["sources"]))
            print(f"  - {slug} / {code}: {sources}")
    else:
        print("  (none — every series comes from exactly one source)")


if __name__ == "__main__":
    main()
