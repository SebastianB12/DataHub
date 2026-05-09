# EconPulse — Projekt-Kontext

Kostenlose Alternative zu Trading Economics. MVP: Makroökonomische Indikatoren.

## Stack

| Komponente | Service |
|---|---|
| Frontend | Next.js 16 App Router + ISR (Vercel) |
| Datenbank + API | Supabase (PostgreSQL + PostgREST) |
| Datenpipeline | Python + APScheduler (lokal, Railway bei Go-Live) |
| Job-Monitoring | Prefect Cloud (erst bei Go-Live) |
| Charts | TradingView Lightweight Charts v5 |
| UI | shadcn/ui + Tailwind, Dark/Light Toggle |

## Architektur

- **Kein eigener API-Server** — Supabase PostgREST ersetzt FastAPI. Next.js Server Components fragen Supabase direkt ab.
- **Eine Primärquelle pro Zeitreihe** — keine Merge-Logik. Quelle steht in `data_points.source`.
- **BaseProvider ABC** — jeder Datenprovider implementiert `BaseProvider.fetch() -> list[DataPoint]`. Neue Provider = eine Datei + DB-Eintrag in `data_sources`.
- **15-Min Polling** — APScheduler liest `data_sources` Tabelle, registriert Jobs dynamisch.

## Datenquellen (MVP: 4 Länder)

| Region | Quelle | Status |
|---|---|---|
| US | FRED (fredapi) | Implementiert, 11.816 Datenpunkte |
| EU + DE | Eurostat Statistics API | Implementiert, ~4.000 Datenpunkte |
| EU (Zinsen) | ECB Data API (SDMX) | Implementiert, ~4.000 Datenpunkte |
| UK | ONS CSV + BoE IADB | Implementiert, ~6.700 Datenpunkte |

## DB-Schema (Supabase)

5 Tabellen: `countries` (4), `indicators` (19), `data_points` (~26.6k), `data_sources` (4), `pipeline_runs`
- RLS: Daten öffentlich lesbar, Schreiben nur via Service Role Key
- Unique Constraint: `(indicator, country, date)` — eine Quelle pro Datenpunkt
- Supabase MCP für DDL-Operationen verwenden (direkte DB-Verbindung funktioniert nicht wg. IPv6/Firmennetzwerk)

## Projektstruktur

```
src/app/                     -> Next.js Pages
  indicators/[slug]/[country]/  -> Indikator-Detailseite (wichtigste Seite)
  indicators/[slug]/            -> Laendervergleich
  countries/[code]/             -> Laenderprofil
src/components/              -> UI-Komponenten (sidebar, chart, theme)
src/lib/                     -> Supabase Client, Indicator-Definitionen
pipeline/                    -> Python Datenpipeline
  providers/fred.py          -> FredProvider (US)
  providers/eurostat.py      -> EurostatProvider (EU + DE)
  providers/ecb.py           -> EcbProvider (EU Zinsen/Bilanz/M2)
  providers/ons.py           -> OnsProvider (UK, inkl. BoE)
  base_provider.py           -> BaseProvider ABC
  transforms.py              -> Shared transforms (compute_yoy, compute_trade_balance)
  db.py                      -> Supabase write helpers
  scheduler.py               -> APScheduler (dynamische Jobs)
```

## Aktueller Stand & Naechste Schritte

Plan: `C:\Users\sb\.claude\plans\wise-moseying-waterfall.md`
Spec: `docs/superpowers/specs/2026-04-15-econpulse-mvp-design.md`

**Erledigt:** Phase 1 (Setup) + Phase 2 (FRED) + Phase 2b (Navigation) + Phase 3 (alle Provider)
**Naechste Phase:** Phase 4 — Frontend-Features:
1. Laender-Overlay im Chart (Vergleich zweier Laender)
2. CSV + Excel Export
3. ISR konfigurieren
4. Dashboard erweitern (Multi-Series Chart, Releases Feed)
5. Responsive Layout (Tablet/Mobile)

## Konventionen

- Antworte auf Deutsch
- API-Keys nur in `.env`, nie in der DB oder im Code
- Lightweight Charts v5 API: `chart.addSeries(AreaSeries, {...})` (nicht `addAreaSeries`)
- Keine Unicode-Sonderzeichen in Python print() (Windows Console = cp1252)
- `pipeline/.venv` fuer Python Dependencies
