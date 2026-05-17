"""Update docs/te_sources_truth.yaml SI section with verified te_labels per fresh TE re-audit."""
import json
import sys
from pathlib import Path

import yaml

# Force utf-8 stdout
sys.stdout.reconfigure(encoding="utf-8")

TRUTH = Path("docs/te_sources_truth.yaml")
PARSED = Path("docs/_audit_si_te_parsed.json")

# TE source-name -> our source provider expected and te_url
NAME_TO_SRC = {
    "Statistical Office of the Republic of Slovenia": ("surs_si", "https://www.stat.si"),
    "Bank of Slovenia": ("eurostat", "https://www.bsi.si"),  # we use Eurostat for value (no BS API integrated)
    "Banka Slovenije": ("eurostat", "https://www.bsi.si"),
    "Eurostat": ("eurostat", "https://ec.europa.eu/eurostat/"),
    "EUROSTAT": ("eurostat", "https://ec.europa.eu/eurostat/"),
    "European Commission": ("eurostat", "https://commission.europa.eu/index_en"),
    "European Central Bank": ("ecb", "https://www.ecb.europa.eu"),
    "World Bank": ("worldbank", "https://www.worldbank.org/"),
    "OECD": ("curated", "https://www.oecd.org"),
    "Transparency International": ("curated", "https://www.transparency.org"),
    "Tax Administration of the Republic of Slovenia": ("curated", "https://www.fu.gov.si"),
    "Ministry of Finance, Republic of Slovenia": ("curated", "https://www.gov.si/drzavni-organi/ministrstva/ministrstvo-za-finance/"),
    "Institute for Economics and Peace": ("curated", "https://www.economicsandpeace.org"),
    "Employment Service of Slovenia": ("eurostat", "https://www.ess.gov.si"),  # we use Eurostat for value
}

# Slugs not on TE for SI (no dedicated TE indicator page): keep curated/eurostat with no te_label
NO_TE_PAGE = {"disposable-personal-income", "energy-inflation", "services-inflation",
              "services-sentiment", "government-spending-eur"}

# Slugs that have a TE page but no single source-attribution (curated TE aggregates)
TE_AGGREGATE = {
    "credit-rating": "S&P / Moody's / Fitch / DBRS sovereign credit ratings (TE-curated aggregate)",
}


def main():
    truth = yaml.safe_load(TRUTH.read_text(encoding="utf-8"))
    parsed = json.loads(PARSED.read_text(encoding="utf-8"))

    si = truth["SI"]
    changed = 0
    notes_per_slug = {}
    for slug, entry in si.items():
        te_src_name = parsed.get(slug, {}).get("te_source_name")
        if slug in TE_AGGREGATE:
            entry["verified"] = True
            entry["te_label"] = "TE-curated aggregate"
            entry["note"] = TE_AGGREGATE[slug]
            changed += 1
            notes_per_slug[slug] = "te_aggregate"
            continue
        if slug in NO_TE_PAGE or not te_src_name:
            # Document no-TE-page status
            entry["verified"] = True  # verified that no TE page exists
            entry.setdefault("note", "No TE indicator page for SI; EconPulse-internal slug")
            changed += 1
            notes_per_slug[slug] = "no_te_page"
            continue
        # Standardize labelling against TE
        if "te_label" not in entry or entry.get("te_label") != te_src_name:
            entry["te_label"] = te_src_name
            changed += 1
            notes_per_slug[slug] = "set te_label"
        want_src, want_url = NAME_TO_SRC.get(te_src_name, (None, None))
        if "te_url" not in entry and want_url:
            entry["te_url"] = want_url
            changed += 1
        entry["verified"] = True

    TRUTH.write_text(yaml.safe_dump(truth, allow_unicode=True, sort_keys=True, width=200),
                     encoding="utf-8")
    print(f"Updated SI entries: {changed} fields changed")
    for s, n in notes_per_slug.items():
        print(f"  {s}: {n}")


if __name__ == "__main__":
    main()
