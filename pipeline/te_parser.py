"""TE-HTML-Scraper + Description-Fingerprint-Parser.

Holt fuer eine indicator_instance die TE-Seite, parsed sie und schreibt eine
te_page_snapshots-Row. Liefert die snapshot_id zurueck fuer den Audit.

Fingerprint-Felder (entscheidend fuer series-correctness-check):
  - te_last_value, te_last_period:    Headline (most-recent reading)
  - te_avg, te_avg_from_year, te_avg_to_year:  Long-term Durchschnitt
  - te_ath, te_ath_period:            All-time-high
  - te_atl, te_atl_period:            All-time-low
  - te_source_label, te_source_url:   Source-Attribution

Wenn eine Reihe falsch ist (falscher FRED-Code, IDBANK-Swap), kann der
Headline-Wert *zufaellig* matchen, aber Avg/ATH/ATL fast nie. Deshalb Fingerprint.

Rate-Limit: 20s zwischen Calls als Default (TE banned uns frueher).
Bei 403: 30-Minuten-Cooldown, dann Retry.
"""
from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# Regexes aus dem TE-HTML extrahieren
SOURCE_RE = re.compile(
    r"source:\s*<a class='source-name'[^>]*href\s*=\s*'([^']*)'[^>]*>([^<]+)</a>",
    re.I,
)
DESC_RE = re.compile(r'<h2 id="description"[^>]*>(.*?)</h2>', re.S)
# Stats-Tab enthaelt den Long-term-Fingerprint:
#   <div ... id="stats"><h2 style="line-height: 1.45em;">
#   Inflation Rate ... averaged 3.29 percent from 1914 until 2026,
#   reaching an all time high of 23.70 percent in June of 1920
#   and a record low of -15.80 percent in June of 1921.</h2>
STATS_RE = re.compile(
    r'<div[^>]*\bid="stats"[^>]*>\s*<h2[^>]*>(.*?)</h2>', re.S | re.I
)

# Headline-Value: "...rose to 3.2% in April 2026" / "...stood at 2.7 percent"
VALUE_RE = re.compile(
    r"(?:to|at|of|reached)\s+(-?\d[\d,\.]*)\s*"
    r"(?:%|percent|billion|million|thousand|points|index|usd|eur)",
    re.I,
)
# Range-Value: "kept the federal funds rate unchanged at the 3.5%–3.75% target range"
# Wir nehmen den Mittelwert der Range fuer Headline-Vergleich (interest-rate-Pattern).
RANGE_RE = re.compile(
    r"(?:at|to|of|reached)\s+(?:the\s+)?(-?\d[\d,\.]*)\s*[%]?\s*[–\-—]\s*"
    r"(-?\d[\d,\.]*)\s*(?:%|percent)",
    re.I,
)
PERIOD_RE = re.compile(
    r"\bin\s+(January|February|March|April|May|June|July|August|September|"
    r"October|November|December|Q[1-4]|the\s+(?:first|second|third|fourth)\s+quarter)"
    r"\s*(?:of\s+)?(\d{4})?",
    re.I,
)
# Long-term-Fingerprint:
# "averaged 3.27 percent from 1914 until 2025"
AVG_RE = re.compile(
    r"averag(?:ed|ing)\s+(-?\d[\d,\.]*)\s*"
    r"(?:%|percent|points|billion|million|thousand|usd|eur)?\s*"
    r"from\s+(\d{4})\s+(?:un)?til\s+(\d{4})",
    re.I,
)
# "reaching an all time high of 23.70 percent in June of 1980"
ATH_RE = re.compile(
    r"all[\s-]*time\s+high\s+of\s+(-?\d[\d,\.]*)\s*"
    r"(?:%|percent|points|billion|million|thousand|usd|eur)?"
    r"\s+in\s+([A-Za-z0-9\s]+?\d{4})",
    re.I,
)
# "record low of -0.10 percent in March of 2009" / "all time low of ..."
ATL_RE = re.compile(
    r"(?:record\s+low|all[\s-]*time\s+low|low\s+of)\s+(-?\d[\d,\.]*)\s*"
    r"(?:%|percent|points|billion|million|thousand|usd|eur)?"
    r"\s+in\s+([A-Za-z0-9\s]+?\d{4})",
    re.I,
)

MONTH_NUM = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
}
QUARTER_NUM = {"first": "Q1", "second": "Q2", "third": "Q3", "fourth": "Q4"}


@dataclass
class TeSnapshot:
    """Geparsed aus der TE-Seite. 1:1 te_page_snapshots-Row-Felder."""
    te_last_value:    Optional[float] = None
    te_last_period:   Optional[str] = None
    te_avg:           Optional[float] = None
    te_avg_from_year: Optional[int] = None
    te_avg_to_year:   Optional[int] = None
    te_ath:           Optional[float] = None
    te_ath_period:    Optional[str] = None
    te_atl:           Optional[float] = None
    te_atl_period:    Optional[str] = None
    te_source_label:  Optional[str] = None
    te_source_url:    Optional[str] = None
    raw_description:  Optional[str] = None
    parse_quality:    str = "failed"   # 'ok' | 'partial' | 'failed'
    parse_error:      Optional[str] = None


def _to_float(s: str) -> Optional[float]:
    try:
        return float(s.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def _normalize_period(text: str) -> Optional[str]:
    """'June of 1980' -> '1980-06'. 'Q1 2009' -> '2009-Q1'."""
    text = text.strip().lower()
    pm = PERIOD_RE.search("in " + text)
    if pm:
        when = pm.group(1).lower()
        year = pm.group(2) or ""
        if when in MONTH_NUM:
            return f"{year}-{MONTH_NUM[when]}" if year else when.title()
        if "quarter" in when:
            for k, v in QUARTER_NUM.items():
                if k in when:
                    return f"{year}-{v}" if year else v
        if when.startswith("q") and len(when) == 2:
            return f"{year}-{when.upper()}" if year else when.upper()
    return text or None


def parse_te_html(html: str) -> TeSnapshot:
    """Hauptparser: TE-Indicator-Seite HTML -> TeSnapshot."""
    snap = TeSnapshot()
    if not html or "<html" not in html.lower():
        snap.parse_error = "empty or non-html body"
        return snap

    # Source-Attribution (vor Description, oft im Header)
    sm = SOURCE_RE.search(html)
    if sm:
        snap.te_source_url = sm.group(1).strip()
        snap.te_source_label = sm.group(2).strip()

    # Description-Box (Headline)
    dm = DESC_RE.search(html)
    desc_html = dm.group(1) if dm else html[:5000]
    desc_text = re.sub(r"<[^>]+>", " ", desc_html)
    desc_text = re.sub(r"\s+", " ", desc_text).strip()
    # Stats-Tab (Long-term-Fingerprint: averaged X from Y to Z, ATH, ATL)
    sm = STATS_RE.search(html)
    stats_text = ""
    if sm:
        stats_text = re.sub(r"<[^>]+>", " ", sm.group(1))
        stats_text = re.sub(r"\s+", " ", stats_text).strip()
    # Beide Texte werden persistiert; Fingerprint-Regexes muessen Stats-Text bekommen.
    snap.raw_description = (desc_text + " || " + stats_text)[:2000]
    # Fingerprint-Search-Korpus: bevorzugt stats_text, sonst desc_text als Fallback.
    fingerprint_text = stats_text if stats_text else desc_text

    # Headline (versuche zuerst Range, fallback einzelner Wert)
    rm = RANGE_RE.search(desc_text)
    if rm:
        a = _to_float(rm.group(1))
        b = _to_float(rm.group(2))
        if a is not None and b is not None:
            snap.te_last_value = (a + b) / 2
    if snap.te_last_value is None:
        vm = VALUE_RE.search(desc_text)
        if vm:
            snap.te_last_value = _to_float(vm.group(1))
    pm = PERIOD_RE.search(desc_text)
    if pm:
        when = pm.group(1).lower()
        year = pm.group(2) or ""
        if when in MONTH_NUM:
            snap.te_last_period = f"{year}-{MONTH_NUM[when]}" if year else when.title()
        elif "quarter" in when:
            for k, v in QUARTER_NUM.items():
                if k in when:
                    snap.te_last_period = f"{year}-{v}" if year else v
                    break
        elif when.startswith("q") and len(when) == 2:
            snap.te_last_period = f"{year}-{when.upper()}" if year else when.upper()

    # Fingerprint: Average + From/Until (aus Stats-Tab)
    am = AVG_RE.search(fingerprint_text)
    if am:
        snap.te_avg = _to_float(am.group(1))
        try:
            snap.te_avg_from_year = int(am.group(2))
            snap.te_avg_to_year = int(am.group(3))
        except (ValueError, TypeError):
            pass

    # Fingerprint: ATH
    hm = ATH_RE.search(fingerprint_text)
    if hm:
        snap.te_ath = _to_float(hm.group(1))
        snap.te_ath_period = _normalize_period(hm.group(2))

    # Fingerprint: ATL
    lm = ATL_RE.search(fingerprint_text)
    if lm:
        snap.te_atl = _to_float(lm.group(1))
        snap.te_atl_period = _normalize_period(lm.group(2))

    # Quality-Assessment
    filled = sum(1 for x in (
        snap.te_last_value, snap.te_avg, snap.te_ath, snap.te_atl,
        snap.te_source_label,
    ) if x is not None)
    if filled >= 4:
        snap.parse_quality = "ok"
    elif filled >= 2:
        snap.parse_quality = "partial"
    else:
        snap.parse_quality = "failed"
        if snap.te_source_label is None and snap.te_last_value is None:
            snap.parse_error = "no source-label, no headline-value"
    return snap


@dataclass
class FetchResult:
    status:   str            # 'ok' | '403' | '404' | 'http:NNN' | 'curl:N' | 'net:Err' | 'empty'
    html:     Optional[str] = None
    snapshot: Optional[TeSnapshot] = None


def fetch_te_page(url: str, timeout_s: int = 40) -> FetchResult:
    """curl-basierter Fetch — python-requests bekommt fast immer 403, curl mit UA klappt."""
    try:
        r = subprocess.run(
            [
                "curl", "-s", "-A", UA, "--max-time", str(timeout_s),
                "-w", "\n__HTTP_CODE__%{http_code}", url,
            ],
            capture_output=True,
            timeout=timeout_s + 5,
        )
    except (subprocess.SubprocessError, OSError) as e:
        return FetchResult(status=f"net:{e.__class__.__name__}")
    if r.returncode != 0:
        return FetchResult(status=f"curl:{r.returncode}")
    out_text = r.stdout.decode("utf-8", errors="ignore")
    code_m = re.search(r"__HTTP_CODE__(\d+)$", out_text)
    code = int(code_m.group(1)) if code_m else 0
    body = out_text[: code_m.start()] if code_m else out_text
    if code == 403:
        return FetchResult(status="403")
    if code == 404:
        return FetchResult(status="404")
    if code != 200:
        return FetchResult(status=f"http:{code}")
    if not body or "<html" not in body.lower():
        return FetchResult(status="empty")
    return FetchResult(status="ok", html=body, snapshot=parse_te_html(body))


# ---------------- DB-Persistierung ----------------

def insert_snapshot(sb, instance_id: int, snap: TeSnapshot) -> Optional[int]:
    """Insert eine te_page_snapshots-Row, return snapshot_id."""
    row = {
        "instance_id": instance_id,
        "te_last_value": snap.te_last_value,
        "te_last_period": snap.te_last_period,
        "te_avg": snap.te_avg,
        "te_avg_from_year": snap.te_avg_from_year,
        "te_avg_to_year": snap.te_avg_to_year,
        "te_ath": snap.te_ath,
        "te_ath_period": snap.te_ath_period,
        "te_atl": snap.te_atl,
        "te_atl_period": snap.te_atl_period,
        "te_source_label": snap.te_source_label,
        "te_source_url": snap.te_source_url,
        "raw_description": snap.raw_description,
        "parse_quality": snap.parse_quality,
        "parse_error": snap.parse_error,
    }
    res = sb.table("te_page_snapshots").insert(row).execute()
    if res.data:
        return res.data[0]["snapshot_id"]
    return None


# ---------------- Rate-Limit-Helper ----------------

class RateLimiter:
    """Konservative TE-Rate-Limit-Strategie: 20s default; bei 403 30min cooldown."""

    def __init__(self, normal_delay_s: float = 20.0,
                 cooldown_403_s: float = 1800.0):
        self.normal_delay_s = normal_delay_s
        self.cooldown_403_s = cooldown_403_s
        self.last_fetch_ts = 0.0
        self.consecutive_403 = 0

    def wait_normal(self):
        elapsed = time.time() - self.last_fetch_ts
        if elapsed < self.normal_delay_s:
            time.sleep(self.normal_delay_s - elapsed)
        self.last_fetch_ts = time.time()

    def on_403(self):
        self.consecutive_403 += 1
        print(f"  [rate] 403 received (consecutive={self.consecutive_403}); "
              f"cooldown {self.cooldown_403_s:.0f}s ...")
        time.sleep(self.cooldown_403_s)
        # next call: lengthen the cooldown if it 403's again
        self.cooldown_403_s = min(self.cooldown_403_s * 1.5, 5400.0)

    def on_ok(self):
        self.consecutive_403 = 0
        self.cooldown_403_s = 1800.0


# ---------------- Convenience: scrape one instance ----------------

def scrape_instance(sb, instance_id: int, te_url: str,
                    rate: RateLimiter) -> tuple[str, Optional[int]]:
    """Scrape + parse + persist. Returns (status, snapshot_id_or_None)."""
    rate.wait_normal()
    fr = fetch_te_page(te_url)
    if fr.status == "403":
        rate.on_403()
        return ("403", None)
    if fr.status != "ok" or fr.snapshot is None:
        return (fr.status, None)
    rate.on_ok()
    sid = insert_snapshot(sb, instance_id, fr.snapshot)
    return ("ok", sid)


__all__ = [
    "TeSnapshot", "FetchResult", "RateLimiter",
    "parse_te_html", "fetch_te_page", "insert_snapshot", "scrape_instance",
]
