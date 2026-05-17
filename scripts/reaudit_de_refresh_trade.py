"""Refresh DE trade-related Destatis data (51000-0002): exports, imports, trade-balance."""
import sys
sys.stdout.reconfigure(encoding="utf-8")

import time
from dotenv import load_dotenv
load_dotenv()

from pipeline.providers.destatis import (
    _setup_pystatis,
    _fetch_table,
    _parse_dataframe,
    _compute_trade_balance,
    TABLES,
)
from pipeline.db import datapoints_to_rows, upsert_data_points


def main():
    _setup_pystatis()
    trade_tables = [t for t in TABLES if t.get("name") == "51000-0002"]
    all_points = []
    # Single full fetch then parse for each indicator config (saves one Destatis hit)
    df_full = _fetch_table("51000-0002", startyear="1991")
    print(f"  Full table: {len(df_full)} rows")
    # Also fetch only 2026 with explicit startyear to capture newest months
    df_2026 = _fetch_table("51000-0002", startyear="2026")
    print(f"  2026 sub: {len(df_2026)} rows")
    import pandas as pd
    df_merged = pd.concat([df_full, df_2026]).drop_duplicates()
    print(f"  Merged: {len(df_merged)} rows")
    for table in trade_tables:
        print(f"Parsing {table['indicator']}...")
        points = _parse_dataframe(df_merged, table)
        if points:
            print(f"  {len(points)} points ({min(p.date for p in points)} -> {max(p.date for p in points)})")
            all_points.extend(points)
        time.sleep(1)
    balance = _compute_trade_balance(all_points)
    if balance:
        print(f"  trade-balance computed: {len(balance)} points")
        all_points.extend(balance)
    rows = datapoints_to_rows(all_points)
    total = 0
    for i in range(0, len(rows), 500):
        c = upsert_data_points(rows[i:i+500])
        total += c
    print(f"Upserted {total} rows.")


if __name__ == "__main__":
    main()
