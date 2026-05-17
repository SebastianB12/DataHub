-- Migration 084: indicator_families — Family-Templates (eine Row pro Indikator-Slug,
-- nicht pro Country×Slug).
--
-- Hintergrund: 226 Slugs × 31 Länder = ~7000 potentielle Instances. Strukturelle
-- Defaults (Frequenz, Display-Transform, Refresh-Cron, Toleranzen) sind family-weit
-- identisch. Per-Country-Abweichungen sitzen in indicator_instances.*_override.
--
-- Geseedet vom scripts/migrate_to_v2.py aus der bestehenden indicators-Tabelle.

CREATE TABLE IF NOT EXISTS indicator_families (
  family_id                    SERIAL PRIMARY KEY,
  family_code                  TEXT UNIQUE NOT NULL,
  family_name                  TEXT NOT NULL,
  category                     TEXT,
  default_te_display_transform TEXT,
  default_freq                 TEXT,
  default_refresh_cron         TEXT,
  default_unit                 TEXT,
  tolerance_abs                NUMERIC NOT NULL DEFAULT 0.05,
  tolerance_pct                NUMERIC NOT NULL DEFAULT 0.001,
  notes                        TEXT,
  created_at                   TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE  indicator_families IS 'Family-Templates: strukturelle Defaults pro Indikator-Slug (gilt für alle Country-Instances). Per-Country-Overrides in indicator_instances.';
COMMENT ON COLUMN indicator_families.family_code IS 'Slug-Form: inflation-cpi, ppi, unemployment-rate. Identisch zum bisherigen indicators.slug.';
COMMENT ON COLUMN indicator_families.default_te_display_transform IS 'Wie TE den Wert per Default zeigt: level | yoy_pct | mom_pct | qoq_pct | sign_flipped_level. Frontend transformiert data_series.value_kind passend.';
COMMENT ON COLUMN indicator_families.default_freq IS 'M=monthly, Q=quarterly, A=annual, W=weekly, D=daily, S=semi-annual.';
COMMENT ON COLUMN indicator_families.default_refresh_cron IS 'Cron-Expression für Scheduler (z.B. ''0 9 15 * *'' = monatlich am 15. um 9 UTC). Per-Instance via refresh_cron_override anpassbar.';
COMMENT ON COLUMN indicator_families.tolerance_abs IS 'Absolute Toleranz für TE-Conformity-Check; Default sehr tight (0.05) — nur Rundungs-/Vintage-Drift.';
COMMENT ON COLUMN indicator_families.tolerance_pct IS 'Relative Toleranz (0.001 = 0.1%). Match wenn |obs - exp| < tolerance_abs OR |obs - exp| / |exp| < tolerance_pct.';

CREATE INDEX IF NOT EXISTS idx_indicator_families_category ON indicator_families (category);
