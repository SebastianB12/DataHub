"""Phase-1.8 Migration: bestehende V1-Daten ins V2-Schema lifteen.

V1: indicators (slug, ...), indicator_sources (indicator, country, source, series_id, ...),
    data_points (indicator, country, source, ...). Wahrheiten verteilt in 5 YAMLs.

V2: indicator_families (family_code), te_source_attributions (attribution_id),
    indicator_instances (instance_id), data_series (series_pk), data_points.series_pk.

Dieses Skript ist **idempotent** (ON CONFLICT, UPDATE-or-INSERT) und kann mehrfach
gefahren werden — z.B. nach einem indicator_sources-Update darf man es nochmal
laufen lassen, um die data_series-Tabelle nachzuziehen.

Ablauf:
  A. indicator_families seed aus indicators (226 Rows)
  B. te_source_attributions ergänzen für Provider-Namen die in 083 fehlten
     (akshare, cso_ie, csp_lv, cystat_cy, dst, dzs_hr, ine_pt, insse_ro, ksh_hu,
      nbb, nso_mt, scb_se, stat_at, stat_ee, stat_fi, statbel, surs_si, susr_sk)
  C. indicator_instances seed aus indicator_sources WHERE is_default=true,
     attribution-Lookup via truth.yaml.te_label → te_source_attributions
  D. data_series seed aus indicator_sources (eine Row pro indicator_sources-Row)
  E. data_points.series_pk Backfill (UPDATE pro Series-Group)

Sicherheits-Netze:
  - Pre-Phase-Status-Dump (counts vor + nach)
  - Bestehende Series werden als grandfathered behandelt: fingerprint_check_passed=true,
    activated_at=NOW(). Phase 2 (TE-Audit) überschreibt das anhand realer Snapshots.
  - data_points.series_pk bleibt nullable in Phase 1. Phase 7 setzt NOT NULL.
"""
import os
import sys
import json
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict
import yaml

sys.stdout.reconfigure(encoding="utf-8")

# Repo-Root und pipeline.db importierbar machen
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from pipeline.db import supabase as sb  # noqa: E402


# ---------------- Mappings ----------------

# indicators.frequency -> indicator_families.default_freq
FREQ_MAP = {
    "daily": "D", "weekly": "W", "monthly": "M",
    "quarterly": "Q", "annual": "A", "event": "M",
}

# default_freq -> default_refresh_cron (UTC)
CRON_MAP = {
    "D": "0 8 * * *",             # taeglich 08:00
    "W": "0 9 * * 4",             # Donnerstag 09:00
    "M": "0 9 15 * *",            # Monatlich am 15. um 09:00
    "Q": "0 9 15 1,4,7,10 *",     # Quartal um 15. Jan/Apr/Jul/Okt 09:00
    "A": "0 9 1 2 *",             # 1. Februar 09:00
    "S": "0 9 1 1,7 *",           # Semi-annual: 1. Januar + 1. Juli
}

# indicators.default_display -> indicator_families.default_te_display_transform
DISPLAY_MAP = {
    "raw": "level",
    "yoy": "yoy_pct",
    "pop":  "level",
    None:   "level",
    "":     "level",
}

# indicator_sources.transform -> data_series.value_kind
TRANSFORM_TO_VALUE_KIND = {
    "":           "level",
    "raw":        "level",
    "none":       "level",
    "yoy":        "yoy_pct",
    "mom":        "mom_pct",
    "diff":       "level",       # trade-balance differenz; bleibt level
    "computed":   "level",
    "scale_1000": "level",
    "scale_1e6":  "level",
    "scale_1e9":  "level",
}

# Eltern-Provider fuer Aliase: source -> canonical Pipeline-Provider
PROVIDER_ALIAS = {
    "akshare":      "akshare_cn",   # akshare ist gleichbedeutend mit akshare_cn
}


def chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


# ---------------- Phase A: indicator_families ----------------

def seed_indicator_families():
    print("\n=== Phase A: indicator_families ===")
    inds = sb.table("indicators").select(
        "slug,name,category,frequency,unit,unit_type,default_display"
    ).execute().data
    print(f"  indicators rows: {len(inds)}")

    payload = []
    for ind in inds:
        freq = FREQ_MAP.get((ind.get("frequency") or "").lower(), "M")
        cron = CRON_MAP[freq]
        transform = DISPLAY_MAP.get(ind.get("default_display"), "level")
        payload.append({
            "family_code": ind["slug"],
            "family_name": ind["name"],
            "category": ind.get("category"),
            "default_te_display_transform": transform,
            "default_freq": freq,
            "default_refresh_cron": cron,
            "default_unit": ind.get("unit") or ind.get("unit_type"),
        })

    # upsert via ON CONFLICT (family_code)
    res = sb.table("indicator_families").upsert(
        payload, on_conflict="family_code"
    ).execute()
    print(f"  indicator_families upserted: {len(res.data)}")
    return {row["family_code"]: row for row in res.data}


# ---------------- Phase B: te_source_attributions ergaenzen ----------------

def ensure_provider_attributions(country_lookup):
    """Stelle sicher dass fuer jedes (country, source)-Paar in indicator_sources
    eine Attribution existiert. Falls 083 das schon angelegt hat (echtes te_label) -> ok.
    Sonst lege Default-Attribution mit te_label = uppercased source an.
    """
    print("\n=== Phase B: te_source_attributions Auffuellen ===")
    pairs = sb.rpc("get_distinct_source_country_pairs").execute() if False else None
    # PostgREST kann kein DISTINCT direkt; via Python aggregaten
    rows = sb.table("indicator_sources").select("country,source").execute().data
    distinct = {(r["country"], r["source"]) for r in rows}
    print(f"  distinct (country, source): {len(distinct)}")

    # Existing attributions: canonical_provider -> ja, te_label match -> ja
    existing_attr = sb.table("te_source_attributions").select(
        "attribution_id,te_label,country_id,canonical_provider"
    ).execute().data
    by_cprov_country = defaultdict(list)  # (canonical_provider, country_id) -> [attribution_ids]
    for a in existing_attr:
        by_cprov_country[(a["canonical_provider"], a["country_id"])].append(a)

    new_rows = []
    for country_code, source in distinct:
        country_id = country_lookup.get(country_code)
        if country_id is None:
            print(f"  WARN: unknown country '{country_code}' in indicator_sources -> skipped")
            continue
        cprov = PROVIDER_ALIAS.get(source, source)
        # Match: gibt es schon eine attribution fuer (cprov, country_id)?
        if by_cprov_country.get((cprov, country_id)):
            continue
        # Globale Match: cprov ohne country?
        if by_cprov_country.get((cprov, None)):
            continue
        # Fallback: neuer Stub-Eintrag (Phase 2 ueberschreibt mit echtem TE-Label)
        new_rows.append({
            "te_label": source,            # provisorisch — wird in Phase 2 ueberschrieben
            "te_url": None,
            "country_id": country_id,
            "canonical_provider": cprov,
            "notes": "auto-seeded by migrate_to_v2; replace te_label with real TE-attribution in Phase 2.",
        })

    if new_rows:
        for batch in chunks(new_rows, 200):
            res = sb.table("te_source_attributions").upsert(
                batch, on_conflict="te_label,country_id"
            ).execute()
        print(f"  attributions auto-seeded: {len(new_rows)}")
    else:
        print("  attributions: nothing to add")

    # Re-Load attributions fuer Phase C/D Lookup
    all_attr = sb.table("te_source_attributions").select(
        "attribution_id,te_label,country_id,canonical_provider"
    ).execute().data
    return all_attr


# ---------------- Phase C: indicator_instances ----------------

def load_truth_yaml():
    """Lese alle docs/_te_inventory/<CC>.yaml. Return dict (country, slug) -> entry."""
    truth = {}
    inv_dir = REPO / "docs" / "_te_inventory"
    for yaml_file in sorted(inv_dir.glob("*.yaml")):
        try:
            with yaml_file.open(encoding="utf-8") as fh:
                doc = yaml.safe_load(fh) or {}
        except Exception as e:
            print(f"  WARN: cannot parse {yaml_file.name}: {e}")
            continue
        for cc, slugs in doc.items():
            if not isinstance(slugs, dict):
                continue
            for slug, entry in slugs.items():
                if isinstance(entry, dict):
                    truth[(cc, slug)] = entry
    # zusaetzlich docs/te_sources_truth.yaml (legacy, hat manchmal mehr Details)
    legacy = REPO / "docs" / "te_sources_truth.yaml"
    if legacy.exists():
        with legacy.open(encoding="utf-8") as fh:
            doc = yaml.safe_load(fh) or {}
        for cc, slugs in doc.items():
            if not isinstance(slugs, dict):
                continue
            for slug, entry in slugs.items():
                if isinstance(entry, dict):
                    truth.setdefault((cc, slug), entry)
    print(f"  truth.yaml entries loaded: {len(truth)}")
    return truth


def seed_indicator_instances(country_lookup, family_lookup, attribution_lookup_fn, te_path_lookup, truth):
    print("\n=== Phase C: indicator_instances ===")
    # Alle Default-Sources die wir tracken
    rows = sb.table("indicator_sources").select(
        "indicator,country,source,active,is_default"
    ).eq("is_default", True).eq("active", True).execute().data
    print(f"  default+active indicator_sources rows: {len(rows)}")

    payload = []
    skipped_missing_family = 0
    skipped_missing_country = 0
    for r in rows:
        slug = r["indicator"]
        cc = r["country"]
        source = r["source"]
        family = family_lookup.get(slug)
        if family is None:
            skipped_missing_family += 1
            continue
        country_id = country_lookup.get(cc)
        if country_id is None:
            skipped_missing_country += 1
            continue
        # Truth-Entry holen
        truth_entry = truth.get((cc, slug)) or {}
        te_label = truth_entry.get("te_label")
        te_url = truth_entry.get("te_page")
        if not te_url:
            te_path = te_path_lookup.get(cc, cc.lower())
            te_url = f"https://tradingeconomics.com/{te_path}/{slug}"
        # Attribution finden
        attribution_id = attribution_lookup_fn(te_label, country_id, source)
        if attribution_id is None:
            print(f"  WARN no attribution for ({cc}, {slug}, source={source}, te_label={te_label!r})")
            continue
        payload.append({
            "family_id": family["family_id"],
            "country_id": country_id,
            "te_attribution_id": attribution_id,
            "te_url": te_url,
            "is_active": True,
            "notes": f"auto-seeded from indicator_sources (source={source}).",
        })

    print(f"  skipped (missing family): {skipped_missing_family}")
    print(f"  skipped (missing country): {skipped_missing_country}")
    print(f"  payload: {len(payload)}")

    # Upsert via composite-unique (country_id, family_id)
    for batch in chunks(payload, 200):
        sb.table("indicator_instances").upsert(
            batch, on_conflict="country_id,family_id"
        ).execute()
    # Re-load fuer Lookup
    instances = sb.table("indicator_instances").select(
        "instance_id,family_id,country_id,te_attribution_id,te_url"
    ).execute().data
    print(f"  indicator_instances now: {len(instances)}")
    return {(i["country_id"], i["family_id"]): i for i in instances}


# ---------------- Phase D: data_series ----------------

def seed_data_series(country_lookup, family_lookup, instances_by_cf, attribution_by_id):
    print("\n=== Phase D: data_series ===")
    rows = sb.table("indicator_sources").select(
        "indicator,country,source,series_id,transform,conversion,unit,adjustment,"
        "freq_hint,extra_params,active,is_default,note"
    ).eq("active", True).execute().data
    print(f"  active indicator_sources rows: {len(rows)}")

    # Existing data_series fuer Idempotenz-Check holen
    existing_ds = sb.table("data_series").select(
        "series_pk,instance_id,fetch_provider,fetch_series_id"
    ).is_("valid_to", "null").execute().data
    existing_by_key = {
        (d["instance_id"], d["fetch_provider"], d["fetch_series_id"]): d
        for d in existing_ds
    }
    print(f"  existing active data_series: {len(existing_ds)}")

    new_payload = []
    skipped = 0
    for r in rows:
        slug = r["indicator"]
        cc = r["country"]
        family = family_lookup.get(slug)
        country_id = country_lookup.get(cc)
        if family is None or country_id is None:
            skipped += 1
            continue
        instance = instances_by_cf.get((country_id, family["family_id"]))
        if instance is None:
            # non-default source (z.B. secondary) deren default-Instance noch nicht existiert
            skipped += 1
            continue
        provider = r["source"]
        series_id_value = r["series_id"]
        key = (instance["instance_id"], provider, series_id_value)
        if key in existing_by_key:
            continue  # bereits angelegt
        # value_kind aus transform
        value_kind = TRANSFORM_TO_VALUE_KIND.get((r.get("transform") or "").lower(), "level")
        # Deviation-Reason: wenn fetch_provider != canonical_provider der attribution
        attribution = attribution_by_id.get(instance["te_attribution_id"])
        canonical = (attribution or {}).get("canonical_provider")
        canonical_resolved = PROVIDER_ALIAS.get(provider, provider)
        deviation_reason = None
        if canonical and canonical != canonical_resolved:
            deviation_reason = (
                f"v1-grandfathered: TE attributes '{(attribution or {}).get('te_label')}' "
                f"(canonical {canonical}) but pipeline fetches via {provider}. "
                f"Phase-2 audit re-evaluates."
            )
        new_payload.append({
            "instance_id": instance["instance_id"],
            "role": "primary" if r.get("is_default") else "secondary",
            "is_default": bool(r.get("is_default")),
            "fetch_provider": provider,
            "fetch_series_id": series_id_value,
            "fetch_extra_params": r.get("extra_params"),
            "fetch_unit": r.get("unit"),
            "fetch_adjustment": r.get("adjustment") or "",
            "value_kind": value_kind,
            "source_deviation_reason": deviation_reason,
            # grandfathered: bestehende Reihen waren bisher in Produktion
            "fingerprint_check_passed": True,
            "activated_at": datetime.now(tz=timezone.utc).isoformat(),
            "notes": (r.get("note") or "") + " | v1->v2 migrated",
        })

    print(f"  skipped (missing family/country/instance): {skipped}")
    print(f"  data_series to insert: {len(new_payload)}")

    inserted = 0
    for batch in chunks(new_payload, 200):
        res = sb.table("data_series").insert(batch).execute()
        inserted += len(res.data)
    print(f"  inserted: {inserted}")

    # Re-load fuer Phase E Lookup
    all_ds = sb.table("data_series").select(
        "series_pk,instance_id,fetch_provider,fetch_series_id"
    ).is_("valid_to", "null").execute().data
    return all_ds


# ---------------- Phase E: data_points.series_pk Backfill ----------------
#
# Wird NICHT von diesem Skript ausgefuehrt — passiert ueber Supabase MCP
# `apply_migration 089_backfill_data_points_series_pk` als einzelner SQL-JOIN.
# Grund: 570k Rows updaten ueber 2800 individuelle PostgREST-Calls dauert
# zu lange; ein einziger UPDATE...FROM-Statement ist 10-100x schneller.


# ---------------- Orchestration ----------------

def build_attribution_lookup_fn(all_attr):
    """Returns a function (te_label, country_id, source) -> attribution_id or None.

    Try-Order:
      1. exact match (te_label, country_id)
      2. exact match (te_label, NULL)  (globaler Provider)
      3. fallback: canonical_provider==PROVIDER_ALIAS.get(source,source) AND country_id
      4. fallback: canonical_provider==... AND country_id IS NULL (globaler)
    """
    by_label_country = {(a["te_label"], a["country_id"]): a["attribution_id"] for a in all_attr}
    by_cprov_country = defaultdict(list)
    for a in all_attr:
        by_cprov_country[(a["canonical_provider"], a["country_id"])].append(a["attribution_id"])

    def lookup(te_label, country_id, source):
        if te_label:
            aid = by_label_country.get((te_label, country_id))
            if aid:
                return aid
            aid = by_label_country.get((te_label, None))
            if aid:
                return aid
        cprov = PROVIDER_ALIAS.get(source, source)
        candidates = by_cprov_country.get((cprov, country_id))
        if candidates:
            return candidates[0]
        candidates = by_cprov_country.get((cprov, None))
        if candidates:
            return candidates[0]
        return None

    return lookup


def status_dump(label):
    print(f"\n--- {label} ---")
    counts = {}
    for t in ("indicator_families", "indicator_instances", "data_series",
              "te_source_attributions", "te_page_snapshots", "te_audit_findings"):
        try:
            r = sb.table(t).select("count", count="exact").execute()
            counts[t] = r.count
        except Exception:
            counts[t] = "?"
    # data_points series_pk filled-ratio
    try:
        r1 = sb.table("data_points").select("count", count="estimated").execute()
        r2 = sb.table("data_points").select("count", count="estimated").not_.is_("series_pk", "null").execute()
        counts["data_points (est)"] = r1.count
        counts["data_points.series_pk filled (est)"] = r2.count
    except Exception as e:
        counts["data_points"] = f"err: {e}"
    for k, v in counts.items():
        print(f"  {k}: {v}")


def main():
    print("=== migrate_to_v2: V1 -> V2 schema ===")
    status_dump("BEFORE")

    # Country-Lookup (code -> country_id) + (code -> te_country_path)
    country_rows = sb.table("countries").select("code,country_id,te_country_path").execute().data
    country_lookup = {r["code"]: r["country_id"] for r in country_rows}
    te_path_lookup = {r["code"]: r["te_country_path"] for r in country_rows}
    print(f"countries loaded: {len(country_lookup)}")

    # Phase A
    family_lookup = seed_indicator_families()

    # Phase B
    all_attr = ensure_provider_attributions(country_lookup)
    attribution_by_id = {a["attribution_id"]: a for a in all_attr}
    attribution_lookup_fn = build_attribution_lookup_fn(all_attr)

    # Phase C
    truth = load_truth_yaml()
    instances_by_cf = seed_indicator_instances(
        country_lookup, family_lookup, attribution_lookup_fn, te_path_lookup, truth
    )

    # Phase D
    seed_data_series(country_lookup, family_lookup, instances_by_cf, attribution_by_id)

    status_dump("AFTER")
    print("\nDONE. Backfill data_points.series_pk separat via SQL (migrate_to_v2 Phase E).")


if __name__ == "__main__":
    main()
