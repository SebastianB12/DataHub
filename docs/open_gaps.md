# EconPulse — Offene TE-Konformitäts-Gaps pro Land

> Sammelt nach jedem Country-Audit die Slugs, die **nicht** automatisch TE-konform
> auflösbar sind. Pro Eintrag: was fehlt, welche Aktion du als User triggern
> musst (API-Key, Credential, manuelle Entscheidung), oder warum es ein
> echter externer Gap ist (Lizenz, Vintage-Lag, TE-eigene Page-Bugs).
>
> Format pro Slug:
> ```
> - **<slug>** — <kurze Diagnose>
>   - **TE-Quelle:** <name>
>   - **Was wir haben:** <unsere Quelle + Wert>
>   - **TODO für dich:** <konkrete User-Aktion>
>   - **Alternativ:** <fallback wenn TODO nicht möglich>
> ```
>
> Letztes Update: 2026-05-16

---

## US (auditiert 2026-05-16, 191 Slugs)

Ergebnis: 25 DB-Fixes, 86 sofort OK, 57 Frontend-only (Level statt MoM/YoY
Display — kein Source-Problem), **6 offene Gaps**.

### Gaps — User-Aktion nötig

- **capital-flows** — TE zeigt monatlichen TIC-Net-Flow für Long-Term Securities (USD M)
  - **TE-Quelle:** U.S. Department of the Treasury (TIC System)
  - **Was wir haben:** FRED `NETFI` (annualized current account, $890B) — falsches Konzept
  - **TODO für dich:** Treasury Direct API hat keinen Auth-Key (öffentlich), aber **keine SDMX/CSV-Bulk-Endpoints für die TIC monthly net flow series**. Entweder:
    - (a) Manuell die TIC-S-Aggregat-Tabelle monatlich scrapen von `https://home.treasury.gov/data/treasury-international-capital-tic-system`
    - (b) Bekanntmachung wenn du eine Bloomberg/Refinitiv-Subscription hast — TIC-monthly läuft dort als clean series
  - **Alternativ:** Slug als `licensed-gap` markieren wie Lizenzreihen (GfK/ifo Pattern)

- **foreign-exchange-reserves** — TE zeigt ESF Foreign Currency Holdings (38121 USD M)
  - **TE-Quelle:** U.S. Department of the Treasury / Exchange Stabilization Fund
  - **Was wir haben:** FRED Total Reserve Assets (241283, inkl. Gold + SDR + IMF) — TE zeigt aber nur ESF-Foreign-Currency-Sub-Position
  - **TODO für dich:** Treasury veröffentlicht ESF-Bestände monatlich als XLS unter `https://home.treasury.gov/data/exchange-stabilization-fund`. Brauchst keinen Key, aber **manuellen Scraper** für die XLS-Tabelle.
  - **Alternativ:** Akzeptiere konzeptionelle Differenz und behalte Total-Reserves; im UI Hinweis „inkl. Gold/SDR" anzeigen

- **steel-production** — TE zeigt World Steel Association Tonnen (7200 kt monthly)
  - **TE-Quelle:** World Steel Association (worldsteel.org)
  - **Was wir haben:** FRED `IPG331S` (Industrial Production Index, Iron & Steel, 2017=100) — semantisch verwandt, falsche Einheit
  - **TODO für dich:** worldsteel.org veröffentlicht monatlich PDF/XLS — siehe `https://worldsteel.org/data/world-steel-in-figures/`. **Kein API**, manueller Scraper aus PDF nötig.
  - **Alternativ:** AISI (American Iron and Steel Institute) hat freie Wochendaten unter `https://www.steel.org/industry-data/`, könnten zu monatlich aggregiert werden

- **military-expenditure** — Vintage-Lag, nicht akut
  - **TE-Quelle:** SIPRI Yearbook (jährlich, neuste 2025)
  - **Was wir haben:** World Bank Indicator `MS.MIL.XPND.CD` (vintage 2024)
  - **TODO für dich:** Nichts akut. World Bank wird SIPRI 2025 in ~6 Monaten aufnehmen. Wenn du es früher willst: SIPRI hat CSV-Download unter `https://www.sipri.org/databases/milex` (kein Key, einmaliger Manual-Download)

- **total-vehicle-sales** — Vintage-Lag, nicht akut
  - **TE-Quelle:** Wards Intelligence (monatlich)
  - **Was wir haben:** FRED `TOTALSA` (vintage 1 Monat hinter Wards)
  - **TODO für dich:** Nichts akut. FRED zieht Wards nach 4-6 Wochen Lag nach. Wards-Direct ist hinter Paywall ($)

### Gaps — kein Action (TE-eigene Page-Issues)

- **strategic-petroleum-reserve** — TE hat **keine eigene Page** unter diesem Slug. Unsere EIA-Series `WCSSTUS1` ist die korrekte Quelle. Kein Gap.
- **hospitals**, **gasoline-stocks** — TE-Pages liefern leere Description-Blöcke (TE-Bug). Unsere Daten sind semantisch korrekt.
- **cpi-clothing** — TE zeigt unter dieser URL fälschlich CPI-Transportation-Daten (TE-Page-Bug). Unsere `CPIAPPSL` Apparel ist korrekt.
- **central-bank-balance** — TE-Description leer im Fetch, aber unser `WALCL` (Fed H.4.1) ist die richtige Series.

### Lizenz-Gaps (bekannt, dokumentiert in `docs/te_coverage_gaps.yaml`)

- **consumer-confidence (UMich preliminary mid-month)** — wir ziehen nur Final-Release. Mid-Month Preliminary kostet Lizenz.
- **business-confidence** (Conference Board) — lizenziert
- **GfK/ifo equivalents** — keine für US relevant

---

## CN (China)
_Noch nicht durchaudited — Audit folgt._

## GB (UK) — auditiert 2026-05-16, 47 Slugs

Ergebnis: 7 DB-Fixes, ~32 sofort OK, 4 Frontend-only (Index statt YoY-Display), **3 offene Gaps + 3 wartend auf Mai-Release**.

### Fixes durchgeführt

- `food-inflation` — Serien-Korrektur `l522` (CPIH all items, falsch!) → **d7bu** (CPI Food & Non-Alc Beverages). YoY 3.74% = TE.
- `corruption-index` — Curated 71 → 70 (TI 2025).
- `government-debt` — Series `hf6x` (% GDP) → **hf6w** (Level £bn) + unit. Jetzt 2910.8 Bn = TE.
- `labor-force-participation-rate` — `MGWG` (Inaktivitätsrate, falsch!) → **LF22** (Aktivitätsrate 16-64 SA). Jetzt 79.0 = TE.
- `hospital-beds` — Curated 2.36 → 2.44 (OECD 2023).
- `hospitals` — Curated 28.0 → 29.73 (WHO 2022).
- `money-supply-m2` — Label-Drift behoben (LPQVQJT-legacy → LPMAUYM), Unit Million→Billion.

### Gaps — User-Aktion / Beobachtung nötig

- **central-bank-balance** — TE zeigt **774,297 GBP M weekly** (May 13), wir 644 Bn (LPMBL22 monthly)
  - **TE-Quelle:** Bank of England — Weekly Bank Return (konsolidiertes Total)
  - **Was wir haben:** BoE `LPMBL22` (Monthly Total Assets) — Series-Label-Eintrag in DB sagt fälschlich `boe:rpwb55a`, Provider holt `LPMBL22`. Ergebnis ist 130 Bn niedriger als TE-Wochenstand.
  - **Was ich probiert habe:** Curl mit UA gegen BoE IADB CSV-Endpoint, ca. 30 Series-Code-Kandidaten (`RPWB55A/B/C/...`, `RPWB67A/Z`, `LPWB55A/X`, `RPWBL52/57`, `YWWB55A`, etc.). Treffer waren nur Sub-Items (97k, 103k, 20k Bn) — die konsolidierte 774-Bn-Total-Reihe verbirgt sich unter einem nicht offensichtlichen Code. DBnomics-Suche brachte 404. FRED-Pendant `UKASSETS` ist seit 2014 discontinued.
  - **TODO für dich:** Manuell BoE Bankstats Table A1.1 "Weekly amounts outstanding" auf der IADB-Web-UI öffnen und den exakten Series-Code für **"Total assets — consolidated weekly Bank Return"** ermitteln: `https://www.bankofengland.co.uk/boeapps/database/Bank.asp?Travel=NIxAZxSPxTRx` → "Statistical Interactive Database — interest & exchange rates data" → drill-down zu Table A1.1. Sobald du den Code hast (vermutlich 4-7 Zeichen, Format `XPWBxxx`), gib ihn mir, dann update ich die Row in 2 Min.
  - **Alternativ:** Akzeptiere LPMBL22 monthly als 95-%-Approximation, im UI als "monthly aggregate vs TE's weekly snapshot" labeln.

- **gdp-per-capita** — Wir frischer als TE
  - **TE-Quelle:** World Bank
  - **Was wir haben:** WB `NY.GDP.PCAP.CD` 2024 = 53,246; TE zeigt 47,265 (älterer Vintage)
  - **TODO für dich:** Nichts. Wir sind besser. TE updated periodisch nach.

- **gdp-per-capita-ppp** — Wir frischer als TE
  - **TE-Quelle:** World Bank
  - **Was wir haben:** WB `NY.GDP.PCAP.PP.CD` 2024 = 62,009; TE zeigt 52,517
  - **TODO für dich:** Nichts.

### Stale-Upstream (Mai-Release)

- **unemployment**, **unemployed-persons**, **youth-unemployment-rate** — warten auf ONS LFS-Release am **19. Mai 2026** (3 Tage). TE zeigt schon Forecast/Preview. DB wird sich automatisch synchronisieren bei nächstem ons-Run nach dem 19. Mai.

## EA (Euro Area) — auditiert 2026-05-16, 52 Slugs

Ergebnis: 9 DB-Fixes, ~38 sofort OK, **5 echte Gaps + 2 frontend-only**.

### Fixes durchgeführt

- `current-account` — Source `eurostat` (quarterly bop_eu6_q) → **ECB BPS** monthly. Exakt €21.1 bn Feb 2026 = TE.
- `current-account-to-gdp` — Falsches bop_eu6_q-Config (0 Datenpunkte) → **tipsbp20** annual, geo=EA20. 2025 = 1.7 = TE.
- `consumer-spending` — Nominal `CP_MEUR` → **chain-linked `CLV20_MEUR`** SCA. Q4 2025 = €1678.74 bn = TE.
- `gdp-per-capita` — WB `NY.GDP.PCAP.CD` (current) → **`NY.GDP.PCAP.KD`** (constant). DB 38,254 ≈ TE 38,145.
- `gdp-per-capita-ppp` — WB `PP.CD` → **`PP.KD`**. DB 56,432 ≈ TE 56,326.
- `government-spending` — Annual `gov_10a_main` → **quarterly `namq_10_gdp` P3_S13 CLV15**. Q4 2025 = 673.65 = TE.
- `gross-fixed-capital-formation` — Nominal `CP_MEUR` → **chain-linked `CLV15_MEUR`**. Q4 2025 = 650.90 = TE.
- `industrial-production` — `s_adj=SCA` → **`CA`** (calendar-adjusted). YoY -2.13% ≈ TE -2.10%.
- `population` — Eurostat geo `EA21` (mit BG) → **EA20-Override**. 351.64M = TE.

### Gaps — User-Aktion / Beobachtung nötig

- **exports / imports** — Eurostat-Monatsreihe leer
  - **TE-Quelle:** Eurostat (monthly external trade)
  - **Was wir haben:** Annual `nama_10_exi` als Fallback
  - **Problem:** Eurostat `ei_etea_m` liefert leere `value`-Map; `ext_st_eu27_2020sitc` nur EU27-geo (kein EA20)
  - **TODO für dich:** Nichts akut. Eurostat republiziert wahrscheinlich in nächster Veröffentlichungsrunde, dann automatisch synchronisiert. Falls länger persistent: Eurostat-Helpdesk anschreiben (`ESTAT-USER-SUPPORT@ec.europa.eu`) und nach EA20-Aggregat fragen.
  - **Alternativ:** ECB BPS für Total Goods+Services Trade nehmen (analog wie current-account jetzt)

- **job-vacancies** — Beidseitiger Gap
  - **TE-Quelle:** TE hat keine eigene Page für diesen Slug
  - **Was wir haben:** Eurostat `jvs_q_nace2` liefert 0 Rows für EA20/EA19/EA21
  - **TODO für dich:** Slug evtl. komplett für EA entfernen (kein TE-Pendant existiert). Oder ECB BPS-Pendant suchen.

- **personal-income-tax-rate, sales-tax-rate** — Source-Label-Diff, Wert identisch
  - **TE-Quelle:** "European Commission" Label
  - **Was wir haben:** `curated` (gleicher EC-Wert: 41.3 / 21.2)
  - **TODO für dich:** Nichts. Label-Kosmetik. Optional: Curated-Eintrag als `eurostat`-Source umlabeln, da TE so attribuiert.

- **changes-in-inventories** — Vintage-Mismatch
  - **TE-Quelle:** Eurostat `namq_10_gdp`
  - **Was wir haben:** Korrekte Serie, Q4 2025 SCA=20.32 / NSA=-3.02
  - **Problem:** TE zeigt 26.52 (Q4 2025) — anderer Vintage-Snapshot
  - **TODO für dich:** Nichts. TE liefert ältere oder eigene Revision.

- **employment-rate** — Frequenz-Mismatch
  - **TE-Quelle:** Eurostat `lfsi_emp_q` (quarterly)
  - **Was wir haben:** Annual `lfsa_ergan` (70.8 für 2025 vs TE 70.9 Q4 2025)
  - **TODO für dich:** Wenn dir die Q-Frequenz wichtig ist, sag Bescheid — dann switche ich auf `lfsi_emp_q`. Sonst aktuell ausreichend (Rundungsdifferenz).

### Frontend-only (2)

- **core-cpi** — wir Index 102.34, TE YoY 2.2% (Frontend computed)
- **productivity** — wir 99.38, TE 104.07 (TE wendet eigene Aggregation auf RLPR_HW an)

## DE (Deutschland) — auditiert 2026-05-16, 79 Slugs

Ergebnis: 4 DB-Fixes, ~43 sofort OK, **~15 echte Lizenz-/Konzept-Gaps + 4 frontend-only**.

### Fixes durchgeführt

- `bankruptcies` — Destatis Series `52411-0019` (Industrie-Breakdown, 0 Punkte) → **`52411-0011`** ISV006 Insgesamt. Jan 2026 = 1919 = TE.
- `changes-in-inventories` — Eurostat `namq_10_gdp:P52` → **Destatis `81000-0020`** VGR034. Q4 2025 = 21.0 = TE.
- `current-account` — Eurostat-Reste → **Bundesbank `BBFBOPV...CA...`** Provider neu gelaufen. Mar 2026 = 23,635 Mio EUR = TE.
- `food-inflation` — Eurostat HICP → **Destatis `61111-0004#CC13-01`** (gleiche Quelle wie cpi-food). YoY 1.54% = TE 1.50%.
- `core-cpi` — Eurostat HICP → **Destatis `61111-0006` Sonderposition `CC13-63E`** (Gesamtindex ohne Nahrungsmittel und Energie). Apr 2026 YoY 2.29% = TE 2.2-2.3%. 256 Punkte.
- `energy-inflation` — Eurostat HICP → **Destatis `61111-0006` Sonderposition `CC13-65D`** (Energie). Apr 2026 YoY 10.15% = TE 10.1%. 424 Punkte.
- `government-spending-to-gdp` — `curated` → **Eurostat `gov_10a_main` TE/PC_GDP/S13**. 2025 = 50.5% = TE. 31 Punkte.

### Gaps — User-Aktion / Beobachtung nötig

**Lizenz-Gaps (großer Block):** TE attribuiert primäre Quellen, zu denen wir keinen Zugang haben.

- **medical-doctors, nurses, hospital-beds** — TE-Quelle: OECD Health Stats (lizenz/Account)
- **military-expenditure, weapons-sales** — TE-Quelle: SIPRI (CSV-Download, Manual)
- **terrorism-index** — TE-Quelle: IEP Global Terrorism Index (Manual PDF)
- **personal-income-tax-rate, sales-tax-rate, withholding-tax-rate, retirement-age-men/women, minimum-wages**, **3× social-security-rate** — TE-Quelle: BZSt / OECD Policy. Werte sind in `curated` korrekt, nur Source-Label-Mismatch.
- **TODO für dich:** Diese sind allesamt Quasi-Statiken (jährlich/seltener). Niedrige Priorität für API-Onboarding. Akzeptiere `curated` mit korrekten Werten. Optional: Curated-Source umlabeln zu "oecd"/"sipri"/"iep" für Frontend-Anzeige.

**Echte fixbare Konzept-Gaps:**

- **unemployed-persons** — TE zeigt BA-registriert (~3.006 Mio), wir Eurostat ILO (~1.76 Mio)
  - **TE-Quelle:** Bundesagentur für Arbeit
  - **TODO für dich:** Wenn dir die deutsche Registrierungs-Definition wichtig ist (TE-Headline-Konsistenz): wir bräuchten einen BA-Scraper. Genesis-statistic.arbeitsagentur.de hat eine offene CSV-Schnittstelle, kein Key nötig. Sag Bescheid wenn ich das aufsetzen soll.
  - **Alternativ:** Dokumentiere Methodologie-Diff im UI ("ILO Konzept" vs "BA Registrierung").

- **wages** — TE zeigt jährlich EUR/Monat (~4701 €/2024), wir Destatis Index (100.4) — **VERSUCHT, NICHT FIXBAR**
  - **TE-Quelle:** Destatis (Source-Label bereits korrekt = destatis)
  - **Was probiert:** Tabellen 62321-0001/0010/0500 + 62361-0020/0021/0030/0034/0036. 0001 hat 4-Dimensionen (überschreitet GENESIS-Sync-Cap). 0020/0021 nur Indizes. Keine fetch-bare aggregierte EUR-Tabelle via GENESIS Sync-API.
  - **TODO für dich:** Annual Bruttomonatsverdienste EUR/Month-Tabelle ist via GENESIS-Sync-API zu groß. Optionen:
    - (a) GENESIS Async-API + Job-Polling implementieren (größere Investition)
    - (b) Curated YAML mit jährlichen Werten ergänzen (Quick-Fix für Headline)
  - **Alternativ:** Behalte 62361-0007 Index als Display, Hinweis im UI "Index, nicht EUR/Monat".

- **productivity** — TE Bundesbank monatlich (95.60), wir Eurostat quarterly RLPR_HW (100.28) — **VERSUCHT, BLOCKIERT**
  - **TE-Quelle:** Bundesbank
  - **Was probiert:** Bundesbank DSD `BBK_DOES` (9 Dimensionen) — Codelist-Metadata gibt 404; DBnomics-BUBA-Volltext 0 Treffer; SDMX-Test-Keys alle 404.
  - **TODO für dich:** Bundesbank-Web-UI direkt auf bundesbank.de aufmachen und "Arbeitsproduktivität" suchen, exakte Series-Key aus Excel-Download extrahieren und mir geben. Dann 5-Min-Fix.
  - **Alternativ:** Akzeptiere Eurostat-Pendant (Konzept ähnlich, Wert 100.28 vs 95.60 = ca. 5% Differenz).

- **current-account-to-gdp** — 0 Datenpunkte (bop_c6_q-Config broken)
  - **TE-Quelle:** Eurostat
  - **TODO für dich:** Eurostat `tipsbp20`-Filter für reines `PC_GDP` ist tricky bei DE (returnt MIO_EUR Mix). Workaround wäre custom-compute current-account-MioEUR / GDP-MioEUR. Niedrige Prio.

- **loans-to-private-sector** — Wir 3901 bn, TE 1975 bn (2× off)
  - **TE-Quelle:** Bundesbank — NFC-only Subset
  - **TODO für dich:** Bundesbank `BBBK10.M.TXI358` enthält Households+NFC. Brauchen NFC-only Series. Bundesbank-Discovery nötig.

- **banks-balance-sheet** — Wir 9,980, TE 11,380
  - **TE-Quelle:** Bundesbank
  - **TODO für dich:** Bundesbank `BBBK10.M.TXI355` ist Subset, brauchen broader Bilanzsumme. Discovery via DBnomics.

- **job-vacancies** — Wir Eurostat Rate (2.6%), TE BA Level (641K Apr 2026)
  - **TE-Quelle:** Bundesagentur für Arbeit
  - **TODO für dich:** Gleicher BA-Scraper-Bedarf wie unemployed-persons (gemeinsam aufsetzen).

- **central-bank-balance** — Vermutlich ähnliches Problem wie GB (BoE-IADB): Bundesbank-Bilanzsumme-Series finden.

### Updates 2026-05-16 (Primary-Source-Round)

- ✅ `productivity` — Bundesbank `BBDE1.M.DE.Y.BA10.A2P200000.F.C.I21.A` (Produktionsergebnis je Arbeitsstunde, CSA, 2021=100). Q1 2026 = 94.4-95.7, matches TE 95.60.

### Frontend-only (4)

- **mining-production, retail-sales, services-inflation, factory-orders, industrial-production, manufacturing-production, gdp-real** — wir Index, TE YoY/MoM% (Frontend computed).
- **budget-deficit** — wir Mrd-EUR-Level (-119.15), TE als %-Anteil (-2.7% GDP).

### Source-Label-Drift

- **government-debt** — Frontend-konzept unklar (Level vs %), bitte prüfen ob Slug-Setup wie US.

### Coverage-Gaps (TE-eigene Page-Issues)

- **government-spending-eur, hospitals, house-price-index** — TE-Page leer / Europace-lizenziert / no value.

## FR (Frankreich) — auditiert 2026-05-16, 67 Slugs

Ergebnis: **19 DB-Fixes**, 36 sofort OK, **15 dokumentierte Gaps**.

### Fixes durchgeführt (19)

- `current-account` — Eurostat quarterly → **BdF DBnomics BPM6 monthly SA**. Mar 2026 = -1.175 Bn = TE.
- `cpi-food` — Eurostat HICP CP-HI01 → **INSEE IPC-2025 COICOP01** (IDBANK 011814667).
- `current-account-to-gdp` — Eurostat `bop_gdp6_q` neu konfiguriert (war 0 Punkte). 2025 = -0.3% = TE.
- `government-debt` — Eurostat → **INSEE DETTE-TRIM-APU-2020:010777608**. Q4 2025 = 115.6% = TE.
- `government-debt-total` — Eurostat → **INSEE DETTE-TRIM-APU-2020:010777616**. Q4 2025 = 3460.5 Bn = TE.
- `gross-fixed-capital-formation` — INSEE V (nominal) → **L (chained-volume)**. 142.928 Bn = TE.
- `labor-force-participation-rate` — Annual Melodi → **quarterly INSEE EMPLOI-BIT-TRIM CTTA15**. 75.6 = TE.
- `exports`, `imports` — Quarterly CNT → **monthly INSEE COM-EXT sum-of-zones**.
- `medical-doctors`, `nurses` — Stale 2022-Rows gelöscht, Curated 2021-Werte aktiv.
- `terrorism-index` Curated 4.8 → **3.22** (TE GTI 2025).
- `social-security-rate` 67.4→68; `social-security-rate-employees` 22.4→23 (Curated).
- `retirement-age-men/women` 64 → **63**.
- `minimum-wages` 1801.8 → **1823** (Eurostat earn_mw_cur 2026-S1).
- `population` — World Bank → **INSEE BDM 001641586**. 69.082M = TE.
- `productivity` — Eurostat RLPR_HW I20 → **RLPR_PER I15 SCA**. Q1 2026 = 101.41 = TE.
- `youth-unemployment-rate` — INSEE annual → **Eurostat `une_rt_m` monthly**. 20.5 = TE.

### Gaps — User-Aktion / Beobachtung nötig

- **budget-deficit** — Source-Label-Drift (Wert -5.1 = TE exakt; INSEE-Pendant in pynsee/DBnomics stale seit 2022). **TODO:** Akzeptieren oder INSEE Melodi DD_FIPU freischalten.
- **consumer-spending** — Base-Year-Diff: TE CNT-2014 (345,945) vs unsere CNT-2020 (390,447). **TODO:** Grünes Licht zum Base-Year-Switch.
- **cpi-clothing, cpi-education, cpi-recreation-and-culture** — TE-Page-Stubs (Description leer). Unsere INSEE-Werte korrekt. **Keine Action.**
- **employed-persons** — Value-Drift 3-4%, kein clean Eurostat lfsi_emp_q/a-Combo matched 28177. **TODO:** Drift akzeptieren oder weitersuchen.
- **employment-rate** — Annual (68.8) vs TE quarterly (69.5). INSEE BDM CTTE15 quarterly discontinued seit 2019; Melodi DD_EEC_TRIM nicht exposed. **TODO:** Annual akzeptieren oder API-Key für Melodi besorgen.
- **job-vacancies, unemployed-persons** — TE = DARES (Cat A: ~3109k Arbeitslose, ~295.2k Vacancies). Wir = ILO LFS / Eurostat Rate. **TODO:** DARES hat keine public API. Falls dir DARES wichtig: gib grünes Licht für Web-Scraper auf `dares.travail-emploi.gouv.fr`.
- **labour-costs** — 0.3 Punkt Diff (TE ECB 113.8 vs unsere INSEE ICT 114.1). ECB SDW LCI nicht direkt callable. **TODO:** Tolerieren.
- **government-spending-eur** — TE hat keine eigene Page (Duplikat von government-spending). **TODO:** Slug deprecaten — sag Bescheid, dann lösche ich die Row.
- **ppi** — Base-Year-Diff: TE Base 2015=126.1 vs unsere IPPI-2021=115.4. IPPI-2015 discontinued seit Aug 2020. **TODO:** Base 2021 akzeptieren.
- **unemployment** — Vintage: TE 8.1 (Q1 2026), wir 7.7 (Q4 2025). Selbst-korrigiert bei nächstem INSEE-Run.
- **retail-sales** — Source-Label "Banque de France" vs wir INSEE ICA-2021 (BdF/STS endet 2024-08, INSEE ist frischer). **TODO:** Akzeptieren; Frontend könnte "INSEE mirror of BdF" labeln.
- **long-term-unemployment-rate** — Source-Label INSEE vs wir Eurostat (Wert 1.8 = TE exakt). INSEE LTU TXCHLODU discontinued seit 2019. **Keine Action möglich.**

## DK, SE, FI, GR, CY, MT
_Noch nicht durchaudited._

## PL, CZ, HU, SK, RO, BG, HR, SI
_Noch nicht durchaudited._

## LT, LV, EE
_Noch nicht durchaudited._

---

## Verbleibende ehrliche Source-Mismatches nach Re-Audit 2026-05-16

Bei diesen 2 Slugs attribuiert TE eine Primärquelle, zu der wir keinen direkten API-Zugang haben. Wir fetchen technisch von einem Re-Distributor (Eurostat), Source-Label spiegelt das wider (nicht TE-Attribution).

- **DE/minimum-wages** — DB=curated, TE=Destatis. Destatis publiziert Mindestlohn als Verwaltungsstatistik ohne GENESIS-API-Endpoint. Wert ist verifiziert gegen Destatis-Pressemeldung.
- **FR/ppi** — DB=eurostat (sts_inppd_m), TE=INSEE. INSEE IPPI-2015 (passende Base) ist discontinued 2020; IPPI-2021 (115.4) matched TE 126.1 nicht (verschiedener Base-Year). Eurostat sts_inppd_m liefert 126.1 als INSEE-Re-Distribution.

## Konsolidierter API-Key/Credential-TODO-Stack

Wenn du dich mal hinsetzt und mir Keys gibst, hier die Wunschliste:

| Service | Wozu | Wie bekommen | Priorität |
|---|---|---|---|
| _(bisher kein Key nötig — US Gaps brauchen Scraper, keine Auth)_ | | | — |

_(Wird ergänzt wenn weitere Länder audited werden und ich auf Paywalls/Auth-APIs stoße.)_

---

## IT (auditiert 2026-05-16, 66 Slugs)

Ergebnis: 6 sofort-Fixes (curated updates + Eurostat-Switches), 24 OK, 8 Frontend-only
(Level statt MoM/YoY Display), 4 strukturelle TE-No-Page-Gaps, **6 offene Gaps**.

### Strukturelle TE-No-Page (TE hat für IT keine Seite)
- **cpi-clothing** — TE hat nur cpi-housing-utilities und cpi-transportation für IT
- **cpi-food** — siehe oben
- **cpi-education** — keine TE-Page für IT
- **cpi-recreation-and-culture** — keine TE-Page für IT

Wir behalten Eurostat HICP-Subindices (ei_cphi_m) als ehrliche Approximation, mit
Hinweis im Frontend dass die HICP-Indizes auf 2025=100 basieren während ISTAT NIC
2026 launch-basis ist.

### Source-Mismatches per HARD CONSTRAINT zulässig
Folgende Slugs: TE attribuiert ISTAT (NIC-Basis), wir fetchen aus Eurostat (HICP-
oder europäische Quellen). Werte stimmen (gleicher YoY) oder leichte Vintage-
Differenz. Per Source-Label = Fetch-Provider behalten wir `eurostat`:
- consumer-confidence, business-confidence (TE = ISTAT NIC; wir = Eurostat ICI Balance Index)
- cpi-housing-utilities, cpi-transportation (TE = ISTAT NIC; wir = Eurostat HICP)
- disposable-personal-income, consumer-spending, gross-fixed-capital-formation,
  changes-in-inventories, government-spending, government-spending-eur,
  gdp-real (TE = ISTAT annual; wir = Eurostat namq_10_gdp quarterly aggregates)
- employment-rate, labor-force-participation-rate, labour-costs, youth-unemployment-rate
  (TE = ISTAT NIC; wir = Eurostat LFS — Werte konvergieren ±0.5pp)
- food-inflation, services-inflation, energy-inflation (TE = ISTAT YoY; wir = Eurostat Index;
  Frontend rechnet YoY)
- mining-production (TE = ISTAT; wir = Eurostat sts_inpr_m; verschiedene Bases)
- budget-deficit, government-debt-total (TE = ISTAT % GDP; wir = Eurostat gov_10dd_edpt1)

### Gaps — User-Aktion nötig

- **minimum-wages** — Italien hat keinen gesetzlichen Mindestlohn
  - **TE-Quelle:** TE zeigt `Italy/wages` (annual nominal wages) als Proxy
  - **Was wir haben:** value=0, note „kein statutorischer Mindestlohn"
  - **TODO für dich:** Entscheidung ob slug entfernen oder TE-Proxy übernehmen
  - **Alternativ:** Slug als `concept-not-applicable` markieren und im Frontend ausblenden

- **government-debt** — TE zeigt Banca d'Italia monatlich (EUR Million Stock)
  - **TE-Quelle:** Banca d'Italia (monatlich, 3.14 Bn EUR Feb 2026)
  - **Was wir haben:** Eurostat gov_10dd_edpt1 (% GDP, 137.1 — anderes Konzept)
  - **TODO für dich:** Banca d'Italia hat SDW-Series via ECB; brauchen BFM endpoint discovery
  - **Alternativ:** Slug umbenennen zu `government-debt-pct-gdp` damit es semantisch passt

- **business-confidence / consumer-confidence** — Concept mismatch (ISTAT NIC 2021=100 vs Eurostat balance)
  - **TE-Quelle:** ISTAT NIC Indices (87.9 / 90.8 April 2026)
  - **Was wir haben:** Eurostat balance index (-6.9 / -20.6) — anderes Basisjahr+Methodik
  - **TODO für dich:** ISTAT Esploradati (esploradati.istat.it) ist von diesem Netz aus blockiert (siehe Netzwerk-Caveat in pipeline/providers/istat.py). Wenn Network/Geo erreichbar wird, aktivieren sich die `consumer-confidence` und `business-confidence` SERIES-Einträge im ISTAT-Provider automatisch.
  - **Alternativ:** Eurostat-Balance behalten und im Frontend Methodik-Hinweis

- **core-cpi, food-inflation, services-inflation, energy-inflation, retail-sales, manufacturing-production, mining-production** — ISTAT Esploradati unerreichbar
  - **TE-Quelle:** ISTAT (nationale Basis 2021=100 / 2026 NIC)
  - **Was wir haben:** Eurostat HICP subindices (ei_cphi_m) bzw. sts_inpr_m
  - **TODO für dich:** ISTAT Esploradati network access — siehe Netzwerk-Caveat
  - **Alternativ:** Eurostat behalten; Werte konvergieren in YoY-Computation

- **interest-rate** — TE zeigt 2.15% (aktueller ECB DFR), wir korrekt
  - **TE-Quelle:** ECB
  - **Was wir haben:** ECB MRR_FR (2.15%) — matches
  - **TODO:** Keiner. TE-Page hat „averaged 1.88% / record high 4.75%" im Description-Block, von dem unser Regex-Parser fälschlicherweise 4.75 extrahiert. False positive.

- **gdp-per-capita, gdp-per-capita-ppp** — TE-Page hat „% of world's average" Text mit kleinen Zahlen
  - **TE-Quelle:** World Bank
  - **Was wir haben:** World Bank exakte Werte (34495.25 / 53265) — matches TE
  - **TODO:** Keiner. Parser-Limitation, false positive im Audit.

---

## Konventionen für künftige Country-Audits

Wenn ich Country `XX` audit (Schema wie US-Audit oben):

1. **DB-Fixes** (Series-ID schwammig oder falsche Reihe) — fixe ich direkt, kein TODO.
2. **Source-Switch** (z.B. von Eurostat-Mirror auf nationales Amt) — wenn nationaler Provider in Pipeline existiert, fixe ich direkt. Wenn neuer Provider nötig: notiere hier als Gap mit „TODO für dich: Provider-Approval".
3. **Konzept-Mismatch ohne FRED/Eurostat-Equivalent** — landet hier mit konkretem TODO (API-Key, Scraper-OK, Lizenz-Eskalation, etc.).
4. **Vintage-Lag** — landet hier nur wenn Lag > 2 Monate konsistent. Sonst ignoriere ich.
5. **TE-Page-Bugs** — kein TODO, nur Dokumentation damit ich nicht versehentlich „fixe" was nicht falsch ist.
