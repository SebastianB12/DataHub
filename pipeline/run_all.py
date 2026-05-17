"""V2 one-shot manual full refresh — fetches alle aktiven data_series via Dispatcher.

Sequential pro Provider (intern Rate-Limit-controlled durch PROVIDER_RATE_LIMITS).
Falls --only-default gesetzt: nur is_default=true Reihen (Standard fuer Frontend).

Usage from repo root:
  pipeline/.venv/Scripts/python -m pipeline.run_all
  pipeline/.venv/Scripts/python -m pipeline.run_all --providers fred,eurostat
  pipeline/.venv/Scripts/python -m pipeline.run_all --only-default
"""
from __future__ import annotations

import argparse
import sys
import time
import traceback
from collections import defaultdict


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("--providers", help="Comma-separated provider names; default: alle registrierten")
    p.add_argument("--only-default", action="store_true",
                   help="Nur is_default=true Reihen")
    p.add_argument("--dry-run", action="store_true",
                   help="Fetch ohne Upsert")
    args = p.parse_args()

    # Provider laden -> Registry fuellt sich
    from pipeline import providers           # noqa: F401
    from pipeline.dispatcher import dispatch, list_providers

    registered = list_providers()
    targets = args.providers.split(",") if args.providers else registered
    targets = [t for t in targets if t in registered or t in (None,)]
    print(f"Registered providers ({len(registered)}): {registered}")
    print(f"Target providers ({len(targets)}): {targets}")

    grand_stats = defaultdict(int)
    results: list[tuple[str, dict, float]] = []
    overall_start = time.time()

    for prov in targets:
        bar = "=" * 60
        print(f"\n{bar}\n{prov.upper()}\n{bar}")
        t0 = time.time()
        try:
            stats = dispatch(provider_filter=prov,
                             only_default=args.only_default,
                             dry_run=args.dry_run)
            results.append((prov, stats, time.time() - t0))
            for k, v in stats.items():
                grand_stats[k] += v
        except Exception as exc:
            print(f"\n>>> {prov} FAILED: {exc}")
            traceback.print_exc()
            results.append((prov, {"crashed": str(exc)}, time.time() - t0))

    total_dt = time.time() - overall_start
    bar = "=" * 60
    print(f"\n{bar}\nSUMMARY ({total_dt:.0f}s total)\n{bar}")
    for prov, stats, dt in results:
        nice = ", ".join(f"{k}={v}" for k, v in stats.items())
        print(f"  {prov:14}  {nice:60}  {dt:6.0f}s")

    crashed = [r for r in results if "crashed" in r[1]]
    if crashed:
        print(f"\n{len(crashed)}/{len(results)} provider crashes.")
        raise SystemExit(1)
    print(f"\nGRAND TOTAL: {dict(grand_stats)}")
    print(f"All {len(results)} provider runs completed.")


if __name__ == "__main__":
    main()
