"""Update docs/te_sources_truth.yaml HU entries to reflect fresh TE re-audit."""
import re
from pathlib import Path

TRUTH = Path("docs/te_sources_truth.yaml")
text = TRUTH.read_text(encoding="utf-8")

# Each update: slug -> dict of overrides to apply to the entry
# - If 'stage' is added/changed, write that key.
# - If 'source' changes, swap it.
# - 'note' is added/updated.
UPDATES = {
    # Migrated to ksh_hu (real-data fix)
    "exports": {
        "source": "ksh_hu",
        "te_label": "Hungarian Central Statistical Office",
        "te_url": "https://www.ksh.hu/",
        "verified": True,
        "note": "Migrated 2026-05-17: KSH kkr0065 col 19 monthly mEUR matches TE attribution",
    },
    "imports": {
        "source": "ksh_hu",
        "te_label": "Hungarian Central Statistical Office",
        "te_url": "https://www.ksh.hu/",
        "verified": True,
        "note": "Migrated 2026-05-17: KSH kkr0064 col 19 monthly mEUR matches TE attribution",
    },
    # TE has no public page for HU — keep current source as honest label, mark gap.
    "cpi-clothing": {
        "verified": True,
        "stage": "gap",
        "note": "TE 2026-05-17: no public HU page for /cpi-clothing. Keep Eurostat HICP coicop CP03 as honest fetcher.",
    },
    "cpi-education": {
        "verified": True,
        "stage": "gap",
        "note": "TE 2026-05-17: no public HU page for /cpi-education. Keep Eurostat HICP CP10.",
    },
    "cpi-food": {
        "verified": True,
        "stage": "gap",
        "note": "TE 2026-05-17: no public HU page for /cpi-food. Keep Eurostat HICP CP01.",
    },
    "cpi-housing-utilities": {
        "verified": True,
        "stage": "gap",
        "note": "TE 2026-05-17: no public HU page for /cpi-housing-utilities. Keep Eurostat HICP CP04.",
    },
    "cpi-recreation-and-culture": {
        "verified": True,
        "stage": "gap",
        "note": "TE 2026-05-17: no public HU page for /cpi-recreation-and-culture. Keep Eurostat HICP CP09.",
    },
    "credit-rating": {
        "verified": True,
        "stage": "gap",
        "note": "TE 2026-05-17: TE renders SPA fallback for /credit-rating. Keep curated value (S&P/Moody's/Fitch consensus).",
    },
    "disposable-personal-income": {
        "verified": True,
        "stage": "gap",
        "note": "TE 2026-05-17: no public HU page for /disposable-personal-income. Keep Eurostat NASA national accounts.",
    },
    "energy-inflation": {
        "verified": True,
        "stage": "gap",
        "note": "TE 2026-05-17: no public HU page for /energy-inflation. Keep Eurostat HICP energy aggregate.",
    },
    "medical-doctors": {
        "verified": True,
        "stage": "gap",
        "note": "TE 2026-05-17: no public HU page for /medical-doctors. Keep curated WHO/OECD value.",
    },
    "nurses": {
        "verified": True,
        "stage": "gap",
        "note": "TE 2026-05-17: no public HU page for /nurses. Keep curated WHO/OECD value.",
    },
    "services-inflation": {
        "verified": True,
        "stage": "gap",
        "note": "TE 2026-05-17: no public HU page for /services-inflation. Keep Eurostat HICP services aggregate.",
    },
    "services-sentiment": {
        "verified": True,
        "stage": "gap",
        "note": "TE 2026-05-17: no public HU page for /services-sentiment. Keep Eurostat BCS services confidence.",
    },
    # GKI Konjunktura attribution — proprietary, no public API. Keep Eurostat.
    "business-confidence": {
        "te_label": "GKI Economic Research Co.",
        "te_url": "https://www.gki.hu/",
        "verified": True,
        "stage": "gap",
        "note": "TE attributes GKI Konjunktura (proprietary). No public API. Keep Eurostat BCS industrial confidence.",
    },
    "consumer-confidence": {
        "te_label": "GKI Economic Research Co.",
        "te_url": "https://www.gki.hu/",
        "verified": True,
        "stage": "gap",
        "note": "TE attributes GKI Konjunktura (proprietary). No public API. Keep Eurostat BCS consumer confidence.",
    },
    # ÁKK attribution — government-debt
    "government-debt": {
        "te_label": "Government Debt Management Agency Ltd, Hungary",
        "te_url": "https://www.akk.hu/",
        "verified": True,
        "stage": "gap",
        "note": "TE attributes ÁKK (Hungary public debt agency). ÁKK publishes monthly PDFs only — no public API. Keep Eurostat gov_10dd_edpt1.",
    },
    "government-debt-total": {
        "te_label": "Government Debt Management Agency Ltd, Hungary",
        "te_url": "https://www.akk.hu/",
        "verified": True,
        "stage": "gap",
        "note": "TE attributes ÁKK. Same gap as government-debt. Keep Eurostat absolute-level series.",
    },
    # Minimum wages: TE attributes Eurostat, but DB is curated.
    "minimum-wages": {
        "verified": True,
        "stage": "gap",
        "note": "TE 2026-05-17 attributes EUROSTAT (earn_mw_cur). Keep curated HUF/Month value (290800 from KSH); future migration to Eurostat earn_mw_cur would switch to EUR.",
    },
    # core-cpi: TE attributes KSH but we use Eurostat HICP excl food/energy.
    "core-cpi": {
        "verified": True,
        "stage": "gap",
        "note": "TE attributes KSH (publishes core-cpi YoY rate); our Eurostat HICP-X-FENT proxy gives index (102.63). Honest label = eurostat.",
    },
    # government-spending-eur: TE shows HUF Million quarterly (1838274). We have eurostat EUR.
    "government-spending-eur": {
        "te_label": "Hungarian Central Statistical Office",
        "te_url": "https://www.ksh.hu/",
        "verified": True,
        "stage": "gap",
        "note": "TE shows HUF Million quarterly (KSH gdp0094 col 6 = 1838274 mHUF). We already have ksh_hu for slug 'government-spending' (mHUF). government-spending-eur kept as Eurostat EUR conversion for comparability.",
    },
    # budget-deficit: Eurostat-based deficit % of GDP (-4.7) matches TE attribution effectively.
    "budget-deficit": {
        "verified": True,
        "note": "Eurostat gov_10dd_edpt1 deficit/GDP matches TE -4.70% for 2025. TE attributes KSH which republishes Eurostat data.",
    },
    # unemployed-persons: TE attributes KSH (226.4k). We use eurostat (214k LFS). Different age band.
    "unemployed-persons": {
        "verified": True,
        "stage": "gap",
        "note": "TE shows 226.4k (KSH mun0099 15-74 LFS). Our Eurostat = 214k (LFS 15-74 SA). Eurostat acceptable but ksh_hu mun0099 col 6 would match exactly; future migration.",
    },
}


def find_hu_slug_block(text: str, slug: str) -> tuple[int, int] | None:
    """Locate the line range covering 'HU:' -> '  {slug}:' -> entries until next '  ' or next country."""
    hu_match = re.search(r"^HU:\n", text, re.M)
    if not hu_match:
        return None
    hu_start = hu_match.end()
    # find next top-level country
    next_country = re.search(r"^[A-Z]{2}:\n", text[hu_start:], re.M)
    hu_end = hu_start + (next_country.start() if next_country else len(text) - hu_start)
    sub = text[hu_start:hu_end]
    slug_re = re.compile(rf"^  {re.escape(slug)}:\n((?:    .*\n)+)", re.M)
    m = slug_re.search(sub)
    if not m:
        return None
    return (hu_start + m.start(), hu_start + m.end())


def parse_entry_keys(entry_text: str) -> dict:
    """Parse '    key: val' lines into dict."""
    out = {}
    for line in entry_text.splitlines():
        m = re.match(r"^    ([a-z_]+):\s*(.*)$", line)
        if not m:
            continue
        k, v = m.group(1), m.group(2)
        out[k] = v
    return out


def format_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    if any(ch in s for ch in [":", "#", "'", '"', "\n"]) or s.startswith(" "):
        return '"' + s.replace('"', '\\"') + '"'
    return s


def rebuild_entry(slug: str, kv: dict) -> str:
    """Rebuild entry block, ordering keys logically."""
    order = ["source", "te_label", "te_page", "te_url", "verified", "stage", "note"]
    used = set()
    lines = [f"  {slug}:"]
    for k in order:
        if k in kv:
            lines.append(f"    {k}: {format_value(kv[k])}")
            used.add(k)
    for k, v in kv.items():
        if k not in used:
            lines.append(f"    {k}: {format_value(v)}")
    return "\n".join(lines) + "\n"


updated_count = 0
for slug, overrides in UPDATES.items():
    loc = find_hu_slug_block(text, slug)
    if loc is None:
        print(f"NOT_FOUND: HU.{slug}")
        continue
    start, end = loc
    block = text[start:end]
    # First line is '  slug:'; rest is '    key: val'
    body_start_idx = block.find("\n") + 1
    body = block[body_start_idx:]
    kv = parse_entry_keys(body)
    # Apply overrides
    for k, v in overrides.items():
        kv[k] = v
    new_block = rebuild_entry(slug, kv)
    text = text[:start] + new_block + text[end:]
    updated_count += 1

TRUTH.write_text(text, encoding="utf-8")
print(f"Updated {updated_count} HU entries in {TRUTH}")
