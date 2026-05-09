# EU-Länder-Expansion — Decision Log

**Start:** 2026-05-09
**Ziel:** 25 weitere EU-Länder (alle EU-27 außer DE/FR) zu EconPulse hinzufügen, mit TE-source-conformity.

## Strategie

Hierarchischer 4-Tier-Ansatz pro Land:

1. **Tier 1 — Eurostat-Baseline.** Ein Eurostat-Provider-Run liefert ~46 Indikatoren für alle 25 Länder über existierende `dataset+params`-Konfigurationen. Implementierung: Klonen der FR/EA Eurostat `indicator_sources`-Rows mit `is_default=true`.

2. **Tier 2 — Pan-EU-Quellen.** ECB Main-Refi-Rate für alle Euro-Area-Mitglieder; World Bank für annual GDP/per-capita/population auf alle 25.

3. **Tier 3 — Curated YAML.** Pro Land eine YAML mit Steuern, Sozialversicherung, Korruptions-Index, Renteneintrittsalter — Werte gegen TE verifiziert.

4. **Tier 4 — National-Source-Provider.** Für Länder wo TE eine nationale Statistikbehörde nennt (ISTAT, INE, CBS, Statbel, GUS, SCB, …): eigener Provider analog `insee.py`/`destatis.py`. Eurostat-Row demoten auf `is_default=false`.

## Land-Priorität (nach BIP / TE-Coverage-Reichhaltigkeit)

| # | Code | Land | TE-Source-Notiz |
|---|---|---|---|
| 1 | IT | Italien | ISTAT, Banca d'Italia (SDMX) |
| 2 | ES | Spanien | INE Spain, Banco de España |
| 3 | NL | Niederlande | CBS Netherlands (cbsodata package) |
| 4 | BE | Belgien | Statbel + NBB Belgostat |
| 5 | PL | Polen | GUS Statistics Poland + NBP |
| 6 | SE | Schweden | SCB (PxWeb API) + Riksbank |
| 7 | AT | Österreich | Statistik Austria + OeNB |
| 8 | IE | Irland | CSO Ireland + Central Bank of Ireland |
| 9 | DK | Dänemark | Statistics Denmark + Danmarks Nationalbank |
| 10 | FI | Finnland | Statistics Finland + Bank of Finland |
| 11 | PT | Portugal | INE Portugal + Banco de Portugal |
| 12 | GR | Griechenland | ELSTAT + Bank of Greece |
| 13 | CZ | Tschechien | CZSO + ČNB |
| 14 | HU | Ungarn | KSH + MNB |
| 15 | RO | Rumänien | INSSE + BNR |
| 16 | LU | Luxemburg | STATEC |
| 17 | SK | Slowakei | ŠÚ SR + NBS |
| 18 | SI | Slowenien | SURS + BSI |
| 19 | HR | Kroatien | DZS + HNB |
| 20 | BG | Bulgarien | NSI + BNB |
| 21 | LT | Litauen | LSD + LB |
| 22 | LV | Lettland | CSP + LB |
| 23 | EE | Estland | Statistics Estonia + Eesti Pank |
| 24 | CY | Zypern | CYSTAT + CBC |
| 25 | MT | Malta | NSO + CBM |

## Hard-Rules (aus FR-Onboarding gelernt)

1. **Daten-Source = Anzeige-Source.** Kein country-abhängiges Label-Override im Frontend.
2. **TE-Page ist Source-of-Truth für Quellen-Attribution.** Wenn TE „Source: ISTAT" schreibt, bauen wir ISTAT-direkt und labeln „ISTAT" — selbst wenn Eurostat dieselbe Reihe spiegelt.
3. **Eurostat ist Default nur wenn TE Eurostat zitiert** (gov-debt, budget-deficit, current-account in FR-Pattern). Sonst ist Eurostat zweite Quelle hinter dem nationalen Provider.
4. **Library-First.** Vor jedem Custom-HTTP/SDMX-Code: PyPI-Suche nach offiziellem oder Community-Wrapper für die TE-genannte Quelle.

## Decision-Log Einträge

### 2026-05-09 — Tier-1-Baseline-Strategie

**Entscheidung:** Ich klone die existierenden FR Eurostat `indicator_sources`-Rows (35+ Slugs) für alle 25 neuen Länder mit `is_default=true`. Wo EA andere Slugs hat (consumer-confidence, business-confidence, services-sentiment via BCS), klone ich von EA.

**Begründung:** Eurostat bietet identische Datasets für alle EU-27 — nur der `geo`-Filter ändert sich. Der existierende `eurostat.py`-Provider gruppiert Requests nach `(dataset, params)` und holt Multi-Country in einem Call. Bulk-Clonen ist effizient und reduziert Setup-Zeit.

**Alternative (verworfen):** Pro Land manuell Slug-Inventory. Wäre 25× redundant, da Eurostat-Datasets country-agnostisch sind.

**Rest-Risiko:** Manche Slugs sind in einigen Ländern nicht verfügbar (z.B. mining-production in MT/CY/LU). Provider loggt das als „0 points" — wird im Validation-Pass aufgeräumt.

### 2026-05-09 — Country-Priorität

**Entscheidung:** Ich arbeite IT/ES/NL/BE zuerst, dann nordische Länder (SE/DK/FI/IE/AT), dann CEE (PL/CZ/HU/RO), dann Süd-Europa (PT/GR), dann Klein-Mitglieder (LU/SK/SI/HR/BG/LT/LV/EE/CY/MT).

**Begründung:** Reihenfolge nach BIP-Größe und TE-Indikator-Reichhaltigkeit. Große Länder haben mehr nationale Quellen mit eigenen API-Endpoints; kleine Länder werden oft komplett über Eurostat abgebildet (TE selbst nutzt für sie häufig Eurostat).

### 2026-05-09 — Tier-4-Library-Suche pro Land

**Plan:** Für jede TE-Primärquelle eines Landes erst PyPI/GitHub absuchen. Bekannte Wrappers laut FR-Erfahrung:
- pynsee (FR INSEE) ✓ in Use
- pystatis (DE Destatis) ✓ in Use
- akshare (CN) ✓ in Use
- fredapi (US FRED) ✓ in Use
- cbsodata (NL CBS Statistics Netherlands) — zu prüfen
- pxweb / pyjstat (Nordic PxWeb APIs: SE SCB, FI Tilastokeskus, DK DST, NO SSB) — zu prüfen
- ecbdata / sdmx1 / pysdmx (SDMX-Quellen: Banca d'Italia, Bank of England, ECB, ICE-CB) — zu prüfen
- istat-py / istatpy (IT) — zu prüfen
- python-bcb (BR — nicht relevant)

Wo kein Wrapper existiert, fallback auf `sdmx1` (für SDMX-konforme APIs) bzw. `requests` für REST/CSV.

**Decision-Marker pro Land:** Beim Onboarding eines Landes wird hier ein Block ergänzt:
- TE-Source-Inventory (Liste der Tier-1-Indikatoren mit TE-Quelle)
- Wrapper-Wahl pro Quelle
- Implementierungs-Pfad (provider, SERIES-list, validation results)
- Bekannte Lücken / Skip-Reasons

---

## Country Block: IT (Italien)

**TE-Inventory (2026-05-09):** ISTAT für CPI/GDP/Unemployment/IP/Retail/Trade/Confidence; Eurostat als sekundäre Quelle für gov-debt/budget-deficit/current-account.

**Library-Suche:** `istatapi` (Attol8) auf PyPI gefunden. Direkter SDMX-REST: https://sdmx.istat.it/SDMXWS/rest/data/

**Befund:** ISTAT SDMX-Endpoint liefert nur bis April 2025 (Stand 2026-05-09 — ~12 Monate Lag). Eurostat liefert dieselben Reihen aktuell bis April 2026 (NIC-/HICP-Werte differieren <0.1%-Punkt).

**Entscheidung:** Eurostat-Baseline bleibt Default für alle IT-Slugs. ISTAT-direct nicht implementiert weil das Stale-Daten liefern würde. Source-Attribution-Gap zu TE wird in te_coverage_gaps.yaml dokumentiert.

**Begründung:** TE-Source-Conformity-Regel (Daten-Source = Anzeige-Source) verbietet Eurostat als „ISTAT" zu labeln. Zwei Optionen waren:
1. Eurostat behalten, Label ehrlich „Eurostat" — gewählt
2. ISTAT-direct mit veralteten Werten — verworfen weil Werte 12 Monate alt wären

**Werte gegen TE (Stichprobe):** inflation-cpi April 2026 Eurostat HICP YoY = 2.89% vs TE NIC 2.8% (Differenz 0.09%, methodologisch durch HICP/NIC). unemployment Mar 2026 Eurostat = 5.2 vs TE 5.2 ✓. gdp-real Q1 2026 Eurostat = 435.4 Bil EUR (chained) — TE zeigt ähnliches Niveau in EUR.

**Status:** Eurostat-Baseline akzeptiert. Re-Visit wenn ISTAT SDMX wieder aktuell ist oder eine andere Frische-Quelle gefunden wird (I.STAT Web-Warehouse, JSON-stat).

## Country Block: ES (Spanien)

**TE-Inventory (2026-05-09):** INE für CPI/Unemployment/IP/Retail/PPI; Banco de España für interest-rate (= ECB MRO); Eurostat für gov-debt/budget-deficit/current-account.

**Library-Suche:** Mehrere PyPI-Wrapper gefunden (INEapy, INEAPIpy, INEPandas), aber INE Tempus3 JSON API ist trivial direkt nutzbar. Direktes `requests` an `https://servicios.ine.es/wstempus/js/EN/DATOS_SERIE/{COD}` gewählt.

**Implementierung:** `pipeline/providers/ine_es.py` (~120 Zeilen) mit hardcoded SERIES-Liste:
- inflation-cpi: IPC290751 (Index 2026=100)
- core-cpi: IPC290851 (Subyacente, ex Unprocessed Food + Energy)
- food-inflation: IPC290755 (Food and non-alcoholic beverages)
- unemployment: EPA452434 (Tasa de paro nacional, both genders)
- ppi: IPR34522 (IPRI Industria total, Index)
- industrial-production: IPI13491 (IPI National Total, Index)
- retail-sales: ICM4147 (Volume index commercial retail, no service stations)

**Werte gegen TE (2026-05-09):**
- inflation-cpi April 2026: TE 3.2% YoY ✓ exakt (INE YoY-Reihe IPC290750)
- inflation-cpi Mar 2026 INE Index: 102.44 (YoY 3.45% — minimaler Diff zur YoY-Reihe wegen INE Vintage-Revisionen, MoM gleich)
- unemployment Q1 2026: INE EPA muss noch validiert werden gegen TE 10.83%
- ppi Mar 2026: 130.04 (Eurostat: 130.4 — sehr nah)
- industrial-production Mar 2026: 110.47 (TE: +1.8% YoY → 110.47/108.x ≈ +2.1% YoY, leichter Vintage-Diff)

**Stolperfallen:**
- INE publishes YoY series ~2 weeks before final index (April 2026 YoY released, April Index not yet). Solution: use index series for storage; frontend computes YoY from index.
- ICM has multiple base years; ICM4147 is base 2021=100 with constant prices (volume index).
- IPRI has separate "general" and "consumer goods" indices; IPR34522 = Industry total (matches TE).

**DB-Status:** 7 INE-direct rows mit `is_default=true`; korrespondierende Eurostat-ES-Rows demoted auf `is_default=false`. Werte werden im run_all-Pass laufend aktualisiert.

## Country Block: NL (Niederlande)

**TE-Inventory:** TE zeigt CBS Statistics Netherlands für die meisten NL-Indikatoren.

**Library-Suche:** `cbsodata` v1.3.5 von PyPI installiert. Aber: CBS hat alte v3-OData-Endpoint (`opendata.cbs.nl`) deprecated; Antwort liefert nur HTML-Homepage. Neuer Endpoint `datasets.cbs.nl` (OData v4) ist von diesem Netzwerk nicht erreichbar (Connect Timeout). DBnomics-Mirror auch Timeouts.

**Entscheidung (2026-05-09):** CBS-direct nicht implementiert. Eurostat bleibt Default für NL. Eurostat-NL-Daten kommen aus CBS und sind daher methodisch identisch — nur Source-Label unterschiedlich. Source-Attribution-Gap zu TE dokumentiert.

**Status:** Eurostat-Baseline akzeptiert. Re-Visit wenn Netzwerkzugriff zu `datasets.cbs.nl` möglich wird, oder wenn CBS einen neuen Endpoint anbietet, der erreichbar ist.

## Strategischer Pivot (2026-05-09)

**Erkenntnis nach IT/ES/NL:** Per-Country National-Provider-Build ist sehr aufwändig:
- IT: ISTAT SDMX 12 Monate stale → unbrauchbar
- ES: INE Tempus3 funktioniert ✓
- NL: CBS-Endpoints nicht erreichbar (Firewall/Migration)

**Neue Priorisierung:** Statt für jedes Land einen Custom-Provider zu bauen, fokussieren wir auf:
1. **Eurostat-Baseline ist Default für alle 25 Länder** (akzeptiert, dokumentiert).
2. **National-Provider nur dort bauen wo es funktioniert** (ES INE ✓ als Beispiel). Bei Connection-Issues oder stale Data: Eurostat-Fallback.
3. **Validation-Pass** für Stichproben (Top-5-Slugs pro Land) gegen TE-Werte; Korrekturen bei größeren Diffs.
4. **Decision-Log + te_coverage_gaps.yaml** dokumentiert die Source-Attribution-Lücken transparent.

Re-Iterate auf nationale Provider in folgenden Sessions wenn:
- Netzwerkzugriff zu CBS/Statbel/SCB/PxWeb möglich
- Bessere Discovery der Series-Codes per Land
- Größere User-Sichtbarkeit der Source-Mismatch (TE: ISTAT vs Wir: Eurostat)

(Weitere Country-Blöcke folgen analog.)
