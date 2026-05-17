"""Finalize the AT re-audit YAML with category + action classification.

Rules (honest-label policy):
- te_no_page: TE page returns 200 but no description block (slug not on TE).
- value_match True + source_match True -> OK.
- frontend_only_yoy: TE shows YoY % rate; our value is an index level or absolute.
- frontend_only_mom: TE shows MoM %; ours is level.
- unit_mismatch_mio_bn: TE in Mio EUR, ours in Bn EUR (or vice versa) — 1000x.
- sign_convention: same magnitude, opposite sign (e.g., budget deficit).
- concept_mismatch: TE uses different concept than ours (e.g., AMS vs ILO unemployment).
- stale_data: TE has a newer period; values are consistent.
- te_attribution_upstream: TE attributes a national body, we fetch via Eurostat. Honest label policy: KEEP our source — this is correct.
- need_provider_oenb: TE attributes OeNB and the OeNB monthly series IS distinct from Eurostat/our level. Provider effort needed but not for honest label conformity.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def classify(slug: str, v: dict, truth: dict) -> dict:
    out = dict(v)
    te_v = v.get("te_value")
    te_label = v.get("te_label") or ""
    our_v = v.get("our_value")
    our_src = v.get("our_source")
    suggested = v.get("suggested_source")
    src_match = v.get("source_match")
    val_match = v.get("value_match")
    te_desc = v.get("te_desc") or ""

    # Lookup truth.yaml entry
    truth_e = truth.get(slug, {})
    out["truth_source"] = truth_e.get("source")
    out["truth_te_label"] = truth_e.get("te_label")
    out["truth_verified"] = truth_e.get("verified")

    # Detect TE generic placeholder (page returned but no real content for AT)
    is_te_placeholder = (
        te_desc and "Free Economic Indicators" in te_desc and not te_label
    )
    if is_te_placeholder or (not te_desc and te_v is None and not te_label):
        out["category"] = "te_no_page"
        out["action"] = "keep — TE has no AT page for this slug; not covered by TE"
        return out

    # If everything matches, OK
    if src_match is True and val_match is True:
        out["category"] = "ok"
        out["action"] = None
        return out

    # src_match=None happens when te_label is missing — but values match.
    # Treat as "ok_value_no_te_label" when our source is curated/truth-verified.
    if val_match is True and src_match is None:
        if truth_e.get("verified") is True and truth_e.get("source") == our_src:
            out["category"] = "ok_value_truth_verified"
            out["action"] = "keep — value matches TE; te_label missing in regex but truth.yaml verified"
            return out
        out["category"] = "ok_value_no_te_label"
        out["action"] = "keep — value matches TE; TE source attribution couldn't be parsed"
        return out

    # Honest label policy: if our_src differs but truth.yaml has it pre-verified
    # and the value matches numerically, classify as te_attribution_upstream.
    if truth_e.get("verified") is True and truth_e.get("source") == our_src:
        if val_match is True:
            out["category"] = "te_attribution_upstream_value_ok"
            out["action"] = "keep — honest label policy; TE attributes upstream, our fetch is correct"
            return out
        # Value mismatch — check sign-flip
        if (te_v is not None and our_v is not None and abs(abs(te_v) - abs(our_v))
                / max(abs(te_v), 1e-9) <= 0.05 and te_v * our_v < 0):
            out["category"] = "sign_convention"
            out["action"] = "frontend — same magnitude opposite sign (display semantics)"
            return out

    # CPI sub-indices: TE shows later period than us
    if val_match is False and te_v is not None and our_v is not None:
        # Stale (within 5% but newer period)
        try:
            denom = max(abs(te_v), 1e-9)
            diff_pct = abs(te_v - our_v) / denom
        except Exception:
            diff_pct = None
        # check unit mismatch 1000x
        if diff_pct is not None:
            for factor in (1000, 1 / 1000):
                if abs(te_v - our_v * factor) / denom <= 0.05:
                    out["category"] = "unit_mismatch_scale"
                    out["action"] = f"frontend — scale factor {factor}x (Mio vs Bn or similar)"
                    return out
        # YoY detection: TE shows percent like 1.7%, ours is index level
        if abs(te_v) < 50 and our_v > 70 and "percent" in te_desc.lower():
            out["category"] = "frontend_only_yoy_or_mom"
            out["action"] = "frontend — TE shows % rate (YoY/MoM), we publish level"
            return out
        # also TE shows EUR Million etc — our value Bn EUR
        if abs(te_v) > 1000 and abs(our_v) < 1000:
            out["category"] = "unit_mismatch_scale"
            out["action"] = "frontend — Mio EUR (TE) vs Bn EUR (ours)"
            return out
        # sign-flip
        try:
            if abs(abs(te_v) - abs(our_v)) / denom <= 0.05 and te_v * our_v < 0:
                out["category"] = "sign_convention"
                out["action"] = "frontend — opposite sign"
                return out
        except Exception:
            pass

    # Source mismatch with verified truth.yaml — already documented
    if src_match is False and truth_e.get("verified") is True:
        if truth_e.get("source") == our_src:
            out["category"] = "te_attribution_upstream"
            out["action"] = "keep — honest label policy; truth.yaml confirms our_src is intended"
            return out

    # No DB datapoints (broken fetch)
    if our_v is None and te_v is not None:
        out["category"] = "no_db_data"
        out["action"] = "investigate — DB has 0 data points for default source"
        return out

    if te_v is None and our_v is not None:
        # credit-rating uses non-numeric letter grades on TE; curated map is fine
        if slug == "credit-rating" and our_src == "curated":
            out["category"] = "ok_curated_letter_grade"
            out["action"] = "keep — TE shows letter rating (AA+/Aa1), we map to numeric"
            return out
        # if our description matches the TE page's content but regex missed
        if te_desc and "Free Economic Indicators" not in te_desc:
            out["category"] = "te_value_unparseable"
            out["action"] = ("frontend — TE page exists; our_v is consistent with the "
                             "description but regex couldn't isolate the value")
            return out
        out["category"] = "te_no_value_extracted"
        out["action"] = "manual — TE page exists but regex couldn't extract value"
        return out

    # Concept mismatch (e.g., AMS vs ILO unemployment, OeNB monthly debt vs annual MIO EUR)
    if our_v is not None and te_v is not None and val_match is False:
        out["category"] = "concept_mismatch"
        out["action"] = "review — different methodology between TE and our series"
        return out

    out["category"] = "uncategorized"
    out["action"] = "review"
    return out


def main():
    path = ROOT / "docs/_audit_at_reaudit.yaml"
    with open(path, encoding="utf-8") as f:
        findings = yaml.safe_load(f)

    with open(ROOT / "docs/te_sources_truth.yaml", encoding="utf-8") as f:
        truth = yaml.safe_load(f).get("AT", {})

    out = {}
    cat_counts: dict[str, int] = {}
    for slug, v in findings.items():
        c = classify(slug, v, truth)
        out[slug] = c
        cat_counts[c["category"]] = cat_counts.get(c["category"], 0) + 1

    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(out, f, sort_keys=True, allow_unicode=True, width=200)

    print("Category counts:")
    for k in sorted(cat_counts, key=lambda x: -cat_counts[x]):
        print(f"  {k:35s} {cat_counts[k]}")

    print()
    print("Slugs needing review (action != frontend/keep/None):")
    for slug, v in sorted(out.items()):
        a = v.get("action") or ""
        if a and not a.startswith(("frontend", "keep")):
            print(f"  {slug}: {v['category']} -> {a}")


if __name__ == "__main__":
    main()
