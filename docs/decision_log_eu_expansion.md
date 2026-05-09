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

(Wird befüllt sobald ES-Phase beginnt.)

(Weitere Country-Blöcke folgen analog.)
