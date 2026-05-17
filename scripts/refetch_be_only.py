"""Refetch only BE-affected indicators after re-audit fix.

Targets:
 - Statbel CPI subgroups (cpi-clothing/food/housing-utilities/transportation)
 - NBB government-spending-eur (alias)
"""
from __future__ import annotations

import sys
from datetime import date

from pipeline.base_provider import DataPoint
from pipeline.providers.national_eu import (
    BE_SERIES, fetch_be_statbel_csv, fetch_nbb_sdmx,
)
from pipeline.db import upsert_data_points, datapoints_to_rows
from pipeline.transforms import normalize_date

TARGETS = {
    "cpi-clothing", "cpi-food", "cpi-housing-utilities", "cpi-transportation",
    "government-spending-eur",
}

def main():
    out: list[DataPoint] = []
    for cfg in BE_SERIES:
        if cfg["slug"] not in TARGETS:
            continue
        kind = cfg["kind"]
        try:
            if kind == "statbel":
                pairs = fetch_be_statbel_csv(
                    cfg["view_id"], cfg["value_col"], cfg["freq"],
                    cfg.get("row_filter"),
                )
                src = "statbel"
                sid = f"STATBEL/{cfg['view_id'][:8]}"
            elif kind == "nbb":
                pairs = fetch_nbb_sdmx(cfg["dataflow"], cfg["key"], cfg["freq"])
                src = "nbb"
                sid = f"NBB/{cfg['dataflow']}/{cfg['key']}"
            else:
                continue
            for dt, val in pairs:
                out.append(DataPoint(
                    indicator=cfg["slug"], country="BE",
                    date=normalize_date(dt, cfg["freq"]),
                    value=float(val) * float(cfg.get("conversion") or 1),
                    source=src,
                    unit=cfg.get("unit", ""),
                    series_id=sid,
                    adjustment=cfg.get("adjustment", "") or "",
                ))
            print(f"  {cfg['slug']}: {len(pairs)} pts, latest={pairs[-1] if pairs else None}")
        except Exception as e:
            print(f"  FAIL {cfg['slug']}: {e}", file=sys.stderr)

    print(f"Total points: {len(out)}")
    rows = datapoints_to_rows(out)
    n = upsert_data_points(rows)
    print(f"Upserted: {n}")


if __name__ == "__main__":
    main()
