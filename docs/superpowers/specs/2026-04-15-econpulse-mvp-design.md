# EconPulse — MVP Design Spec

> Kostenlose Alternative zu Trading Economics, basierend auf öffentlichen Datenquellen.
> MVP-Fokus: Makroökonomische Indikatoren.

## 1. Projektziel

Trading Economics bietet umfangreiche Wirtschaftsdaten, ist aber kostenpflichtig und limitiert die historische Tiefe für Free-User. Da ~90% der Daten aus öffentlichen Quellen stammen, bauen wir eine kostenlose Alternative mit voller Historie.

**Use Case:** Ein Journalist liest, dass neue GDP-Daten veröffentlicht wurden → öffnet EconPulse → Daten sind da, mit voller Historie und Ländervergleich.

## 2. Tech Stack

| Komponente | Service | Kosten |
|---|---|---|
| Frontend + SSR | Vercel (Next.js App Router + ISR) | 0€ |
| Datenbank + API | Supabase (PostgreSQL + PostgREST) | 0€ |
| Datenpipeline | Railway (Python + APScheduler + Prefect) | ~5$/Mo |
| Job-Monitoring | Prefect Cloud | 0€ |
| Chart Library | TradingView Lightweight Charts | 0€ (MIT) |
| UI Components | shadcn/ui | 0€ |
| Excel Export | SheetJS (xlsx) | 0€ |

### Architektur-Entscheidungen

- **Kein separater API-Server (FastAPI):** Supabase PostgREST ersetzt einen eigenen Backend-Server. Next.js Server Components fragen Supabase direkt ab. Python wird nur für die Datenpipeline verwendet, nicht als API.
- **Railway statt GitHub Actions:** Für 15-Minuten-Freshness pollt ein persistenter Python-Prozess auf Railway alle Quellen regelmäßig. GitHub Actions wäre mit 96 Runs/Tag zu teuer (2.880 Min/Mo > 2.000 Free Tier). Railway (~5€/Mo) ist simpler: ein Prozess, APScheduler intern, alle Quellen in einer App.
- **Eine Chart Library:** TradingView Lightweight Charts für alles (Einzel-Charts + Multi-Series Ländervergleiche). Keine zweite Library.
- **Dark/Light Toggle:** Sidebar-Navigation (Dark Default) mit Light-Mode Switch. shadcn/ui CSS-Variablen machen das trivial.

### Datenfluss

```
Lesen:  User → Vercel CDN (ISR cached) → Next.js Server Component → Supabase
Schreiben: Railway (Python + APScheduler + Prefect) → Supabase
Monitoring: Python @flow/@task Decorators → Prefect Cloud Dashboard
```

Vercel und Railway wissen nichts voneinander — Supabase ist die einzige Verbindung.

### ISR Revalidation

- Indikator-Detailseiten: `revalidate = 3600` (1 Stunde) — Daten ändern sich maximal täglich
- Dashboard: `revalidate = 1800` (30 Minuten) — zeigt aggregierte neueste Daten
- Länder/Indikator-Übersichtsseiten: `revalidate = 3600` (1 Stunde)

## 3. MVP Scope

### 3.1 Indikatoren (6 Kategorien, 18 Indikatoren)

**BIP & Wachstum:**
- BIP nominal (Mrd USD)
- BIP real (Mrd USD)
- BIP Wachstumsrate (% YoY)
- BIP pro Kopf (USD)

**Inflation & Preise:**
- Inflationsrate CPI (% YoY)
- Kerninflation Core CPI (% YoY)
- Erzeugerpreisindex PPI (% YoY)

**Arbeitsmarkt:**
- Arbeitslosenquote (%)
- Beschäftigungsquote (%)
- Bevölkerung

**Zinsen & Geldpolitik:**
- Leitzins (%)
- Zentralbank-Bilanzsumme (Mrd USD / Mrd EUR)
- Geldmenge M2 (Mrd USD / lokale Währung)

**Handel & Außenwirtschaft:**
- Handelsbilanz (Mrd USD)
- Leistungsbilanz (% BIP)
- Exporte (Mrd USD)
- Importe (Mrd USD)

**Staatsfinanzen:**
- Staatsverschuldung (% BIP)
- Haushaltsdefizit (% BIP)

### 3.2 Länder (MVP: 4 Einträge)

- 🇺🇸 **USA** — Primärquelle: FRED
- 🇪🇺 **Euro-Area** (Aggregat) — Primärquelle: Eurostat + ECB
- 🇬🇧 **UK** — Primärquelle: ONS
- 🇩🇪 **Deutschland** — Primärquelle: Eurostat (einzelne DE-Daten)

Erweiterbar auf G7, G20, BRICS, 196 Länder — OECD, IMF, World Bank decken den Rest ab.

### 3.3 Datenvolumen

19 Indikatoren × 4 Länder = 76 Zeitreihen.
Bei Ø 60 Datenpunkten pro Reihe (1960–2024) = ~21.600 Datensätze.
Supabase Free Tier (500 MB) reicht selbst bei 196 Ländern locker.

## 4. Datenquellen-Strategie

### Prinzip: Eine Primärquelle pro Zeitreihe

Jede Kombination aus Indikator + Land wird von genau EINER Quelle geladen. Keine Merge-Logik, keine Prioritäten, keine Duplikate. Einfach.

**Kritische Erkenntnis:** World Bank hat 6-24 Monate Lag. Sie wird nur dort verwendet, wo keine schnellere Alternative existiert (Bevölkerung, BIP pro Kopf für Nicht-OECD-Länder).

### Primärquelle pro Indikator und Region

| Indikator | 🇺🇸 US | 🇩🇪🇫🇷🇮🇹🇪🇸 EU | 🇬🇧 UK | 🇯🇵🇨🇦🇦🇺🇰🇷🇨🇭 OECD | 🇨🇳🇮🇳🇧🇷🇷🇺🇿🇦🇲🇽🇮🇩🇹🇷🇸🇦 Nicht-OECD |
|---|---|---|---|---|---|
| BIP (nominal/real/Wachstum) | FRED | Eurostat | ONS | OECD | OECD* |
| BIP pro Kopf | FRED | Eurostat | ONS | OECD | World Bank |
| CPI / Core CPI / PPI | FRED | Eurostat | ONS | OECD | OECD* |
| Arbeitslosenquote | FRED | Eurostat | ONS | OECD | OECD* |
| Beschäftigungsquote | FRED | Eurostat | ONS | OECD | OECD* |
| Bevölkerung | World Bank | World Bank | World Bank | World Bank | World Bank |
| Leitzins | FRED | ECB | BIS | BIS | BIS |
| Zentralbank-Bilanz | FRED | ECB | — | — | — |
| Geldmenge M2 | FRED | ECB | — | OECD | — |
| Handelsbilanz | FRED | Eurostat | ONS | OECD | OECD* |
| Leistungsbilanz | FRED | Eurostat | ONS | OECD | IMF |
| Staatsverschuldung | FRED | Eurostat | ONS | OECD | IMF |
| Haushaltsdefizit | FRED | Eurostat | ONS | OECD | IMF |

*OECD deckt auch einige Nicht-Mitglieder ab (China, Brasilien, Indien, Russland, Südafrika, Indonesien, Saudi-Arabien). Wo OECD keine Daten hat, IMF als Fallback.*

*Zentralbank-Bilanz und M2 werden im MVP nur für US + EU abgedeckt — für andere Länder fehlen konsistente öffentliche APIs.*

### Pipeline (Railway — ein Python-Prozess, APScheduler)

Ein persistenter Python-Prozess auf Railway mit internem Scheduler. Jeder Job checkt intern ob neue Daten seit dem letzten Fetch vorliegen — wenn nein, sofortiger Return (kein unnötiger Traffic).

```python
# Alle 15 Minuten — Primärquellen für aktuelle Daten
scheduler.add_job(fetch_fred,     'interval', minutes=15)  # US-Daten
scheduler.add_job(fetch_eurostat, 'interval', minutes=15)  # EU-Daten (DE, FR, IT, ES)
scheduler.add_job(fetch_ecb,      'interval', minutes=15)  # EZB Leitzins, Bilanz, M2
scheduler.add_job(fetch_ons,      'interval', minutes=15)  # UK-Daten

# Seltener — langsamere Quellen
scheduler.add_job(fetch_oecd,      'interval', hours=6)    # JP, CA, AU, KR, CH etc.
scheduler.add_job(fetch_bis,       'cron', day_of_week='mon', hour=8)   # Leitzinsen int.
scheduler.add_job(fetch_imf,       'cron', day=1, hour=6)              # Staatsfinanzen
scheduler.add_job(fetch_worldbank, 'cron', day=1, hour=7)             # Bevölkerung, BIP/Kopf
```

### Erweiterungspfad (nach MVP)

Falls Zeitreihen der Primärquellen zu kurz sind: World Bank / OECD als Ergänzung für historische Daten (1960+) hinzufügen. Dann Merge-Logik einbauen.

Nationale Statistikämter für schnellere Nicht-OECD Daten:
- Japan: e-Stat API
- Kanada: Statistics Canada API
- Australien: ABS API
- Südkorea: KOSTAT + Bank of Korea
- Brasilien: IBGE + BCB
- Bei Marktdaten (5-Min-Updates): GitHub Actions → Railway Worker

## 5. Provider-Architektur

### BaseProvider Interface

Jeder Datenprovider implementiert eine einheitliche Klasse. Neuer Provider = eine Datei, eine Klasse.

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date

@dataclass
class DataPoint:
    indicator: str      # 'gdp', 'inflation-cpi'
    country: str        # 'US', 'DE'
    date: date
    value: float
    source: str         # 'fred', 'eurostat'

class BaseProvider(ABC):
    name: str           # 'fred', 'eurostat'
    display_name: str   # 'Federal Reserve Economic Data'

    @abstractmethod
    def fetch(self) -> list[DataPoint]:
        """Holt neue Daten, gibt nur geänderte/neue Datenpunkte zurück."""
        ...
```

### Provider-Registry (config-getrieben)

Provider werden in der DB registriert, nicht hardcoded. Der Scheduler liest beim Start die Tabelle und registriert Jobs dynamisch. Neuen Provider hinzufügen = DB-Eintrag + Python-Klasse.

```python
# scheduler.py — dynamisch statt hardcoded
providers = load_enabled_providers()  # liest data_sources Tabelle
for provider in providers:
    scheduler.add_job(
        provider.fetch,
        trigger=parse_schedule(provider.schedule),  # 'interval:15m' → IntervalTrigger
        id=provider.name,
        max_instances=1,
        misfire_grace_time=300,
    )
```

Skaliert auf 100+ Provider ohne Architekturänderung.

## 6. Datenbank-Schema (Supabase)

```sql
-- Länder
CREATE TABLE countries (
  code        TEXT PRIMARY KEY,           -- 'US', 'DE', 'JP'
  name        TEXT NOT NULL,              -- 'United States'
  name_de     TEXT,                       -- 'USA'
  region      TEXT,                       -- 'North America'
  flag_emoji  TEXT                        -- '🇺🇸'
);

-- Indikator-Definitionen
CREATE TABLE indicators (
  slug        TEXT PRIMARY KEY,           -- 'gdp', 'inflation-cpi'
  name        TEXT NOT NULL,              -- 'Gross Domestic Product'
  name_de     TEXT,                       -- 'Bruttoinlandsprodukt'
  category    TEXT NOT NULL,              -- 'gdp-growth'
  unit        TEXT NOT NULL,              -- 'Billion USD', '%'
  frequency   TEXT NOT NULL,              -- 'annual', 'monthly', 'quarterly'
  description TEXT,                       -- Erklärungstext
  source_name TEXT,                       -- Primärquelle, z.B. 'World Bank'
  source_url  TEXT                        -- Link zur Originalquelle (Daten können von mehreren Quellen kommen, siehe data_points.source)
);

-- Zeitreihendaten (Kern-Tabelle)
CREATE TABLE data_points (
  id          BIGSERIAL PRIMARY KEY,
  indicator   TEXT NOT NULL REFERENCES indicators(slug),
  country     TEXT NOT NULL REFERENCES countries(code),
  date        DATE NOT NULL,
  value       DOUBLE PRECISION,
  source      TEXT NOT NULL,              -- 'fred', 'eurostat', 'world-bank'
  fetched_at  TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(indicator, country, date)        -- eine Quelle pro Datenpunkt, keine Duplikate
);

CREATE INDEX idx_data_lookup ON data_points(indicator, country, date DESC);

-- Provider-Registry (config-getrieben, skaliert auf 100+ Provider)
CREATE TABLE data_sources (
  slug        TEXT PRIMARY KEY,           -- 'fred', 'eurostat', 'ecb'
  name        TEXT NOT NULL,              -- 'Federal Reserve Economic Data'
  schedule    TEXT NOT NULL,              -- 'interval:15m', 'cron:monday:08:00'
  enabled     BOOLEAN DEFAULT true,
  config      JSONB DEFAULT '{}',         -- API keys, endpoints, Mappings
  last_run_at TIMESTAMPTZ,
  last_status TEXT                        -- 'success', 'failed'
);

-- Pipeline-Tracking
CREATE TABLE pipeline_runs (
  id            BIGSERIAL PRIMARY KEY,
  source        TEXT NOT NULL,              -- 'fred', 'eurostat', 'world-bank'
  status        TEXT NOT NULL,              -- 'running', 'success', 'failed'
  started_at    TIMESTAMPTZ DEFAULT NOW(),
  finished_at   TIMESTAMPTZ,
  rows_upserted INT,
  error_message TEXT
);
```

## 7. Seiten & Routing (Next.js App Router)

```
/                                → Dashboard (Homepage)
/indicators                      → Alle Indikator-Kategorien
/indicators/[slug]               → Ein Indikator, alle Länder (z.B. /indicators/gdp)
/indicators/[slug]/[country]     → Indikator-Detail (z.B. /indicators/gdp/us)
/countries                       → Alle Länder
/countries/[code]                → Länderprofil (z.B. /countries/us)
```

### 7.1 Dashboard (Homepage)

- Key Metrics Cards (GDP, Inflation, Leitzins, Arbeitslosigkeit — konfigurierbares Land)
- G7/G20 Vergleichschart (Multi-Series, TradingView Lightweight Charts)
- Ländervergleichs-Tabelle (Kernindikatoren pro Land)
- Letzte Veröffentlichungen (Feed der neuesten Datenpunkte)

### 7.2 Indikator-Detailseite (`/indicators/[slug]/[country]`)

Die wichtigste Seite. Komponenten:

1. **Header** — Aktueller Wert, Trend (▲/▼), Quelle + Quellenlink
2. **Beschreibungstext** — Was ist der Indikator, wer veröffentlicht ihn, wie wird er gemessen
3. **Key Stats Bar** — Aktuell, Vorjahr/Vormonat, Allzeithoch, Allzeittief, Zeitraum
4. **Interaktiver Chart** — TradingView Lightweight Charts, Area Chart, Zeitraum-Buttons (5J, 10J, 25J, Max), Länder-Overlay für Vergleich
5. **Nächster Veröffentlichungstermin** — "Next release: Apr 30, 2026"
6. **Ländervergleichs-Tabelle** — Gleicher Indikator, andere Länder, sortierbar
7. **Historische Datentabelle** — Alle Datenpunkte, CSV + Excel Export (SheetJS)
8. **Verwandte Indikatoren** — Quick-Link Cards zu ähnlichen Indikatoren

### 7.3 Indikator-Übersicht (`/indicators/[slug]`)

- Tabelle: alle 20 Länder für diesen Indikator
- Sortierbar nach Wert, Veränderung, Land
- Mini-Sparklines pro Land

### 7.4 Länderprofil (`/countries/[code]`)

- Alle 18 Indikatoren für dieses Land auf einer Seite
- Gruppiert nach Kategorie
- Mini-Charts pro Indikator

### 7.5 Übersichtsseiten (`/indicators`, `/countries`)

- Kategorie-Grid (Indikator-Kategorien als Cards)
- Länder-Grid (Flaggen + Name + Key Metrics)

## 8. UI Design

### Design-Sprache

- **Sidebar-Navigation** (nicht Top-Tabs wie TE) — skaliert besser mit wachsenden Kategorien
- **Dark Theme Default** mit Light-Mode Toggle (shadcn/ui CSS-Variablen)
- **Card-basiertes Layout** statt Dense Tables
- **TradingView Lightweight Charts** — Area Charts mit Gradient Fill
- **Eigene Farbpalette:** Indigo (#818cf8) als Accent, Grün/Rot für Trends
- **Differenzierung zu TE:** Sidebar statt Top-Nav, Cards statt Textlisten, moderner Look, mehr Whitespace

### Sidebar-Navigation Struktur

```
EconPulse (Logo)
├── Übersicht
│   ├── Dashboard
│   └── Weltkarte (später)
├── Indikatoren
│   ├── BIP & Wachstum
│   ├── Inflation & Preise
│   ├── Arbeitsmarkt
│   ├── Zinsen & Geldpolitik
│   ├── Handel & Außenwirtschaft
│   └── Staatsfinanzen
├── Länder
│   ├── 🇺🇸 USA
│   ├── 🇩🇪 Deutschland
│   ├── ... (Top 20)
│   └── + Alle Länder
└── (später: Märkte, Kalender, News)
```

### Responsive Breakpoints

- Desktop (>1200px): Sidebar + Hauptbereich
- Tablet (768-1200px): Kollabierte Sidebar (Icons only)
- Mobile (<768px): Hamburger-Menu

## 9. Spätere Erweiterungen (nach MVP)

In der Reihenfolge der geplanten Umsetzung:

1. **Märkte** — Aktienindizes, Währungen, Rohstoffe, Anleihen (Yahoo Finance via yfinance). Braucht Railway Worker für häufige Updates.
2. **Länder-Profile erweitern** — Nationale Statistikämter (e-Stat, StatCan, ABS) für schnellere Daten.
3. **Wirtschaftskalender** — Geplante Veröffentlichungen, Erwartungen vs. Ist-Werte.
4. **News** — RSS Feeds, aggregierte Wirtschaftsnachrichten pro Indikator/Land.
5. **Redis Cache** (Upstash) — Wenn Supabase Connection-Limits eng werden.
6. **Weltkarte** — Choropleth-Map für visuellen Ländervergleich.

## 10. Verifikation

### Wie testen wir das MVP?

1. **Pipeline testen:** Jeden Fetch-Job lokal ausführen (`python -m pipeline.fred` etc.), prüfen ob Daten in Supabase landen, Prefect Cloud Dashboard auf Fehler prüfen.
2. **Daten-Integrität:** SQL-Query: Für jeden Indikator × Land prüfen ob Datenpunkte vorhanden sind und der neueste Datenpunkt plausibel aktuell ist.
3. **Frontend testen:** Jede Seite im Browser aufrufen, Chart-Rendering prüfen, Zeitraum-Buttons testen, Export (CSV + Excel) testen.
4. **Unique-Constraint testen:** Prüfen dass pro Indikator+Land+Datum nur ein Datenpunkt existiert (kein Duplikat-Risiko).
5. **ISR testen:** Seite aufrufen, Daten in Supabase ändern, nach Revalidation-Intervall prüfen ob neue Daten angezeigt werden.
