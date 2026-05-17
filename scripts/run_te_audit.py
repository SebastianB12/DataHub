"""Mass-Audit-Runner.

  python -m scripts.run_te_audit --countries US --slugs inflation-cpi,unemployment,interest-rate
  python -m scripts.run_te_audit --all  # 2160 instances, ~6h bei 20s/Call
  python -m scripts.run_te_audit --countries US,GB,DE --rate-s 15

Idempotent: ueberspringt Instances die bereits einen Snapshot < --reuse-age-days haben.
Schreibt:
  - te_page_snapshots (1 row pro erfolgreichem Fetch)
  - te_audit_findings (offene Tickets pro Abweichung)
  - druckt Zwischen-Summary alle 25 Calls
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

sys.stdout.reconfigure(encoding="utf-8")

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from pipeline.db import supabase as sb
from pipeline.te_parser import RateLimiter, scrape_instance
from pipeline.te_audit import audit_instance, insert_findings


def load_instances(countries: Optional[list[str]] = None,
                   slugs: Optional[list[str]] = None,
                   limit: Optional[int] = None) -> list[dict]:
    """Holt aktive indicator_instances inkl. country-code und family-code."""
    q = sb.table("indicator_instances").select(
        "instance_id, te_url, country_id, family_id, is_active"
    ).eq("is_active", True)
    if limit:
        q = q.limit(limit)
    rows = q.execute().data or []
    # Filter via separate lookup-Maps
    ccs = {r["country_id"]: r["code"] for r in sb.table("countries").select("country_id,code").execute().data}
    fams = {r["family_id"]: r["family_code"] for r in sb.table("indicator_families").select("family_id,family_code").execute().data}
    for r in rows:
        r["country_code"] = ccs.get(r["country_id"])
        r["family_code"] = fams.get(r["family_id"])
    if countries:
        rows = [r for r in rows if r["country_code"] in countries]
    if slugs:
        rows = [r for r in rows if r["family_code"] in slugs]
    return rows


def fresh_snapshot_exists(instance_id: int, max_age_days: int) -> bool:
    cutoff = (datetime.now(tz=timezone.utc) - timedelta(days=max_age_days)).isoformat()
    r = (
        sb.table("te_page_snapshots")
          .select("snapshot_id")
          .eq("instance_id", instance_id)
          .gte("scraped_at", cutoff)
          .limit(1)
          .execute()
    )
    return bool(r.data)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--countries", help="Comma-separated ISO codes (e.g. US,GB,DE)")
    p.add_argument("--slugs", help="Comma-separated family codes (e.g. inflation-cpi,ppi)")
    p.add_argument("--limit", type=int, help="Max instances to process (smoke-test)")
    p.add_argument("--rate-s", type=float, default=20.0, help="Sekunden zwischen Calls")
    p.add_argument("--reuse-age-days", type=int, default=7,
                   help="Snapshot wird wieder verwendet wenn juenger als N Tage; "
                        "0 = immer neu scrapen.")
    p.add_argument("--all", action="store_true", help="Run all 2160 instances")
    args = p.parse_args()

    countries = args.countries.split(",") if args.countries else None
    slugs = args.slugs.split(",") if args.slugs else None
    if not (args.all or countries or slugs or args.limit):
        p.error("Specify --all, --countries, --slugs, or --limit.")

    instances = load_instances(countries=countries, slugs=slugs, limit=args.limit)
    print(f"Loaded {len(instances)} instances. Rate: {args.rate_s}s/call.")

    rate = RateLimiter(normal_delay_s=args.rate_s)
    stats = {"ok": 0, "skipped_fresh": 0, "403": 0, "404": 0, "fail": 0,
             "audit_findings": 0}
    t0 = time.time()

    for i, inst in enumerate(instances, 1):
        instance_id = inst["instance_id"]
        te_url = inst["te_url"]
        label = f"{inst.get('country_code')}/{inst.get('family_code')}"

        if args.reuse_age_days > 0 and fresh_snapshot_exists(instance_id, args.reuse_age_days):
            print(f"[{i:>4}/{len(instances)}] {label}: reuse fresh snapshot")
            stats["skipped_fresh"] += 1
        else:
            status, snap_id = scrape_instance(sb, instance_id, te_url, rate)
            if status == "ok":
                stats["ok"] += 1
                print(f"[{i:>4}/{len(instances)}] {label}: ok (snapshot_id={snap_id})")
            elif status == "403":
                stats["403"] += 1
                print(f"[{i:>4}/{len(instances)}] {label}: 403 (cooldown)")
                continue
            elif status == "404":
                stats["404"] += 1
                print(f"[{i:>4}/{len(instances)}] {label}: 404 ({te_url})")
                continue
            else:
                stats["fail"] += 1
                print(f"[{i:>4}/{len(instances)}] {label}: {status}")
                continue

        # Audit
        try:
            findings = audit_instance(sb, instance_id)
            if findings:
                stats["audit_findings"] += insert_findings(sb, findings)
                for f in findings:
                    print(f"    -> {f.severity.upper()} {f.finding_type}: {f.message[:120]}")
        except Exception as e:
            print(f"    -> audit error: {e}")

        if i % 25 == 0:
            elapsed = time.time() - t0
            rate_per_min = (stats["ok"]) / max(elapsed / 60, 0.01)
            remaining = (len(instances) - i) / max(rate_per_min / 60, 0.001) if rate_per_min else 0
            print(f"  [progress] {i}/{len(instances)} done, "
                  f"ok={stats['ok']} 403={stats['403']} 404={stats['404']} fail={stats['fail']} "
                  f"findings={stats['audit_findings']} elapsed={elapsed/60:.1f}min "
                  f"eta={remaining/60:.1f}min")

    print("\n=== Final ===")
    elapsed = time.time() - t0
    print(f"Duration: {elapsed/60:.1f} min")
    print(f"Stats: {stats}")


if __name__ == "__main__":
    main()
