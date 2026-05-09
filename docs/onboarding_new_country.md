# Onboarding eines neuen Landes — Pflicht-Checkliste

Diese Checkliste ist verpflichtend für jedes neue Land in EconPulse. Sie existiert weil bei FR (Mai 2026) zwei Fehler gleichzeitig gemacht wurden, die beide gegen explizite Sebastian-Regeln verstießen:

1. Eurostat-Daten als Default genommen, obwohl TE für FR-Tier-1-Reihen „Source: INSEE" zeigt — also nicht die Primärquelle.
2. Im Frontend ein Source-Override eingebaut, das `eurostat`-Rows als „INSEE" labelte — also Daten-Source ≠ Anzeige-Source.

Beide Fehler werden mit der Reihenfolge unten verhindert. **Keinen Schritt überspringen.**

---

## Phase 0 — TE-Inventory (vor jeder Code-Zeile)

1. Öffne `tradingeconomics.com/<country>/indicators` und gehe alle Tabs durch (GDP, Labour, Prices, Money, Trade, Government, Business, Consumer, Housing, Health, Taxes, Climate, Energy).
2. Für jeden Indikator den Slug in der TE-URL ablesen, den aktuellen Wert + Reference-Period notieren.
3. **Auf jede einzelne Indikator-Page klicken** und ganz nach unten scrollen — dort steht die Source-Zeile. **Das ist die Wahrheit.** Beispiele:
   - `tradingeconomics.com/france/inflation-cpi` → „Source: National Institute of Statistics and Economic Studies (INSEE)"
   - `tradingeconomics.com/germany/government-debt-to-gdp` → „Source: Eurostat"
   - `tradingeconomics.com/china/inflation-cpi` → „Source: National Bureau of Statistics of China"
4. Output dieser Phase: eine Markdown-Tabelle `Slug | TE-Wert | Reference-Period | TE-Source | TE-URL` mit ≥30 Tier-1-Indikatoren. Diese Tabelle steht zu Beginn der Implementation, nicht am Ende.

**Niemals annehmen, dass „die EU-Aggregator-Quelle die ähnliche Daten hat" eine Primärquelle ist.** Eurostat ist Mirror, nicht Original — selbst wenn die Numbers identisch sind, bleibt der Source-Name in der TE-Page maßgeblich.

---

## Phase 1 — Library-Suche pro Quelle (BEVOR irgendeine Zeile Code)

Pro unterschiedlicher TE-Source aus Phase 0 einmal: PyPI- und GitHub-Suche nach offiziellem oder Community-Wrapper.

| TE-Source | Bekannter Python-Wrapper | Status |
|---|---|---|
| FRED (USA) | `fredapi` | offiziell |
| Eurostat | `eurostat` (PyPI) oder direkter REST-Call | optional |
| INSEE (FR) | `pynsee` (InseeFrLab, maintained) | offiziell |
| Destatis (DE) | `pystatis` (CorrelAid, maintained) | community |
| ONS (UK) | direkter CSV/API | kein Wrapper |
| Bundesbank | `dbnomics` indexiert; kein eigener BdF-Wrapper | SDMX-direkt |
| ECB | direkter SDMX | kein Wrapper |
| World Bank | `wbdata` oder direkter API | optional |
| NBS / PBoC / GACC (CN) | `akshare` | community |
| EIA (USA Energy) | direkter API | kein Wrapper |
| Bank of Canada | `bocddata` | community |
| Bank of England | direkter IADB-CSV | kein Wrapper |

Vorgehen:
1. `pip search <quellen-name>` (oder `pip index`); GitHub-Topic-Suche nach `<source-name>`, `<source-acronym>`, `webstat`, `sdmx`, etc.
2. Wenn ein Package gefunden: ist es maintained (Commits in den letzten 12 Monaten)? Coverage check: deckt es die TE-Tier-1-Indikatoren ab?
3. **Wenn ja → benutzen. Niemals neu schreiben.** Das ist eine harte Regel, kein Soft-Recommendation.
4. Wenn nicht maintained oder zu schmale Coverage: SDMX-Endpoint via `sdmx1`/`pysdmx` versuchen, dann erst HTML/CSV-Direkt-Scrape.
5. Library-Wahl pro Source dokumentieren in `docs/api-cheatsheets.md`.

**Negative Beispiele aus der Vergangenheit:** Bei CN habe ich zuerst custom NBS/PBoC-Scraper angefangen zu bauen, bevor `akshare` (das genau das wrapped) entdeckt wurde. Sebastian hat das hart korrigiert — siehe Memory `feedback_check_libraries_first.md`.

---

## Phase 2 — Provider implementieren

1. Vorlage: `pipeline/providers/destatis.py` (DB-driven via TABLES-Liste) oder `pipeline/providers/akshare_cn.py` (config-per-slug). Pattern kopieren — nicht neu erfinden.
2. Hardcoded SERIES-Liste am Top des Files. Pro Slug: `dataset` + `filters`-Dict + `freq` + `unit` + `adjustment` + `conversion`.
3. Filter-Dict so präzise dass nach Anwendung exakt eine Zeitreihe übrig bleibt. Wenn mehrere matchen → `raise ValueError(...)`. Lieber FAIL als die falsche Reihe stillschweigend mitnehmen.
4. **Probe-Phase:** für jeden Slug einmal interaktiv:
   - Library-Funktion aufrufen, latest Wert lesen.
   - Gegen die TE-Page (Phase 0 Tabelle) abgleichen.
   - Akzeptanz: Diff <1%, Vintage-Diff max 1 Periode (z.B. wir haben März, TE noch Februar).
   - Wenn der Wert offensichtlich abweicht → Filter-Dict ist falsch → korrigieren bis Match.
5. Erst wenn Stage-1-Probe komplett gepasst ist, kommt der Slug in die SERIES-Liste in Produktion.

---

## Phase 3 — DB & Provider-Registry

1. Pro Slug ein `indicator_sources`-Row mit `source='<provider>'`, `is_default=True`. Felder: `indicator`, `country`, `series_id` (z.B. `<dataset>:<idbank>`), `transform='raw'`, `conversion`, `unit`, `adjustment`, `freq_hint`, `extra_params=NULL`, `active=True`, `is_default=True`.
2. **Existierende Eurostat/FRED-Rows demoten:** wenn TE für diesen Slug eine andere Quelle nennt, bestehende Mirror-Rows auf `is_default=False` setzen — sie bleiben als Fallback in der DB, aber das Default-Display kommt von der TE-konformen Quelle.
3. `pipeline/run_all.py` PROVIDERS-Liste um den neuen Provider-Modulpfad erweitern.
4. `pipeline/scheduler.py` PROVIDER_MAP erweitern + `data_sources`-Supabase-Row anlegen (`slug=<provider>, enabled=true, schedule='interval:Xh'`).
5. `python -m pipeline.providers.<provider>` Probefetch laufen lassen → Logs sauber, alle Slugs „OK" mit ≥10 Datenpunkten.

---

## Phase 4 — Frontend (NULL Source-Override)

1. **`src/lib/sources.ts`:** für jeden neuen `source`-Code (z.B. `insee`, `bdf`, `nbs`) einen Eintrag in `STATIC_LABELS` mit dem ECHTEN Quellennamen + URL hinzufügen.
2. **Kein country-abhängiges Override-Mapping.** Wenn die Daten von Eurostat kommen, steht „Eurostat" da. Wenn die Daten von INSEE kommen, steht „INSEE" da. Punkt.
3. `src/lib/indicators.ts` COUNTRIES-Array um Land+Flagge erweitern.
4. Smoke-Test im Browser:
   - `/countries/<code>` rendert ohne Fehler, alle Indikatoren mit korrekten Quellen.
   - `/indicators/<top-slug>/<code>` zeigt die Quelle die TE auch zeigt.
   - Stichprobe: 3–5 Slugs visuell gegen TE-Page abgleichen.

**Hard-Regel:** Wenn dir auffällt, dass das Source-Label „falsch" aussieht (z.B. „Eurostat" wo TE „INSEE" zeigt), ist die Lösung NIEMALS ein Override-Mapping im Frontend. Die Lösung ist immer: eigenen Fetch von der TE-genannten Primärquelle bauen. Override-Mapping ist Lügen für den User über Datenherkunft. Memory: `feedback_real_sources.md`.

---

## Phase 5 — Coverage-Gaps dokumentieren

1. TE-Slugs die nicht abrufbar sind (lizenziert wie PMI von S&P Global, GeoIP-blockiert wie NBS aus DE, paywall) → `docs/te_coverage_gaps.yaml` mit Felder `country, indicator_name, te_category, reason, source, note, possible_workaround`.
2. **Niemals einen falschen Mirror als Default eintragen nur um den Slug „grün" zu bekommen.** Lieber ehrliche Lücke als irreführender Wert mit falscher Quelle.

---

## Phase 6 — Verifikation

1. `python -m pipeline.run_all` läuft ohne neue FAILs durch.
2. Spot-Check-Skript: alle Tier-1-Werte gegen TE-Page abgleichen; ≥90% exakt-Match (Diff <1%, Vintage max 1 Periode).
3. Memory-Update: neuer Eintrag `project_<country>_coverage.md` mit:
   - Provider-Verteilung (welcher Slug von welcher Quelle).
   - Bekannte Gaps die nicht abrufbar sind.
   - Begründung warum welcher Provider gewählt wurde (TE-Source-Konformität).
4. Eintrag in `MEMORY.md` als One-Liner-Pointer auf das neue Memory-File.

---

## Hard Rules — niemals brechen

❌ Daten-Source ≠ Anzeige-Source. Kein Label-Override im Frontend.
❌ EU-Aggregator (Eurostat) als Default für Mitgliedstaat-Reihe wenn TE die nationale Behörde nennt.
❌ Custom-HTTP-Code wenn ein gepflegtes Python-Package existiert.
❌ Falscher Mirror eingetragen nur um den Slug „grün" zu kriegen.

✅ TE-Page ist die Source-of-Truth für Quellen-Attribution.
✅ Library-Check (PyPI + GitHub) gehört in jede Onboarding-Checkliste an Position 1 nach dem TE-Inventory.
✅ Lieber ehrliche Lücke als irreführender Proxy.
✅ Probe-Phase mit Wert-Match gegen TE BEVOR ein Slug in Produktion geht.

---

## Referenz-Memories

- `feedback_primary_sources.md` — Immer nationale Statistikbehörden direkt, nie FRED/Eurostat als Proxy für nationale Daten.
- `feedback_real_sources.md` — Source-Label = Download-Provider; kein Relabeling/Override.
- `feedback_te_sources.md` — Immer exakt die Quelle verwenden die Trading Economics nutzt.
- `feedback_te_source_first.md` — Pro Indikator: TE → Quellen-Name → Quellen-URL → Download.
- `feedback_check_libraries_first.md` — VOR Custom-Scraper IMMER PyPI/GitHub nach Python-Wrapper suchen.
