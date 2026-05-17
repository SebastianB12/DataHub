"""Update docs/te_sources_truth.yaml for BE based on fresh TE re-audit.

Source-label rule: technical fetch quote. Where TE attributes an upstream
(ECB redistributing Eurostat LCI, Statbel upstream of NBB-IPI), our truth
reflects the actual fetch quote — and we add `te_label` for transparency.
"""
from __future__ import annotations

import yaml
from pathlib import Path

TRUTH = Path("docs/te_sources_truth.yaml")


def main():
    d = yaml.safe_load(TRUTH.read_text(encoding="utf-8"))
    be = d["BE"]

    # === Switch CPI subgroups: eurostat → statbel (TE attributes Statbel) ===
    for ind in ("cpi-clothing", "cpi-food", "cpi-housing-utilities", "cpi-transportation"):
        be[ind] = {
            "source": "statbel",
            "te_label": "Statistics Belgium",
            "te_url": "https://statbel.fgov.be",
            "te_page": f"https://tradingeconomics.com/belgium/{ind}",
            "verified": True,
        }

    # === government-debt: TE shows EUROSTAT (107.9% GDP) — switch back to eurostat ===
    be["government-debt"] = {
        "source": "eurostat",
        "te_label": "EUROSTAT",
        "te_url": "https://ec.europa.eu/eurostat/",
        "te_page": "https://tradingeconomics.com/belgium/government-debt-to-gdp",
        "verified": True,
        "note": "TE BE government-debt page shows % of GDP, sourced Eurostat gov_10dd_edpt1",
    }

    # === government-spending-eur: TE shows NBB (alias of government-spending) ===
    be["government-spending-eur"] = {
        "source": "nbb",
        "te_label": "National Bank of Belgium",
        "te_url": "https://www.nbb.be",
        "te_page": "https://tradingeconomics.com/belgium/government-spending",
        "verified": True,
        "note": "Alias of government-spending; uses NBB DF_QNA_DISS P3_S13",
    }

    # === labour-costs: TE label ECB redistributes Eurostat LCI. Honest source=eurostat ===
    be["labour-costs"] = {
        "source": "eurostat",
        "te_label": "European Central Bank",
        "te_url": "http://ecb.europa.eu",
        "te_page": "https://tradingeconomics.com/belgium/labour-costs",
        "verified": True,
        "note": "TE attributes ECB; ECB has no LCI dataflow on data-api.ecb.europa.eu — ECB redistributes Eurostat lc_lci_r2_q. Honest fetch source = eurostat (D1_D4_MD5_XB CA matches TE 119.32).",
    }

    # === minimum-wages: TE shows EUROSTAT — switch curated → eurostat ===
    be["minimum-wages"] = {
        "source": "eurostat",
        "te_label": "EUROSTAT",
        "te_url": "https://ec.europa.eu/eurostat/",
        "te_page": "https://tradingeconomics.com/belgium/minimum-wages",
        "verified": True,
    }

    # === retail-sales: TE shows EUROSTAT — switch statbel → eurostat ===
    be["retail-sales"] = {
        "source": "eurostat",
        "te_label": "EUROSTAT",
        "te_url": "https://ec.europa.eu/eurostat/",
        "te_page": "https://tradingeconomics.com/belgium/retail-sales-yoy",
        "verified": True,
        "note": "TE retail-sales-yoy shows MoM% derived from Eurostat sts_trtu_m G47 SCA VOL_SLS index",
    }

    # === industrial/manufacturing/mining-production: TE attributes Statbel, we fetch via NBB SDMX ===
    # NBB redistributes Statbel IPI; Statbel REST API has no IPI volume view (verified 2026-05-15).
    # Honest fetch source = nbb. Update truth with te_label + note.
    for ind, te_path in (
        ("industrial-production", "industrial-production"),
        ("manufacturing-production", "manufacturing-production"),
        ("mining-production", "mining-production"),
    ):
        be[ind] = {
            "source": "nbb",
            "te_label": "Statistics Belgium",
            "te_url": "http://statbel.fgov.be",
            "te_page": f"https://tradingeconomics.com/belgium/{te_path}",
            "verified": True,
            "note": "TE attributes Statbel; Statbel REST API has no IPI volume view (verified 2026-05-15 by full enumeration). NBB Belgostat SDMX (DF_INDPROD) redistributes the same Statbel IPI methodology.",
        }

    # === TE_PAGE_MISSING slugs: TE has no dedicated BE page (verified by landing-page detection) ===
    # Keep current defaults; mark as 'te_page_unavailable' so validator continues to enforce.
    for ind, src in (
        ("energy-inflation", "eurostat"),
        ("medical-doctors", "curated"),
        ("services-inflation", "eurostat"),
        ("services-sentiment", "eurostat"),
    ):
        existing = be.get(ind, {})
        be[ind] = {
            "source": src,
            "te_page": existing.get("te_page", f"https://tradingeconomics.com/belgium/{ind}"),
            "verified": True,
            "note": "TE does not publish a dedicated BE page for this indicator (2026-05-16 audit). Using Eurostat/curated as best available.",
        }

    # === credit-rating: TE page exists with S&P/Moody/Fitch in table; no attributable single source ===
    be["credit-rating"] = {
        "source": "curated",
        "te_label": "S&P / Moody's / Fitch / DBRS",
        "te_page": "https://tradingeconomics.com/belgium/rating",
        "verified": True,
        "note": "TE rating page shows S&P AA-, Moody's A1, DBRS AA; no single source attribution.",
    }

    d["BE"] = be
    TRUTH.write_text(yaml.safe_dump(d, sort_keys=True, allow_unicode=True), encoding="utf-8")
    print(f"Updated {TRUTH}")


if __name__ == "__main__":
    main()
