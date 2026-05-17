-- Migration 088: te_page_snapshots + te_audit_findings — Observability-Layer.
--
-- te_page_snapshots: append-only Log eines TE-HTML-Scrapes pro Instance. Speichert
-- Fingerprint-Felder (latest + avg + ATH + ATL) die der te_parser aus der TE-Seite
-- extrahiert. Wird vom Massen-Audit-Run (Phase 2) gefüllt und danach inkrementell
-- vom scheduler-Post-Fetch-Hook.
--
-- te_audit_findings: Ticket-System. Ein Audit-Lauf erzeugt offene Tickets
-- (resolved_at IS NULL) für jede Abweichung. Health-Dashboard listet sie auf,
-- User kann auf "akzeptieren" klicken (resolved_at=NOW, resolution_note='accepted by user').
-- CI fails, wenn critical-Tickets offen sind.

CREATE TABLE IF NOT EXISTS te_page_snapshots (
  snapshot_id      BIGSERIAL PRIMARY KEY,
  instance_id      INT NOT NULL REFERENCES indicator_instances(instance_id) ON DELETE CASCADE,
  scraped_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  -- Headline
  te_last_value    NUMERIC,
  te_last_period   TEXT,
  -- Long-term-Fingerprint (aus Description-Box auf der TE-Page)
  te_avg           NUMERIC,
  te_avg_from_year INT,
  te_avg_to_year   INT,
  te_ath           NUMERIC,
  te_ath_period    TEXT,
  te_atl           NUMERIC,
  te_atl_period    TEXT,
  -- Attribution
  te_source_label  TEXT,
  te_source_url    TEXT,
  -- Raw
  raw_description  TEXT,
  parse_quality    TEXT CHECK (parse_quality IN ('ok','partial','failed')),
  parse_error      TEXT
);

COMMENT ON TABLE  te_page_snapshots IS 'Append-only Log eines TE-HTML-Scrapes pro Instance. Liefert Fingerprint-Felder für Series-Korrektheits-Check.';
COMMENT ON COLUMN te_page_snapshots.te_avg IS 'Long-term Durchschnitt aus TE-Description (z.B. "averaged 3.27% from 1914 until 2025").';
COMMENT ON COLUMN te_page_snapshots.te_ath IS 'All-time-high aus TE-Description. Plus te_ath_period (z.B. "June of 1980").';
COMMENT ON COLUMN te_page_snapshots.te_atl IS 'All-time-low aus TE-Description. Plus te_atl_period.';
COMMENT ON COLUMN te_page_snapshots.parse_quality IS 'ok = alle Felder geparst, partial = einige NULL, failed = HTML nicht parsebar (z.B. TE-Page existiert nicht).';

CREATE INDEX IF NOT EXISTS idx_te_page_snapshots_instance_time ON te_page_snapshots (instance_id, scraped_at DESC);

-- te_audit_findings: Ticket-System
CREATE TABLE IF NOT EXISTS te_audit_findings (
  finding_id       SERIAL PRIMARY KEY,
  instance_id      INT NOT NULL REFERENCES indicator_instances(instance_id) ON DELETE CASCADE,
  snapshot_id      BIGINT REFERENCES te_page_snapshots(snapshot_id) ON DELETE SET NULL,
  series_pk        INT REFERENCES data_series(series_pk) ON DELETE SET NULL,
  finding_type     TEXT NOT NULL,
  severity         TEXT NOT NULL CHECK (severity IN ('critical','warning','info')),
  message          TEXT,
  observed_value   NUMERIC,
  expected_value   NUMERIC,
  transform_used   TEXT,
  detected_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  resolved_at      TIMESTAMPTZ,
  resolved_by      TEXT,
  resolution_note  TEXT,
  CHECK (finding_type IN (
    'series_wrong',        -- Fingerprint matched nicht: andere Reihe gefetched
    'transform_diff',      -- Wert weicht ab, aber Fingerprint passt: falsche Transform
    'vintage_drift',       -- Wert weicht innerhalb Toleranz ab: Revision/Vintage
    'stale_data',          -- Letzter data_point älter als erwartete Frequenz
    'no_db_data',          -- TE hat Wert, wir haben keinen
    'no_te_data',          -- Wir haben Wert, TE-Page hat keinen
    'source_mismatch',     -- te_source_label auf Page weicht von attribution.te_label ab
    'parse_failure'        -- TE-Page konnte nicht geparst werden
  ))
);

COMMENT ON TABLE  te_audit_findings IS 'Ticket-System: offene Findings = aktive Probleme. resolved_at = geschlossen. Health-Dashboard listet alle resolved_at IS NULL.';
COMMENT ON COLUMN te_audit_findings.finding_type IS 'series_wrong (kritisch — Fingerprint-Mismatch), transform_diff (falsche Display-Transform), vintage_drift (innerhalb Toleranz), stale_data (zu alt), no_db_data, no_te_data, source_mismatch, parse_failure.';
COMMENT ON COLUMN te_audit_findings.severity IS 'critical = blockiert CI, warning = Dashboard-rot, info = nur Log.';
COMMENT ON COLUMN te_audit_findings.resolved_by IS 'NULL=offen, "auto"=durch nächsten Audit-Lauf gelöst, "user:sebastian"=manuell akzeptiert, "migration:082"=durch Code-Fix erledigt.';

CREATE INDEX IF NOT EXISTS idx_te_audit_findings_open
  ON te_audit_findings (instance_id, severity)
  WHERE resolved_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_te_audit_findings_type ON te_audit_findings (finding_type, severity);
