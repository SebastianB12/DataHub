# Datenquellen-API Cheatsheet

Konsolidierte Doku für alle APIs die unsere Pipeline nutzt. Quelle: offizielle Anbieter-Dokumentation, eigene Live-Tests. Bei Kollisionen mit der API: hier reinschauen, nicht raten.

---

## 1. Destatis GENESIS-Online (`api.statistiken.bundesbank.de` ist NICHT Destatis — siehe Bundesbank weiter unten)

**Base URL:** `https://www-genesis.destatis.de/genesisWS/rest/2020/`

**Offizielle Doku:** PDF (212 Seiten, deutsch) — `https://daten.statistik-bw.de/genesisonline/misc/GENESIS-Webservices_Einfuehrung.pdf` (auch lokal: `genesis_doc.pdf`).
**OpenAPI/Swagger:** `https://www-genesis.destatis.de/genesisWS/rest/2020/openapi.json`
**WADL:** `https://www-genesis.destatis.de/genesisWS/rest/2020/application.wadl`

### Authentifizierung
- `username` + `password` HTTP-Header (POST) oder Query-Param (GET, deprecated).
- Token funktioniert: token-string sowohl als Username als auch Passwort senden.
- Ohne Auth: `username=GAST password=GAST` (Default) — limitierte Daten.

### Wichtigste Endpoints (alle POST mit `application/x-www-form-urlencoded` Body)

| Endpoint | Zweck | Wichtige Params |
|---|---|---|
| `/helloworld/whoami` | GET — Echo der eigenen Identität | (none, GET) |
| `/helloworld/logincheck` | Token gültig? räumt zombie-Sessions auf | username, password |
| `/find/find` | Volltext-Suche nach Tabellen/Statistiken/etc. | term, category=tables/statistics/cubes, pagelength |
| `/catalogue/jobs` | **Liste der eigenen Background-Jobs** | type, pagelength |
| `/catalogue/results` | Liste der bereitgestellten Ergebnisse (nach Job-Mode) | selection |
| `/data/tablefile` | **Die Standard-Tabellen-API** — liefert ZIP mit CSV | name, format=ffcsv, classifyingvariable1-5, classifyingkey1-5, regionalvariable, regionalkey, startyear, endyear, timeslices, compress, job |
| `/data/timeseries` | Liefert eine Zeitreihe (nicht Tabelle) | name, area=all, classifyingvariable1-3, classifyingkey1-3 |
| `/data/result` / `/data/resultfile` | **Holt das Ergebnis eines Background-Jobs** | name=<auftrags-name>, area=user |
| `/metadata/table` | Struktur einer Tabelle (Dimensionen) | name |
| `/metadata/timeseries` | Struktur einer Zeitreihe | name |

### `/data/tablefile` Vollparameter

Body (form-urlencoded):
```
name              = Tabellen-Code (z.B. "61111-0002")
area              = "all" / "free" / "user" (Default "free")
format            = "ffcsv" (Flat-File-CSV, am besten parsebar) / "datencsv" / "csv" / "xlsx"
compress          = "true" — leere Zellen weglassen, Tabellengröße schrumpft → vermeidet Job-Mode
transpose         = "false"
contents          = "" — explizite Wertvariablen-Auswahl
startyear         = "1991"
endyear           = "2026"
timeslices        = "" — Anzahl Zeitscheiben (Pagination)
regionalvariable  = "DLAND" / "DINSG"
regionalkey       = "DG" (Deutschland) / "01" (Schleswig-Holstein) etc.
classifyingvariable1..5 = "WERT03" / "ABSATZ" / "WZ08Y1" / "ISVART" / etc.
classifyingkey1..5      = "WERTORG" / "INSGESAMT" / "WZ08-C" / "ISVART01" / etc.
job               = "false" / "true" — Background-Mode
stand             = "01.01.1970" — Inkrementell-Update-Zeitpunkt (für unsere Use-Cases default lassen)
language          = "de"
```

### Response-Format

- **Wenn klein genug:** Status 200, Content-Type `application/zip` mit ein `.csv` drin (UTF-8-BOM, `;` Separator, ffcsv hat Spalten `time, time_label, 1_variable_code, 1_variable_attribute_code, ..., value, value_unit, value_variable_code, value_variable_label`).
- **Wenn JSON-Error:** Content-Type `application/json` mit `{"Status":{"Code":N,"Content":"…","Type":"ERROR"}}`. Auch bei `Code:0` (success) kann der Body JSON sein wenn Job-Mode aktiv.
- **Wenn HTML 5xx:** Server-Wackler oder Generic-Error-Page „Ups, ein Fehler!" — nicht aus der API. Retry.

### Status-Codes (im JSON-Body, NICHT HTTP)

| Code | Bedeutung | Was tun |
|---|---|---|
| 0 | OK | weiter |
| 6 | **Anzahl paralleler Requests > 3** | `logincheck` aufrufen, dann retry |
| 12 | „Sie sind nicht berechtigt diesen Service aufzurufen!" | meist Auth-Fehler beim Job-Mode-Workflow — Token in Header sicherstellen |
| 22 | Tabelle hat Brüche / Anmerkungen | Daten OK, Hinweis loggen |
| 98 | **Tabelle zu groß für synchronen Abruf** | Job-Mode starten (siehe unten) |
| 104 | „Es gibt keine Objekte zum angegebenen Selektionskriterium" | Filter falsch — Codes prüfen |

### Job-Mode für große Tabellen (>20.000 Wertfelder)

Aus offizieller Doku (Kap. 4.2):

```
1. POST /data/tablefile  mit job=true
   → liefert {Code:100, Content:"… abrufbar als <auftrag-name>"}
   z.B. "51000-0013_117056270"

2. POST /catalogue/jobs  alle 30s pollen (selection=<auftrag-name>)
   → bis Status="Fertig"

3. POST /data/resultfile  name=<auftrag-name>, area=user
   → liefert die fertige ZIP/CSV
```

**Wichtig:** Auftrags-Name ist immer `<original-name>_<numerische-id>`. Im Schritt 3 IMMER `area=user` setzen — nicht `all`.

### Ressourcennutzung & Limits (Doku Kapitel 1.7)

- „Nur eine gewisse Anzahl Requests darf parallel laufen" — exakte Zahl steht im `logincheck`-Response.
- Bei Überschreitung: `logincheck` beendet hängengebliebene Requests (>15 Min).
- **Sequenziell arbeiten — nie parallele POSTs zum selben Token.**
- Server-Wartung passiert: 5xx-Antworten haben oft generic HTML, nicht JSON.

### Praxis-Stolperfallen aus eigenen Live-Tests

- **`User-Agent: python-requests` reicht** — die API checkt UA nicht (entgegen meiner früheren Vermutung).
- **`compress=true`** im Request-Body kann eine Tabelle unter den 20k-Cap drücken → Job-Mode vermeiden.
- **Server-side Filter mit `classifyingkey1-5`** ist meist effektiver als Client-side filtern. Tabelle 42151-0001 (5-dim) braucht 3 classifyingkeys um synchron abrufbar zu sein.
- **`pystatis` Wrapper** unterstützt KEIN `classifyingkey1-5` direkt — `Table.get_data()` API ist begrenzt. Für große Tabellen: eigene `requests.post()`-Calls (siehe `pipeline/providers/destatis.py:_fetch_table_direct`).

### Standard-GENESIS-Variable-Codes

| Variable | Bedeutung | Häufige Keys |
|---|---|---|
| DINSG | Region "Deutschland insgesamt" | DG |
| DLAND | Region "Bundesländer" | 01–16 |
| MONAT | Monat | MONAT01–12 |
| JAHR | Jahr | YYYY |
| QUARTG | Quartal | QUART1–4 |
| WERT03 | Wertart Auftragseingang | WERTORG (Original) / X13JDKSB (saisonbereinigt) |
| ABSATZ | Absatzrichtung | INSGESAMT / INLAND / AUSLAND / AUSLAND01 (Eurozone) / AUSLAND02 (Nicht-EZ) |
| WZ08Y1 | WZ2008 Hauptgruppen | WZ08-C (Verarb. Gewerbe), WZ08-B (Bergbau), … |
| ISVART | Insolvenz-Verfahrensart | ISVART01 (eröffnet) / ISVART02 (mangels Masse abgewiesen) |

---

## 2. Bundesbank SDMX

**Base URL:** `https://api.statistiken.bundesbank.de/rest/`

**Offizielle Doku:** `https://www.bundesbank.de/en/statistics/time-series-databases/help-for-sdmx-web-service`
**Hilfsindex:** DBnomics (`https://api.db.nomics.world/v22/series/BUBA/{flowRef}?limit=400`) — fertig indexierte Suche mit englischen Series-Namen.

### Authentifizierung
- Keine — komplett anonym.

### Endpoints

| Endpoint | Zweck |
|---|---|
| `GET /rest/data/{flowRef}/{key}?lastNObservations=N` | Daten holen (CSV oder XML) |
| `GET /rest/metadata/dataflow/BBK` | **Liste aller flowRefs** (3.1 MB XML) |
| `GET /rest/metadata/codelist/BBK` | Liste aller Codelists |
| `GET /rest/metadata/codelist/BBK/{id}` | Werte einer Codelist |
| `GET /rest/metadata/datastructure/BBK/{id}` | Dimensionsstruktur eines Flows |

### Headers

- `Accept: application/vnd.sdmx.data+csv` → CSV mit Header-Zeile (BBK_ID, TIME_PERIOD, OBS_VALUE, BBK_TITLE …)
- `Accept: application/xml` für Metadata (JSON-Accept gibt 406!)

### Wildcards

- `..` (zwei Punkte hintereinander) im Key = Wildcard für eine Position.
- `+` zwischen Werten = OR (mehrere Werte einer Dimension).
- Beispiel: `M.DB.Y.U..X.1.U2.2300.Z01.E` listet alle BSI-Items für DB-Beitrag.

### Discovery-Workflow

1. `GET /rest/metadata/dataflow/BBK` → grep auf bekannte Prefixes (BBBK, BBBS, BBFI, BBDA, BBDP).
2. ODER schneller: DBnomics Volltextsuche pro flow:
   ```
   curl "https://api.db.nomics.world/v22/series/BUBA/BBBK10?limit=400" \
     | jq '.series.docs[] | select(.series_name | test("M1|loans|reserve"; "i"))'
   ```
3. Series-Code dann gegen Bundesbank verifizieren.

### Wichtige Flows (live verifiziert)

| FlowRef | Inhalt |
|---|---|
| BBBS2 | Geldmengenaggregate (M2, M3, M3A) — DB Beitrag + Eurozone |
| BBBK10 | Konsolidierter Ausweis Eurosystem — M1/M2/M3 DE-Beitrag, MFI Aktiva, Lending Aggregate |
| BBBK11 | Bundesbank-Wochenausweis — TTA032 = Bilanzsumme Bundesbank (täglich) |
| BBFI1 | Balance of Payments — Reserve Assets Total |
| BBDA1 | Außenhandel — Saldo/Exporte/Importe |
| BBDP1 | Erzeugerpreise (PPI) |
| BBIB1 | Zinsstatistik |

### Stolperfallen

- **`/rest/structure/...`** ist NICHT der Pfad — das ist `/rest/metadata/...`.
- **JSON-Accept gibt 406** — XML ist Pflicht für Metadata.
- **flowRef-Discovery:** kein `/rest/dataflow/BBK`, sondern `/rest/metadata/dataflow/BBK`.
- **UNIT_MULT in CSV-Header** beachten: 6 = Mio EUR (also /1000 für Mrd), 9 = Mrd direkt.
- SOAP/XML-Schnittstelle wird Mitte 2025 abgeschaltet — nur RESTful nutzen.

---

## 3. Eurostat REST API

**Base URL:** `https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/`

**Doku:** `https://ec.europa.eu/eurostat/web/main/help/web-services`

### Authentifizierung
- Keine.

### Endpoints

```
GET {BASE}/{dataset_code}?{dim1}={value}&{dim2}={value}...&format=JSON&lang=en
```

**Output-Formate:** JSON-stat (Default `format=JSON`), SDMX-CSV, SDMX-XML.

### Wichtige Datasets

| Dataset | Inhalt |
|---|---|
| namq_10_gdp | GDP + Komponenten quarterly |
| nama_10_gdp | GDP annual |
| ei_cphi_m | HICP Flash (Index 2025=100, monthly, Subkomponenten via `indic` z.B. CP-HI01 Food, CP-HI04 Housing) |
| prc_hicp_midx | HICP Index (alt, 1996-2025, base I15/I05/I96) |
| prc_hicp_manr | HICP YoY % (annual rate of change) |
| sts_inpr_m | Industrieproduktion (Index I21=100, oder PCH_PRE/PCH_SM für Δ) |
| sts_inppd_m | PPI |
| ei_lmhr_m | Unemployment Flash |
| lfsi_emp_q | Employed persons quarterly |
| lfsa_ergan | Employment Rate annual |
| jvs_q_nace2 | Job Vacancies (`indic_em=JVR` für Rate, `JOBVAC` für Anzahl) |
| lc_lci_r2_q | Labour Cost Index (I20) |
| ei_bsin_q_r2 | Industrial Capacity Utilization (`indic=BS-ICU-PC`) |
| bop_c6_q | Balance of Payments (DE/Länder) |
| bop_eu6_q | Balance of Payments (EA Aggregate) |
| bop_gdp6_q | BoP / GDP Ratio |
| gov_10dd_edpt1 | Government Debt + Deficit |
| demo_pjan | Population annual |

### Geo-Codes

- `EA20` / `EA19` / `EA21` für Eurozone (Komposition wechselt — geo_override Liste in eurostat.py probiert diese in Reihenfolge)
- `UK` (nicht `GB` — Eurostat-spezifisch, GEO_MAP in eurostat.py mappt)

### Stolperfallen

- **HICP Index-Basisjahr wechselt** — alt `I15` (2015=100) bis 2025-12, neu `I25` oder via `ei_cphi_m unit=HICP2025`.
- **`time` Parameter im Format `2026-Q1`** (mit Bindestrich!), nicht `2026Q1`.
- **`s_adj` Werte:** NSA, SA, CA (calendar-adjusted), SCA (saisonal+kalender bereinigt). Bei manchen Datasets nur einzelne erlaubt.
- **400 Bad Request bei Discovery** wenn man invalide Param schickt → ohne `time`-Filter probieren um Dimensionen sichtbar zu machen.

---

## 4. ECB Data API

**Base URL:** `https://data-api.ecb.europa.eu/service/data/`

**Endpoint-Pattern:** `{BASE}/{dataflow}/{key}?lastNObservations=N&format=jsondata`

**Wichtige Dataflows:** BSI (Banking Statistics), MIR (Interest Rates), EXR (Exchange Rates), CIS (Coin/Banknote), SEC (Securities).

### Stolperfallen

- DE-spezifische Subaggregate kommen NICHT von ECB-aggregiert (das ist Eurozone-Total). Für DE-Beitrag → Bundesbank.

---

## 5. FRED (St. Louis Fed)

**Base URL:** `https://api.stlouisfed.org/fred/`
**Auth:** `api_key` Query-Param (in `.env` als `FRED_API_KEY`).
**Library:** `fredapi` (PyPI).

### Provider-Pattern

`pipeline/providers/fred.py` liest aus `indicator_sources` (source='fred') und ruft `Fred.get_series(series_id)`. Series-IDs sind kurz (z.B. `INDPRO`, `CPIAUCSL`, `UNRATE`).

### Stolperfallen

- **`transform`-Spalte in `indicator_sources` wird NICHT angewendet** — fred.py speichert raw value. Wenn man YoY/MoM braucht, das Frontend rechnet das.
- **Daily-Series werden auf Monatsende kollabiert** in unserem Provider.

---

## 6. ONS (UK)

**Base URL:** `https://api.ons.gov.uk/`

Hardcoded SERIES-Liste in `pipeline/providers/ons.py` mit `uri`-Pfaden zur ONS-Detailseite. Kein indicator_sources-driven (TODO: migrieren).

---

## 7. World Bank

**Base URL:** `https://api.worldbank.org/v2/`

Pattern: `country/{ISO}/indicator/{INDICATOR_ID}?format=json&per_page=200`

### Wichtige Indikatoren

| ID | Inhalt |
|---|---|
| NY.GDP.MKTP.CD | GDP nominal USD |
| NY.GDP.PCAP.CD | GDP per capita USD |
| NY.GDP.PCAP.PP.CD | GDP per capita PPP |
| FP.CPI.TOTL.ZG | CPI inflation YoY |

---

## 8. EIA (Energy Information Administration)

**Base URL:** `https://api.eia.gov/v2/`
**Auth:** `api_key` Query-Param (`EIA_API_KEY` in `.env`).

**Status:** Provider noch NICHT in DB integriert (B10 pending — siehe Memory `project_eia_pending.md`).

---

## 9. DBnomics

**Base URL:** `https://api.db.nomics.world/v22/`

**Wichtigste Endpoints:**
- `series/{provider_code}/{dataset_code}?limit=N` — alle Series eines Datasets
- `series/{provider_code}` — alle Series eines Providers
- `providers/{code}?datasets=true` — Dataset-Listing eines Providers

**Provider-Codes:** `BUBA` (Bundesbank), `EUROSTAT`, `FED` (FRED), `OECD`, `IMF`, `BIS`.

### Verwendung

DBnomics indexiert ALLE öffentlichen Statistik-APIs mit englischen Series-Namen. Perfekt zum Discovery wenn die Anbieter-eigene Suche schlecht ist (siehe Bundesbank).

---

## 10. pystatis (Destatis-Wrapper)

**Pakete:** `pystatis>=0.5.5,<0.6` — installiert in `pipeline/.venv`.

### Setup

```python
import pystatis
from pystatis import config as cfg, Table
cfg.config.set("genesis", "username", DESTATIS_TOKEN)
cfg.config.set("genesis", "password", DESTATIS_TOKEN)

t = Table("61111-0002")
t.get_data(prettify=False, compress=False, language="de", startyear="1991")
print(t.data)  # pandas DataFrame
```

### Was pystatis NICHT kann

- `classifyingvariable1-5` Parameter werden nicht durchgereicht.
- Job-Mode für sehr große Tabellen — Token wird mit „Code 12" abgewiesen wenn der Workflow nicht korrekt orchestriert wird.

→ Für große Tabellen unseren eigenen `_fetch_table_direct` in `pipeline/providers/destatis.py` benutzen.

---

## Konventionen & Lessons-Learned

1. **TE-Source-Conformity:** Pro Indikator immer die Quelle nutzen die TradingEconomics nennt. Niemals relabeln, niemals via Aggregator wenn Original verfügbar.
2. **Index/Level-Reihen bevorzugen** — daraus rechnet das Frontend MoM/QoQ/YoY automatisch via Display-Toggle. Pre-computed % YoY-Reihen vermeiden.
3. **Niemals parallele Test-Calls bei Destatis** — saturiert die 3-Slot-Limit. Sequenziell mit `logincheck` zwischen großen Calls.
4. **Bei API-Discovery-Schwierigkeiten zuerst DBnomics probieren** (gilt für Bundesbank, OECD, IMF — die haben oft schlechte eigene Suchen).
5. **`pystatis` ist canonical für Destatis** — aber für große Tabellen mit Filter direkt `requests.post()`.
