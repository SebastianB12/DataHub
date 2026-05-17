"""Apply the PT truth.yaml updates from the re-audit (2026-05-17).

For each PT slug, reconcile truth.yaml to the fresh TE attributions we
collected in docs/_audit_pt_reaudit.yaml. Where TE attributes a national
source we cannot fetch from yet, we ADD te_label + te_url + a gap note,
but keep source = (whatever we actually fetch from). Per the project's
hard constraint: source label = technical fetch source, not upstream.

Run after pipeline/migrations/077_pt_reaudit.py applied the minimum-wages
DB switch.
"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
TRUTH = ROOT / "docs" / "te_sources_truth.yaml"

# (slug -> {keys to set/replace}). Only the listed keys are written.
# 'source' is set ONLY where we actually changed the DB (minimum-wages).
PT_UPDATES: dict[str, dict] = {
    # --- real source change after migration 077 ---
    "minimum-wages": {
        "source": "eurostat",
        "te_label": "EUROSTAT",
        "te_url": "https://ec.europa.eu/eurostat/",
        "te_page": "https://tradingeconomics.com/portugal/minimum-wages",
        "verified": True,
    },
    # --- TE attributes INE Portugal (Statistics Portugal); we fetch via Eurostat ---
    "consumer-confidence": {
        "source": "eurostat",
        "te_label": "Statistics Portugal",
        "te_url": "https://www.ine.pt",
        "te_page": "https://tradingeconomics.com/portugal/consumer-confidence",
        "verified": True,
        "note": (
            "gap: TE attributes Statistics Portugal (INE Consumer Survey). "
            "We fetch via Eurostat ei_bsco_m as fallback (no INE-PT pindica "
            "varcd for the headline indicator mapped yet)."
        ),
    },
    "consumer-spending": {
        "source": "eurostat",
        "te_label": "Statistics Portugal",
        "te_url": "https://www.ine.pt",
        "te_page": "https://tradingeconomics.com/portugal/consumer-spending",
        "verified": True,
        "note": (
            "gap: TE attributes Statistics Portugal (INE). We use Eurostat "
            "namq_10_gdp:P31_S14 (household final consumption) as fallback."
        ),
    },
    "core-cpi": {
        "source": "eurostat",
        "te_label": "Statistics Portugal",
        "te_url": "https://www.ine.pt",
        "te_page": "https://tradingeconomics.com/portugal/core-inflation-rate",
        "verified": True,
        "note": (
            "gap: TE attributes Statistics Portugal (INE IPC excl energy & food). "
            "We use Eurostat ei_cphi_m:CP-HI00XEF (HICP excluding energy, food, "
            "alcohol, tobacco) as fallback."
        ),
    },
    "exports": {
        "source": "eurostat",
        "te_label": "Statistics Portugal",
        "te_url": "https://www.ine.pt",
        "te_page": "https://tradingeconomics.com/portugal/exports",
        "verified": True,
        "note": (
            "gap: TE attributes Statistics Portugal (INE). We use Eurostat "
            "nama_10_exi:P6 as fallback (no INE-PT monthly merchandise trade "
            "mapped yet)."
        ),
    },
    "government-spending": {
        "source": "eurostat",
        "te_label": "Statistics Portugal",
        "te_url": "https://www.ine.pt",
        "te_page": "https://tradingeconomics.com/portugal/government-spending",
        "verified": True,
        "note": (
            "gap: TE attributes Statistics Portugal (INE). We use Eurostat "
            "namq_10_gdp:P3_S13 (general government final consumption) as fallback."
        ),
    },
    "gross-fixed-capital-formation": {
        "source": "eurostat",
        "te_label": "Statistics Portugal",
        "te_url": "https://www.ine.pt",
        "te_page": "https://tradingeconomics.com/portugal/gross-fixed-capital-formation",
        "verified": True,
        "note": (
            "gap: TE attributes Statistics Portugal (INE). We use Eurostat "
            "namq_10_gdp:P51G as fallback."
        ),
    },
    "house-price-index": {
        "source": "eurostat",
        "te_label": "Statistics Portugal",
        "te_url": "https://www.ine.pt",
        "te_page": "https://tradingeconomics.com/portugal/housing-index",
        "verified": True,
        "note": (
            "gap: TE attributes Statistics Portugal (INE). We use Eurostat "
            "prc_hpi_q:INX (harmonized HPI) as fallback."
        ),
    },
    "imports": {
        "source": "eurostat",
        "te_label": "Statistics Portugal",
        "te_url": "https://www.ine.pt",
        "te_page": "https://tradingeconomics.com/portugal/imports",
        "verified": True,
        "note": (
            "gap: TE attributes Statistics Portugal (INE). We use Eurostat "
            "nama_10_exi:P7 as fallback."
        ),
    },
    "manufacturing-production": {
        "source": "eurostat",
        "te_label": "Statistics Portugal",
        "te_url": "https://www.ine.pt",
        "te_page": "https://tradingeconomics.com/portugal/manufacturing-production",
        "verified": True,
        "note": (
            "gap: TE attributes Statistics Portugal (INE IPI Manufacturing). "
            "We use Eurostat sts_inpr_m:C:I21 as fallback (no INE-PT pindica "
            "varcd for manufacturing-only sub-aggregate mapped yet)."
        ),
    },
    "mining-production": {
        "source": "eurostat",
        "te_label": "Statistics Portugal",
        "te_url": "https://www.ine.pt",
        "te_page": "https://tradingeconomics.com/portugal/mining-production",
        "verified": True,
        "note": (
            "gap: TE attributes Statistics Portugal (INE IPI Mining). "
            "We use Eurostat sts_inpr_m:B:I21 as fallback."
        ),
    },
    "unemployed-persons": {
        "source": "eurostat",
        "te_label": "Statistics Portugal",
        "te_url": "https://www.ine.pt",
        "te_page": "https://tradingeconomics.com/portugal/unemployed-persons",
        "verified": True,
        "note": (
            "gap: TE attributes Statistics Portugal (INE LFS). We use Eurostat "
            "une_rt_m:TOTAL:THS_PER as fallback (the INE LFS unemployment-rate "
            "varcd 0012136 is already mapped, but absolute persons count was "
            "not).  "
        ),
    },
    # --- TE attributes Banco de Portugal; we use Eurostat fallback ---
    "current-account": {
        "source": "eurostat",
        "te_label": "Banco de Portugal",
        "te_url": "https://www.bportugal.pt/",
        "te_page": "https://tradingeconomics.com/portugal/current-account",
        "verified": True,
        "note": (
            "gap: TE attributes Banco de Portugal. No bdp_pt provider yet. "
            "We use Eurostat bop_c6_q:CA as fallback (BdP-derived data)."
        ),
    },
    "current-account-to-gdp": {
        "source": "eurostat",
        "te_label": "Banco de Portugal",
        "te_url": "https://www.bportugal.pt",
        "te_page": "https://tradingeconomics.com/portugal/current-account-to-gdp",
        "verified": True,
        "note": (
            "gap: TE attributes Banco de Portugal. No bdp_pt provider yet. "
            "We use Eurostat bop_gdp6_q:CA as fallback."
        ),
    },
    "government-debt": {
        "source": "eurostat",
        "te_label": "Banco de Portugal",
        "te_url": "https://www.bportugal.pt",
        "te_page": "https://tradingeconomics.com/portugal/government-debt",
        "verified": True,
        "note": (
            "gap: TE attributes Banco de Portugal (Monthly Statistical Bulletin). "
            "No bdp_pt provider yet. We use Eurostat gov_10dd_edpt1:GD as fallback "
            "(quarterly EDP debt, same definitional perimeter)."
        ),
    },
    "government-debt-total": {
        "source": "eurostat",
        "te_label": "Banco de Portugal",
        "te_url": "https://www.bportugal.pt",
        "te_page": "https://tradingeconomics.com/portugal/government-debt",
        "verified": True,
        "note": (
            "gap: TE attributes Banco de Portugal. Same gap as government-debt; "
            "uses Eurostat gov_10dd_edpt1:GD:MIO_EUR for EUR-denominated total."
        ),
    },
    # --- TE attributes DGO (Direccao Geral do Orcamento); we use Eurostat ---
    "government-spending-eur": {
        "source": "eurostat",
        "te_label": "DGO - Direccao Geral do Orcamento, Portugal",
        "te_url": "https://www.dgo.gov.pt",
        "te_page": "https://tradingeconomics.com/portugal/government-budget-value",
        "verified": True,
        "note": (
            "gap: TE attributes DGO (Direccao Geral do Orcamento). No dgo_pt "
            "provider yet. We use Eurostat namq_10_gdp:P3_S13 (EUR mio) as "
            "fallback (NA-aggregate, broadly aligned with DGO budget execution)."
        ),
    },
    # --- TE attributes IEFP; we use Eurostat ---
    "job-vacancies": {
        "source": "eurostat",
        "te_label": "IEFP - Institute of Employment and Professional Formation, Portugal",
        "te_url": "https://www.iefp.pt",
        "te_page": "https://tradingeconomics.com/portugal/job-vacancies",
        "verified": True,
        "note": (
            "gap: TE attributes IEFP (registered offers). No iefp_pt provider "
            "yet. We use Eurostat jvs_q_nace2:JVR (job vacancy rate) as a "
            "conceptually different fallback."
        ),
    },
    # --- Already TE-conform (just refresh verified=true + te_label cleanup) ---
    "budget-deficit": {
        "source": "eurostat",
        "te_label": "EUROSTAT",
        "te_url": "https://ec.europa.eu/eurostat/",
        "te_page": "https://tradingeconomics.com/portugal/government-budget",
        "verified": True,
    },
    "labour-costs": {
        "source": "eurostat",
        "te_label": "EUROSTAT",
        "te_url": "https://ec.europa.eu/eurostat/",
        "te_page": "https://tradingeconomics.com/portugal/labour-costs",
        "verified": True,
    },
    "long-term-unemployment-rate": {
        "source": "eurostat",
        "te_label": "EUROSTAT",
        "te_url": "https://ec.europa.eu/eurostat/",
        "te_page": "https://tradingeconomics.com/portugal/long-term-unemployment-rate",
        "verified": True,
    },
    "sales-tax-rate": {
        "source": "curated",
        "te_label": "Autoridade Tributaria e Aduaneira",
        "te_url": "https://info.portaldasfinancas.gov.pt",
        "te_page": "https://tradingeconomics.com/portugal/sales-tax-rate",
        "verified": True,
    },
    "corporate-tax-rate": {
        "source": "curated",
        "te_label": "Autoridade Tributaria e Aduaneira",
        "te_url": "https://info.portaldasfinancas.gov.pt",
        "te_page": "https://tradingeconomics.com/portugal/corporate-tax-rate",
        "verified": True,
    },
    "corruption-index": {
        "source": "curated",
        "te_label": "Transparency International",
        "te_url": "https://www.transparency.org",
        "te_page": "https://tradingeconomics.com/portugal/corruption-index",
        "verified": True,
    },
    "corruption-rank": {
        "source": "curated",
        "te_label": "Transparency International",
        "te_url": "https://www.transparency.org",
        "te_page": "https://tradingeconomics.com/portugal/corruption-rank",
        "verified": True,
    },
    "hospital-beds": {
        "source": "curated",
        "te_label": "OECD",
        "te_url": "https://www.oecd.org",
        "te_page": "https://tradingeconomics.com/portugal/hospital-beds",
        "verified": True,
    },
    "nurses": {
        "source": "curated",
        "te_label": "OECD",
        "te_url": "https://www.oecd.org",
        "te_page": "https://tradingeconomics.com/portugal/nurses",
        "verified": True,
    },
    "terrorism-index": {
        "source": "curated",
        "te_label": "Institute for Economics and Peace",
        "te_url": "https://www.economicsandpeace.org",
        "te_page": "https://tradingeconomics.com/portugal/terrorism-index",
        "verified": True,
    },
    "social-security-rate-companies": {
        "source": "curated",
        "te_label": "Instituto da Seguranca Social",
        "te_url": "http://www.seg-social.pt",
        "te_page": "https://tradingeconomics.com/portugal/social-security-rate-for-companies",
        "verified": True,
    },
    "social-security-rate-employees": {
        "source": "curated",
        "te_label": "Instituto da Seguranca Social",
        "te_url": "http://www.seg-social.pt",
        "te_page": "https://tradingeconomics.com/portugal/social-security-rate-for-employees",
        "verified": True,
    },
}

# Slugs where the existing entry is fine — leave as-is.
KEEP_AS_IS = {
    "business-confidence",  # already has te_label
    "capacity-utilization",
    "changes-in-inventories",
    "cpi-clothing", "cpi-education", "cpi-food", "cpi-housing-utilities",
    "cpi-recreation-and-culture", "cpi-transportation",
    "credit-rating",  # no TE page; keep curated
    "disposable-personal-income",
    "employed-persons", "employment-rate",
    "energy-inflation",  # no PT page
    "food-inflation",
    "gdp", "gdp-per-capita", "gdp-per-capita-ppp", "gdp-real",
    "industrial-production",
    "inflation-cpi",
    "interest-rate",
    "labor-force-participation-rate",
    "medical-doctors",  # no PT page
    "personal-income-tax-rate",
    "population",
    "ppi", "productivity", "retail-sales",
    "retirement-age-men", "retirement-age-women",
    "services-inflation", "services-sentiment",  # no PT page
    "social-security-rate",
    "unemployment",
    "youth-unemployment-rate",
}


def main() -> None:
    data = yaml.safe_load(TRUTH.read_text(encoding="utf-8"))
    pt = data["PT"]
    changed = 0
    for slug, updates in PT_UPDATES.items():
        if slug not in pt:
            print(f"  WARN: {slug} not in PT block; skipping")
            continue
        old = dict(pt[slug])
        new = dict(old)
        new.update(updates)
        # Drop the old stale notes if we set a new one (or replace UTF-8 mojibake)
        if "note" not in updates and "note" in new and (
            "no internal source code" in new["note"]
            or "â€" in new["note"]
        ):
            del new["note"]
        if new != old:
            pt[slug] = new
            changed += 1
            print(f"  + PT/{slug}: updated")
    # Now repair UTF-8 mojibake in KEEP_AS_IS where the labels got mangled
    for slug in KEEP_AS_IS:
        if slug not in pt:
            continue
        entry = pt[slug]
        modified = False
        for k in ("te_label", "note"):
            if k in entry and isinstance(entry[k], str):
                fixed = (
                    entry[k]
                    .replace("Ã§", "c")
                    .replace("Ã¡", "a")
                    .replace("â€”", "—")
                    .replace("â€“", "-")
                    .replace("Tribut�ria", "Tributaria")
                    .replace("Seguran�a", "Seguranca")
                )
                if fixed != entry[k]:
                    entry[k] = fixed
                    modified = True
        if modified:
            changed += 1
            print(f"  ~ PT/{slug}: utf-8 mojibake repaired")

    TRUTH.write_text(
        yaml.safe_dump(data, sort_keys=True, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )
    print(f"\nWrote {TRUTH} ({changed} PT entries updated)")


if __name__ == "__main__":
    main()
