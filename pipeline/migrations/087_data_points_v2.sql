-- Migration 087: data_points um series_pk FK erweitern.
--
-- Strategie: series_pk wird zunächst NULLABLE hinzugefügt. scripts/migrate_to_v2.py
-- backfillt anschließend pro Row aus (country, indicator, source) -> data_series.
-- Erst NACH erfolgreichem Backfill darf series_pk auf NOT NULL gesetzt werden
-- (separates Cleanup in Phase 7) — sonst bricht die Migration auf 570k Rows.
--
-- Die alten String-Spalten (country, indicator, source) bleiben in Phase 1 bestehen
-- damit die existierende Pipeline (validate_te_conformity, run_all) während des
-- Übergangs weiter funktioniert. Phase 7 dropped sie nach Frontend-Migration.

ALTER TABLE data_points
  ADD COLUMN IF NOT EXISTS series_pk INT REFERENCES data_series(series_pk) ON DELETE RESTRICT;

COMMENT ON COLUMN data_points.series_pk IS 'FK zu data_series. Wird in Phase 1 nullable hinzugefügt, von migrate_to_v2.py befüllt, in Phase 7 NOT NULL gemacht und alte String-Spalten gedroppt.';

-- Lookup-Index für series_pk-Queries (typischer Frontend-Read: alle data_points einer Series)
CREATE INDEX IF NOT EXISTS idx_data_points_series_pk_date
  ON data_points (series_pk, date)
  WHERE series_pk IS NOT NULL;
