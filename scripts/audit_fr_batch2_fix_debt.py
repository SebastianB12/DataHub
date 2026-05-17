"""Switch FR government-debt + government-debt-total from eurostat to insee."""
from pipeline.db import supabase as sb
from pipeline.providers.insee import SERIES, InseeProvider
from pipeline.db import datapoints_to_rows, upsert_data_points


def main():
    # 1) Build datapoints for these two slugs only
    prov = InseeProvider()
    # Filter SERIES to just the two we care about
    target = ["government-debt", "government-debt-total"]
    # Patch SERIES in-place at module level
    import pipeline.providers.insee as mod
    orig = list(mod.SERIES)
    mod.SERIES = [s for s in orig if s["indicator"] in target]
    mod.MELODI_SERIES = []
    pts = prov.fetch()
    mod.SERIES = orig
    print(f"\nFetched {len(pts)} datapoints")

    # 2) Replace data_points for these slugs
    for slug in target:
        sb.table("data_points").delete().eq("country", "FR").eq("indicator", slug).execute()
        print(f"  Deleted existing data_points for {slug}")

    # 3) Upsert new data
    rows = datapoints_to_rows([p for p in pts if p.indicator in target])
    for r in rows:
        if r.get("adjustment") is None:
            r["adjustment"] = ""
    n = upsert_data_points(rows)
    print(f"Upserted {n} rows")

    # 4) Update indicator_sources to point at insee
    for slug, idbank, params in [
        ("government-debt", "DETTE-TRIM-APU-2020:010777608",
         {"dataset": "DETTE-TRIM-APU-2020", "idbank": "010777608",
          "filters": {"NATURE": "PROPORTION", "SECT_INST": "S13",
                      "DETTE_MAASTRICHT_INTRUMENTS": "F"}}),
        ("government-debt-total", "DETTE-TRIM-APU-2020:010777616",
         {"dataset": "DETTE-TRIM-APU-2020", "idbank": "010777616",
          "filters": {"NATURE": "VALEUR_ABSOLUE", "SECT_INST": "S13",
                      "DETTE_MAASTRICHT_INTRUMENTS": "F"}}),
    ]:
        sb.table("indicator_sources").update({
            "source": "insee",
            "series_id": idbank,
            "extra_params": params,
            "note": "TE-conformity 2026-05-16: switched eurostat→insee per TE label.",
        }).eq("country", "FR").eq("indicator", slug).eq("is_default", True).execute()
        print(f"  Updated indicator_sources for {slug} -> insee {idbank}")

    # 5) Verify
    for slug in target:
        row = sb.table("indicator_sources").select("source, series_id").eq("country", "FR").eq("indicator", slug).eq("is_default", True).execute().data
        dp = sb.table("data_points").select("date, value, source").eq("country", "FR").eq("indicator", slug).order("date", desc=True).limit(2).execute().data
        print(f"VERIFY {slug}: src={row[0]['source']} series={row[0]['series_id']} latest={dp[0] if dp else None}")


if __name__ == "__main__":
    main()
