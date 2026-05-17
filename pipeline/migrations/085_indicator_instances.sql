-- Migration 085: indicator_instances — die Country×Family-Kombinationen die wir tracken.
--
-- Eine Row hier = „wir zeigen Inflation-CPI für Polen, attribuiert an Statistics Poland,
-- TE-Page https://tradingeconomics.com/poland/inflation-cpi". Die konkrete Daten-Quelle
-- (welche GUS-Tabelle, welcher Eurostat-Code) steht in data_series — eine Instance kann
-- mehrere data_series haben (primary + secondary + fallback).
--
-- Unique-Constraint (country_id, family_id) verhindert Duplikate.
-- Geseedet von scripts/migrate_to_v2.py aus indicator_sources + truth.yaml.

CREATE TABLE IF NOT EXISTS indicator_instances (
  instance_id                     SERIAL PRIMARY KEY,
  family_id                       INT NOT NULL REFERENCES indicator_families(family_id) ON DELETE RESTRICT,
  country_id                      INT NOT NULL REFERENCES countries(country_id)         ON DELETE RESTRICT,
  te_attribution_id               INT NOT NULL REFERENCES te_source_attributions(attribution_id) ON DELETE RESTRICT,
  te_url                          TEXT NOT NULL,
  -- Family-Overrides (NULL = inherit von indicator_families.default_*)
  te_display_transform_override   TEXT,
  tolerance_abs_override          NUMERIC,
  tolerance_pct_override          NUMERIC,
  freq_override                   TEXT,
  refresh_cron_override           TEXT,
  -- Lifecycle
  is_active                       BOOLEAN NOT NULL DEFAULT TRUE,
  created_at                      TIMESTAMPTZ DEFAULT NOW(),
  notes                           TEXT,
  UNIQUE (country_id, family_id)
);

COMMENT ON TABLE  indicator_instances IS 'Country×Family — eine Instance pro Indikator-Slug pro Land. Frontend liest hieraus die TE-Page-Attribution.';
COMMENT ON COLUMN indicator_instances.te_attribution_id IS 'Welche TE-Source attribuiert TE für diese Instance? Zentrales Mapping in te_source_attributions.';
COMMENT ON COLUMN indicator_instances.te_url IS 'Konkrete TE-Page für dieses Country×Family-Paar.';
COMMENT ON COLUMN indicator_instances.te_display_transform_override IS 'Per-Instance-Override, z.B. wenn TE eine Family normalerweise als yoy_pct zeigt, aber für ein spezifisches Land als level. NULL = family default.';

CREATE INDEX IF NOT EXISTS idx_indicator_instances_family       ON indicator_instances (family_id);
CREATE INDEX IF NOT EXISTS idx_indicator_instances_country      ON indicator_instances (country_id);
CREATE INDEX IF NOT EXISTS idx_indicator_instances_attribution  ON indicator_instances (te_attribution_id);
CREATE INDEX IF NOT EXISTS idx_indicator_instances_active       ON indicator_instances (is_active) WHERE is_active;
