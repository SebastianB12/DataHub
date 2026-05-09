-- Switch industrial-production / manufacturing-production / mining-production
-- from pre-computed YoY/MoM percent values to the underlying volume Index.
-- The frontend Display-Toggle (computeYoY / computePoP) derives MoM and YoY from the Index.
--
-- Eurostat sts_inpr_m: change unit param PCH_SM/PCH_PRE -> I21 (Index 2021=100), s_adj=SCA.
-- FRED INDPRO/IPMAN/IPMINE: data already is the Index (transform="yoy"/"mom" was never wired
-- in fred.py — bug-by-luck means we just relabel unit and drop the redundant -mom slugs).

-- 1. Drop -mom slugs entirely (data + sources + indicators)
DELETE FROM data_points       WHERE indicator IN ('industrial-production-mom','manufacturing-production-mom');
DELETE FROM indicator_sources WHERE indicator IN ('industrial-production-mom','manufacturing-production-mom');
DELETE FROM indicators        WHERE slug      IN ('industrial-production-mom','manufacturing-production-mom');

-- 2. Drop existing eurostat data points (those are PCH_SM YoY values; will refetch as Index)
DELETE FROM data_points
WHERE source = 'eurostat'
  AND indicator IN ('industrial-production','manufacturing-production','mining-production');

-- 3. FRED data is already the Index — just fix the wrong unit label (was '%').
UPDATE data_points
SET unit = 'Index'
WHERE source = 'fred'
  AND indicator IN ('industrial-production','manufacturing-production','mining-production');

-- 4. Update eurostat indicator_sources: I21 + SCA, transform=raw, unit=Index
UPDATE indicator_sources
SET extra_params = jsonb_set(
      jsonb_set(extra_params, '{params,unit}', '"I21"'),
      '{params,s_adj}', '"SCA"'
    ),
    series_id = REGEXP_REPLACE(series_id, ':PCH_(SM|PRE)$', ':I21'),
    unit = 'Index',
    adjustment = 'SA',
    transform = 'raw'
WHERE source = 'eurostat'
  AND indicator IN ('industrial-production','manufacturing-production','mining-production');

-- 5. Update FRED indicator_sources: transform=raw, unit=Index
UPDATE indicator_sources
SET unit = 'Index',
    transform = 'raw'
WHERE source = 'fred'
  AND indicator IN ('industrial-production','manufacturing-production','mining-production');

-- 6. indicators table: relabel unit + clean name
UPDATE indicators
SET unit    = 'Index',
    name_de = REPLACE(REPLACE(name_de, ' (YoY)', ''), ' (MoM)', '')
WHERE slug IN ('industrial-production','manufacturing-production','mining-production');
