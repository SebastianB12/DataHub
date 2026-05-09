-- Drop redundant -mom/-yoy/-growth slugs that are now derivable from their parent
-- via the frontend Display-Toggle (see indicator-detail.tsx Frequency/Display logic).
--
-- These slugs duplicate information already encoded in their parent series:
--   building-permits-mom              <- building-permits (Thousand)
--   case-shiller-home-price-index-mom <- case-shiller-home-price-index (Index)
--   case-shiller-home-price-index-yoy <- case-shiller-home-price-index (Index)
--   existing-home-sales-mom           <- existing-home-sales (Thousand)
--   house-price-index-mom             <- house-price-index (Index)
--   house-price-index-yoy             <- house-price-index (Index)
--   housing-starts-mom                <- housing-starts (Thousand units)
--   new-home-sales-mom                <- new-home-sales (Thousand units)
--   gdp-growth                        <- gdp-real (Billion USD, quarterly)
--   gdp-annual-growth-rate            <- gdp-real (computeYoY); Pre-1947 US-Werte gehen damit verloren
--
-- Provider-side cleanup is in this migration:
--   pipeline/providers/ons.py: gdp-growth SERIES entry removed
--   pipeline/migrations/002_seed_eurostat.sql: gdp-growth INSERTs removed (file rewrite)

DELETE FROM data_points WHERE indicator IN (
  'building-permits-mom',
  'case-shiller-home-price-index-mom',
  'case-shiller-home-price-index-yoy',
  'existing-home-sales-mom',
  'house-price-index-mom',
  'house-price-index-yoy',
  'housing-starts-mom',
  'new-home-sales-mom',
  'gdp-growth',
  'gdp-annual-growth-rate'
);

DELETE FROM indicator_sources WHERE indicator IN (
  'building-permits-mom',
  'case-shiller-home-price-index-mom',
  'case-shiller-home-price-index-yoy',
  'existing-home-sales-mom',
  'house-price-index-mom',
  'house-price-index-yoy',
  'housing-starts-mom',
  'new-home-sales-mom',
  'gdp-growth',
  'gdp-annual-growth-rate'
);

DELETE FROM indicators WHERE slug IN (
  'building-permits-mom',
  'case-shiller-home-price-index-mom',
  'case-shiller-home-price-index-yoy',
  'existing-home-sales-mom',
  'house-price-index-mom',
  'house-price-index-yoy',
  'housing-starts-mom',
  'new-home-sales-mom',
  'gdp-growth',
  'gdp-annual-growth-rate'
);
