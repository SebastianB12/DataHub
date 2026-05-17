"""Fix FR exports/imports: switch from quarterly CNT P6/P7 to monthly COM-EXT (sum EU+Third+Misc).
TE labels these as 'Ministère de l'Économie et des Finances' (DGDDI/lekiosque).
COM-EXT is INSEE-hosted DGDDI customs data — closest match available.
"""
import datetime as dt
from pynsee.macrodata import get_series
from pipeline.db import supabase as sb
from pipeline.base_provider import DataPoint
from pipeline.db import datapoints_to_rows, upsert_data_points
from pipeline.transforms import normalize_date


EXPORT_IDBANKS = [
    ("001568557", "EU-27"),
    ("001569440", "Third countries"),
    ("001568969", "Misc overseas"),
]
IMPORT_IDBANKS = [
    ("001568560", "EU-27"),
    ("001569539", "Third countries"),
    ("001569479", "Misc overseas"),
]


def fetch_total(idbanks):
    df = get_series([b for b, _ in idbanks])
    df = df.dropna(subset=["OBS_VALUE"])
    # Sum by TIME_PERIOD
    df["OBS_VALUE"] = df["OBS_VALUE"].astype(float)
    totals = df.groupby("TIME_PERIOD")["OBS_VALUE"].sum().sort_index()
    return totals


def parse_month(period):
    y, m = period.split("-")
    return dt.date(int(y), int(m), 1)


def main():
    for slug, idbanks in [("exports", EXPORT_IDBANKS), ("imports", IMPORT_IDBANKS)]:
        totals = fetch_total(idbanks)
        print(f"{slug}: {len(totals)} months; last 3:")
        for p, v in totals.tail(3).items():
            print(f"  {p}: {v} Mio EUR  ({v/1000:.2f} Bn EUR)")

        # Build datapoints — convert Million EUR to Billion EUR (TE shows €52.5 Bn etc.)
        # indicators.unit for exports = "Billion USD" but our actual FR rep stays Bn EUR.
        # Best: store as Billion EUR (frontend can re-label).
        # The indicator was previously stored in "Billion EUR" too (db value 248.534), so keep that.
        pts = []
        series_id = "COM-EXT:total(EU+Third+Misc)"
        for period, val in totals.items():
            d = parse_month(period)
            pts.append(DataPoint(
                indicator=slug, country="FR",
                date=normalize_date(d, "M"),
                value=round(float(val) / 1000.0, 6),  # Mio -> Bn EUR
                source="insee",
                unit="Billion EUR",
                series_id=series_id,
                adjustment="SA",
            ))

        # Delete old + upsert
        sb.table("data_points").delete().eq("country", "FR").eq("indicator", slug).execute()
        rows = datapoints_to_rows(pts)
        for r in rows:
            if r.get("adjustment") is None:
                r["adjustment"] = ""
        n = upsert_data_points(rows)
        print(f"  Upserted {n} rows")

        # Update indicator_sources
        sb.table("indicator_sources").update({
            "source": "insee",
            "series_id": series_id,
            "extra_params": {
                "dataset": "COM-EXT",
                "method": "sum_zones",
                "zones": ["Z7712 EU-27", "Z7711 Third countries", "Z6600 Misc overseas"],
                "indicateur": "E" if slug == "exports" else "I",
                "correction": "CVS-CJO",
                "naf2": "SO",
            },
            "note": "TE-conformity 2026-05-16: switched quarterly CNT P6/P7 -> monthly COM-EXT (DGDDI via INSEE). TE label = Ministère/lekiosque; COM-EXT is the INSEE-hosted official mirror.",
        }).eq("country", "FR").eq("indicator", slug).eq("is_default", True).execute()
        print(f"  Updated indicator_sources for {slug}")

        # Verify
        dp = sb.table("data_points").select("date, value").eq("country", "FR").eq("indicator", slug).order("date", desc=True).limit(2).execute().data
        print(f"  VERIFY {slug}: latest={dp[0] if dp else None}")


if __name__ == "__main__":
    main()
