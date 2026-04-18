-- EconPulse MVP Schema
-- Run this in Supabase Dashboard → SQL Editor

-- 1. Länder
CREATE TABLE countries (
  code        TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  name_de     TEXT,
  region      TEXT,
  flag_emoji  TEXT
);

-- 2. Indikator-Definitionen
CREATE TABLE indicators (
  slug        TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  name_de     TEXT,
  category    TEXT NOT NULL,
  unit        TEXT NOT NULL,
  frequency   TEXT NOT NULL,
  description TEXT,
  source_name TEXT,
  source_url  TEXT
);

-- 3. Zeitreihendaten (Kern-Tabelle)
CREATE TABLE data_points (
  id          BIGSERIAL PRIMARY KEY,
  indicator   TEXT NOT NULL REFERENCES indicators(slug),
  country     TEXT NOT NULL REFERENCES countries(code),
  date        DATE NOT NULL,
  value       DOUBLE PRECISION,
  source      TEXT NOT NULL,
  fetched_at  TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(indicator, country, date)
);

CREATE INDEX idx_data_lookup ON data_points(indicator, country, date DESC);

-- 4. Provider-Registry
CREATE TABLE data_sources (
  slug        TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  schedule    TEXT NOT NULL,
  enabled     BOOLEAN DEFAULT true,
  config      JSONB DEFAULT '{}',
  last_run_at TIMESTAMPTZ,
  last_status TEXT
);

-- 5. Pipeline-Tracking
CREATE TABLE pipeline_runs (
  id            BIGSERIAL PRIMARY KEY,
  source        TEXT NOT NULL,
  status        TEXT NOT NULL,
  started_at    TIMESTAMPTZ DEFAULT NOW(),
  finished_at   TIMESTAMPTZ,
  rows_upserted INT,
  error_message TEXT
);

-- RLS: Daten öffentlich lesbar
ALTER TABLE countries ENABLE ROW LEVEL SECURITY;
ALTER TABLE indicators ENABLE ROW LEVEL SECURITY;
ALTER TABLE data_points ENABLE ROW LEVEL SECURITY;
ALTER TABLE data_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE pipeline_runs ENABLE ROW LEVEL SECURITY;

-- Öffentlich lesbar
CREATE POLICY "Public read countries" ON countries FOR SELECT USING (true);
CREATE POLICY "Public read indicators" ON indicators FOR SELECT USING (true);
CREATE POLICY "Public read data_points" ON data_points FOR SELECT USING (true);

-- Nur Service Role kann schreiben (Pipeline)
CREATE POLICY "Service write countries" ON countries FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "Service write indicators" ON indicators FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "Service write data_points" ON data_points FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "Service write data_sources" ON data_sources FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "Service write pipeline_runs" ON pipeline_runs FOR ALL USING (auth.role() = 'service_role');
