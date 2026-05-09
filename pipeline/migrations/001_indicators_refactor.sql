-- Migration 001: Indicators schema refactor + indicator_sources table
-- Phase A of the TE-indicator-coverage project.
--
-- Goal: scale from 19 → 380+ indicators (US) and eventually 30k+ (indicator × country)
-- by moving hardcoded Python dicts into a lookup table, and making the
-- frontend category grouping DB-driven.

-- =============================================================================
-- 1. Extend indicators table
-- =============================================================================

ALTER TABLE indicators
  ADD COLUMN IF NOT EXISTS category text,
  ADD COLUMN IF NOT EXISTS subcategory text,
  ADD COLUMN IF NOT EXISTS frequency text,
  ADD COLUMN IF NOT EXISTS tier int DEFAULT 3,
  ADD COLUMN IF NOT EXISTS unit_type text,
  ADD COLUMN IF NOT EXISTS te_slug text;

COMMENT ON COLUMN indicators.category IS 'TE top-level tab: Overview / GDP / Labour / Prices / Money / Trade / Government / Business / Consumer / Housing / Energy / Health / Taxes';
COMMENT ON COLUMN indicators.subcategory IS 'Optional grouping within a category (e.g. "Fed Regional Surveys", "ADP Breakdowns")';
COMMENT ON COLUMN indicators.frequency IS 'daily / weekly / monthly / quarterly / annual / event';
COMMENT ON COLUMN indicators.tier IS '1=Dashboard flagship, 2=main indicator page, 3=detail/search-only';
COMMENT ON COLUMN indicators.unit_type IS 'percent / index / count / currency / ratio / points';
COMMENT ON COLUMN indicators.te_slug IS 'Trading Economics URL slug (e.g. "initial-jobless-claims") for coverage validation';

CREATE INDEX IF NOT EXISTS idx_indicators_category ON indicators (category);
CREATE INDEX IF NOT EXISTS idx_indicators_tier ON indicators (tier);

-- =============================================================================
-- 2. Backfill existing 19 indicators with category / tier / frequency
-- =============================================================================

-- GDP & Growth
UPDATE indicators SET category='GDP',       frequency='quarterly', tier=1, unit_type='percent',  te_slug='gdp-growth-rate'   WHERE slug='gdp-growth';
UPDATE indicators SET category='GDP',       frequency='quarterly', tier=2, unit_type='currency', te_slug='gdp-constant-prices' WHERE slug='gdp-real';
UPDATE indicators SET category='GDP',       frequency='annual',    tier=2, unit_type='currency', te_slug='gdp'                 WHERE slug='gdp';
UPDATE indicators SET category='GDP',       frequency='annual',    tier=2, unit_type='currency', te_slug='gdp-per-capita'      WHERE slug='gdp-per-capita';

-- Prices (Inflation)
UPDATE indicators SET category='Prices',    frequency='monthly',   tier=1, unit_type='index',    te_slug='consumer-price-index-cpi' WHERE slug='inflation-cpi';
UPDATE indicators SET category='Prices',    frequency='monthly',   tier=2, unit_type='index',    te_slug='core-consumer-prices'     WHERE slug='core-cpi';
UPDATE indicators SET category='Prices',    frequency='monthly',   tier=2, unit_type='index',    te_slug='producer-prices'          WHERE slug='ppi';

-- Labour
UPDATE indicators SET category='Labour',    frequency='monthly',   tier=1, unit_type='percent',  te_slug='unemployment-rate'   WHERE slug='unemployment';
UPDATE indicators SET category='Labour',    frequency='monthly',   tier=2, unit_type='percent',  te_slug='employment-rate'     WHERE slug='employment-rate';
UPDATE indicators SET category='Labour',    frequency='annual',    tier=3, unit_type='count',    te_slug='population'          WHERE slug='population';

-- Money
UPDATE indicators SET category='Money',     frequency='event',     tier=1, unit_type='percent',  te_slug='interest-rate'          WHERE slug='interest-rate';
UPDATE indicators SET category='Money',     frequency='weekly',    tier=2, unit_type='currency', te_slug='central-bank-balance-sheet' WHERE slug='central-bank-balance';
UPDATE indicators SET category='Money',     frequency='monthly',   tier=2, unit_type='currency', te_slug='money-supply-m2'        WHERE slug='money-supply-m2';

-- Trade
UPDATE indicators SET category='Trade',     frequency='monthly',   tier=1, unit_type='currency', te_slug='balance-of-trade' WHERE slug='trade-balance';
UPDATE indicators SET category='Trade',     frequency='quarterly', tier=2, unit_type='currency', te_slug='current-account'   WHERE slug='current-account';
UPDATE indicators SET category='Trade',     frequency='monthly',   tier=2, unit_type='currency', te_slug='exports'           WHERE slug='exports';
UPDATE indicators SET category='Trade',     frequency='monthly',   tier=2, unit_type='currency', te_slug='imports'           WHERE slug='imports';

-- Government
UPDATE indicators SET category='Government',frequency='quarterly', tier=1, unit_type='percent',  te_slug='government-debt-to-gdp' WHERE slug='government-debt';
UPDATE indicators SET category='Government',frequency='annual',    tier=2, unit_type='percent',  te_slug='government-budget'      WHERE slug='budget-deficit';

-- =============================================================================
-- 3. indicator_sources table (source mapping, formerly hardcoded Python dicts)
-- =============================================================================

CREATE TABLE IF NOT EXISTS indicator_sources (
  indicator     text NOT NULL,
  country       text NOT NULL,
  source        text NOT NULL,                     -- fred / eurostat / ecb / ons / bundesbank / destatis / worldbank / eia / nfib / curated / bls / treasury / census
  series_id     text NOT NULL,                     -- provider-specific identifier
  transform     text NOT NULL DEFAULT 'raw',       -- raw / yoy / mom / diff / invert / trade_balance / scale_1000
  conversion    numeric NOT NULL DEFAULT 1,        -- multiplier applied to raw value (e.g. 1/1000 for M->B)
  unit          text,                              -- override; falls back to indicator.unit
  adjustment    text NOT NULL DEFAULT '',          -- SA / NSA / '' (seasonally adjusted)
  freq_hint     text,                              -- D/W/M/Q/A — pipeline hint for normalize_date
  extra_params  jsonb,                             -- provider-specific params (eurostat filters, ecb SDMX keys)
  priority      int NOT NULL DEFAULT 100,          -- lower = preferred in merged view
  active        boolean NOT NULL DEFAULT true,
  note          text,                              -- free-form comment (e.g. "replaces discontinued RPQB56A")
  created_at    timestamptz DEFAULT now(),
  PRIMARY KEY (indicator, country, source, series_id)
);

COMMENT ON TABLE indicator_sources IS 'Per-(indicator, country, source) series mapping. Replaces hardcoded dicts in pipeline/providers/*.py.';
COMMENT ON COLUMN indicator_sources.transform IS 'How to derive the stored value from the raw series (raw/yoy/mom/diff/invert/trade_balance/scale_1000)';
COMMENT ON COLUMN indicator_sources.priority IS 'Merged-view ordering: lower priority wins per (indicator, country, date, adjustment)';
COMMENT ON COLUMN indicator_sources.active IS 'false = keep the row for documentation but do not fetch (e.g. source temporarily broken)';

CREATE INDEX IF NOT EXISTS idx_indicator_sources_lookup ON indicator_sources (source, active);
CREATE INDEX IF NOT EXISTS idx_indicator_sources_indicator ON indicator_sources (indicator, country);

-- RLS: readable by anon (frontend may want to show source list), writable by service role only.
ALTER TABLE indicator_sources ENABLE ROW LEVEL SECURITY;
CREATE POLICY indicator_sources_select_all ON indicator_sources FOR SELECT USING (true);
