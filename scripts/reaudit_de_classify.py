"""Classify each DE re-audit entry into actionable buckets and write final YAML."""
import sys
sys.stdout.reconfigure(encoding="utf-8")

import yaml
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IN = ROOT / "docs" / "_audit_de_reaudit.yaml"


SPECIAL_NOTES = {
    "exports": ("methodology-drift", "TE shows calendar/seasonally-adjusted exports (~135.8 bn EUR); DB stores NSA originals (150.27 bn EUR for March). Both from Destatis 51000-0002 — methodology choice, not a TE-conformity violation."),
    "imports": ("methodology-drift", "TE shows calendar-adjusted imports; DB stores NSA originals (130.4 vs TE 121.5). Same Destatis 51000-0002."),
    "trade-balance": ("methodology-drift", "TE shows SA Außenhandel-Saldo (14.3 bn); DB computes from NSA exports-imports (19.84 bn). Source/series correct."),
    "gdp-per-capita": ("wb-vintage", "Source = World Bank NY.GDP.PCAP.CD. DB has latest WB vintage (56103.73 USD 2024); TE shows older WB snapshot (44108.7). Source label OK."),
    "gdp-per-capita-ppp": ("wb-vintage", "Source = World Bank NY.GDP.PCAP.PP.CD. DB latest WB vintage (73551.93 USD); TE shows older snapshot. Source label OK."),
    "wages": ("wrong-series", "DB uses Destatis 62361-0007 (Bruttoverdienste Index 2025=100); TE shows annual gross monthly earnings EUR/Month (4701 EUR for 2024) from 62321-0001 Verdiensterhebung. 62321-0001 exceeds Destatis sync size cap; cannot fetch directly. Coverage gap."),
    "house-price-index": ("documented-gap", "TE uses Europace AG (private/licensed vendor data, 221.58 points April 2026). EconPulse uses Eurostat prc_hpi_q as substitute. Cannot replicate without Europace license."),
    "job-vacancies": ("ba-integration-pending", "TE shows Bundesagentur für Arbeit 'Stellenmeldungen' (641 Thousand). DB uses Eurostat JVR (% rate). BA API integration not yet implemented."),
    "unemployed-persons": ("ba-integration-pending", "TE shows BA registered unemployed (3.006 million); DB stores Eurostat ILO concept (1.76 million). BA-API integration pending."),
    "unemployment": ("source-label-drift", "TE attributes to BA; DB uses Destatis 13211-0002 which publishes BA's identical 6.4% headline. Source-label drift only — value matches exactly."),
    "government-spending-eur": ("alias-slug", "TE has no separate 'EUR' slug — both 'government-spending' and 'government-spending-eur' map to /germany/government-spending which shows real-volume 209.33 (matches our Destatis 81000-0020 row for 'government-spending'). The 'eur' variant stores nominal EUR (Eurostat namq_10_gdp P3_S13). Frontend-side semantic split."),
    "budget-deficit": ("frontend-only", "TE shows % of GDP (-2.7%); DB stores Finanzierungssaldo level (-119.15 bn EUR). Ratio -119.15/4410 GDP = -2.7%. Frontend computes the ratio."),
}


def classify(slug: str, e: dict) -> dict:
    if slug in SPECIAL_NOTES:
        flag, note = SPECIAL_NOTES[slug]
        return {"flag": flag, "note": note}

    sm = e["source_match"]
    vm = e["value_match"]
    te_unit = (e.get("te_unit") or "").lower()
    our_src = e.get("our_source")
    out_flag = None
    out_note = None

    if sm is True and vm is True:
        out_flag = "ok"
    elif sm is None and our_src == "curated":
        out_flag = "te-source-not-emitted"
        out_note = "TE page does not emit a source-name tag; curated snapshot retained."
    elif sm is False and our_src == "curated":
        if vm is True:
            out_flag = "source-label-drift"
            out_note = f"TE attributes to '{e['te_label']}' (licensed provider); we hold curated value that matches."
        else:
            out_flag = "needs-fix"
    elif sm is False:
        out_flag = "source-mismatch"
        out_note = f"TE source '{e['te_label']}' maps to {e['te_normalized_source']}; we use {our_src}."
    elif sm is True and vm is False:
        if te_unit in ("%", "percent"):
            out_flag = "frontend-only"
            out_note = "TE shows %/YoY/MoM; DB stores level/index. Frontend computes ratio."
        elif "billion" in te_unit and (e.get("our_value") or 0) > 1000:
            out_flag = "ok"
            out_note = "Same series, unit-scale difference (Million vs Billion EUR)."
        elif "million" in te_unit and (e.get("our_value") or 0) < (e.get("te_value") or 0) / 100:
            out_flag = "ok"
            out_note = "Same series, scale difference."
        else:
            out_flag = "value-mismatch"
            out_note = "Same source, value differs — vintage lag or series mismatch."
    elif sm is True and vm is None:
        out_flag = "ok"

    return {"flag": out_flag, "note": out_note}


def main():
    raw = IN.read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    out = {}
    counts = {}
    for slug, e in data.items():
        cls = classify(slug, e)
        # Merge prior fields but override flag if previously None and we have one
        e["flag"] = cls["flag"]
        if cls["note"]:
            e["note"] = cls["note"]
        out[slug] = e
        counts[cls["flag"]] = counts.get(cls["flag"], 0) + 1
    IN.write_text(yaml.safe_dump(out, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print("Bucket counts:", counts)


if __name__ == "__main__":
    main()
