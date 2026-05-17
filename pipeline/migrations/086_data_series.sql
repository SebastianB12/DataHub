-- Migration 086: data_series — die konkreten Fetch-Koordinaten pro instance.
--
-- 1:n zu indicator_instances (eine Instance kann mehrere Series haben):
--   - role='primary',   is_default=true  → Frontend zeigt diese per Default
--   - role='secondary', is_default=false → User-Toggle alternative Source
--   - role='fallback',  is_default=false → Backup wenn primary down
--   - role='cross-check'                 → nur Validation, nie UI
--
-- Versionierung über (valid_from, valid_to). Wenn sich z.B. fetch_series_id ändert
-- (FRED rename, neuer Eurostat-Code), schließt der Pre-Activation-Guard die alte Row
-- (valid_to=NOW()) und legt eine neue auf. Damit bleiben historische data_points
-- über series_pk-FK an die ursprüngliche Spec gekoppelt — keine Wert-Verfälschung.
--
-- Pre-Activation-Guard: fingerprint_check_passed muss true sein, bevor activated_at
-- gesetzt wird. Ohne Activation darf der Scheduler die Series nicht fetchen.

CREATE TABLE IF NOT EXISTS data_series (
  series_pk                 SERIAL PRIMARY KEY,
  instance_id               INT NOT NULL REFERENCES indicator_instances(instance_id) ON DELETE RESTRICT,
  -- Role + Default-Status
  role                      TEXT NOT NULL DEFAULT 'primary',
  is_default                BOOLEAN NOT NULL DEFAULT FALSE,
  -- Source-Identifikation
  fetch_provider            TEXT NOT NULL,
  fetch_series_id           TEXT NOT NULL,
  fetch_extra_params        JSONB,
  fetch_unit                TEXT,
  fetch_adjustment          TEXT NOT NULL DEFAULT '',
  -- Was liefert die Source?
  value_kind                TEXT NOT NULL DEFAULT 'level',
  -- Honest-Label: wenn fetch_provider != te_source_attributions.canonical_provider
  source_deviation_reason   TEXT,
  -- Refresh-Tracking
  last_fetched_at           TIMESTAMPTZ,
  last_fetch_status         TEXT,
  -- Versionierung
  valid_from                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  valid_to                  TIMESTAMPTZ,
  superseded_by             INT REFERENCES data_series(series_pk) ON DELETE SET NULL,
  -- Pre-Activation-Guard
  fingerprint_check_passed  BOOLEAN NOT NULL DEFAULT FALSE,
  activated_at              TIMESTAMPTZ,
  notes                     TEXT,
  CHECK (role IN ('primary','secondary','fallback','cross-check')),
  CHECK (value_kind IN ('level','yoy_pct','mom_pct','qoq_pct','sign_flipped_level'))
);

COMMENT ON TABLE  data_series IS 'Fetch-Specs pro Instance. 1:n zu indicator_instances. Versioniert über valid_from/valid_to — alte data_points behalten ihre series_pk-Linkage.';
COMMENT ON COLUMN data_series.role IS 'primary (Default-Anzeige) | secondary (User-Toggle) | fallback (Backup) | cross-check (nur Validation, kein UI).';
COMMENT ON COLUMN data_series.is_default IS 'Genau EINE Row pro instance_id darf is_default=true UND valid_to IS NULL haben (siehe Unique-Index).';
COMMENT ON COLUMN data_series.fetch_provider IS 'Provider-Name in pipeline (fred, eurostat, destatis, insee, ons, bundesbank, ecb, statec, akshare_cn, national_eu, ...).';
COMMENT ON COLUMN data_series.fetch_series_id IS 'Provider-spezifische Series-ID, z.B. CPIAUCSL für FRED, 61111-0001 für Destatis.';
COMMENT ON COLUMN data_series.fetch_extra_params IS 'JSON-Bag für provider-spezifische Filter (eurostat: dataset+filters, ecb: SDMX-Key etc.).';
COMMENT ON COLUMN data_series.value_kind IS 'Was liefert die Source? level (Index/absoluter Wert, bevorzugt) | yoy_pct/mom_pct/qoq_pct (pre-computed Rate) | sign_flipped_level (Budget Surplus statt Deficit etc.).';
COMMENT ON COLUMN data_series.source_deviation_reason IS 'NULL wenn fetch_provider == te_source_attributions.canonical_provider. Sonst Text-Grund (z.B. "nationale API blockiert — fallback Eurostat").';
COMMENT ON COLUMN data_series.valid_to IS 'NULL = aktiv. Wenn series_id wechselt, hier alten Eintrag schließen, neuen mit valid_from=NOW() öffnen.';
COMMENT ON COLUMN data_series.fingerprint_check_passed IS 'true = Sample-Fetch matched TE-Description-Fingerprint (latest + avg + ATH + ATL). Pre-Activation-Guard verhindert dass false-Series aktiviert werden.';
COMMENT ON COLUMN data_series.activated_at IS 'NULL = noch nicht aktiviert (Scheduler ignoriert). Wird durch update_data_series-Helper gesetzt nachdem fingerprint_check_passed=true.';

-- Unique: exakt eine is_default=true unter valid_to IS NULL pro Instance
CREATE UNIQUE INDEX IF NOT EXISTS data_series_one_default_active
  ON data_series (instance_id)
  WHERE is_default = TRUE AND valid_to IS NULL;

-- Lookup-Indizes
CREATE INDEX IF NOT EXISTS idx_data_series_instance        ON data_series (instance_id);
CREATE INDEX IF NOT EXISTS idx_data_series_provider_active ON data_series (fetch_provider) WHERE valid_to IS NULL;
CREATE INDEX IF NOT EXISTS idx_data_series_active          ON data_series (instance_id) WHERE valid_to IS NULL;
