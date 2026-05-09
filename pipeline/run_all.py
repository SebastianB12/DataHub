"""One-shot manual full refresh — runs every EconPulse provider sequentially.

Sequential (not parallel) because:
- Destatis has a 3-parallel-call limit per token (Code 6 + 15-min lockout).
- ONS has Cloudflare 1015 throttling on rapid requests.
- Sequential makes per-provider failure diagnosis simple.

Usage from repo root: pipeline/.venv/Scripts/python -m pipeline.run_all
"""

import importlib
import time
import traceback

PROVIDERS = [
    "pipeline.providers.curated",     # local YAML, no network
    "pipeline.providers.fred",        # US, well-behaved
    "pipeline.providers.worldbank",   # GDP, GDP-PPP, military
    "pipeline.providers.eurostat",    # DE/EA/GB
    "pipeline.providers.insee",       # FR (TE-source-conform via pynsee)
    "pipeline.providers.bdf",         # FR Banque de France (via DBnomics)
    "pipeline.providers.ine_es",      # ES (TE-source-conform via INE Tempus3 JSON API)
    "pipeline.providers.ecb",         # EA money/rates
    "pipeline.providers.ons",         # GB (slow due to anti-bot sleeps)
    "pipeline.providers.bundesbank",  # DE money/banking
    "pipeline.providers.destatis",    # DE — slowest, run last on the data side
    "pipeline.providers.eia",         # US energy
    "pipeline.providers.gacc",        # CN trade (Customs)
    "pipeline.providers.akshare_cn",  # CN macro (NBS/PBoC/SAFE via akshare)
]


def main():
    results: list[tuple[str, str, float]] = []
    overall_start = time.time()
    for mod_path in PROVIDERS:
        name = mod_path.rsplit(".", 1)[-1]
        bar = "=" * 60
        print(f"\n{bar}\n{name.upper()}\n{bar}")
        t0 = time.time()
        try:
            mod = importlib.import_module(mod_path)
            mod.run()
            results.append((name, "ok", time.time() - t0))
        except Exception as exc:
            print(f"\n>>> {name} FAILED: {exc}")
            traceback.print_exc()
            results.append((name, f"fail: {exc}", time.time() - t0))

    total_dt = time.time() - overall_start
    bar = "=" * 60
    print(f"\n{bar}\nSUMMARY ({total_dt:.0f}s total)\n{bar}")
    for name, status, dt in results:
        print(f"  {name:14}  {status:50}  {dt:6.0f}s")

    failed = [r for r in results if not r[1].startswith("ok")]
    if failed:
        print(f"\n{len(failed)}/{len(results)} providers failed.")
        raise SystemExit(1)
    print(f"\nAll {len(results)} providers completed successfully.")


if __name__ == "__main__":
    main()
